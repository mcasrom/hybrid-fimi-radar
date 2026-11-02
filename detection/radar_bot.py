#!/usr/bin/env python3
"""radar_bot.py — Bot de Telegram del Observatorio de lo publicado.

Menú de 4 temas y consulta de publicaciones recientes desde observatorio.db.
No usa clusters, bandas, diales ni atribución.
"""
import hashlib
import html
import json
import os
import socket
import sqlite3
import sys
import time
from pathlib import Path

import urllib3.util.connection
urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402
from schema_suscripciones import init  # noqa: E402

ENV_FILE = ROOT / ".env"
OBS_DB = Path("/home/deploy/observatorio/data/observatorio.db")
BASE = "https://fimi.viajeinteligencia.com"
TOPICS = [
    ("frontera_sur", "Frontera Sur", "/observatorio/ceuta/"),
    ("protestas_juveniles", "Protestas juveniles", "/observatorio/juventud/"),
    ("elecciones_generales", "Elecciones generales", "/observatorio/campana/"),
    ("infraestructuras_espana", "Infraestructuras", "/observatorio/infraestructuras/"),
]
TOPIC = {k: (label, path) for k, label, path in TOPICS}


def load_env(filepath: Path):
    try:
        for line in filepath.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


load_env(ENV_FILE)
TOKEN = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "")
API = f"https://api.telegram.org/bot{TOKEN}"


def e(x):
    return html.escape(str(x or ""))


def api_get(method, client_timeout=20, **params):
    try:
        r = requests.post(f"{API}/{method}", data=params, timeout=(10, client_timeout))
        return r.json()
    except Exception as exc:
        print(f"[bot] api {method} error: {type(exc).__name__}", file=sys.stderr)
        return {"ok": False}


def get_updates(offset, timeout=25):
    return api_get("getUpdates", client_timeout=timeout + 20, offset=offset, timeout=timeout)


def send(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        data["reply_markup"] = json.dumps(reply_markup)
    api_get("sendMessage", **data)


def keyboard(selected=None):
    selected = set(selected or [])
    rows = [[{"text": ("✅ " if key in selected else "▫ ") + label,
              "callback_data": f"tema:{key}"}] for key, label, _ in TOPICS]
    rows.append([{"text": "✅ Todos", "callback_data": "all"},
                 {"text": "✅ Confirmar", "callback_data": "conf"},
                 {"text": "✖ Cancelar", "callback_data": "can"}])
    return {"inline_keyboard": rows}


def edit(chat, message_id, text, reply_markup=None):
    data = {"chat_id": chat, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        data["reply_markup"] = json.dumps(reply_markup)
    r = api_get("editMessageText", **data)
    if not r or not r.get("ok"):
        send(chat, text, reply_markup)


def sid(chat):
    return hashlib.sha256(f"telegram:{chat}".encode()).hexdigest()[:20]


def subs(chat):
    c = init()
    row = c.execute("SELECT temas FROM suscripciones WHERE id=?", (sid(chat),)).fetchone()
    c.close()
    try:
        vals = json.loads(row[0]) if row else []
    except Exception:
        vals = []
    return [t for t in vals if t in TOPIC]


def save_subs(chat, topics):
    c = init()
    i = sid(chat)
    if topics:
        c.execute("INSERT OR IGNORE INTO suscripciones (id,canal,destino,temas,frecuencia) VALUES (?,?,?,?,?)",
                  (i, "telegram", str(chat), "[]", "on_change"))
        c.execute("UPDATE suscripciones SET temas=?, ultimo_estado=NULL WHERE id=?",
                  (json.dumps(sorted(set(topics))), i))
    else:
        c.execute("DELETE FROM suscripciones WHERE id=?", (i,))
    c.commit()
    c.close()


def recent(topic, limit=3):
    if not OBS_DB.exists():
        return []
    c = sqlite3.connect(f"file:{OBS_DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT title,url,source,published FROM items WHERE topic=? "
            "AND published IS NOT NULL "
            "ORDER BY published DESC LIMIT ?", (topic, limit)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def hoy_text(chat):
    mine = subs(chat) or [k for k, _, _ in TOPICS]
    lines = ["📰 <b>Observatorio de lo publicado</b>", "Últimas publicaciones capturadas."]
    for key in mine:
        label, path = TOPIC[key]
        lines.append(f"\n<b>{e(label)}</b>")
        rows = recent(key)
        if not rows:
            lines.append("Sin publicaciones recientes.")
            continue
        for r in rows:
            title = e(r["title"])
            if len(title) > 150:
                title = title[:147] + "…"
            lines.append(f"• {title} — {e(r['source'] or 'sin fuente')}")
        lines.append(f"<a href=\"{BASE}{path}\">Ver registro →</a>")
    return "\n".join(lines)


def sugerir(chat, text):
    c = init()
    # La tabla de sugerencias vive en radar.db; se crea si no existe.
    c.execute("CREATE TABLE IF NOT EXISTS sugerencias (id INTEGER PRIMARY KEY AUTOINCREMENT, texto TEXT, canal TEXT, ip TEXT, fecha TIMESTAMP DEFAULT (strftime('%s','now')))")
    c.execute("INSERT INTO sugerencias (texto,canal,ip) VALUES (?,?,?)", (text[:500], "telegram", str(chat)))
    c.commit()
    c.close()
    owner = int(os.environ.get("FIMI_OWNER_CHAT", "47652516"))
    send(owner, f"📥 <b>Sugerencia para el Observatorio</b>\n\n{e(text[:500])}")


def main():
    if not TOKEN or ":" not in TOKEN:
        print("[bot] token no configurado", file=sys.stderr)
        return
    print(f"[bot] Observatorio: {len(TOPICS)} temas", flush=True)
    offset = 0
    sel = {}
    while True:
        upd = get_updates(offset)
        if not upd or not upd.get("ok"):
            time.sleep(3)
            continue
        for u in upd.get("result", []):
            offset = u["update_id"] + 1
            cb = u.get("callback_query") or {}
            if cb:
                chat = cb["message"]["chat"]["id"]
                data = cb.get("data", "")
                cur = sel.get(chat, set())
                m_id = cb["message"]["message_id"]
                if data.startswith("tema:"):
                    key = data.split(":", 1)[1]
                    if key in TOPIC:
                        cur.symmetric_difference_update({key})
                    sel[chat] = cur
                    labels = ", ".join(TOPIC[t][0] for t in sorted(cur)) or "ninguno"
                    edit(chat, m_id, f"Selección: <b>{e(labels)}</b>\nPulsa ✅ Confirmar para guardar.", keyboard(cur))
                elif data == "all":
                    sel[chat] = {k for k, _, _ in TOPICS}
                    edit(chat, m_id, "Selección: <b>los cuatro temas</b>\nPulsa ✅ Confirmar para guardar.", keyboard(sel[chat]))
                elif data == "conf":
                    final = sorted(cur)
                    save_subs(chat, final)
                    sel.pop(chat, None)
                    edit(chat, m_id, "✅ Suscrito a: <b>" + (", ".join(TOPIC[t][0] for t in final) or "ninguno") + "</b>")
                elif data == "can":
                    sel.pop(chat, None)
                    edit(chat, m_id, "Cancelado. No se cambió nada.")
                else:
                    edit(chat, m_id, "Ese botón es del FIMI anterior. Usa /temas.")
                continue
            msg = u.get("message") or {}
            chat = msg.get("chat", {}).get("id")
            if not chat:
                continue
            txt = (msg.get("text") or "").strip()
            low = txt.lower()
            if low.startswith("/start") or low.startswith("/help"):
                send(chat,
                     "📡 <b>Observatorio de lo publicado</b>\n"
                     "Registro de publicaciones sobre cuatro temas. No detecta campañas ni atribuye intenciones.\n\n"
                     "/temas — elegir temas\n/mis — tus temas\n/hoy — últimas publicaciones\n"
                     "/evidencia — estado documental\n/fuentes — fuentes y método\n"
                     "/sugerir TEXTO — proponer una corrección\n/baja — darte de baja")
            elif low.startswith("/temas") or low.startswith("/radar"):
                sel[chat] = set(subs(chat))
                send(chat, f"Selección: <b>{e(', '.join(TOPIC[t][0] for t in sorted(sel[chat])) or 'ninguno')}</b>\nMarca los temas y pulsa ✅ Confirmar:", keyboard(sel[chat]))
            elif low.startswith("/mis"):
                mine = subs(chat)
                send(chat, "Tus temas: " + (", ".join(TOPIC[t][0] for t in mine) if mine else "ninguno (usa /temas)"))
            elif low.startswith("/hoy"):
                send(chat, hoy_text(chat))
            elif low.startswith("/evidencia"):
                send(chat, f"🔎 Evidencia y vacíos: {BASE}/observatorio/evidencia/")
            elif low.startswith("/fuentes"):
                send(chat, f"📚 Fuentes y método: {BASE}/observatorio/fuentes/")
            elif low.startswith("/sugerir"):
                text = txt[len("/sugerir"):].strip()
                if text:
                    sugerir(chat, text)
                    send(chat, "📥 Gracias. La sugerencia ha llegado al administrador.")
                else:
                    send(chat, "Uso: /sugerir una corrección o un enlace")
            elif low.startswith("/baja"):
                save_subs(chat, [])
                send(chat, "Listo. Te has dado de baja del Observatorio.")
            else:
                send(chat, "No reconozco ese comando. Usa /start.")
        time.sleep(1)


if __name__ == "__main__":
    main()
