"""Acceso READ-ONLY a los datos reales (sqlite mode=ro)."""
import sqlite3
from pathlib import Path

ROOT = Path("/home/deploy/hybrid-fimi-radar")
DB = ROOT / "data" / "radar.db"


def connect_ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def load_cluster_events(label, conn=None):
    """Eventos reales del cluster (tabla cluster_events)."""
    c = conn or connect_ro()
    c.row_factory = sqlite3.Row
    row = c.execute("SELECT id FROM clusters WHERE cluster_label=?", (label,)).fetchone()
    if not row:
        return []
    rows = c.execute(
        "SELECT ts, source, author, title, text, url FROM cluster_events"
        " WHERE cluster_id=? ORDER BY ts", (row["id"],)).fetchall()
    return [dict(r) for r in rows]


def load_clusters(tema=None):
    """Clusters activos (label, tema, score) — el score SOLO para comparar."""
    c = connect_ro()
    c.row_factory = sqlite3.Row
    q = "SELECT cluster_label, tema_id, overall_score FROM clusters"
    p = ()
    if tema:
        q += " WHERE tema_id=?"
        p = (tema,)
    return [dict(r) for r in c.execute(q, p).fetchall()]
