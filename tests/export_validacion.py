#!/usr/bin/env python3
"""Exporta una MUESTRA ESTRATIFICADA de clusters para validación curada (ground truth).

Genera un CSV que el analista etiqueta a mano en la columna `label`:
    coordinado | no_coordinado | dudoso

Rúbrica:
  - coordinado     : el cluster refleja coordinación real entre cuentas
                     (publicación sincronizada de contenido compartido),
                     sea o no inauténtica.
  - no_coordinado  : eco de una pieza/noticia difundida por medios (no es
                     coordinación de cuentas) o actividad dispersa sin patrón.
  - dudoso         : no concluyente con la evidencia mostrada.

Por qué una muestra CONGELADA: los `cluster_label` NO son estables entre ciclos
(se regeneran cada 6 h). El CSV es el snapshot: incluye todo lo necesario para
juzgar cada cluster, y el cálculo (validacion_curada.py) se hace sobre ese mismo
fichero, así que las etiquetas nunca quedan huérfanas.

Uso:
  .venv/bin/python tests/export_validacion.py [--per-band 8] [--out data/validacion]
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

BANDS = [("CRITICAL", 80, 101), ("HIGH", 60, 80), ("ANOMALOUS", 40, 60), ("WATCH", 20, 40)]


def _netloc(u):
    m = re.match(r"https?://([^/]+)", u or "")
    return m.group(1).lower().replace("www.", "") if m else ""


def _lang(text):
    """Heurística de idioma (es/fr/en/tr/sv/de) sobre titulares+dominios."""
    t = " " + " ".join((text or "").lower().split()) + " "
    def c(words):
        return sum(t.count(" %s " % w) for w in words)
    es = c(["el","la","los","las","del","un","una","que","por","para","con","es","son","esta","mas","pero","como","cuando","sobre","tras","segun","gobierno","pais","contra","entre","desde","hasta","ceuta","espana","marruecos"]) + (3 if any(ch in t for ch in "áéíóúñ¿¡") else 0)
    fr = c(["les","des","une","du","dans","pour","avec","sur","est","qui","aux","cette","ont","ete","plus","comme","selon","gouvernement","france","rapport"])
    en = c(["the","of","and","to","in","is","are","was","with","for","from","that","this","has","have","will","said"])
    tr = c(["ve","bir","bu","icin","ile","olan","daha","gibi","olarak"])
    sv = c(["och","att","for","med","det","som","inte","har","den","till"])
    de = c(["der","die","das","und","mit","fur","auf","ist","nicht","eine","auch","sich"])
    sc = {"es": es, "fr": fr, "en": en, "tr": tr, "sv": sv, "de": de}
    return max(sc, key=sc.get) if max(sc.values()) > 0 else "?"


def _active_themes():
    try:
        import yaml
        c = yaml.safe_load(open(ROOT / "config.yaml"))
        return {t for t, m in (c.get("temas") or {}).items()
                if (m or {}).get("estado", "produccion") in ("produccion", "piloto")}
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-band", type=int, default=8, help="clusters muestreados por banda")
    ap.add_argument("--out", default=str(ROOT / "data" / "validacion"))
    ap.add_argument("--idioma", default=None, help="filtrar por idioma (p.ej. es)")
    args = ap.parse_args()
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M")
    csvp = outdir / f"muestra_{stamp}.csv"

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    activos = _active_themes()

    rows = []
    for name, lo, hi in BANDS:
        q = ("SELECT id, cluster_label, tema_id, overall_score, confidence "
             "FROM clusters WHERE overall_score>=? AND overall_score<? ")
        params = [lo, hi]
        if activos:
            q += "AND tema_id IN (%s) " % ",".join("?" * len(activos))
            params += list(activos)
        q += "ORDER BY RANDOM() LIMIT ?"
        params.append(max(args.per_band * 8, 60))
        _kept = 0
        for c in conn.execute(q, params):
            if _kept >= args.per_band:
                break
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
            _row = {
                "cluster_label": c["cluster_label"],
                "tema": c["tema_id"],
                "banda": name,
                "score": round(c["overall_score"], 1),
                "conf": c["confidence"],
                "n_eventos": len(evs),
                "n_cuentas": len(authors),
                "n_urls": len(set(urls)),
                "span_h": span_h,
                "top_dominios": " | ".join(f"{d}({n})" for d, n in doms.most_common(3)),
                "top_titulares": " || ".join(t[:90] for t, _ in titles.most_common(3)),
                "coord": round(a["coordination_score"], 1) if a else "",
                "anom": round(a["anomaly_score"], 1) if a else "",
                "infra": round(a["infrastructure_score"], 1) if a else "",
                "label": "",
                "nota": "",
            }
            if args.idioma and _lang(_row["top_titulares"] + " " + _row["top_dominios"]) != args.idioma:
                continue
            _kept += 1
            rows.append(_row)
    conn.close()

    cols = list(rows[0].keys()) if rows else ["cluster_label", "tema", "banda", "score", "label"]
    with open(csvp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"OK: {csvp}  ({len(rows)} clusters, {args.per_band}/banda)")
    print("Etiqueta la columna 'label' con: coordinado | no_coordinado | dudoso")
    return str(csvp)


if __name__ == "__main__":
    main()
