#!/usr/bin/env python3
"""mantenimiento.py — Retención y almacenamiento del Radar FIMI.

Política óptima adaptada al server Hetzner (disco 38 GB al 61%, RAM limitada):
el radar detecta campañas FIMI a corto plazo (días/semanas), no mantiene un
archivo histórico infinito. Los eventos > ventana no aportan ni a la detección
ni al dashboard (tendencia 48h), solo queman disco y ralentizan consultas.

Reglas:
  events + event_temas : purgar > RETENTION_EVENTS_DIAS (90)
  findings             : purgar > RETENTION_EVENTS_DIAS (90) por fecha
  clusters/indicators/assessments/cluster_events : se reemplazan cada ciclo
      (DELETE+re-INSERT por tema en run_fimi) -> retención implícita.
  raw JSON (data/raw)  : 30 días (lo gestiona cron_every_6h.sh)
  logs                : rotación 5 MB (la gestiona cron_every_6h.sh)
  VACUUM               : tras cada purga para compactar la DB
  backup BD            : gzip a {BASE_BACKUP}/radar-YYYYMMDD.db.gz, rotar a N=4
  suscripciones / daily_reports : NO se tocan (datos de usuario/config)

Uso:
  .venv/bin/python detection/mantenimiento.py          # hace todo
  .venv/bin/python detection/mantenimiento.py --dry     # solo informa, no borra
"""
import argparse
import datetime
import gzip
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "radar.db"
RAW_DIR = ROOT / "data" / "raw"
LOGS_DIR = ROOT / "logs"
# Backups automáticos: directorio propio de deploy dentro del repo (gitignored).
# /var/backups/fimi queda reservado a backups manuales puntuales (sudo, root).
BASE_BACKUP = ROOT / "backups"

RETENTION_EVENTS_DIAS = 90
BACKUP_ROTACION = 4


def _now() -> float:
    return datetime.datetime.now().timestamp()


def _info(msg: str):
    print(f"[mant] {datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}")


def backup_bd(keep: int = BACKUP_ROTACION) -> str:
    """Copia comprimida de la DB y rota a N copias (la más antigua se elimina)."""
    BASE_BACKUP.mkdir(parents=True, exist_ok=True)
    fname = f"radar-{datetime.datetime.now():%Y%m%d_%H%M%S}.db.gz"
    dst = BASE_BACKUP / fname
    with open(DB, "rb") as src, gzip.open(dst, "wb") as out:
        shutil.copyfileobj(src, out, length=1024 * 1024)
    copias = sorted(BASE_BACKUP.glob("radar-*.db.gz"))
    for viejo in copias[:-keep]:
        viejo.unlink()
    _info(f"backup -> {dst.name} ({round(dst.stat().st_size/1024)} KB); copias: {len(copias)} (max {keep}) en {BASE_BACKUP}")
    return str(dst)


def _purge_table(conn, dry: bool, table: str, ts_col: str, cutoff: float, label: str):
    cur = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {ts_col} < ?", (cutoff,))
    n = cur.fetchone()[0]
    if n:
        if dry:
            _info(f"[DRY] {label}: {n} filas borrables (>90d)")
            return n
        cur = conn.execute(f"DELETE FROM {table} WHERE {ts_col} < ?", (cutoff,))
        _info(f"purga {label}: {cur.rowcount} filas")
    else:
        _info(f"{label}: 0 filas >90d")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="solo informa, no borra")
    ap.add_argument("--no-backup", action="store_true", help="no hace backup")
    args = ap.parse_args()

    cutoff = _now() - RETENTION_EVENTS_DIAS * 86400

    _info(f"DB={DB} ({round(DB.stat().st_size/1024)} KB) — retención {RETENTION_EVENTS_DIAS}d, cutoff {datetime.datetime.fromtimestamp(cutoff):%Y-%m-%d}")

    if not args.no_backup:
        backup_bd()

    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA journal_mode=WAL")

    # eventos antiguos: recoger ids que se van a borrar para quitar event_temas
    _purge_table(conn, args.dry, "events", "timestamp", cutoff, "events>90d")
    # event_temas huérfanos del purge de events
    cur = conn.execute(
        "DELETE FROM event_temas WHERE event_id NOT IN (SELECT id FROM events)")
    if not args.dry:
        _info(f"limpieza event_temas huérfanos: {cur.rowcount}")
    # findings antiguos
    _purge_table(conn, args.dry, "findings", "fecha", cutoff, "findings>90d")

    # eventos huérfanos de cluster_events (ya no referenciados) - no son daño pero dejarlo limpio
    cur = conn.execute(
        "DELETE FROM cluster_events WHERE cluster_id NOT IN (SELECT id FROM clusters)")

    if not args.dry:
        # primero eliminamos event_temas de los events borrados (hecho arriba por NOT IN)
        conn.commit()
        _info("VACUUM...")
        vac = _now()
        conn.execute("PRAGMA incremental_vacuum")
        conn.execute("VACUUM")
        _info(f"VACUUM en {round(_now()-vac)}s — DB ahora {round(DB.stat().st_size/1024)} KB")
    conn.close()

    _info("mantenimiento OK")


if __name__ == "__main__":
    main()