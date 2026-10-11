"""Tests de los indicadores de forma de cluster (fix 11-oct).

El bug: `_indicadores_clusters` clasificaba como "eco_1_pieza" cualquier
cluster con `n_urls <= 1`, así que los clusters SIN enlace (n_urls == 0,
contenido de texto copiado) se etiquetaban como eco de una pieza. El fix exige
EXACTAMENTE 1 URL para "eco de 1 pieza" y admite `n_urls == 0` en la ventana
sostenida (para no perder la señal text-only).
"""
import sqlite3

from detection.indicadores import _indicadores_clusters


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE clusters(id INTEGER PRIMARY KEY, cluster_label TEXT,"
        " tema_id TEXT, overall_score REAL);"
        "CREATE TABLE cluster_events(cluster_id INTEGER, author TEXT, url TEXT,"
        " ts INTEGER);")
    return conn


def _add(conn, cid, label, score, n_ev, n_auth, url, span_h):
    conn.execute("INSERT INTO clusters VALUES (?,?,?,?)", (cid, label, "tema_x", score))
    for i in range(n_ev):
        author = "a%d" % (i % n_auth)
        ts = 1_700_000_000 + int(span_h * 3600 * i / max(1, n_ev - 1))
        conn.execute("INSERT INTO cluster_events VALUES (?,?,?,?)", (cid, author, url, ts))
    conn.commit()


def _tipos(conn):
    ind = _indicadores_clusters(conn)
    return {t["label"]: t["tipo"] for t in ind["top"]}, ind["resumen"]


def test_sin_url_sostenida_no_es_eco():
    conn = _conn()
    _add(conn, 1, "sin_url_sostenida", 61.0, n_ev=12, n_auth=3, url=None, span_h=30)
    tipos, resumen = _tipos(conn)
    assert tipos["sin_url_sostenida"] == "coordinacion_sostenida"
    assert "eco_1_pieza" not in resumen


def test_una_url_sigue_siendo_eco():
    conn = _conn()
    _add(conn, 1, "un_enlace", 55.0, n_ev=4, n_auth=3, url="http://x/1", span_h=40)
    tipos, resumen = _tipos(conn)
    assert tipos["un_enlace"] == "eco_1_pieza"
    assert resumen.get("eco_1_pieza") == 1


def test_sin_url_rafaga():
    conn = _conn()
    _add(conn, 1, "sin_url_rafaga", 50.0, n_ev=6, n_auth=4, url=None, span_h=1)
    tipos, _ = _tipos(conn)
    assert tipos["sin_url_rafaga"] == "rafaga"


def test_sin_url_pocos_eventos_no_clasifica():
    conn = _conn()
    _add(conn, 1, "sin_url_ruido", 30.0, n_ev=2, n_auth=2, url=None, span_h=50)
    tipos, resumen = _tipos(conn)
    assert "sin_url_ruido" not in tipos
    assert resumen == {}
