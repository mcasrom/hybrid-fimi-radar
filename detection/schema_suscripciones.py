#!/usr/bin/env python3
"""schema_suscripciones.py — Crea la tabla central de suscripciones del radar FIMI.

Un único esquema para los 3 canales (telegram / email / futuro). Idempotente:
se puede ejecutar tantas veces como se quiera (CREATE TABLE IF NOT EXISTS).

Semilla única: la misma tabla sirve para todos los proyectos del ecosistema
(blog, fimi, etc.) con columna `proyecto` (default 'fimi' para compatibilidad).
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
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SUSCRIPCIONES)
    # Migración suave: añadir columna proyecto si falta (BDs viejas)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(suscripciones)").fetchall()]
        if "proyecto" not in cols:
            conn.execute("ALTER TABLE suscripciones ADD COLUMN proyecto TEXT NOT NULL DEFAULT 'fimi'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_susc_proyecto ON suscripciones(proyecto)")
            conn.commit()
    except Exception:
        pass
    conn.commit()
    return conn


def n_suscripciones(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM suscripciones").fetchone()[0]


if __name__ == "__main__":
    c = init()
    print(f"OK tabla suscripciones en {DB} — {n_suscripciones(c)} filas")
    c.close()
