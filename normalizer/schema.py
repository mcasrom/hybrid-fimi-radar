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


def get_conn(db_path):
    """Devuelve conexión SQLite con el esquema creado."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.executescript(SCHEMA)
    return conn
