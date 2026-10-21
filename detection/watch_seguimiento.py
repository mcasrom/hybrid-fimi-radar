#!/usr/bin/env python3
"""watch_seguimiento.py — vigila terminos del caso Frontera Sur sin tocar keywords.

Lee la BD (read-only), busca los terminos en los ultimos N dias y avisa por
Telegram solo si hay piezas NUEVAS (dedup por id de evento). No captura ni
puntua: solo seguimiento editorial.

Uso:
  .venv/bin/python detection/watch_seguimiento.py --seed     # marca lo actual sin avisar
  .venv/bin/python detection/watch_seguimiento.py --dry      # muestra nuevas, no guarda
  .venv/bin/python detection/watch_seguimiento.py --tg       # avisa por Telegram si hay nuevas
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
STATE = ROOT / "data" / "seguimiento_state.json"
ENV = ROOT / ".env"
CASE = "https://fimi.viajeinteligencia.com/casos/frontera_sur_hibridos/"

TERMS = [
    "honda de david",
    "david's sling",
    "davids sling",
]
# terminos amplios: solo cuentan si el evento menciona Marruecos
CONTEXT = [
    "cúpula israelí",
    "cupula israeli",
    "escudo antimisiles",
    "antimisiles",
    "defensa aérea",
    "defensa aerea",
    "escudo aéreo",
    "escudo aereo",
]
MAR = ("marruecos", "morocco", "maroc", "rabat")


def match(blob: str) -> bool:
    if any(t in blob for t in TERMS):
        return True
    return any(t in blob for t in CONTEXT) and any(m in blob for m in MAR)


def env(path):
    d = {}
    try:
        for ln in open(path, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, _, v = ln.partition("=")
                d[k.strip()] = v.strip()
    except OSError as ex:
        print("[env] no se pudo leer %s: %s" % (path, ex), file=sys.stderr)
    return d


def send_tg(text):
    e = env(ENV)
    tok = e.get("FIMI_TELEGRAM_BOT_TOKEN", "")
    chat = (e.get("TELEGRAM_CANAL") or e.get("FIMI_CANAL") or "").strip()
    if not tok or not chat:
        print("[tg] sin token/canal; no se envia")
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % tok, data=data)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return bool(json.loads(r.read().decode()).get("ok"))
    except Exception as ex:
        print("[tg] fallo:", ex)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=7)
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--tg", action="store_true")
    a = ap.parse_args()

    since = int((datetime.now(timezone.utc) - timedelta(days=a.dias)).timestamp())
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    rows = con.execute(
        "SELECT id, timestamp, source, title, text, url FROM events WHERE timestamp >= ?",
        (since,),
    ).fetchall()

    hits = []
    for r in rows:
        blob = " ".join(str(x or "") for x in (r[3], r[4])).lower()
        if match(blob):
            hits.append(r)

    state = {"seen": [], "updated": ""}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text(encoding="utf-8"))
        except ValueError as ex:
            print("[state] JSON invalido: %s" % ex, file=sys.stderr)
    seen = set(state.get("seen", []))
    nuevos = [r for r in hits if r[0] not in seen]

    print(f"[seguimiento] {len(rows)} eventos ({a.dias} d) · {len(hits)} con terminos · {len(nuevos)} nuevos")
    for r in sorted(nuevos, key=lambda x: x[1], reverse=True)[:8]:
        ts = datetime.fromtimestamp(r[1], timezone.utc).strftime("%Y-%m-%d %H:%M")
        print(f"  {ts} | {r[2]} | {(r[3] or r[4] or '')[:110]}")

    if a.seed or (nuevos and not a.dry):
        state = {
            "seen": sorted(seen | {r[0] for r in hits}),
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if not a.dry:
            STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            print(f"[seguimiento] estado guardado ({len(state['seen'])} vistos)")

    if a.tg and nuevos and not a.dry:
        lines = []
        for r in sorted(nuevos, key=lambda x: x[1], reverse=True)[:4]:
            t = (r[3] or r[4] or "").replace("\n", " ")[:120]
            lines.append(f"· {t} ({r[2]})")
        msg = (
            f"Seguimiento Frontera Sur: {len(nuevos)} pieza(s) nueva(s) con términos del escudo israelí.\n"
            + "\n".join(lines)
            + f"\n\n{CASE}"
        )
        print("[tg] enviado:", send_tg(msg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
