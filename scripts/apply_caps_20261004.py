#!/usr/bin/env python3
"""One-off (4-Oct): aplica a los scores YA almacenados los dos topes nuevos
— `meta_coverage_cap` (rol dominante meta_analysis) y `single_domain_cap`
(>=0.9 de enlaces de un mismo dominio) — para reflejar en el dashboard, sin
re-ejecutar todo el pipeline. La lógica permanente vive en detection/scoring.py
y detection/run_fimi.py; esto solo reconcilia la BD actual.

Uso: .venv/bin/python scripts/apply_caps_20261004.py [--aplicar]
Sin --aplicar: dry-run (solo informa).
"""
import json
import sqlite3
import sys
from urllib.parse import urlparse

DB = "data/radar.db"
CAP = 59.0                      # tope de ANOMALOUS
MIN_DDF = 0.9                   # single_domain_cap.min_domain_frac
META = {"meta_analysis"}        # meta_coverage_cap.subtypes
APLICAR = "--aplicar" in sys.argv


def _host(u):
    try:
        h = urlparse(str(u)).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, cluster_label, tema_id, overall_score, narrative_subtype "
        "FROM clusters WHERE overall_score > ?", (CAP,)).fetchall()
    cambios = []
    for c in rows:
        try:
            ns = json.loads(c["narrative_subtype"] or "{}")
        except Exception:
            ns = {}
        meta = ns.get("dominant") in META
        ev = con.execute("SELECT url FROM cluster_events WHERE cluster_id=?", (c["id"],)).fetchall()
        hs = [_host(r["url"]) for r in ev if r["url"]]
        hs = [h for h in hs if h]
        ddf = (max(hs.count(h) for h in set(hs)) / len(hs)) if hs else 0.0
        if meta or ddf >= MIN_DDF:
            cambios.append((c["id"], c["cluster_label"], c["overall_score"], meta, ddf))
    print(f"clusters > {CAP}: {len(rows)} · a topar: {len(cambios)}")
    for _id, lab, sc, meta, ddf in cambios:
        print(f"  {lab:34} {sc:.1f} -> {CAP:.0f}  meta={int(meta)} ddf={ddf:.2f}")
    if APLICAR:
        for _id, *_ in cambios:
            con.execute("UPDATE clusters SET overall_score=? WHERE id=? AND overall_score>?", (CAP, _id, CAP))
        con.commit()
        print("APLICADO")
    else:
        print("(dry-run; usa --aplicar para escribir)")


if __name__ == "__main__":
    main()
