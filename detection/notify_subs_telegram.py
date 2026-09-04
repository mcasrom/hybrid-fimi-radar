#!/usr/bin/env python3
"""notify_subs_telegram.py — Envía avisos a los suscritos cuando cambia un dial.

Se lanza tras cada ciclo de run_fimi (cron 6h). Para cada suscriptor de
Telegram que sigue un tema con frecuencia 'on_change':

  1. Calcula el estado actual del dial del tema (radar_trend).
  2. Lo compara con el último estado notificado (ultimo_estado de la BD).
  3. Si cambió (o no hay registro previo) y el tema no está en 'recopilando',
     envía:
       📡 [Tema]: ahora [Subiendo/Bajando]. [frase]. Ver: https://fimi...
  4. Actualiza ultimo_estado con el valor actual (aunque no envíe, para no
     repetir después).

Idempotente y seguro: no envía nada si no ha cambiado. Se puede cronificar
sin miedo a spam.
"""
import json
import os
import socket
import sys
from pathlib import Path

import urllib3.util.connection
urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests  # noqa: E402
from schema_suscripciones import init  # noqa: E402
from radar_trend import estado_por_tema, texto_dial, _cargar_temas_activos  # noqa: E402

URL_DASH = "https://fimi.viajeinteligencia.com"


def load_env(filepath: Path):
    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


def main(dry_run: bool = False):
    load_env(ROOT / ".env")
    token = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "")
    if not token or ":" not in token:
        print("[notify] FIMI_TELEGRAM_BOT_TOKEN no configurado — sin envíos.")
        return 0

    api = f"https://api.telegram.org/bot{token}"
    conn = init()
    temas = _cargar_temas_activos()
    estados = estado_por_tema(temas)

    subs = conn.execute("SELECT * FROM suscripciones WHERE canal='telegram'").fetchall()
    enviados = 0
    for row in subs:
        if not row["confirmado"] and row["frecuencia"] != "on_change":
            # los de telegram se activan al suscribirse; on_change basta
            pass
        try:
            mis_temas = json.loads(row["temas"]) or []
        except Exception:
            mis_temas = []
        prev = {}
        if row["ultimo_estado"]:
            try:
                prev = json.loads(row["ultimo_estado"]) or {}
            except Exception:
                prev = {}
        nuevo_prev = dict(prev)
        for t in mis_temas:
            if t not in estados:
                continue
            st = estados[t]
            estado = st["estado"]
            nuevo_prev[t] = estado
            if estado == "recopilando":
                continue  # aún sin datos: no molestar
            if prev.get(t) == estado:
                continue  # SIN cambio: no enviar nada
            txt = texto_dial(t, estado)
            line = (f"📡 <b>Radar FIMI</b> — {t}\n"
                    f"Ahora: <b>{txt}</b>.\n")
            if estado == "subiendo":
                line += f"({st['hoy']} hallazgos hoy, {st['high_hoy']} en alerta alta)\n"
            elif estado == "bajando":
                line += f"({st['hoy']} hallazgos hoy frente a {st['hace48']} hace 48h)\n"
            line += f"Ver: {URL_DASH}"
            if not dry_run:
                try:
                    requests.post(f"{api}/sendMessage", data={
                        "chat_id": row["destino"], "text": line, "parse_mode": "HTML"
                    }, timeout=30)
                    enviados += 1
                    print(f"[notify] -> {row['destino']} {t}: {estado}")
                except Exception as e:
                    print(f"[notify] error a {row['destino']}: {e}")
            else:
                print(f"[dry] -> {row['destino']} {t}: {estado}")
                enviados += 1
        # guardar el estado del ciclo aunque no se haya notificado, para no
        # re-notificar en el próximo ciclo lo que ya vimos.
        conn.execute("UPDATE suscripciones SET ultimo_estado=? WHERE id=?",
                     (json.dumps(nuevo_prev), row["id"]))
    conn.commit()
    conn.close()
    print(f"[notify] {enviados} avisos enviados de {len(subs)} suscriptores telegram")
    return enviados


if __name__ == "__main__":
    main(dry_run="--dry" in sys.argv)
