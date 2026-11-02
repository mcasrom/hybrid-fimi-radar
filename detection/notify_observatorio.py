#!/usr/bin/env python3
"""Avisos Telegram del Observatorio: nuevas publicaciones por tema.

No habla de clusters, bandas ni coordinación. La primera pasada solo siembra
el estado (no envía el histórico).
"""
import html
import json
import os
import socket
import sqlite3
import sys
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
TOPICS = {
    "frontera_sur": ("Frontera Sur", "/observatorio/ceuta/"),
    "protestas_juveniles": ("Protestas juveniles", "/observatorio/juventud/"),
    "elecciones_generales": ("Elecciones generales", "/observatorio/campana/"),
    "infraestructuras_espana": ("Infraestructuras", "/observatorio/infraestructuras/"),
}
STATE_KEY = "__obs_last__"


def load_env(path):
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except OSError:
        pass


def e(x):
    return html.escape(str(x or ""))


def max_published(topic):
    c = sqlite3.connect(f"file:{OBS_DB}?mode=ro", uri=True)
    try:
        row = c.execute("SELECT MAX(published) FROM items WHERE topic=?", (topic,)).fetchone()
        return row[0] if row else None
    finally:
        c.close()


def new_items(topic, since, limit=3):
    c = sqlite3.connect(f"file:{OBS_DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT title,url,source,published FROM items "
            "WHERE topic=? AND published IS NOT NULL AND published > ? "
            "ORDER BY published DESC LIMIT ?", (topic, since, limit)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def main(dry=False):
    load_env(ENV_FILE)
    token = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "")
    if not token or ":" not in token:
        print("[notify-obs] token no configurado", file=sys.stderr)
        return 0
    api = f"https://api.telegram.org/bot{token}"
    con = init()
    subs = con.execute("SELECT * FROM suscripciones WHERE canal='telegram'").fetchall()
    sent = 0
    for row in subs:
        try:
            temas = [t for t in (json.loads(row["temas"] or "[]") or []) if t in TOPICS]
        except Exception:
            temas = []
        if not temas:
            continue
        try:
            state = json.loads(row["ultimo_estado"] or "{}")
        except Exception:
            state = {}
        last = state.get(STATE_KEY)
        if not isinstance(last, dict):
            # Primera pasada: sembrar sin enviar histórico.
            last = {t: max_published(t) for t in temas}
            state[STATE_KEY] = last
            if not dry:
                con.execute("UPDATE suscripciones SET ultimo_estado=? WHERE id=?", (json.dumps(state), row["id"]))
            continue
        blocks = []
        nuevo = dict(last)
        for t in temas:
            since = last.get(t)
            if not since:
                nuevo[t] = max_published(t)
                continue
            rows = new_items(t, since)
            if not rows:
                continue
            label, path = TOPICS[t]
            lines = [f"<b>{e(label)}</b>"]
            for r in rows:
                title = e(r["title"])
                if len(title) > 140:
                    title = title[:137] + "…"
                lines.append(f"• {title} — {e(r['source'] or 'sin fuente')}")
            lines.append(f'<a href="{BASE}{path}">Ver registro →</a>')
            blocks.append("\n".join(lines))
            nuevo[t] = max(x["published"] for x in rows)
        if blocks and not dry:
            text = "📰 <b>Observatorio de lo publicado</b>\n\n" + "\n\n".join(blocks)
            try:
                requests.post(f"{api}/sendMessage", data={
                    "chat_id": row["destino"], "text": text, "parse_mode": "HTML"
                }, timeout=30)
                sent += 1
            except Exception as exc:
                print(f"[notify-obs] error: {type(exc).__name__}", file=sys.stderr)
        elif blocks and dry:
            print("[dry] aviso para", row["destino"], "temas", list(nuevo))
            sent += 1
        if not dry:
            state[STATE_KEY] = nuevo
            con.execute("UPDATE suscripciones SET ultimo_estado=? WHERE id=?", (json.dumps(state), row["id"]))
    if not dry:
        con.commit()
    con.close()
    print(f"[notify-obs] {sent} avisos")
    return sent


if __name__ == "__main__":
    main(dry="--dry" in sys.argv)
