#!/usr/bin/env python3
"""hybrid-fimi-radar — modelo de datos SQLite (esquema completo del prompt).

Tablas: sources, events, narratives, clusters, indicators, assessments, evidence.
Actor-agnostic: taxonomía neutra (UNKNOWN/DOMESTIC/FOREIGN_STATE/...), nunca
ideología como indicador de amenaza.
"""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT, url TEXT UNIQUE, type TEXT,       -- official|media|opendata|social|web
    country TEXT, language TEXT, reliability TEXT,
    enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER, source TEXT, author TEXT, title TEXT, url TEXT,
    text TEXT, language TEXT, topic TEXT,
    tema_id TEXT DEFAULT 'frontera_sur',           -- dominio/alert tematico (multi-tema)
    raw_json TEXT,                                -- observación original (auditable)
    features_json TEXT,                           -- características extraídas
    normalized INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS narratives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT UNIQUE, keywords TEXT,
    first_seen INTEGER, last_seen INTEGER,
    observations INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at INTEGER, cluster_label TEXT UNIQUE,
    type TEXT,                                     -- temporal|content|url|mixed
    tema_id TEXT DEFAULT 'frontera_sur',           -- dominio/alert tematico (multi-tema)
    coordination_score REAL, amplification_score REAL,
    anomaly_score REAL, infrastructure_score REAL,
    network_density REAL, overall_score REAL,
    confidence TEXT                                -- NONE|LOW|MEDIUM|HIGH
);

CREATE TABLE IF NOT EXISTS indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id INTEGER, indicator TEXT, value REAL, weight REAL,
    FOREIGN KEY(cluster_id) REFERENCES clusters(id)
);

CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id INTEGER UNIQUE,
    coordination_score REAL, amplification_score REAL,
    anomaly_score REAL, infrastructure_score REAL, network_density REAL,
    overall_score REAL, confidence TEXT,
    assessment TEXT,                               -- texto explicable
    hypotheses_json TEXT,                          -- H1-H6 alternativas
    attribution TEXT,                              -- taxonomía neutra
    attribution_confidence TEXT,                   -- NO|LOW|MEDIUM|HIGH
    attribution_evidence TEXT,
    missing_evidence TEXT,
    FOREIGN KEY(cluster_id) REFERENCES clusters(id)
);

 CREATE TABLE IF NOT EXISTS evidence (
     id INTEGER PRIMARY KEY AUTOINCREMENT,
     cluster_id INTEGER, timestamp INTEGER, source TEXT,
     original_url TEXT, raw TEXT, normalized TEXT,
     features TEXT, algorithm TEXT, parameters TEXT,
     score REAL, decision TEXT,
     FOREIGN KEY(cluster_id) REFERENCES clusters(id)
 );

CREATE TABLE IF NOT EXISTS event_temas (
    event_id INTEGER NOT NULL,
    tema_id TEXT NOT NULL,
    PRIMARY KEY (event_id, tema_id),
    FOREIGN KEY(event_id) REFERENCES events(id)
);

-- Hallazgos positivos persistidos (historial de resultados, no se pierde
-- cuando el evento deja de ser noticia). Fecha de primera/last detección.
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha INTEGER,                 -- fecha de detección (epoch día)
    tipo TEXT,                     -- amplificacion_narrativa | cluster | cascada
    titulo TEXT,
    detalle TEXT,
    n_sources INTEGER, n_events INTEGER,
    window_hours REAL,
    fuentes TEXT,
    intensidad REAL,
    url TEXT
);

-- Informes diarios (resumen de hallazgos del día)
CREATE TABLE IF NOT EXISTS daily_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT UNIQUE,             -- YYYY-MM-DD
    resumen TEXT,
    n_findings INTEGER,
    created_at INTEGER
);
"""


def _ensure_column(conn, table, column, ddl):
    """Añade una columna a una tabla SQLite si no existe ya (idempotente).
    Necesario porque CREATE TABLE IF NOT EXISTS no altera tablas existentes,
    y la BD de producción ya tiene datos previos a multi-tema."""
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _ensure_event_temas(conn):
    """Backfill idempotente de la relacion many-to-many evento<->tema.

    events.tema_id se conserva como tema primario/legacy; event_temas es la
    fuente de verdad multi-tema. Para los eventos ya existentes (todos con
    tema_id='frontera_sur'), se crea su fila en event_temas. Es seguro repetir:
    INSERT OR IGNORE + PK(event_id,tema_id)."""
    # Backfill: cada evento existente -> su tema_id actual en la relacion
    conn.execute(
        "INSERT OR IGNORE INTO event_temas (event_id, tema_id)"
        " SELECT id, tema_id FROM events WHERE tema_id IS NOT NULL AND tema_id != ''")
    conn.commit()


def _ensure_events_unique(conn):
    """Dedupe + índice UNIQUE en events sobre la clave natural de captura.

    events no tenía ninguna constraint UNIQUE: el INSERT OR IGNORE de capture
    no ignoraba nada y cada ciclo de captura re-insertaba eventos ya vistos
    (13.6k de 16.4k filas eran duplicados), inflando clusters y conteos.

    Clave natural: (source, author, timestamp, substr(text,1,80)) — la misma
    que capture.py usa para dedupe en memoria. Idempotente: si el índice ya
    existe, no hace nada.
    """
    idx = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_events_natural'").fetchone()
    if idx:
        return
    conn.execute("BEGIN")
    try:
        key = "source, author, timestamp, substr(text,1,80)"
        conn.execute(
            f"DELETE FROM events WHERE id NOT IN (SELECT MIN(id) FROM events GROUP BY {key})")
        conn.execute("DELETE FROM event_temas WHERE event_id NOT IN (SELECT id FROM events)")
        conn.execute(
            "CREATE UNIQUE INDEX idx_events_natural ON events (source, author, timestamp, substr(text,1,80))")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def get_conn(db_path):
    """Devuelve conexión SQLite con el esquema creado."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.executescript(SCHEMA)
    # Migraciones sobre tablas ya existentes (multi-tema, sin romper datos)
    _ensure_column(conn, "events", "tema_id", "tema_id TEXT DEFAULT 'frontera_sur'")
    _ensure_column(conn, "clusters", "tema_id", "tema_id TEXT DEFAULT 'frontera_sur'")
    _ensure_events_unique(conn)
    _ensure_event_temas(conn)
    conn.commit()
    return conn
