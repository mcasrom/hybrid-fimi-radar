#!/usr/bin/env python3
"""Tests de detection/auditoria_subtipos.py.

Cubren: agrupación por rol dominante (incluido 'sin_rol'), muestreo reproducible
(seed) y homogéneo por rol, y CSV bien formado. Usan una BD temporal mínima.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys  # noqa: E402
sys.path.insert(0, str(ROOT))

from detection.auditoria_subtipos import (  # noqa: E402
    agrupar, emitir_csv, seleccionar_muestra,
)

SCHEMA = """
CREATE TABLE clusters (id INTEGER PRIMARY KEY, cluster_label TEXT, overall_score REAL,
  confidence TEXT, alternative_explanations TEXT, narrative_subtype TEXT);
CREATE TABLE cluster_lineage (id INTEGER PRIMARY KEY, cluster_label TEXT, lineage_id TEXT);
CREATE TABLE cluster_events (id INTEGER PRIMARY KEY, cluster_id INT, ts INT, source TEXT,
  author TEXT, title TEXT, text TEXT, url TEXT);
"""


def _mk(tmp_path):
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    def cl(i, label, rol):
        con.execute(
            "INSERT INTO clusters (id, cluster_label, overall_score, confidence,"
            " alternative_explanations, narrative_subtype) VALUES (?,?,?,?,?,?)",
            (i, label, 62.0, "NO_ATTRIBUTION", "[]",
             json.dumps({"dominant": rol, "counts": {rol: 2}}) if rol else None))
        con.execute("INSERT INTO cluster_lineage (cluster_label, lineage_id) VALUES (?,?)",
                    (label, f"{label}@123"))
        for j in range(3):
            con.execute(
                "INSERT INTO cluster_events (cluster_id, ts, source, author, title, text, url)"
                " VALUES (?,?,?,?,?,?,?)",
                (i, 1700000000 + j, "bluesky", f"cuenta_{j}", f"titulo {label} {j}", "", "https://x"))
    cl(1, "tema_cluster_001", "official_response")
    cl(2, "tema_cluster_002", "incident_report")
    cl(3, "tema_cluster_003", "meta_analysis")
    cl(4, "tema_cluster_004", None)   # sin rol
    con.commit()
    con.row_factory = sqlite3.Row
    return con


def test_agrupar(tmp_path):
    con = _mk(tmp_path)
    g = agrupar(con)
    assert g["official_response"], "rol dominante detectado"
    assert g["sin_rol"], "clusters sin narrative_subtype caen en sin_rol"
    assert len(g["official_response"]) == 1
    con.close()


def test_seleccionar_reproducible(tmp_path):
    con = _mk(tmp_path)
    g = agrupar(con)
    a = seleccionar_muestra(g, muestra=1, sin_rol=1, seed=7)
    b = seleccionar_muestra(g, muestra=1, sin_rol=1, seed=7)
    assert [(r, x["cluster_label"]) for r, x in a[0]] == \
           [(r, x["cluster_label"]) for r, x in b[0]], "mismo seed -> misma muestra"
    # una por rol, incluido sin_rol
    roles = sorted(r for r, _ in a[0])
    assert roles == ["incident_report", "meta_analysis", "official_response", "sin_rol"]
    con.close()


def test_csv_completo(tmp_path):
    con = _mk(tmp_path)
    g = agrupar(con)
    sel, _ = seleccionar_muestra(g, muestra=1, sin_rol=1, seed=7)
    out = tmp_path / "muestra.csv"
    emitir_csv(con, sel, k=2, max_text_len=80,
               bands={"NORMAL": (0, 19), "WATCH": (20, 39), "ANOMALOUS": (40, 59),
                      "HIGH": (60, 79), "CRITICAL": (80, 100)},
               out=str(out), delim=";")
    rows = list(csv.reader(open(out, encoding="utf-8"), delimiter=";"))
    assert len(rows) == 1 + 4, "cabecera + 4 clusters"
    assert rows[0][-2:] == ["rol_anotado", "observaciones"]
    assert all(r[-2] == "" for r in rows[1:]), "rol_anotado vacío para el anotador"
    con.close()