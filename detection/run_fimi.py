#!/usr/bin/env python3
"""hybrid-fimi-radar — orquestador principal.

Flujo (del prompt):
  COLLECTORS -> RAW -> NORMALIZER -> FEATURES -> DETECTION -> CLUSTERING
  -> SCORING -> ATTRIBUTION -> SQLITE -> REPORT -> DASHBOARD

Agnóstico al actor: primero la anomalía, después la atribución (si procede).
Uso: python -m detection.run_fimi --input data/raw/events.csv --db data/radar.db
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from normalizer.schema import get_conn
from features.features import build_features
from features.bot_signals import bot_signal_score
from detection.anomaly import detect_anomalies
from detection.coordination import build_edges
from detection.fakenews import detect_cascades, amplification_signal, detect_narrative_amplification
from clustering.clustering import cluster_by_components, cluster_summary, cluster_evidence_details
from detection.scoring import compute_scores, band_for, load_bands
from attribution.attribution import classify_hypotheses, attribution


def load_config(path=None):
    path = path or ROOT / "config.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(ROOT / "data" / "raw" / "events.csv"))
    ap.add_argument("--db", default=str(ROOT / "data" / "radar.db"))
    ap.add_argument("--config", default=None)
    ap.add_argument("--tema", default=None, help="Tema/dominio (frontera_sur, geopolitica_ue_marruecos, politica_nacional). Default: frontera_sur")
    args = ap.parse_args()

    cfg = load_config(args.config)
    t0 = time.time()
    tema = getattr(args, "tema", None) or "frontera_sur"

    # --- INGEST + NORMALIZE ---
    from normalizer.ingest import load, normalize, load_sqlite
    print(f"[1/7] Ingest {args.input} (tema={tema})")
    if str(args.input).endswith(".db"):
        df = load_sqlite(args.input, tema=tema)
    else:
        raw = load(args.input)
        df = normalize(raw)
    print(f"      {len(df)} eventos, {df['author'].nunique()} cuentas")

    # --- FEATURES ---
    print("[2/7] Features por cuenta")
    feat = build_features(df, cfg)
    for a in feat.index:
        feat.loc[a, "bot_signal"], _ = bot_signal_score(feat.loc[a].to_dict())

    # --- DETECTION (anomalías) ---
    print("[3/7] Anomalías (Isolation Forest)")
    scored, thr = detect_anomalies(feat, cfg)
    print(f"      umbral anomalía p={cfg['detection']['anomaly_percentile']}")

    # --- COORDINATION + CASCADES ---
    print("[4/7] Coordinación (grafo)")
    edges = build_edges(df, cfg)
    edges_df = pd.DataFrame(edges) if edges else pd.DataFrame(columns=["source", "target", "weight", "evidence"])
    print(f"      {len(edges)} aristas")
    cascades = detect_cascades(df, cfg)
    amp = amplification_signal(edges_df, df["author"].nunique())
    narratives = detect_narrative_amplification(df, cfg)
    print(f"      {len(cascades)} cascadas, {len(narratives)} narrativas amplificadas")

    # --- CLUSTERING ---
    print("[5/7] Clustering (componentes conexas)")
    merged = cluster_by_components(scored, edges_df, cfg)
    summary = cluster_summary(merged, edges_df, cfg)
    details = {}
    sub_clustered = None
    if merged["cluster_label"].notna().any():
        for label in merged["cluster_label"].dropna().unique():
            mem = merged[merged["cluster_label"] == label]
            details[label] = cluster_evidence_details(df, label, mem, edges_df)
        # miembros por cluster (para persistir el contenido real en cluster_events)
        ev_idx = merged["cluster_label"].notna()
        sub = df[df["author"].isin(merged[ev_idx].index)].copy()
        lab_map = merged.loc[merged[ev_idx].index, "cluster_label"]
        sub["cluster"] = sub["author"].map(lab_map)
        sub["fecha_utc"] = pd.to_datetime(sub["ts"], unit="s", utc=True).dt.strftime("%Y-%m-%d %H:%M:%S")
        sub_clustered = sub
        (ROOT / "data" / "processed").mkdir(parents=True, exist_ok=True)
        sub[["cluster", "fecha_utc", "author", "text", "url", "hashtags", "action"]].to_csv(
            ROOT / "data" / "processed" / "cluster_events.csv", index=False, encoding="utf-8")

    # --- SCORING + ATTRIBUTION + PERSIST ---
    print("[6/7] Scoring + atribución + persistencia SQLite")
    bands = load_bands(cfg)
    conn = get_conn(args.db)

    # Snapshot del estado actual: la tabla clusters es la VISTA ACTIVA (los
    # clusters que el dashboard muestra ahora mismo). Cada ciclo REEMPLAZA el
    # snapshot del tema: se borran los clusters previos (y sus dependencias)
    # antes de insertar los detectados en este ciclo. El historial (findings)
    # se conserva aparte, con su fecha, y no se toca aqui.
    old_ids = [r[0] for r in conn.execute("SELECT id FROM clusters WHERE tema_id=?", (tema,))]
    if old_ids:
        ph = ",".join("?" * len(old_ids))
        conn.execute(f"DELETE FROM cluster_events WHERE cluster_id IN ({ph})", old_ids)
        conn.execute(f"DELETE FROM indicators WHERE cluster_id IN ({ph})", old_ids)
        conn.execute(f"DELETE FROM assessments WHERE cluster_id IN ({ph})", old_ids)
        conn.execute(f"DELETE FROM evidence WHERE cluster_id IN ({ph})", old_ids)
        conn.execute(f"DELETE FROM clusters WHERE id IN ({ph})", old_ids)
        conn.commit()
        print(f"      snapshot previo reemplazado: {len(old_ids)} clusters del tema '{tema}'")

    n_assessed = 0
    for label, s in summary.items():
        comp = {
            "synchronization": min(100, s.get("coordination_score", 0) * 12),
            "content_similarity": _content_score(details.get(label, {})),
            "amplification": min(100, amp * 100),
            "infrastructure": _infra_score(details.get(label, {})),
            "network_density": min(100, s.get("coordination_score", 0) * 6),
            "anomaly": min(100, s.get("anomaly_score", 0) * 100),
        }
        overall, _ = compute_scores(comp, cfg)
        band = band_for(overall, bands)

        # FIX: el historial (tabla findings) debe guardar el score que tenia el
        # cluster EN EL MOMENTO de deteccion, no su valor actual. cluster_summary
        # no devuelve overall_score, asi que lo inyectamos aqui para que
        # persist_findings_from_run(conn, narratives, summary, ...) lo persista
        # real (antes caia a 0 por .get("overall_score", 0)).
        summary[label]["overall_score"] = overall

        hyp = classify_hypotheses({**s, "accounts": s.get("accounts", 0)})
        att = attribution(hyp, infra_shared=_infra_score(details.get(label, {})) > 30)
        n_assessed += 1

        # guardar cluster
        cur = conn.execute(
            "INSERT INTO clusters (created_at, cluster_label, type, tema_id, coordination_score,"
            " amplification_score, anomaly_score, infrastructure_score, network_density,"
            " overall_score, confidence) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (int(time.time()), label, "mixed", tema, s.get("coordination_score", 0),
             comp["amplification"], comp["anomaly"], comp["infrastructure"],
             comp["network_density"], overall, att["confidence"]))
        cluster_id = cur.lastrowid
        # indicators
        for k, v in comp.items():
            conn.execute("INSERT INTO indicators (cluster_id, indicator, value, weight) VALUES (?,?,?,?)",
                         (cluster_id, k, round(v, 1), cfg["scoring"]["weights"].get(k, 0)))
        # assessments
        conn.execute(
            "INSERT INTO assessments (cluster_id, coordination_score, amplification_score,"
            " anomaly_score, infrastructure_score, network_density, overall_score, confidence,"
            " assessment, hypotheses_json, attribution, attribution_confidence,"
            " attribution_evidence, missing_evidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cluster_id, comp["synchronization"], comp["amplification"], comp["anomaly"],
             comp["infrastructure"], comp["network_density"], overall, att["confidence"],
             f"Cluster {label} con {s.get('accounts',0)} cuentas, banda {band}.",
             json.dumps(hyp, ensure_ascii=False), att["actor"], att["confidence"],
             att["evidence"], att["missing_evidence"]))
        # eventos miembros del cluster -> contenido real (para la UI)
        # cluster_events: 1 fila por evento que forma parte del cluster, con su
        # texto/titular y url originales. Permite explicar DE QUÉ habla el cluster.
        if sub_clustered is not None:
            _mem = sub_clustered[sub_clustered["cluster"] == label]
            for _, ev in _mem.iterrows():
                _txt = str(ev.get("text", "") or "").strip()[:500]
                if not _txt:
                    continue
                conn.execute(
                    "INSERT INTO cluster_events (cluster_id, ts, source, author, title, text, url)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (cluster_id,
                     int(ev.get("ts", 0)) if ev.get("ts") is not None else None,
                     str(ev.get("source", "") or ""),
                     str(ev.get("author", "") or ""),
                     str(_txt)[:200],
                     _txt,
                     str(ev.get("url", "") or "")))
    conn.commit()

    # --- REPORT ---
    print("[7/7] Informe")
    report = _build_report(df, summary, details, bands, amp, cascades, narratives, time.time() - t0)
    rep_path = ROOT / "reports" / f"fimi_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.md"
    rep_path.write_text(report, encoding="utf-8")

    # --- PERSISTIR hallazgos positivos (historial) + informe diario ---
    from detection.persistencia import persist_findings_from_run, build_daily_report, detectar_sostenidas
    inserted, total_findings = persist_findings_from_run(conn, narratives, summary, cascades, tema_id=tema)
    diario = build_daily_report(conn, narratives, list(summary.values()) if summary else [])
    daily_path = ROOT / "reports" / "informe_diario.md"
    daily_path.write_text(diario, encoding="utf-8")
    # narrativas sostenidas (misma narrativa en >=3 dias distintos = alerta elevada)
    sostenidas = detectar_sostenidas(conn, min_dias=3)
    print(f"      hallazgos nuevos: {inserted} (total historial: {total_findings})")
    print(f"      narrativas sostenidas (>=3 dias): {len(sostenidas)}")
    for s in sostenidas[:5]:
        print(f"        - {s['titulo'][:50]} · {s['dias']} dias")
    print(f"      informe diario: {daily_path}")
    conn.close()

    print(f"\nHecho en {time.time()-t0:.1f}s · {n_assessed} clusters evaluados")
    print(f"Informe: {rep_path}")
    print(f"BD: {args.db}")


def _content_score(detail):
    if not detail:
        return 0
    n = len(detail.get("representative_texts", []))
    return min(100, n * 25)


def _infra_score(detail):
    if not detail:
        return 0
    n = len(detail.get("top_urls", [])) + len(detail.get("top_domains", []))
    return min(100, n * 15)


def _build_report(df, summary, details, bands, amp, cascades, narratives, elapsed):
    lines = []
    lines.append("# European Hybrid & FIMI Radar — Informe")
    lines.append("")
    lines.append(f"- Eventos: {len(df)} · Cuentas: {df['author'].nunique()} · Tiempo: {elapsed:.1f}s")
    lines.append(f"- Señal global de amplificación: {amp:.2f}")
    lines.append(f"- Cascadas detectadas: {len(cascades)}")
    lines.append("")
    lines.append("## Clusters y atribución (agnóstica al actor)")
    lines.append("")
    if not summary:
        lines.append("No se detectaron clusters. La ausencia de señal es un resultado válido.")
    for label, s in summary.items():
        d = details.get(label, {})
        comp = {
            "synchronization": min(100, s.get("coordination_score", 0) * 12),
            "content_similarity": _content_score(d),
            "amplification": min(100, amp * 100),
            "infrastructure": _infra_score(d),
            "network_density": min(100, s.get("coordination_score", 0) * 6),
            "anomaly": min(100, s.get("anomaly_score", 0) * 100),
        }
        overall, _ = compute_scores(comp, load_bands(None))
        hyp = classify_hypotheses(s)
        att = attribution(hyp, infra_shared=comp["infrastructure"] > 30)
        lines.append(f"### {label} — {s.get('accounts',0)} cuentas")
        lines.append(f"- Coordinación {comp['synchronization']:.0f} · Amplificación {comp['amplification']:.0f} · "
                     f"Anomalía {comp['anomaly']:.0f} · Infraestructura {comp['infrastructure']:.0f} · "
                     f"Densidad red {comp['network_density']:.0f}")
        lines.append(f"- **Overall {overall:.0f}/100** · banda {band_for(overall, load_bands(None))}")
        lines.append(f"- Atribución: {att['actor']} · confianza {att['confidence']}")
        lines.append(f"- Hipótesis principal: {hyp[0]['label']} (score {hyp[0]['score']})")
        lines.append("")
        for h in hyp[:4]:
            lines.append(f"  - {h['hypothesis']} {h['label']}: {h['score']} — {h['reason'][:50]}")
        lines.append("")

    # Narrativas amplificadas (hecho observable: mismo titular en varias fuentes)
    lines.append("## Narrativas amplificadas (mismo contenido en varias fuentes)")
    lines.append("")
    if narratives:
        lines.append("| Narrativa | Fuentes | Eventos | Ventana |")
        lines.append("|---|---|---|---|")
        for n in narratives[:15]:
            lines.append(f"| {n['seed'][:50]} | {n['n_sources']} ({', '.join(n['source_names'][:4])}) | "
                         f"{n['n_events']} | {n['window_hours']}h |")
        lines.append("")
        lines.append("*Esto indica AMPLIFICACIÓN de una narrativa (una noticia se propaga), "
                     "no coordinación de cuentas. Sin atribución de actor.*")
    else:
        lines.append("Ninguna narrativa compartida por ≥3 fuentes distintas en esta ventana.")
    lines.append("")

    lines.append("## Advertencias metodológicas")
    lines.append("")
    lines.append("- Los scores indican posible actividad coordinada, NUNCA atribución por defecto.")
    lines.append("- La atribución se separa de la detección y requiere evidencia adicional.")
    lines.append("- La ausencia de atribución es un resultado analítico válido.")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
