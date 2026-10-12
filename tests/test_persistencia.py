"""Tests de persistencia de hallazgos (fix 11-oct, bug #5).

cluster_label NO es estable entre ciclos (DELETE + re-INSERT por tamaño cada
6h), y la misma historia cambia de etiqueta -> los findings tipo 'cluster' se
duplicaban por día (medido: 31k filas / 2k títulos). La clave de dedup pasa a
ser el "tema dominante" (texto real del cluster), y el label queda en detalle.
"""
import sqlite3

import detection.persistencia as p


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE findings(id INTEGER PRIMARY KEY AUTOINCREMENT, fecha INTEGER,"
        " tipo TEXT, titulo TEXT, detalle TEXT, n_sources REAL, n_events REAL,"
        " window_hours REAL, fuentes TEXT, intensidad REAL, url TEXT, tema_id TEXT);"
        "CREATE TABLE finding_evidence(finding_id INTEGER, ts INTEGER, source TEXT,"
        " author TEXT, title TEXT, text TEXT, url TEXT);"
        "CREATE TABLE cluster_events(cluster_id INTEGER, ts INTEGER, source TEXT,"
        " author TEXT, title TEXT, text TEXT, url TEXT);"
        "CREATE TABLE clusters(id INTEGER PRIMARY KEY, cluster_label TEXT,"
        " tema_id TEXT, overall_score REAL);")
    conn.commit()
    return conn


def _cluster(label, topic, score=61.0):
    return {"cluster": label, "overall_score": score, "accounts": 5,
            "events": 20, "evidence": {"near_duplicate": 3},
            "topic_dominant": topic}


def _seed_ce(conn, label, cid):
    conn.execute("INSERT INTO clusters VALUES (?,?,?,?)",
                 (cid, label, "tema_x", 61.0))
    conn.execute("INSERT INTO cluster_events VALUES (?,?,?,?,?,?,?)",
                 (cid, 1700000000, "bsky:pepe", "pepe", "t", "Titulo", "http://x"))
    conn.commit()


def _totales(conn):
    return conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]


def test_misma_historia_distinto_label_no_duplica():
    """La misma historia con 2 etiquetas distintas el mismo dia -> 1 finding."""
    conn = _conn()
    _seed_ce(conn, "tema_x_cluster_000", 1)
    _seed_ce(conn, "tema_x_cluster_045", 2)
    n, _ = p.persist_findings(
        conn, [], [_cluster("tema_x_cluster_000", "Casus belli en el Sahel"),
                   _cluster("tema_x_cluster_045", "Casus belli en el Sahel")],
        tema_id="sahel")
    assert n == 1, "el dedup por tema dominante debe colapsar las 2 etiquetas"
    assert _totales(conn) == 1


def test_distintas_historias_mismo_dia_si_insertan():
    conn = _conn()
    _seed_ce(conn, "tema_x_cluster_000", 1)
    _seed_ce(conn, "tema_x_cluster_001", 3)
    n, _ = p.persist_findings(
        conn, [], [_cluster("tema_x_cluster_000", "Historia A"),
                   _cluster("tema_x_cluster_001", "Historia B")])
    assert n == 2
    assert _totales(conn) == 2


def test_misma_historia_en_dias_distintos_si_se_repite():
    """La misma historia en dias distintos SÍ debe persistir (es la materia de
    'narrativas sostenidas') y el dedup solo es por dia."""
    conn = _conn()
    _seed_ce(conn, "tema_x_cluster_000", 1)
    _seed_ce(conn, "tema_x_cluster_001", 3)
    original_today, original_epoch = p._today, p._epoch_day
    # _epoch_day también debe seguir al día simulado: si no, la fila guarda la
    # fecha REAL y el test solo pasa el día en que se escribió (12-oct-2026).
    from datetime import datetime, timezone

    def _ep(fecha):
        return int(datetime.strptime(fecha, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())

    try:
        p._today = lambda: "2026-10-11"
        p._epoch_day = lambda: _ep("2026-10-11")
        n1, _ = p.persist_findings(conn, [], [_cluster("tema_x_cluster_000", "Historia X")])
        p._today = lambda: "2026-10-12"
        p._epoch_day = lambda: _ep("2026-10-12")
        n2, _ = p.persist_findings(conn, [], [_cluster("tema_x_cluster_000", "Historia X")])
    finally:
        p._today, p._epoch_day = original_today, original_epoch
    assert n1 == 1 and n2 == 1
    assert _totales(conn) == 2


def test_label_queda_en_detalle_para_trazabilidad():
    conn = _conn()
    _seed_ce(conn, "satel_cluster_099", 4)
    p.persist_findings(conn, [], [_cluster("satel_cluster_099", "Historia Y")])
    row = conn.execute("SELECT titulo, detalle FROM findings").fetchone()
    assert row[0] == "Historia Y"
    assert "satel_cluster_099" in row[1]


def test_snapshot_evidencia_usa_el_label_del_cluster():
    conn = _conn()
    _seed_ce(conn, "tema_x_cluster_007", 5)
    p.persist_findings(conn, [], [_cluster("tema_x_cluster_007", "Ciber")])
    n_ev = conn.execute("SELECT COUNT(*) FROM finding_evidence").fetchone()[0]
    assert n_ev == 1