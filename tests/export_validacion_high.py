#!/usr/bin/env python3
"""Muestra ESTRATIFICADA POR TEMA de clusters en banda alta (score>=60) para
validacion curada (ground truth). Ciega: NO incluye sugerencias del asistente.

Genera un CSV que el analista etiqueta en la columna `label`:
    coordinado | no_coordinado | dudoso

Rubrica:
  - coordinado    : el cluster refleja coordinacion real entre cuentas
                    (publicacion sincronizada de contenido compartido),
                    sea o no inautentica.
  - no_coordinado : eco de una pieza/noticia difundida por medios (no es
                    coordinacion de cuentas) o actividad dispersa sin patron.
  - dudoso        : no concluyente con la evidencia mostrada.

Uso:
  .venv/bin/python tests/export_validacion_high.py [--per-theme 8] [--min-score 60]
"""
import argparse
import csv
import datetime
import re
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"


def _netloc(u):
    m = re.match(r"https?://([^/]+)", u or "")
    return m.group(1).lower().replace("www.", "") if m else ""


def _band(s):
    return ("CRITICAL" if s >= 80 else "HIGH" if s >= 60 else
            "ANOMALOUS" if s >= 40 else "WATCH" if s >= 20 else "NORMAL")


def _active_themes():
    try:
        import yaml
        c = yaml.safe_load(open(ROOT / "config.yaml"))
        return [t for t, m in (c.get("temas") or {}).items()
                if (m or {}).get("estado", "produccion") in ("produccion", "piloto")]
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-theme", type=int, default=8, help="clusters muestreados por tema")
    ap.add_argument("--min-score", type=float, default=60.0)
    ap.add_argument("--out", default=str(ROOT / "data" / "validacion"))
    args = ap.parse_args()
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M")
    csvp = outdir / f"muestra_high_{stamp}.csv"

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    activos = _active_themes()

    rows = []
    for t in (activos or []):
        q = ("SELECT id, cluster_label, tema_id, overall_score, confidence "
             "FROM clusters WHERE tema_id=? AND overall_score>=? ORDER BY RANDOM() LIMIT ?")
        for c in conn.execute(q, (t, args.min_score, args.per_theme)):
            cid = c["id"]
            evs = conn.execute(
                "SELECT ts, author, title, url FROM cluster_events WHERE cluster_id=?",
                (cid,)).fetchall()
            authors = {e["author"] for e in evs}
            urls = [e["url"] for e in evs if e["url"]]
            doms = Counter(_netloc(u) for u in urls if _netloc(u))
            titles = Counter((e["title"] or "").strip() for e in evs if (e["title"] or "").strip())
            tss = [e["ts"] for e in evs if e["ts"]]
            span_h = round((max(tss) - min(tss)) / 3600, 1) if len(tss) > 1 else 0
            a = conn.execute(
                "SELECT coordination_score, anomaly_score, infrastructure_score "
                "FROM assessments WHERE cluster_id=?", (cid,)).fetchone()
            rows.append({
                "cluster_label": c["cluster_label"],
                "tema": c["tema_id"],
                "banda": _band(c["overall_score"]),
                "score": round(c["overall_score"], 1),
                "n_eventos": len(evs),
                "n_cuentas": len(authors),
                "n_urls": len(set(urls)),
                "span_h": span_h,
                "top_dominios": " | ".join(f"{d}({n})" for d, n in doms.most_common(4)),
                "top_titulares": " || ".join(t[:110] for t, _ in titles.most_common(3)),
                "coord": round(a["coordination_score"], 1) if a else "",
                "anom": round(a["anomaly_score"], 1) if a else "",
                "infra": round(a["infrastructure_score"], 1) if a else "",
                "label": "",
                "nota": "",
            })
    conn.close()

    cols = list(rows[0].keys()) if rows else ["cluster_label", "tema", "score", "label"]
    with open(csvp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    by = Counter(r["tema"] for r in rows)
    print(f"OK: {csvp}  ({len(rows)} clusters >= {args.min_score:.0f}, {args.per_theme}/tema)")
    print("  por tema:", dict(by))
    print("Etiqueta la columna 'label' con: coordinado | no_coordinado | dudoso")
    return str(csvp)


if __name__ == "__main__":
    main()
