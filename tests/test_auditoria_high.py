#!/usr/bin/env python3
"""Tests de detection/auditoria_high.py.

Cubren: exclusión de <60, orden determinista, límites configurables (clusters,
eventos, longitud de texto), cadena señal->FIMI, prioridad de revisión, filtro por
tema y muestreo reproducible. Usan una BD SQLite temporal mínima (sin producción).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from detection.auditoria_high import (  # noqa: E402
    MISSING_EVIDENCE, auditar, evaluar_chain, resumen, review_priority,
    seleccionar_muestra, to_blind_csv, to_csv,
)

SCHEMA = """
CREATE TABLE clusters (id INTEGER PRIMARY KEY, created_at INT, cluster_label TEXT,
  type TEXT, tema_id TEXT, coordination_score REAL, amplification_score REAL,
  anomaly_score REAL, infrastructure_score REAL, network_density REAL,
  overall_score REAL, confidence TEXT, alternative_explanations TEXT,
  narrative_subtype TEXT);
CREATE TABLE assessments (id INTEGER PRIMARY KEY, cluster_id INTEGER UNIQUE,
  coordination_score REAL, amplification_score REAL, anomaly_score REAL,
  infrastructure_score REAL, network_density REAL, overall_score REAL,
  confidence TEXT, assessment TEXT, hypotheses_json TEXT, attribution TEXT,
  attribution_confidence TEXT, attribution_evidence TEXT, missing_evidence TEXT,
  kcore INT, kcore_size INT);
CREATE TABLE cluster_events (id INTEGER PRIMARY KEY, cluster_id INT, ts INT,
  source TEXT, author TEXT, title TEXT, text TEXT, url TEXT);
CREATE INDEX idx_ce ON cluster_events(cluster_id);
"""

_H = 3600


def _mk(tmp_path):
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    # A: HIGH con explicación benigna -> prioridad medium; anomaly alta
    con.execute(
        "INSERT INTO clusters (id, cluster_label, tema_id, coordination_score,"
        " amplification_score, anomaly_score, infrastructure_score, overall_score,"
        " alternative_explanations, narrative_subtype) VALUES (1,'tema_cluster_001',"
        "'espana_amenazas_hibridas',5.6,30,42,45,67.4,?,?)",
        (json.dumps([
            {"code": "mainstream_echo", "label": "Eco de prensa", "status": "supported", "evidence": {}},
            {"code": "unresolved", "label": "Sin explicación concluyente", "status": "ruled_out", "evidence": {}},
        ]), json.dumps({"dominant": "incident_report", "counts": {"incident_report": 2}})))
    con.execute(
        "INSERT INTO assessments (cluster_id, coordination_score, anomaly_score,"
        " infrastructure_score, kcore, kcore_size) VALUES (1,67.2,42,45,2,4)")
    # B: CRITICAL, sin explicación benigna (unresolved supported), anomaly baja
    con.execute(
        "INSERT INTO clusters (id, cluster_label, tema_id, coordination_score,"
        " amplification_score, anomaly_score, infrastructure_score, overall_score,"
        " alternative_explanations, narrative_subtype) VALUES (2,'tema_cluster_002',"
        "'espana_amenazas_hibridas',7.0,20,10,15,85,?,?)",
        (json.dumps([{"code": "unresolved", "label": "Sin explicación concluyente",
                      "status": "supported", "evidence": {}}]),
         json.dumps({"dominant": "potential_narrative", "counts": {}})))
    con.execute(
        "INSERT INTO assessments (cluster_id, coordination_score, anomaly_score,"
        " infrastructure_score, kcore, kcore_size) VALUES (2,84,10,15,1,2)")
    # C: WATCH (<60) -> debe excluirse
    con.execute(
        "INSERT INTO clusters (id, cluster_label, tema_id, overall_score) VALUES"
        " (3,'otro_cluster_000','otro',30)")
    # eventos A: 2 cuentas, 2 urls, 2 dominios, ventana ~18.4h, 1 texto largo
    evs = [
        (1, 0, "bluesky", "a1", "t", "x" * 500, "https://www.elmundo.es/n1"),
        (1, _H * 18, "bluesky", "a2", "t", "texto normal", "https://elpais.com/n2"),
        (1, _H * 18 + 60, "rss", "a2", "t", "otro", "https://www.elmundo.es/n1"),
        (2, 0, "bluesky", "b1", "t", "solo uno", "https://example.org/x"),
    ]
    con.executemany(
        "INSERT INTO cluster_events (cluster_id, ts, source, author, title, text, url)"
        " VALUES (?,?,?,?,?,?,?)", evs)
    con.commit()
    con.close()
    return str(db)


def _rec(records, label):
    return next(r for r in records if r["cluster_label"] == label)


def test_solo_high_critical_y_orden(tmp_path):
    db = _mk(tmp_path)
    records, trunc = auditar(db, cfg={})
    labels = [r["cluster_label"] for r in records]
    assert labels == ["tema_cluster_002", "tema_cluster_001"]  # score desc
    assert "otro_cluster_000" not in labels
    assert all(r["score"] >= 60 for r in records)
    assert trunc is False


def test_campos_y_metricas(tmp_path):
    db = _mk(tmp_path)
    records, _ = auditar(db, cfg={})
    a = _rec(records, "tema_cluster_001")
    assert a["banda"] == "HIGH"
    assert a["cuentas"] == 2
    assert a["eventos"] == 3
    assert a["urls_distintas"] == 2
    assert a["dominios_distintos"] == 2  # elmundo.es, elpais.com
    assert 18.0 <= a["ventana_horas"] <= 18.5
    assert a["coordinacion"] == 67.2      # del assessment (normalizado)
    assert a["anomalia"] == 42
    assert a["infraestructura"] == 45
    assert a["kcore"] == 2 and a["kcore_size"] == 4
    assert a["narrative_role"] == "incident_report"
    assert a["main_explanation"]["code"] == "mainstream_echo"
    assert len(a["missing_evidence"]) == len(MISSING_EVIDENCE)
    assert isinstance(a["alternative_explanations"], list)


def test_chain_no_confirma_fimi(tmp_path):
    db = _mk(tmp_path)
    records, _ = auditar(db, cfg={})
    ch = _rec(records, "tema_cluster_001")["chain"]
    assert ch["coordinacion_observable"]["status"] == "observed"
    assert ch["inautenticidad"]["status"] == "not_confirmed"
    assert ch["intencion"]["status"] == "not_confirmed"
    assert ch["dimension_extranjera"]["status"] == "not_confirmed"
    assert ch["fimi_confirmado"]["status"] == "requires_independent_evidence"


def test_review_priority_pura():
    assert review_priority("HIGH", 10, []) == "medium"
    assert review_priority("HIGH", 45, []) == "high"
    assert review_priority("CRITICAL", 10, []) == "high"
    benign = [{"code": "mainstream_echo", "status": "supported"}]
    assert review_priority("HIGH", 10, benign) == "low"
    assert review_priority("CRITICAL", 45, benign) == "medium"


def test_prioridad_en_registros(tmp_path):
    db = _mk(tmp_path)
    records, _ = auditar(db, cfg={})
    assert _rec(records, "tema_cluster_001")["review_priority"] == "medium"
    assert _rec(records, "tema_cluster_002")["review_priority"] == "high"


def test_limite_clusters(tmp_path):
    db = _mk(tmp_path)
    cfg = {"auditoria": {"max_clusters": 1}}
    records, _ = auditar(db, cfg=cfg)
    assert len(records) == 1
    assert records[0]["cluster_label"] == "tema_cluster_002"


def test_limites_eventos_y_texto(tmp_path):
    db = _mk(tmp_path)
    cfg = {"auditoria": {"max_events_per_cluster": 2, "max_text_len": 10}}
    records, _ = auditar(db, cfg=cfg)
    a = _rec(records, "tema_cluster_001")
    assert len(a["eventos_muestra"]) <= 2
    assert all(len(e["text"]) <= 10 for e in a["eventos_muestra"])


def test_filtro_tema(tmp_path):
    db = _mk(tmp_path)
    records, _ = auditar(db, cfg={}, tema="otro")
    assert records == []


def test_muestra_determinista(tmp_path):
    db = _mk(tmp_path)
    records, _ = auditar(db, cfg={})
    m1 = [r["cluster_label"] for r in seleccionar_muestra(records, 1, 7)]
    m2 = [r["cluster_label"] for r in seleccionar_muestra(records, 1, 7)]
    assert m1 == m2 and len(m1) == 1
    assert seleccionar_muestra(records, 99, 1) == sorted(records, key=lambda r: r["cluster_label"])


def test_exports(tmp_path):
    db = _mk(tmp_path)
    records, _ = auditar(db, cfg={})
    csv = to_csv(records)
    assert csv.splitlines()[0].startswith("cluster_label,tema,score,banda")
    assert "tema_cluster_001" in csv
    blind = to_blind_csv(records)
    head = blind.splitlines()[0]
    assert "label_inautenticidad" in head and "label_fimi" in head
    assert ",,,,," in blind.splitlines()[1]  # columnas de etiqueta vacías
    assert resumen(records)["n"] == 2


def test_load_bands_sin_config(tmp_path):
    # sin config, las bandas por defecto aplican (HIGH 60-79, CRITICAL 80-100)
    db = _mk(tmp_path)
    records, _ = auditar(db, cfg=None)
    assert _rec(records, "tema_cluster_002")["banda"] == "CRITICAL"
    assert _rec(records, "tema_cluster_001")["banda"] == "HIGH"
