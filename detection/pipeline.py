#!/usr/bin/env python3
"""Orquestador: carga dataset → features → anomalías → coordinación → clusters →
informe. Modo offline, sin servicios externos.

Uso:
    python scripts/run_analysis.py --input data/synthetic/events.csv
    python scripts/run_analysis.py --input data/synthetic/events.csv --report
"""
import argparse
import json
import sys
import time
from pathlib import Path

import yaml
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.ingest import load, normalize
from src.features import build_features
from src.anomaly import detect_anomalies
from src.coordination import build_edges
from src.bot_signals import bot_signal_score
from src.fakenews import detect_cascades, amplification_signal
from src.clustering import cluster_by_components, cluster_summary


def load_config(path=None):
    path = path or ROOT / "config.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--config", default=None)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--outdir", default=ROOT / "data" / "processed")
    args = ap.parse_args()

    config = load_config(args.config)
    t0 = time.time()

    print(f"[1/6] Cargando {args.input} ...")
    raw = load(args.input)
    df = normalize(raw)
    print(f"      {len(df)} eventos, {df['author'].nunique()} cuentas")

    print("[2/6] Extrayendo características por cuenta ...")
    feat_df = build_features(df, config)
    print(f"      {len(feat_df)} cuentas con características")

    print("[3/6] Señales de automatización (bot signals) ...")
    bs = {}
    for a in feat_df.index:
        bs[a] = bot_signal_score(feat_df.loc[a].to_dict())
    feat_df["bot_signal"] = [bs[a][0] for a in feat_df.index]

    print("[4/6] Detección de anomalías (Isolation Forest) ...")
    scored, thresh = detect_anomalies(feat_df, config)
    print(f"      umbral anomalía (p={config['thresholds']['anomaly_percentile']}): {thresh:.3f}")

    print("[5/6] Coordinación (grafo ponderado) ...")
    edges = build_edges(df, config)
    graph_n = len({n for e in edges for n in (e["source"], e["target"])})
    print(f"      {len(edges)} aristas, {graph_n} cuentas conectadas")
    cascades = detect_cascades(df, config)
    amp = amplification_signal(pd.DataFrame(edges) if edges else __import__("pandas").DataFrame(), df["author"].nunique())
    print(f"      cascadas detectadas: {len(cascades)}")

    print("[6/6] Clustering (componentes conexas del grafo de coordinación) ...")
    edges_df = pd.DataFrame(edges) if edges else pd.DataFrame(columns=["source", "target", "weight", "evidence"])
    merged = cluster_by_components(scored, edges_df, config)
    summary = cluster_summary(merged, edges_df, config)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # evidencia concreta por cluster (URLs, textos, hashtags, condiciones)
    details = {}
    if merged["cluster_label"].notna().any():
        from src.clustering import cluster_evidence_details
        for label in merged["cluster_label"].dropna().unique():
            mem = merged[merged["cluster_label"] == label]
            details[label] = cluster_evidence_details(df, label, mem, edges_df)
        with open(outdir / "evidence_details.json", "w", encoding="utf-8") as f:
            json.dump(details, f, ensure_ascii=False, indent=1)

        # eventos BRUTOS por cluster (para lectura no ciega): con fecha legible
        ev_idx = merged["cluster_label"].notna()
        sub = df[df["author"].isin(merged[ev_idx].index)].copy()
        lab_map = merged.loc[merged[ev_idx].index, "cluster_label"]
        sub["cluster"] = sub["author"].map(lab_map)
        sub["fecha_utc"] = pd.to_datetime(sub["ts"], unit="s", utc=True).dt.strftime("%Y-%m-%d %H:%M:%S")
        sub[["cluster", "fecha_utc", "author", "text", "url", "hashtags", "action"]].to_csv(
            outdir / "cluster_events.csv", index=False, encoding="utf-8")

    # guardar salidas
    merged.reset_index().to_csv(outdir / "scores.csv", index=False)
    edges_df.to_csv(outdir / "edges.csv", index=False)

    clusters_df = None
    if summary:
        rows = []
        for c in summary.values():
            rows.append({
                "cluster": c["cluster"], "accounts": c["accounts"],
                "events": c["events"], "coordination_score": c["coordination_score"],
                "anomaly_score": c["anomaly_score"],
                "evidence": json.dumps(c["evidence"], ensure_ascii=False),
            })
        clusters_df = __import__("pandas").DataFrame(rows).sort_values("coordination_score", ascending=False)
        clusters_df.to_csv(outdir / "clusters.csv", index=False)

    elapsed = time.time() - t0
    print(f"\nHecho en {elapsed:.1f}s")
    print(f"Salidas en {outdir}/")

    if args.report:
        write_report(df, merged, clusters_df, edges_df, cascades, amp, outdir, config, elapsed)
        print(f"Informe: {outdir / '..' / 'reports'}")


def write_report(df, scored, clusters_df, edges_df, cascades, amp, outdir, config, elapsed):
    rep_dir = ROOT / "reports"
    rep_dir.mkdir(exist_ok=True)
    import datetime
    fname = rep_dir / f"report_{datetime.date.today().strftime('%Y%m%d')}.md"
    lines = []
    lines.append("# Informe ECR — Electoral Coordination Radar")
    lines.append("")
    lines.append(f"- Fecha: {datetime.datetime.now().isoformat()}")
    lines.append(f"- Eventos analizados: {len(df)}")
    lines.append(f"- Cuentas analizadas: {df['author'].nunique()}")
    lines.append(f"- Tiempo de procesamiento: {elapsed:.1f}s")
    lines.append("")
    lines.append("## Clusters detectados")
    lines.append("")
    if clusters_df is not None and not clusters_df.empty:
        lines.append("| Cluster | Cuentas | Eventos | Coord | Anomalía |")
        lines.append("|---|---|---|---|---|")
        for _, r in clusters_df.iterrows():
            lines.append(f"| {r['cluster']} | {r['accounts']} | {r['events']} | {r['coordination_score']} | {r['anomaly_score']} |")
        lines.append("")
        lines.append("### Evidencias por cluster")
        lines.append("")
        details = {}
        det_file = outdir / "evidence_details.json"
        if det_file.exists():
            details = json.loads(det_file.read_text(encoding="utf-8"))
        for _, r in clusters_df.iterrows():
            ev = json.loads(r["evidence"]) if isinstance(r["evidence"], str) else r["evidence"]
            lines.append(f"**{r['cluster']}** ({r['accounts']} cuentas)")
            if ev:
                for k, v in ev.items():
                    lines.append(f"- {k}: {v}")
            else:
                lines.append("- (sin aristas internas)")
            d = details.get(r["cluster"], {})
            if d:
                lines.append("")
                lines.append(f"  *URLs compartidas:* {', '.join(f'{u} (×{n})' for u, n in d.get('top_urls', [])[:5]) or '—'}")
                lines.append(f"  *Dominios:* {', '.join(f'{u} (×{n})' for u, n in d.get('top_domains', [])[:4]) or '—'}")
                lines.append(f"  *Hashtags:* {', '.join(f'#{u} (×{n})' for u, n in d.get('top_hashtags', [])[:5]) or '—'}")
                texts = d.get("representative_texts", [])[:3]
                if texts:
                    lines.append(f"  *Textos representativos:*")
                    for t, n in texts:
                        lines.append(f"    - \"{t[:90]}\" (×{n})")
                conds = d.get("conditions", [])
                if conds:
                    lines.append(f"  *Condiciones que lo agrupan:* {', '.join(f'{c} (×{n})' for c, n in conds)}")
                accs = d.get("accounts_sample", [])
                if accs:
                    lines.append(f"  *Cuentas (muestra):* {', '.join(accs[:15])}")
            lines.append("")
    else:
        lines.append("No se detectaron clusters.")
        lines.append("")
    lines.append("## Cascadas de amplificación (posible propagación artificial)")
    lines.append("")
    if cascades:
        lines.append("| cuentas | eventos | span_s | velocidad(acc/h) |")
        lines.append("|---|---|---|---|")
        for c in cascades[:20]:
            lines.append(f"| {c['n_accounts']} | {c['n_events']} | {c['time_span_s']} | {c['speed_accounts_hour']} |")
    else:
        lines.append("Ninguna.")
    lines.append("")
    lines.append(f"## Señal global de amplificación: {amp:.3f}")
    lines.append("")

    # Cuentas anómalas (aunque no formen cluster)
    if "anomaly_score" in scored.columns:
        anom = scored[scored["anomaly_score"] > 0.5].sort_values("anomaly_score", ascending=False)
        lines.append("## Cuentas anómalas (sin cluster, señal individual)")
        lines.append("")
        lines.append("| Cuenta | Eventos | Anomalía | bot_signal | Concentración 1h |")
        lines.append("|---|---|---|---|---|")
        for a, r in anom.head(15).iterrows():
            lines.append(f"| {a} | {int(r.get('n_events',0))} | {r['anomaly_score']:.2f} | "
                         f"{r.get('bot_signal',0):.2f} | {r.get('max_concentration_1h',0):.2f} |")
        lines.append("")
        lines.append("*Son cuentas con comportamiento estadísticamente desviado en ESTA captura. "
                     "Sin acumulación temporal aún no forman cluster: se requiere historia (cron 6h).*")
        lines.append("")

    lines.append("## Advertencias metodológicas")
    lines.append("")
    lines.append("- Los scores indican **posible actividad coordinada o inorgánica**, nunca atribuyen actor, país o partido.")
    lines.append("- Los clusters son candidatos a investigación humana; requieren verificación OSINT adicional.")
    lines.append("- Sin LLM, sin APIs comerciales, sin embeddings remotos: todo es estadística clásica sobre datos observados.")
    with open(fname, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Informe: {fname}")


if __name__ == "__main__":
    main()
