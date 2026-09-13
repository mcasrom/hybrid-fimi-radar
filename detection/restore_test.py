#!/usr/bin/env python3
"""restore_test.py — prueba de restauración de backups (NO destructiva).

Restaura el backup más reciente (o el indicado con --backup) a un fichero
temporal y verifica que es íntegro y utilizable:

  1. `PRAGMA integrity_check` == 'ok'.
  2. Las tablas clave existen y `events` tiene filas.
  3. (informativo) cuadre de conteos con la BD viva actual.

NUNCA toca la BD de producción: escribe siempre en un temporal que borra al
terminar. Pensado para cron/servidor (donde viven los backups) y para CI (con
un backup sintético generado al vuelo en los tests).

Uso:
  .venv/bin/python detection/restore_test.py
  .venv/bin/python detection/restore_test.py --backup backups/radar-20260913_135444.db.gz
  .venv/bin/python detection/restore_test.py --json
"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / "backups"
LIVE_DB = ROOT / "data" / "radar.db"
TABLAS_CLAVE = ("events", "event_temas", "clusters", "cluster_events",
                "findings", "assessments", "bitacora", "suscripciones")


def latest_backup(base: Path = BACKUP_DIR) -> Path | None:
    """Backup radar-*.db.gz más reciente por fecha de modificación.

    Se ordena por mtime (no por nombre) porque junto a los backups automáticos
    `radar-YYYYMMDD_HHMMSS.db.gz` conviven copias manuales con otros sufijos
    (p.ej. `radar-backfillpre-...`), y el nombre no siempre refleja el orden.
    """
    copias = list(base.glob("radar-*.db.gz"))
    if not copias:
        return None
    return max(copias, key=lambda p: (p.stat().st_mtime, p.name))


def restore(backup_path: Path, dest: Path) -> Path:
    """Descomprime el backup .gz a `dest` (fichero SQLite restaurado)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(backup_path, "rb") as src, open(dest, "wb") as out:
        shutil.copyfileobj(src, out, length=1024 * 1024)
    return dest


def integrity_check(db_path: Path) -> str:
    """Devuelve el resultado de PRAGMA integrity_check ('ok' si íntegro)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()


def table_counts(db_path: Path) -> dict:
    """Conteo de filas de las tablas clave que existan en la BD."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        existentes = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        out = {}
        for t in TABLAS_CLAVE:
            if t in existentes:
                out[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return out
    finally:
        con.close()


def run(backup_path: Path | None = None, live_db: Path = LIVE_DB) -> dict:
    """Restaura el backup y valida integridad + tablas. Devuelve el informe."""
    backup_path = backup_path or latest_backup()
    if backup_path is None or not backup_path.exists():
        return {"ok": False, "error": "no hay backups radar-*.db.gz"}

    tmp = Path(tempfile.mkdtemp(prefix="fimi-restore-")) / "restored.db"
    try:
        restore(backup_path, tmp)
        integ = integrity_check(tmp)
        counts = table_counts(tmp)
        live = table_counts(live_db) if live_db.exists() else {}

        ok = (integ == "ok") and counts.get("events", 0) > 0
        return {
            "ok": ok,
            "backup": str(backup_path.name),
            "backup_bytes_gz": backup_path.stat().st_size,
            "integrity_check": integ,
            "tablas_clave": counts,
            "tablas_faltantes": [t for t in TABLAS_CLAVE if t not in counts],
            "live_eventos": live.get("events"),
            "delta_eventos_vs_vivo": (
                (counts.get("events", 0) - live["events"])
                if "events" in live else None
            ),
        }
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Prueba de restauración de backup FIMI")
    ap.add_argument("--backup", default=None, help="ruta al .db.gz (def: el más reciente)")
    ap.add_argument("--json", action="store_true", help="salida JSON")
    args = ap.parse_args()

    bp = Path(args.backup) if args.backup else None
    r = run(bp)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        if not r["ok"]:
            print(f"[restore] FALLO: {r.get('error', 'integridad/tablas')}")
        else:
            print(f"[restore] OK · {r['backup']} · integrity={r['integrity_check']}")
            print(f"          events={r['tablas_clave'].get('events')} "
                  f"(vivo {r['live_eventos']}, delta {r['delta_eventos_vs_vivo']})")
            print(f"          tablas: {r['tablas_clave']}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
