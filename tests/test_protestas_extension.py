#!/usr/bin/env python3
"""Contrato de la medición exploratoria de extensión entre países."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from detection.protestas_extension import calcular  # noqa: E402


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, author TEXT, timestamp INTEGER, title TEXT, text TEXT)")
    c.execute("CREATE TABLE event_temas (event_id INTEGER, tema_id TEXT)")
    rows = [
        (1, "a", 1000, "Blocus en Barcelona", ""),
        (2, "b", 2000, "Blocus en París", ""),
        (3, "c", 3000, "Manifestación en Milán", ""),
        (4, "d", 4000, "Manifestación en Tirana", ""),
        (5, "e", 5000, "Sin país", ""),
    ]
    c.executemany("INSERT INTO events VALUES (?,?,?,?,?)", rows)
    c.executemany("INSERT INTO event_temas VALUES (?,?)", [(i, "protestas_juveniles") for i in range(1, 6)])
    return c


def test_blocus_extension_72h():
    d = calcular(_db())
    b = next(x for x in d["filas"] if x["simbolo"] == "Blocus")
    assert b["paises_72h"] == ["España", "Francia"]
    assert b["max_paises_72h"] == 2


def test_one_piece_no_observada():
    d = calcular(_db())
    o = next(x for x in d["filas"] if x["simbolo"] == "One Piece")
    assert o["eventos"] == 0
    assert o["estado"] == "no observada"


def test_manifestacion_no_atribuye_coordinacion():
    d = calcular(_db())
    m = next(x for x in d["filas"] if x["simbolo"] == "Manifestación")
    assert "coordinación" in d["nota"]
    assert m["max_paises_72h"] >= 2
