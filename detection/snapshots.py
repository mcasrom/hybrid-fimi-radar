#!/usr/bin/env python3
"""snapshots.py — serie temporal por ciclo (append-only) del Radar FIMI.

Contexto: `clusters` es un snapshot que se REEMPLAZA cada ciclo y
`cluster_lineage` se ACTUALIZA in-place (una fila por linaje, no un log), así
que hoy no existe NINGUNA serie temporal de score. Este módulo escribe, al
final de cada `run_fimi`, una fila por cluster en `cluster_snapshots` (clave
`lineage_id` + `cycle_ts`, idempotente) y un agregado por tema en
`tema_snapshots`.

NO toca scoring/bandas/detección: solo registra lo ya calculado. La retención
por-ciclo es una ventana rodante (def. 60 d); lo más antiguo se enrolla a
`cluster_snapshots_daily` (1 fila linaje/día) para conservar la tendencia larga
sin pagar el detalle por ciclo.

Uso (manual):
  .venv/bin/python detection/snapshots.py --now       # snapshot del ciclo actual
  .venv/bin/python detection/snapshots.py --prune      # poda (> 60 d) + roll diario
"""
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from detection import bandas  # noqa: E402

RETENCION_DIAS = 60
_BAND_INDEX = {name: i for i, (_, name) in enumerate(bandas.BANDAS)}

_DDL = [
    """CREATE TABLE IF NOT EXISTS cluster_snapshots (
        id                   INTEGER PRIMARY KEY,
        cycle_ts             INTEGER NOT NULL,
        lineage_id           TEXT    NOT NULL,
        tema_id              TEXT    NOT NULL,
        cluster_label        TEXT,
        band                 INTEGER NOT NULL,
        overall_score        REAL,
        coordination_score   REAL,
        amplification_score  REAL,
        anomaly_score        REAL,
        infrastructure_score REAL,
        n_events             INTEGER DEFAULT 0,
        n_accounts           INTEGER DEFAULT 0,
        n_sources            INTEGER DEFAULT 0
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_csnap ON cluster_snapshots(lineage_id, cycle_ts)",
    "CREATE INDEX IF NOT EXISTS ix_csnap_cyc ON cluster_snapshots(cycle_ts)",
    "CREATE INDEX IF NOT EXISTS ix_csnap_tema ON cluster_snapshots(tema_id, cycle_ts)",
    """CREATE TABLE IF NOT EXISTS tema_snapshots (
        cycle_ts    INTEGER NOT NULL,
        tema_id     TEXT    NOT NULL,
        n_clusters  INTEGER,
        n_normal    INTEGER,
        n_watch     INTEGER,
        n_anomalous INTEGER,
        n_high      INTEGER,
        n_critical  INTEGER,
        n_events    INTEGER,
        n_accounts  INTEGER,
        PRIMARY KEY (cycle_ts, tema_id)
    )""",
    """CREATE TABLE IF NOT EXISTS cluster_snapshots_daily (
        day           TEXT    NOT NULL,
        lineage_id    TEXT    NOT NULL,
        tema_id       TEXT    NOT NULL,
        band_max      INTEGER,
        band_avg      REAL,
        score_max     REAL,
        score_avg     REAL,
        n_events_max  INTEGER,
        n_ciclos      INTEGER,
        PRIMARY KEY (day, lineage_id, tema_id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_csdaily_lineage ON cluster_snapshots_daily(lineage_id, day)",
]


def _band_index(score):
    return _BAND_INDEX.get(bandas.banda(score), 0)


def ensure_schema(conn):
    for ddl in _DDL:
        conn.execute(ddl)
    conn.commit()


def write(conn, tema, cycle_ts):
    """Escribe el snapshot del ciclo para `tema`. Devuelve nº de clusters."""
    ensure_schema(conn)
    cycle_ts = int(cycle_ts)
    rows = conn.execute(
        "SELECT c.id, c.cluster_label, c.overall_score, c.coordination_score,"
        " c.amplification_score, c.anomaly_score, c.infrastructure_score, l.lineage_id"
        " FROM clusters c"
        " JOIN cluster_lineage l ON l.cluster_label = c.cluster_label AND l.tema_id = c.tema_id"
        " WHERE c.tema_id = ?", (tema,)).fetchall()
    agg = {}
    for r in conn.execute(
            "SELECT ce.cluster_id, COUNT(*), COUNT(DISTINCT ce.author), COUNT(DISTINCT ce.source)"
            " FROM cluster_events ce JOIN clusters c ON c.id = ce.cluster_id"
            " WHERE c.tema_id = ? GROUP BY ce.cluster_id", (tema,)):
        agg[r[0]] = (r[1], r[2], r[3])

    # Dedup por lineage_id: el linaje es la identidad del cluster. Si upstream
    # duplica un lineage_id (visto en inteligencia_artificial, 18-oct), se
    # conserva el de mayor score para no colapsar filas en silencio y que el
    # agregado por tema cuadre (n_clusters == suma de bandas == filas escritas).
    best = {}
    for r in rows:
        lid = r[7]
        prev = best.get(lid)
        if prev is None or (r[2] or 0) > (prev[2] or 0):
            best[lid] = r
    if len(best) != len(rows):
        print(f"      snapshots: aviso {tema}: {len(rows) - len(best)} lineage_id "
              f"duplicado(s) -> se conserva el de mayor score", file=sys.stderr)

    bandas_n = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    for r in best.values():
        cid, label, overall, coord, amp, anom, infra, lid = r
        b = _band_index(overall)
        bandas_n[b] = bandas_n.get(b, 0) + 1
        ne, na, ns = agg.get(cid, (0, 0, 0))
        conn.execute(
            "INSERT OR REPLACE INTO cluster_snapshots (cycle_ts, lineage_id, tema_id,"
            " cluster_label, band, overall_score, coordination_score, amplification_score,"
            " anomaly_score, infrastructure_score, n_events, n_accounts, n_sources)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cycle_ts, lid, tema, label, b, overall, coord, amp, anom, infra, ne, na, ns))

    te = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT ce.author)"
        " FROM cluster_events ce JOIN clusters c ON c.id = ce.cluster_id"
        " WHERE c.tema_id = ?", (tema,)).fetchone()
    conn.execute(
        "INSERT OR REPLACE INTO tema_snapshots (cycle_ts, tema_id, n_clusters, n_normal,"
        " n_watch, n_anomalous, n_high, n_critical, n_events, n_accounts)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (cycle_ts, tema, len(best), bandas_n[0], bandas_n[1], bandas_n[2], bandas_n[3],
         bandas_n[4], te[0] or 0, te[1] or 0))
    conn.commit()
    return len(best)


def count_old(conn, dias=RETENCION_DIAS):
    """Filas por-ciclo fuera de la ventana (para modo dry)."""
    ensure_schema(conn)
    cut = int(time.time()) - dias * 86400
    return conn.execute(
        "SELECT COUNT(*) FROM cluster_snapshots WHERE cycle_ts < ?", (cut,)).fetchone()[0]


def prune(conn, dias=RETENCION_DIAS):
    """Enrolla a diario y borra el detalle por-ciclo anterior a `dias`. Devuelve nº borradas."""
    ensure_schema(conn)
    cut = int(time.time()) - dias * 86400
    conn.execute(
        "INSERT OR REPLACE INTO cluster_snapshots_daily (day, lineage_id, tema_id, band_max,"
        " band_avg, score_max, score_avg, n_events_max, n_ciclos)"
        " SELECT date(cycle_ts,'unixepoch'), lineage_id, tema_id, MAX(band), AVG(band),"
        " MAX(overall_score), AVG(overall_score), MAX(n_events), COUNT(DISTINCT cycle_ts)"
        " FROM cluster_snapshots WHERE cycle_ts < ? GROUP BY 1, lineage_id, tema_id", (cut,))
    cur = conn.execute("DELETE FROM cluster_snapshots WHERE cycle_ts < ?", (cut,))
    conn.commit()
    return cur.rowcount


def _conn(path):
    c = sqlite3.connect(path)
    c.execute("PRAGMA busy_timeout=15000")
    c.execute("PRAGMA journal_mode=WAL")
    return c


def active_temas():
    """Temas que el cron realmente corre (estado produccion|piloto), igual que cron_every_6h.sh."""
    import yaml
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    return [t for t, m in (cfg.get("temas") or {}).items()
            if (m or {}).get("estado", "produccion") in ("produccion", "piloto")]


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Snapshots por ciclo del Radar FIMI")
    ap.add_argument("--db", default=str(ROOT / "data" / "radar.db"))
    ap.add_argument("--tema", default=None)
    ap.add_argument("--now", action="store_true", help="escribe el snapshot del estado actual")
    ap.add_argument("--prune", action="store_true", help="poda (>N d) + roll diario")
    ap.add_argument("--dias", type=int, default=RETENCION_DIAS)
    a = ap.parse_args()
    conn = _conn(a.db)
    if a.now:
        temas = [a.tema] if a.tema else active_temas()
        ct = int(time.time())
        tot = 0
        for t in temas:
            n = write(conn, t, ct)
            tot += n
            print(f"  {t:26s} {n:5d} clusters")
        print(f"snapshot: {tot} filas en {len(temas)} temas @ {ct}")
    if a.prune:
        print(f"podados {prune(conn, a.dias)} filas (> {a.dias} d)")
    if not (a.now or a.prune):
        print("nada que hacer (usa --now y/o --prune)")
    conn.close()


if __name__ == "__main__":
    main()
