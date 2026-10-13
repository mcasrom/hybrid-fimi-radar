#!/usr/bin/env python3
"""export_caso_ceuta.py — Dataset PÚBLICO y citable del caso Ceuta, en dos capas:

  - `frozen` (V1): el análisis CONGELADO (curated, docs/casos/ceuta-v1.json) + hash
    SHA-256 → registro inmutable/reproducible. NO se recalcula.
  - `live`: cifras actuales del tema `frontera_sur` desde la BD (event_temas, regla 7),
    recalculadas en cada ciclo. Es lo que SIGUE llegando tras el congelamiento.

Escribe (JSON + CSV) en docs/casos/ y /var/www/fimi/datos/casos/.
El hash permite probar que el bloque congelado no ha cambiado.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
FROZEN = ROOT / "docs" / "casos" / "ceuta-v1.json"
TEMA = "frontera_sur"
LINEAGE = "frontera_sur_cluster_011"
TS_CASE = int(datetime(2026, 7, 30, tzinfo=timezone.utc).timestamp())


def _hash(obj):
    canon = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _live():
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
    except Exception as e:
        print("export-caso: BD no abrible:", e)
        return {}
    ev = con.execute(
        "SELECT COUNT(*) n, COUNT(DISTINCT e.author) a, COUNT(DISTINCT e.source) s, "
        "COUNT(DISTINCT e.url) u, MAX(e.timestamp) mx FROM events e "
        "JOIN event_temas et ON et.event_id=e.id WHERE et.tema_id=? AND e.timestamp>=?",
        (TEMA, TS_CASE)).fetchone()
    ncl = con.execute("SELECT COUNT(*) FROM clusters WHERE tema_id=?", (TEMA,)).fetchone()[0]
    nhigh = con.execute(
        "SELECT COUNT(*) FROM clusters WHERE tema_id=? AND overall_score>=60", (TEMA,)).fetchone()[0]
    sust = None
    try:
        row = con.execute("SELECT cluster_label FROM cluster_lineage WHERE lineage_id LIKE ? "
                          "ORDER BY first_seen DESC LIMIT 1", (LINEAGE + "@%",)).fetchone()
        if row:
            c = con.execute("SELECT id, anomaly_score FROM clusters WHERE cluster_label=?",
                            (row["cluster_label"],)).fetchone()
            if c:
                sc = con.execute("SELECT COUNT(*) n, COUNT(DISTINCT author) a, MIN(ts) i, MAX(ts) f "
                                 "FROM cluster_events WHERE cluster_id=?", (c["id"],)).fetchone()
                sust = {"cuentas": sc["a"], "mensajes": sc["n"],
                        "anomalia": round(c["anomaly_score"] or 0),
                        "desde": datetime.fromtimestamp(sc["i"], tz=timezone.utc).date().isoformat() if sc["i"] else None,
                        "hasta": datetime.fromtimestamp(sc["f"], tz=timezone.utc).date().isoformat() if sc["f"] else None}
    except Exception as e:
        print("export-caso: sostenido falló:", e)
    con.close()
    return {"periodo": {"desde": "2026-07-30", "hasta":
                        datetime.fromtimestamp(ev["mx"], tz=timezone.utc).date().isoformat() if ev["mx"] else None},
            "eventos": ev["n"], "autores": ev["a"], "fuentes": ev["s"], "urls": ev["u"],
            "clusters": ncl, "banda_alta": nhigh, "cluster_sostenido": sust}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", default="/var/www/fimi/datos/casos")
    a = ap.parse_args()
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    doc = {
        "caso": "ceuta-frontera-sur",
        "url": frozen.get("url"),
        "meta": {
            "generado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "frozen_version": frozen.get("version"),
            "frozen_congelado_utc": frozen.get("congelado_utc"),
            "hash_frozen": _hash(frozen),
            "aviso": "Señal, no atribución. El bloque 'frozen' (V1) es inmutable; 'live' se recalcula cada ciclo.",
        },
        "frozen": frozen,
        "live": _live(),
        "como_actualizar": ("Frozen: editar docs/casos/ceuta-v1.json (cambio de versión, p.ej. V2). "
                            "Live: automático (cron 6 h → update_caso_ceuta_live.py + este export). "
                            "Fuente live: event_temas (tema frontera_sur) y cluster_lineage."),
    }
    od = ROOT / "docs" / "casos"
    od.mkdir(parents=True, exist_ok=True)
    (od / "ceuta.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    # servir
    wp = Path(a.web)
    if wp.parent.exists():
        wp.mkdir(parents=True, exist_ok=True)
        (wp / "ceuta.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        with open(wp / "ceuta-frozen.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["clave", "valor"])
            for k, v in frozen.items():
                if isinstance(v, (str, int, float)):
                    w.writerow([k, v])
    print(f"OK ceuta.json  hash_frozen={doc['meta']['hash_frozen'][:23]}…  "
          f"eventos_live={doc['live'].get('eventos')}  clusters_live={doc['live'].get('clusters')}")


if __name__ == "__main__":
    main()
