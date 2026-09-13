#!/usr/bin/env python3
"""Tests de la prueba de restauración de backups (detection/restore_test.py).

Verifican la mecánica gzip -> SQLite -> validación sin depender de la BD de
producción: crean una BD mínima, la comprimen y comprueban que se restaura
íntegra y con los conteos esperados. La ejecución REAL sobre los backups de
producción se hace con `python detection/restore_test.py` (cron/servidor).
"""
from __future__ import annotations

import gzip
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from detection.restore_test import (  # noqa: E402
    integrity_check, latest_backup, restore, run, table_counts,
)


def _mini_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, text TEXT)")
    con.execute("INSERT INTO events(text) VALUES ('a'),('b'),('c')")
    con.execute("CREATE TABLE event_temas(event_id INTEGER, tema_id TEXT)")
    con.execute("INSERT INTO event_temas VALUES (1,'sahel'),(2,'sahel')")
    con.commit()
    con.close()


def _gz(src: Path, dst: Path) -> Path:
    with open(src, "rb") as f, gzip.open(dst, "wb") as g:
        shutil.copyfileobj(f, g)
    return dst


def test_restore_roundtrip(tmp_path):
    src = tmp_path / "radar.db"
    _mini_db(src)
    bz = _gz(src, tmp_path / "radar-20260101_000000.db.gz")

    dest = tmp_path / "restored.db"
    restore(bz, dest)

    assert integrity_check(dest) == "ok"
    counts = table_counts(dest)
    assert counts["events"] == 3
    assert counts["event_temas"] == 2


def test_latest_backup_picks_newest(tmp_path):
    import os
    a = tmp_path / "radar-20260101_000000.db.gz"
    b = tmp_path / "radar-20260102_000000.db.gz"
    a.write_bytes(b"x")
    b.write_bytes(b"y")
    os.utime(a, (1000, 1000))
    os.utime(b, (2000, 2000))
    assert latest_backup(tmp_path).name == "radar-20260102_000000.db.gz"


def test_run_ok_sin_bd_viva(tmp_path):
    src = tmp_path / "radar.db"
    _mini_db(src)
    bz = _gz(src, tmp_path / "radar-20260101_000000.db.gz")
    r = run(backup_path=bz, live_db=tmp_path / "no-existe.db")
    assert r["ok"] is True
    assert r["integrity_check"] == "ok"
    assert r["tablas_clave"]["events"] == 3
    assert r["live_eventos"] is None


def test_run_falla_sin_backup(tmp_path):
    r = run(backup_path=tmp_path / "nope.db.gz")
    assert r["ok"] is False
