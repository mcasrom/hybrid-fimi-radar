#!/usr/bin/env python3
"""schema_feedback.py — Feedback ligero de usuarios del radar FIMI.

Único esquema central de feedback: votos por tema (Si/No/No lo se) + sugerencias
de temas nuevos. Idempotente. Visibilidad: los votos/sugerencias solo los ve el
dueno (GET /api/admin/feedback con secreto); NUNCA son superficie publica de
conteo (un radar FIMI no debe ser manipulable con votacion publica).
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"

SCHEMA_FEEDBACK = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tema TEXT NOT NULL,                -- id de tema (frontera_sur, ...)
    voto TEXT NOT NULL,                -- si | no | ns
    ip TEXT,
    created_at TIMESTAMP DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS idx_feedback_tema ON feedback(tema, voto);

CREATE TABLE IF NOT EXISTS sugerencias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    texto TEXT NOT NULL,
    canal TEXT NOT NULL DEFAULT 'web', -- web | telegram
    ip TEXT,
    estado TEXT NOT NULL DEFAULT 'nueva', -- nueva | revisada
    created_at TIMESTAMP DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS idx_sugerencias_estado ON sugerencias(estado);
"""


def init(conn: sqlite3.Connection = None) -> sqlite3.Connection:
    """Garantiza que las tablas existen y devuelve la conexión."""
    if conn is None:
        conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_FEEDBACK)
    conn.commit()
    return conn


def n_votos(conn: sqlite3.Connection = None) -> int:
    conn = conn or init()
    return conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]


def n_sugerencias(conn: sqlite3.Connection = None) -> int:
    conn = conn or init()
    return conn.execute("SELECT COUNT(*) FROM sugerencias").fetchone()[0]


if __name__ == "__main__":
    c = init()
    print(f"OK tablas feedback/sugerencias en {DB} — "
          f"{n_votos(c)} votos, {n_sugerencias(c)} sugerencias")
    c.close()