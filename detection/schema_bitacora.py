#!/usr/bin/env python3
"""schema_bitacora.py — Crea la tabla `bitacora` del radar FIMI.

Ciclo de vida de cada tema monitorizado (inicio de ingesta, cambios de estado,
cierre) con motivos en lenguaje metodológico. La decisión de cambiar estado la
toma SIEMPRE el dueño (editando config.yaml); la bitácora documenta el historial
de cómo se llegó al estado vigente (que vive en config.yaml). Idempotente.
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"

SCHEMA_BITACORA = """
CREATE TABLE IF NOT EXISTS bitacora (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tema TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK(tipo IN ('inicio','cambio_estado','cierre','nota','sugerencia')),
    fecha INTEGER NOT NULL,
    estado_anterior TEXT,
    estado_nuevo TEXT,
    motivo TEXT,
    origen TEXT NOT NULL DEFAULT 'manual',
    clave TEXT,  -- hash corto del motivo: UNIQUE sin expresiones (SQLite no las permite)
    UNIQUE(tema, tipo, estado_nuevo, clave)
);
CREATE INDEX IF NOT EXISTS idx_bitacora_tema ON bitacora(tema, fecha);
"""


def init(conn: sqlite3.Connection = None) -> sqlite3.Connection:
    """Garantiza que la tabla existe y devuelve la conexión."""
    if conn is None:
        conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_BITACORA)
    conn.commit()
    return conn


def n_entradas(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM bitacora").fetchone()[0]


if __name__ == "__main__":
    c = init()
    print(f"OK tabla bitacora en {DB} — {n_entradas(c)} entradas")
    c.close()