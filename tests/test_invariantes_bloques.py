"""Tests de invariantes de bloques analíticos (evitan degeneraciones en producción).

Regresión del bug del 23/Sep: 'Narrativas alineadas' generaba un mega-grupo
(703 clusters) por encadenamiento transitivo (union-find / single-linkage).
El bloque ahora debe respetar un tope de miembros.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detection import narrativas_alineadas as na  # noqa: E402


def _con_encadenado(n=40):
    """n clusters que comparten tokens solo con sus vecinos (i con i+1).

    Con union-find clásico esto forma UNA componente (cadena completa); con el
    corte por comunidades debe quedar acotado a <= _MAX_MIEMBROS.
    """
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE clusters (id INTEGER PRIMARY KEY, created_at INT,"
                " cluster_label TEXT, type TEXT, coordination_score REAL,"
                " amplification_score REAL, anomaly_score REAL, infrastructure_score REAL,"
                " network_density REAL, overall_score REAL, confidence TEXT, tema_id TEXT)")
    con.execute("CREATE TABLE cluster_events (id INTEGER PRIMARY KEY, cluster_id INT,"
                " ts INT, source TEXT, author TEXT, title TEXT, text TEXT, url TEXT)")
    for i in range(n):
        con.execute("INSERT INTO clusters (id, cluster_label, tema_id, overall_score)"
                    " VALUES (?,?,?,?)", (i, f"tema_cluster_{i:03d}", "tema", 50.0))
        a, b = f"tokenpuente{i}", f"tokenpuente{i + 1}"
        for j, u in enumerate(("ua", "ub")):  # >=2 eventos por cluster
            con.execute("INSERT INTO cluster_events (cluster_id, ts, source, author, text)"
                        " VALUES (?,?,?,?,?)",
                        (i, j, "bluesky", f"{u}{i}", f"contenido {a} {b} republicado en cadena"))
    con.commit()
    return con


def test_narrativas_alineadas_respeta_tope():
    grupos = na.detectar(_con_encadenado(40))
    assert grupos, "debería detectar al menos un grupo encadenado"
    assert max(g["n_clusters"] for g in grupos) <= na._MAX_MIEMBROS, (
        "mega-grupo degenerado: el corte por comunidades no está aplicado")


def test_narrativas_alineadas_grupos_coherentes():
    grupos = na.detectar(_con_encadenado(10))
    for g in grupos:
        assert g["n_clusters"] >= 2
        assert g["n_eventos"] >= 2
