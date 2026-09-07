#!/usr/bin/env python3
"""check_ingesta.py — Alerta si el cron de captura se ha saltado un ciclo.

El dashboard regenera cada 6h (cron :30). Si la captura más reciente
(MAX(events.timestamp)) supera un umbral (> UMBRAL_H, ~1 ciclo y margen),
el pipeline probablemente ha fallado: avisa al dueño por Telegram UNA vez
por episodio (state en data/ingesta_estado.json), sin spam.

Complementa el indicador rojo "cron saltado" del dashboard: ese es pasivo
(lo ves si miras); este es proactivo (te avisa).

Uso (añadir al cron 6h, tras la captura):
  .venv/bin/python detection/check_ingesta.py >> logs/ingesta.log 2>&1
"""
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
STATE = ROOT / "data" / "ingesta_estado.json"
LOG = ROOT / "logs" / "ingesta.log"
CHAT = int(os.environ.get("FIMI_INGESTA_CHAT", "47652516"))

# Cron cada 6h. Si la última captura supera UMBRAL_H (1.25 ciclos = margen),
# el pipeline se ha saltado al menos un ciclo.
UMBRAL_H = float(os.environ.get("FIMI_INGESTA_H", 7.5))


def load_env(filepath: Path):
    try:
        for line in open(filepath):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


def send(token, text):
    if not token or ":" not in token:
        print("[ingesta] sin token — mensaje no enviado")
        return False
    api = f"https://api.telegram.org/bot{token}"
    try:
        r = requests.post(f"{api}/sendMessage",
                          data={"chat_id": str(CHAT), "text": text}, timeout=20)
        print(f"[ingesta] telegram HTTP {r.status_code}")
        return r.ok
    except Exception as e:
        print(f"[ingesta] telegram error: {e}")
        return False


def main():
    load_env(ROOT / ".env")
    token = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "")
    try:
        con = sqlite3.connect(DB)
        last = con.execute("SELECT MAX(timestamp) FROM events").fetchone()[0]
        con.close()
    except Exception as e:
        print(f"[ingesta] error BD: {e}")
        return 1

    if not last:
        print("[ingesta] sin eventos en BD")
        return 0

    ahora = time.time()
    horas = (ahora - last) / 3600.0
    fecha = datetime.fromtimestamp(last, tz=timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text())
        except Exception:
            state = {}

    if horas <= UMBRAL_H:
        # recuperado o normal: resetear estado
        if state.get("alerta"):
            STATE.write_text(json.dumps({"alerta": False}))
            print(f"[ingesta] OK (hace {horas:.1f}h). Alerta reseteada.")
        else:
            print(f"[ingesta] OK (hace {horas:.1f}h < {UMBRAL_H}h).")
        return 0

    # se saltó un ciclo
    if state.get("alerta"):
        print(f"[ingesta] ya alertado ({horas:.1f}h); sin re-avisar.")
        return 0

    msg = (f"⚠️ FIMI Radar: la captura lleva >{UMBRAL_H:.0f}h sin actualizar.\n"
           f"· Última ingesta: {fecha} (hace {horas:.1f} h)\n"
           f"· El cron cada 6h parece haberse saltado un ciclo.\n"
           f"Revisa: cron_every_6h.sh · pm2 list · logs/capture.log")
    ok = send(token, msg)
    STATE.write_text(json.dumps({"alerta": True}))
    print(f"[ingesta] ALERTA enviada (hace {horas:.1f}h): {ok}")


if __name__ == "__main__":
    sys.exit(main())
