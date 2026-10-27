#!/usr/bin/env python3
"""Tests del registro y del detector de convocatorias públicas."""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from detection.convocatorias import _ciudades, detectar  # noqa: E402


def test_ciudades():
    assert _ciudades("Blocus BCN y Madrid") == ["Barcelona", "Madrid"]
    assert _ciudades("blocus sin ciudad") == []


def _db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp REAL, source TEXT, author TEXT, title TEXT, text TEXT, url TEXT)")
    c.execute("CREATE TABLE event_temas (event_id INTEGER, tema_id TEXT)")
    now = time.time()
    c.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?)", [
        (1, now, "bluesky", "a", "Blocus convoca en Madrid", "", "https://example.org/1"),
        (2, now, "bluesky", "b", "Blocus sin ciudad", "", "https://example.org/2"),
        (3, now-2, "bluesky", "c", "Blocus Barcelona", "", "https://example.org/3"),
    ])
    c.executemany("INSERT INTO event_temas VALUES (?,?)", [(1, "protestas_juveniles"), (2, "protestas_juveniles"), (3, "protestas_juveniles")])
    return c


def test_detectar_exige_ciudad_y_deduplica():
    cand = detectar(_db())
    assert [x["ciudades"] for x in cand] == [["Madrid"], ["Barcelona"]]
    assert all(x["estado_candidato"] == "revisar" for x in cand)
