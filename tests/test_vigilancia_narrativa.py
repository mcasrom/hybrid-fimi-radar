#!/usr/bin/env python3
"""Tests de detection/vigilancia_narrativa.py (observación intensa de narrativas)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from detection.vigilancia_narrativa import contar, evaluar_escalada  # noqa: E402


def test_evaluar_escalada():
    assert evaluar_escalada(None, 5) is False          # primera vez: sin base
    assert evaluar_escalada(10, 11) is False           # +1 (ni delta ni factor)
    assert evaluar_escalada(10, 20) is True            # +10 (delta)
    assert evaluar_escalada(4, 6) is True              # x1.5 (factor)
    assert evaluar_escalada(100, 105) is False         # +5
    assert evaluar_escalada(0, 12) is True             # desde 0 con volumen
    assert evaluar_escalada(0, 5) is False             # desde 0, poco


def _db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE events (id INT, timestamp INT, source TEXT, author TEXT,"
                " url TEXT, tema_id TEXT, text TEXT, title TEXT)")
    con.executemany(
        "INSERT INTO events VALUES (?,?,?,?,?,?,?,?)",
        [(1, 1000, "bluesky", "a1", "u1", "frontera_sur", "dron marroquí sobre Melilla", ""),
         (2, 1001, "rss:x", "a2", "u2", "frontera_sur", "", "España y Marruecos: drones en Ceuta"),
         (3, 1002, "bluesky", "a3", "u3", "oriente_medio", "drones ucranianos en Rusia", ""),
         (4, 1003, "bluesky", "a4", "u4", "frontera_sur", "migración en Ceuta", "")])
    con.commit()
    return con


def test_contar_requiere_contexto():
    con = _db()
    nar = {"requeridos": ["dron"], "contexto": ["ceuta", "melilla", "marruecos"]}
    r = contar(con, nar, ventana_horas=1, ahora=2000)
    assert r["n"] == 2                      # 1 y 2; el 3 (Rusia) y el 4 (sin dron) no
    assert r["redes"] == 1 and r["rss"] == 1
    assert r["cuentas"] == 2 and r["urls"] == 2
    assert r["temas"] == {"frontera_sur": 2}


def test_contar_ventana_excluye_antiguos():
    con = _db()
    nar = {"requeridos": ["dron"], "contexto": ["ceuta", "melilla", "marruecos"]}
    # ventana [ahora-3600, ahora]; con ahora lejano, los eventos (ts~1000) quedan fuera
    assert contar(con, nar, ventana_horas=1, ahora=100000)["n"] == 0


def test_contar_sin_requeridos():
    con = _db()
    assert contar(con, {"requeridos": [], "contexto": ["ceuta"]}, 1, 2000)["n"] == 0
