"""Tests de match_cache: determinismo, invalidación por config y poda."""
import sqlite3
from collections import Counter

from detection import match_cache as mc


def _con():
    con = sqlite3.connect(":memory:")
    mc.ensure(con)
    return con


def test_hash_estable_e_invalida_por_config():
    pt = {"a": ["Ceuta", "Melilla"], "b": ["Gaza"]}
    h1 = mc.hash_cfg(pt, {}, {})
    h2 = mc.hash_cfg({"b": ["Gaza"], "a": ["Melilla", "Ceuta"]}, {}, {})
    assert h1 == h2  # orden irrelevante
    h3 = mc.hash_cfg({"a": ["Ceuta", "Melilla", "Frontera"]}, {}, {})
    assert h3 != h1  # cambio de keywords -> otra cfg


def test_roundtrip():
    con = _con()
    hits = {1: ({"a", "b"}, {"Ceuta", "Gaza"}), 2: ({"b"}, {"Gaza"})}
    assert mc.guardar(con, "cfg1", hits) == 2
    temas, kw = mc.cargar(con, "cfg1", [1, 2, 3])
    assert temas == {1: {"a", "b"}, 2: {"b"}}
    assert kw == Counter({"Ceuta": 1, "Gaza": 2})


def test_cfg_distinta_no_mezcla():
    con = _con()
    mc.guardar(con, "cfg1", {1: ({"a"}, {"x"})})
    temas, kw = mc.cargar(con, "cfg2", [1])
    assert temas == {} and kw == Counter()
    # podar con cfg2 borra la cfg1 vieja
    assert mc.podar(con, "cfg2", [1]) >= 1
    assert con.execute("SELECT COUNT(*) FROM match_cache").fetchone()[0] == 0


def test_podar_ventana():
    con = _con()
    mc.guardar(con, "c", {i: ({"a"}, {"x"}) for i in range(1, 11)})
    mc.podar(con, "c", list(range(6, 11)))
    quedan = {r[0] for r in con.execute("SELECT event_id FROM match_cache")}
    assert quedan == {6, 7, 8, 9, 10}
