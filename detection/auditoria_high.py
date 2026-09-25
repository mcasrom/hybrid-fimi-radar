#!/usr/bin/env python3
"""detection/auditoria_high.py — auditoría ligera y reproducible de HIGH/CRITICAL.

Objetivo: para cada cluster activo con score >= umbral (60 por defecto) producir un
registro **auditable** que:
  (a) resuma la señal observable (cuentas, eventos, URLs/dominios, ventana, componentes,
      k-core);
  (b) exponga las explicaciones alternativas y el rol narrativo YA persistidos;
  (c) separe explícitamente la **coordinación observable** de la **inautenticidad**,
      la **intención**, la **dimensión extranjera** y el **FIMI confirmado** (que
      exige evidencia independiente);
  (d) priorice la revisión humana.

Principios (acordados):
  - NO afirma que nada sea FIMI. NO toca score, bandas ni atribución.
  - NO usa red, LLMs, embeddings ni dependencias pesadas (solo stdlib + numpy-free).
  - NO recorre toda la BD: solo clusters >= umbral y sus eventos, con consultas
    indexables (`cluster_events.cluster_id`) y columnas mínimas.
  - Límites configurables (config.yaml -> auditoria) y timeout razonable.
  - Orden determinista y muestreo reproducible (seed) para una futura validación
    humana ciega.

CLI:
    python detection/auditoria_high.py                      # JSON a stdout
    python detection/auditoria_high.py --formato csv --out auditoria_high.csv
    python detection/auditoria_high.py --tema espana_amenazas_hibridas
    python detection/auditoria_high.py --formato blind --muestra 40 --seed 7 --out ciego.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import random
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from detection.explicaciones import principal as _principal  # noqa: E402
from detection.scoring import band_for, load_bands  # noqa: E402

DEFAULTS = {
    "min_score": 60,
    "max_clusters": 200,
    "max_events_per_cluster": 40,
    "max_text_len": 280,
    "max_urls_per_cluster": 200,
    "max_seconds": 30,
    "sample_seed": 20260924,
    # Nº de filas por defecto en `--formato blind` si no se pasa --muestra
    # (límite seguro y documentado para una revisión humana).
    "blind_default_muestra": 40,
}

# Explicaciones que, si están `supported`, rebajan la prioridad de revisión:
# describen difusión legítima / artefactos, no una posible operación.
BENIGN_SUPPORTED = {
    "single_source_feed", "mainstream_echo", "single_piece_echo", "organic_viral",
    "automated_non_malicious", "legitimate_mobilization", "graph_artifact",
}

# Evidencia que el radar NO produce por sí solo (cadena señal->FIMI).
MISSING_EVIDENCE = [
    "identidad o relación organizativa",
    "prueba de inautenticidad",
    "evidencia de intención",
    "evidencia de dimensión extranjera",
    "evidencia independiente de campaña (FIMI)",
]


def _cfg(cfg):
    """Límites efectivos: DEFAULTS <- config['auditoria']."""
    a = dict(DEFAULTS)
    a.update((cfg or {}).get("auditoria", {}) or {})
    return a


def _host(url):
    try:
        return urlparse(str(url or "")).netloc.replace("www.", "").lower()
    except Exception:
        return ""


def review_priority(band, anomaly, items, cfg=None):
    """Prioridad de revisión humana (pura): 'high' | 'medium' | 'low'.

    - base por banda: CRITICAL->high, HIGH->medium;
    - escala a high si la anomalía es alta (>= 40 por defecto);
    - des-escala si alguna explicación benigna está `supported`.
    """
    hi_anom = (_cfg(cfg)).get("priority_high_anomaly", 40)
    benign = any(it.get("status") == "supported" and it.get("code") in BENIGN_SUPPORTED
                 for it in (items or []))
    # Señal de coordinación real entre cuentas distintas -> prioridad alta siempre.
    if any(it.get("code") == "cross_account_synchrony" and it.get("status") == "supported"
           for it in (items or [])):
        return "high"
    p = {"CRITICAL": "high", "HIGH": "medium"}.get(band, "low")
    if (anomaly or 0) >= hi_anom:
        p = "high"
    if benign:
        p = {"high": "medium", "medium": "low", "low": "low"}[p]
    return p


def evaluar_chain(rec):
    """Separa explícitamente los eslabones señal->FIMI. Nadie confirma FIMI salvo
    evidencia independiente: el radar solo observa coordinación."""
    return {
        "coordinacion_observable": {
            "status": "observed",
            "evidence": {
                "score": rec.get("score"),
                "anomalia": rec.get("anomalia"),
                "kcore": rec.get("kcore"),
                "kcore_size": rec.get("kcore_size"),
            },
        },
        "inautenticidad": {
            "status": "not_confirmed",
            "note": "El radar no puede confirmar por sí solo que las cuentas sean falsas o inauténticas.",
        },
        "intencion": {
            "status": "not_confirmed",
            "note": "Mide forma (coordinación), no motivo ni finalidad.",
        },
        "dimension_extranjera": {
            "status": "not_confirmed",
            "note": "No dispone de dato de país/organización por cuenta.",
        },
        "fimi_confirmado": {
            "status": "requires_independent_evidence",
            "note": "Exige evidencia independiente (organizativa, financiera, contextual) y análisis humano.",
        },
    }


def _main_explanation(items):
    code = _principal(items or [])
    label = next((it.get("label") for it in (items or []) if it.get("code") == code), code)
    status = next((it.get("status") for it in (items or []) if it.get("code") == code), "")
    return {"code": code, "label": label, "status": status}


def _parse_json(raw, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception as e:
        print(f"[warn] auditoria_high: JSON inválido ({e})", file=sys.stderr)
        return default


def _components(row):
    """Componentes 0-100. Prefiere el assessment (ya normalizado: coordination_score
    = sync = coord*12); si no, deriva como run_fimi."""
    if row["a_coord"] is not None:
        coord = row["a_coord"] or 0
        anom = row["a_anom"] or 0
        infra = row["a_infra"] or 0
    else:
        coord = min(100.0, (row["coordination_score"] or 0) * 12)
        anom = row["anomaly_score"] or 0
        infra = row["infrastructure_score"] or 0
    return {
        "coordinacion": round(float(coord), 1),
        "anomalia": round(float(anom), 1),
        "infraestructura": round(float(infra), 1),
        "amplificacion": round(float(row["amplification_score"] or 0), 1),
    }


def _record(con, row, a, bands):
    cid = row["id"]
    agg = con.execute(
        "SELECT COUNT(*) n, COUNT(DISTINCT author) cuentas, COUNT(DISTINCT url) urls,"
        " MIN(ts) mn, MAX(ts) mx FROM cluster_events WHERE cluster_id=?",
        (cid,)).fetchone()
    n = agg["n"] or 0
    mn, mx = agg["mn"], agg["mx"]
    ventana = round(((mx - mn) / 3600.0), 1) if (mn is not None and mx is not None) else 0.0

    doms = set()
    if n:
        for (u,) in con.execute(
                "SELECT DISTINCT url FROM cluster_events WHERE cluster_id=? LIMIT ?",
                (cid, a["max_urls_per_cluster"])):
            h = _host(u)
            if h:
                doms.add(h)

    # Muestra acotada de eventos (textos truncados): permite auditar sin cargar
    # todo el cluster. Límites: max_events_per_cluster y max_text_len.
    muestra = []
    if n:
        for e in con.execute(
                "SELECT ts, source, author, substr(COALESCE(title,''),1,?) title,"
                " substr(COALESCE(text,''),1,?) text, url FROM cluster_events"
                " WHERE cluster_id=? ORDER BY ts ASC LIMIT ?",
                (a["max_text_len"], a["max_text_len"], cid, a["max_events_per_cluster"])):
            muestra.append({
                "ts": e["ts"], "source": e["source"], "author": e["author"],
                "title": e["title"], "text": e["text"], "url": e["url"],
            })

    comp = _components(row)
    items = _parse_json(row["alternative_explanations"], [])
    nsub = _parse_json(row["narrative_subtype"], {})
    band = band_for(row["overall_score"] or 0, bands)
    pri = review_priority(band, comp["anomalia"], items, a)

    rec = {
        "cluster_label": row["cluster_label"],
        "tema": row["tema_id"],
        "score": round(float(row["overall_score"] or 0), 1),
        "banda": band,
        "cuentas": agg["cuentas"] or 0,
        "eventos": n,
        "urls_distintas": agg["urls"] or 0,
        "dominios_distintos": len(doms),
        "ventana_horas": ventana,
        "anomalia": comp["anomalia"],
        "coordinacion": comp["coordinacion"],
        "infraestructura": comp["infraestructura"],
        "amplificacion": comp["amplificacion"],
        "kcore": row["kcore"] if row["kcore"] is not None else 0,
        "kcore_size": row["kcore_size"] if row["kcore_size"] is not None else 0,
        "narrative_role": (nsub or {}).get("dominant", ""),
        "main_explanation": _main_explanation(items),
        "alternative_explanations": items,
        "missing_evidence": list(MISSING_EVIDENCE),
        "review_priority": pri,
        "eventos_muestra": muestra,
    }
    rec["chain"] = evaluar_chain(rec)
    return rec


def auditar(db_path, cfg=None, limite=None, tema=None):
    """Devuelve la lista de registros de auditoría (clusters >= min_score).

    Solo lee `clusters` + `assessments` (join por cluster_id, índice único) y
    `cluster_events` por cluster (índice cluster_id) con LIMIT. No carga `events`.
    `cfg` es el dict de config.yaml (para banda y límites).
    """
    a = _cfg(cfg)
    maxc = a["max_clusters"]
    if limite is not None:
        maxc = min(maxc, int(limite))
    bands = load_bands(cfg)
    q = (
        "SELECT c.id, c.cluster_label, c.tema_id, c.overall_score,"
        " c.coordination_score, c.anomaly_score, c.infrastructure_score,"
        " c.amplification_score, c.alternative_explanations, c.narrative_subtype,"
        " a.coordination_score AS a_coord, a.anomaly_score AS a_anom,"
        " a.infrastructure_score AS a_infra, a.kcore, a.kcore_size"
        " FROM clusters c LEFT JOIN assessments a ON a.cluster_id = c.id"
        " WHERE c.overall_score >= ?")
    params = [a["min_score"]]
    if tema:
        q += " AND c.tema_id = ?"
        params.append(tema)
    q += " ORDER BY c.overall_score DESC, c.cluster_label ASC LIMIT ?"
    params.append(maxc)

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    t0 = time.time()
    out = []
    truncated = False
    try:
        for row in con.execute(q, params):
            if time.time() - t0 > a["max_seconds"]:
                truncated = True
                print("[warn] auditoria_high: timeout alcanzado; salida truncada",
                      file=sys.stderr)
                break
            out.append(_record(con, row, a, bands))
    finally:
        con.close()
    return out, truncated


def resumen(records):
    """Contadores agregados (para log/CLI)."""
    by_pri = {}
    by_band = {}
    for r in records:
        by_pri[r["review_priority"]] = by_pri.get(r["review_priority"], 0) + 1
        by_band[r["banda"]] = by_band.get(r["banda"], 0) + 1
    return {"n": len(records), "por_prioridad": by_pri, "por_banda": by_band}


def seleccionar_muestra(records, n, seed):
    """Muestra determinista (seed) para validación humana ciega.

    Ordena por `cluster_label` (estable entre ciclos de este snapshot) y toma `n`
    con `random.Random(seed)`; devuelve ordenado por label.
    """
    if not n or n >= len(records):
        return sorted(records, key=lambda r: r["cluster_label"])
    pool = sorted(records, key=lambda r: r["cluster_label"])
    rnd = random.Random(int(seed))
    return sorted(rnd.sample(pool, int(n)), key=lambda r: r["cluster_label"])


_COLS = ["cluster_label", "tema", "score", "banda", "cuentas", "eventos",
         "urls_distintas", "dominios_distintos", "ventana_horas", "coordinacion",
         "anomalia", "infraestructura", "amplificacion", "kcore", "kcore_size",
         "narrative_role", "main_explanation", "review_priority", "missing_evidence"]


def to_csv(records):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_COLS)
    for r in records:
        w.writerow([
            r["cluster_label"], r["tema"], r["score"], r["banda"], r["cuentas"],
            r["eventos"], r["urls_distintas"], r["dominios_distintos"],
            r["ventana_horas"], r["coordinacion"], r["anomalia"],
            r["infraestructura"], r["amplificacion"], r["kcore"], r["kcore_size"],
            r["narrative_role"], (r["main_explanation"] or {}).get("label", ""),
            r["review_priority"], "; ".join(r["missing_evidence"]),
        ])
    return buf.getvalue()


# Columnas del CSV CIEGO: solo evidencia bruta + componentes normalizados +
# columnas de anotación humana vacías. Sin etiquetas ni interpretaciones del sistema.
BLIND_COLS = [
    "cluster_label", "tema", "score", "banda",
    "cuentas", "eventos", "urls_distintas", "dominios_distintos", "ventana_horas",
    "coordinacion", "anomalia", "infraestructura", "amplificacion",
    "kcore", "kcore_size", "urls_evidencia", "textos_evidencia",
    "label_coordinacion", "label_inautenticidad", "label_intencion",
    "label_dimension_extranjera", "label_fimi", "notas",
]
# Columnas PROHIBIDAS en el CSV ciego (interpretación/etiqueta automática del sistema).
BLIND_FORBIDDEN = {
    "narrative_role", "main_explanation", "review_priority",
    "alternative_explanations", "hypotheses", "attribution", "missing_evidence",
    "chain", "explanation_summary",
}


def _blind_urls(r):
    seen, out = set(), []
    for e in (r.get("eventos_muestra") or []):
        u = str(e.get("url") or "").strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return "; ".join(out)


def _blind_textos(r):
    parts = []
    for e in (r.get("eventos_muestra") or []):
        t = str(e.get("title") or e.get("text") or "").replace("\n", " ").replace("\r", " ").strip()
        if t:
            parts.append(t)
    return " || ".join(parts)


def to_blind_csv(records):
    """CSV para validación humana CIEGA: solo evidencia bruta + componentes.

    NO incluye `narrative_role`, `main_explanation`, `review_priority`,
    `alternative_explanations`, `hypotheses` ni `attribution` (cegaría al anotador).
    Incluye los textos y URLs de evidencia y columnas `label_*` vacías para anotar.
    """
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(BLIND_COLS)
    for r in records:
        w.writerow([
            r["cluster_label"], r["tema"], r["score"], r["banda"],
            r["cuentas"], r["eventos"], r["urls_distintas"],
            r["dominios_distintos"], r["ventana_horas"],
            r["coordinacion"], r["anomalia"], r["infraestructura"],
            r["amplificacion"], r["kcore"], r["kcore_size"],
            _blind_urls(r), _blind_textos(r),
            "", "", "", "", "", "",
        ])
    return buf.getvalue()


def _load_cfg(config_path=None):
    import yaml
    p = Path(config_path) if config_path else (ROOT / "config.yaml")
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"[warn] auditoria_high: no pude leer config ({e})", file=sys.stderr)
        return {}


def main():
    ap = argparse.ArgumentParser(description="Auditoría ligera de clusters HIGH/CRITICAL.")
    ap.add_argument("--db", default=str(ROOT / "data" / "radar.db"))
    ap.add_argument("--config", default=None)
    ap.add_argument("--tema", default=None)
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--formato", choices=["json", "csv", "blind"], default="json")
    ap.add_argument("--muestra", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cfg = _load_cfg(args.config)
    a = _cfg(cfg)
    records, truncated = auditar(args.db, cfg, limite=args.limite, tema=args.tema)
    print(f"[auditoria_high] {resumen(records)} truncated={truncated}", file=sys.stderr)

    # Muestreo: en `blind` SIEMPRE se aplica (con `--muestra` o con el límite
    # seguro por defecto); en json/csv solo si se pide --muestra.
    muestra = args.muestra
    if args.formato == "blind" and not muestra:
        muestra = a.get("blind_default_muestra", 40)
    if muestra:
        records = seleccionar_muestra(records, muestra, args.seed or a["sample_seed"])
        print(f"[auditoria_high] muestra={len(records)} "
              f"(seed={args.seed or a['sample_seed']})", file=sys.stderr)

    if args.formato == "json":
        body = json.dumps({"records": records, "truncated": truncated,
                           "resumen": resumen(records)}, ensure_ascii=False, indent=2)
    elif args.formato == "csv":
        body = to_csv(records)
    else:
        body = to_blind_csv(records)

    if args.out:
        Path(args.out).write_text(body, encoding="utf-8")
        print(f"[auditoria_high] escrito {args.out}", file=sys.stderr)
    else:
        # sin salto de línea extra (evita una fila vacía al final del CSV)
        sys.stdout.write(body if body.endswith("\n") else body + "\n")
    return 0


if __name__ == "__main__":
    main()
