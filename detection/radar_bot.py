#!/usr/bin/env python3
"""radar_bot.py — Bot de Telegram para suscripciones al radar FIMI.

Bot dedicado (no comparte polling con nearme_status_bot). Comandos:
  /start o /help -> ayuda
  /radar         -> teclado inline multi-selección de temas (elige los que quieras)
  /mis           -> ver sus temas y frecuencia acutales
  /baja          -> borra la suscripción de Telegram de este chat

Alta: tras /radar, el usuario marca los temas y pulsa "Confirmar". La fila
se guarda en la tabla `suscripciones` (canal='telegram', destino=chat_id).

El ENVÍO de avisos (on_change) NO lo hace este bot: lo hace el cron
notify_subs_telegram.py al detectar cambios en los diales. Este script solo
atiende los comandos (long-poll) para no duplicar lógica.

Token: se lee de FIMI_TELEGRAM_BOT_TOKEN (env/PM2) o de .env
(/home/deploy/hybrid-fimi-radar/.env). NO hardcodeado.
"""
import hashlib
import json
import os
import socket
import time
from pathlib import Path

import urllib3.util.connection
urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

ROOT = Path(__file__).resolve().parent.parent
sys_path = str(ROOT)
import sys
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

import requests  # noqa: E402
from schema_suscripciones import init  # noqa: E402
from radar_trend import _cargar_temas_activos, NOMBRE_TEMA  # noqa: E402

ENV_FILE = ROOT / ".env"


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


load_env(ENV_FILE)
TOKEN = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
API = f"https://api.telegram.org/bot{TOKEN}"

# temas del catálogo real (orden estable)
TEMAS = _cargar_temas_activos()


def _short_id(canal: str, destino: str) -> str:
    return hashlib.sha256(f"{canal}:{destino}".encode()).hexdigest()[:20]


def api_get(method: str, **params):
    try:
        r = requests.post(f"{API}/{method}", data=params, timeout=30)
        return r.json()
    except Exception as e:
        print(f"[bot] api {method} error: {e}")
        return {"ok": False}


def get_updates(offset: int, timeout: int = 30):
    return api_get("getUpdates", offset=offset, timeout=timeout)


def send(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        data["reply_markup"] = json.dumps(reply_markup)
    api_get("sendMessage", **data)


def build_keyboard():
    kbd = []
    row = []
    for i, t in enumerate(TEMAS):
        row.append({"text": f"🔴 {NOMBRE_TEMA.get(t, t)}", "callback_data": f"tema:{t}"})
        if len(row) == 2:
            kbd.append(row)
            row = []
    if row:
        kbd.append(row)
    kbd.append([{"text": "✅ Confirmar", "callback_data": "conf"},
                {"text": "✖ Cancelar", "callback_data": "can"}])
    return {"inline_keyboard": kbd}


def upsert_sub(destino, temas):
    conn = init()
    sid = _short_id("telegram", str(destino))
    raw = conn.execute("SELECT temas FROM suscripciones WHERE id=?", (sid,)).fetchone()
    actual = set(json.loads(raw[0])) if raw else set()
    actual |= set(temas)
    if not raw:
        conn.execute(
            "INSERT INTO suscripciones (id, canal, destino, temas, frecuencia)"
            " VALUES (?,?,?,?,?)",
            (sid, "telegram", str(destino), json.dumps(sorted(actual)), "on_change"))
    else:
        conn.execute("UPDATE suscripciones SET temas=?, ultimo_estado=NULL WHERE id=?",
                     (json.dumps(sorted(actual)), sid))
    conn.commit()
    conn.close()
    return sorted(actual)


def set_subs(destino, temas):
    conn = init()
    sid = _short_id("telegram", str(destino))
    if temas:
        conn.execute("UPDATE suscripciones SET temas=? WHERE id=?",
                     (json.dumps(sorted(temas)), sid))
    else:
        conn.execute("DELETE FROM suscripciones WHERE id=?", (sid,))
    conn.commit()
    conn.close()


def my_subs(destino):
    conn = init()
    sid = _short_id("telegram", str(destino))
    row = conn.execute("SELECT temas FROM suscripciones WHERE id=?", (sid,)).fetchone()
    conn.close()
    return sorted(json.loads(row[0])) if row else []


def main():
    if not TOKEN or ":" not in TOKEN:
        print("[bot] FIMI_TELEGRAM_BOT_TOKEN no configurado en env/.env — saliendo.")
        return
    print(f"[bot] arrancando, {len(TEMAS)} temas: {TEMAS}")
    offset = 0
    # estado provisional de selección por chat
    sel = {}
    while True:
        upd = get_updates(offset)
        if not upd or not upd.get("ok"):
            time.sleep(3)
            continue
        for u in upd.get("result", []):
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            cb = u.get("callback_query") or {}
            if cb:
                chat_id = cb["message"]["chat"]["id"]
                m_id = cb["message"]["message_id"]
                data = cb.get("data", "")
                cur = sel.get(chat_id, set())
                if data.startswith("tema:"):
                    t = data.split(":", 1)[1]
                    if t in cur:
                        cur.discard(t)
                    else:
                        cur.add(t)
                    sel[chat_id] = cur
                    send(chat_id, "Selección: " + (", ".join(sorted(cur)) or "ninguno"), build_keyboard())
                elif data == "conf":
                    final = upsert_sub(chat_id, list(cur))
                    del sel[chat_id]
                    send(chat_id, f"✅ Suscrito a: {', '.join(final) or 'ninguno'}.\nTe avisaré solo cuando el dial cambie.")
                elif data == "can":
                    del sel[chat_id]
                    send(chat_id, "Cancelado. Nadie borrado.")
                continue
            chat = msg.get("chat", {}).get("id")
            if not chat:
                continue
            txt = (msg.get("text") or "").strip()
            if txt.startswith("/start") or txt.startswith("/help"):
                send(chat, "📡 <b>Radar FIMI</b> — alertas de los diales por tema.\n\n"
                           "/radar — elegir temas\n/mis — tus temas\n/baja — darte de baja\n\n"
                           "Te aviso SOLO cuando un tema cambia de estado (Subiendo/Bajando/Estable).")
            elif txt.startswith("/radar"):
                sel[chat] = set()
                send(chat, "Marca los temas que quieres seguir y pulsa Confirmar:", build_keyboard())
            elif txt.startswith("/mis"):
                mine = my_subs(chat)
                send(chat, "Tus temas: " + (", ".join(mine) if mine else "ninguno (usa /radar)"))
            elif txt.startswith("/baja"):
                set_subs(chat, [])
                send(chat, "Listo. Te has dado de baja del radar FIMI.")
        time.sleep(1)


if __name__ == "__main__":
    main()
