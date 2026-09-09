#!/usr/bin/env python3
"""backfill_tema_contenido.py — Re-etiquetar eventos existentes por contenido.

Cuando se añaden/cambian keywords de un tema (p.ej. calibrar oriente_medio de
frases FIMI a términos temáticos), los eventos YA capturados no se re-clasifican
automáticamente: capture.py solo clasifica lo nuevo. Este script re-ejecuta
temas_por_contenido sobre el histórico reciente y añade el tema a event_temas
(INSERT OR IGNORE), sin quitar ningún tema existente (multi-tema).

Uso:
  venv/bin/python detection/backfill_tema_contenido.py [--tema oriente_medio] [--dias 30] [--dry]

--tema: solo re-clasifica para ese tema (si se omite, para todos los temas que
        tengan keywords en config). --dias: ventana hacia atrás (default 30).
"""
import argparse
import datetime
import sqlite3
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from normalizer.clasificar import temas_por_contenido


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "radar.db"))
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--tema", default=None)
    ap.add_argument("--dias", type=int, default=30)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config))
    keywords = cfg.get("keywords", []) or []
    temas_con_kw = {}
    for k in keywords:
        if not isinstance(k, dict):
            continue
        t = k.get("tema") or "frontera_sur"
        temas_con_kw.setdefault(t, []).append(k)
    if args.tema:
        if args.tema not in temas_con_kw:
            print(f"el tema {args.tema} no tiene keywords en config")
            sys.exit(1)
        temas_con_kw = {args.tema: temas_con_kw[args.tema]}

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    t0 = int(datetime.datetime.now(datetime.timezone.utc).timestamp()) - args.dias * 86400
    rows = con.execute(
        "SELECT id, text, title FROM events WHERE timestamp>? ORDER BY id", (t0,)).fetchall()
    print(f"eventos en ventana {args.dias}d: {len(rows)}")
    if not rows:
        con.close()
        return

    ya = {}
    for r in con.execute("SELECT event_id, tema_id FROM event_temas").fetchall():
        ya.setdefault(r["event_id"], set()).add(r["tema_id"])

    total_add = 0
    for tema, kws in temas_con_kw.items():
        añadidos = 0
        for r in rows:
            txt = (r["title"] or "") + " " + (r["text"] or "")
            if tema in temas_por_contenido(txt, kws):
                prev = ya.get(r["id"], set())
                if tema not in prev:
                    añadidos += 1
                    if not args.dry:
                        con.execute(
                            "INSERT OR IGNORE INTO event_temas (event_id, tema_id) VALUES (?,?)",
                            (r["id"], tema))
        con.commit()
        total_add += añadidos
        print(f"  tema {tema}: {añadidos} eventos nuevos etiquetados ({'DRY' if args.dry else 'OK'})")
    con.close()
    print(f"total añadidos: {total_add}")


if __name__ == "__main__":
    main()
