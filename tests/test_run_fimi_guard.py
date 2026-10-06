#!/usr/bin/env python3
"""Guardas del pipeline: input inexistente, CSV avisado, y generador sintético
que escribe donde se le indique (no en data/raw de producción).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_run_fimi_input_inexistente_aborta():
    r = subprocess.run(
        [sys.executable, str(ROOT / "detection" / "run_fimi.py"),
         "--input", "/no/existe/de-verdad.db", "--tema", "frontera_sur"],
        capture_output=True, text=True)
    assert r.returncode == 2
    assert "no existe" in (r.stderr + r.stdout)


def test_generate_synthetic_respeta_out_dir(tmp_path):
    env = {**os.environ, "GEN_SYNTHETIC_OUT": str(tmp_path)}
    r = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "generate_synthetic.py")],
        capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "events.csv").exists()
    assert (tmp_path / "ground_truth.csv").exists()


def test_load_sqlite_ventana_desde(tmp_path):
    """load_sqlite(desde=) filtra eventos viejos; sin desde trae todo."""
    import sqlite3
    import time
    sys.path.insert(0, str(ROOT))
    from normalizer.ingest import load_sqlite
    db = tmp_path / "mini.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, timestamp INTEGER,"
                " source TEXT, author TEXT, title TEXT, url TEXT, text TEXT, language TEXT)")
    now = int(time.time())
    con.execute("INSERT INTO events(timestamp,source,author,title,url,text,language)"
                " VALUES (?,?,?,?,?,?,?)", (now - 100 * 86400, "bsky:x", "a", "viejo", "u", "t", "es"))
    con.execute("INSERT INTO events(timestamp,source,author,title,url,text,language)"
                " VALUES (?,?,?,?,?,?,?)", (now - 5 * 86400, "bsky:y", "b", "nuevo", "u", "t", "es"))
    con.commit()
    con.close()
    todo = load_sqlite(str(db))
    assert len(todo) == 2
    ventana = load_sqlite(str(db), desde=now - 30 * 86400)
    assert len(ventana) == 1
    assert ventana.iloc[0]["text"] == "t" and ventana.iloc[0]["author"] == "b"
