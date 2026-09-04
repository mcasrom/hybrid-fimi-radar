#!/usr/bin/env python3
"""schema_suscripciones.py — Crea la tabla central de suscripciones del radar FIMI.

Un único esquema para los 3 canales (telegram / email / futuro). Idempotente:
se puede ejecutar tantas veces como se quiera (CREATE TABLE IF NOT EXISTS).
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"

SCHEMA_SUSCRIPCIONES = """
CREATE TABLE IF NOT EXISTS suscripciones (
    id TEXT PRIMARY KEY,
    canal TEXT NOT NULL,
    destino TEXT NOT NULL,
    temas TEXT NOT NULL DEFAULT '[]',
    frecuencia TEXT NOT NULL DEFAULT 'on_change',
    ultimo_estado TEXT,
    fecha_alta TIMESTAMP DEFAULT (strftime('%s','now')),
    confirmado BOOLEAN DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_susc_destino ON suscripciones(canal, destino);
"""


def init(conn: sqlite3.Connection = None) -> sqlite3.Connection:
    """Garantiza que la tabla existe y devuelve la conexión."""
    if conn is None:
        conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA_SUSCRIPCIONES)
    conn.commit()
    return conn


def n_suscripciones(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM suscripciones").fetchone()[0]


if __name__ == "__main__":
    c = init()
    print(f"OK tabla suscripciones en {DB} — {n_suscripciones(c)} filas")
    c.close()
