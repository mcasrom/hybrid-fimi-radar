#!/usr/bin/env python3
"""monitor_telegram.py — vigila el volumen de Telegram y avisa si se dispara.

Lee `radar.db`; no captura, no escribe eventos.
Umbrales conservadores (26-oct-2026):
  - 24 h: aviso 300, crítico 650
  - 6 h:  aviso 100, crítico 220
  - un canal: aviso 100/24 h, crítico 180/24 h
  - Telegram como % del corpus 24 h: aviso 5 %, crítico 10 %
Avisa por Telegram solo al cambiar de nivel; estado en
`data/telegram_volume_state.json`.

Uso:
  .venv/bin/python detection/monitor_telegram.py
  .venv/bin/python detection/monitor_telegram.py --tg
  .venv/bin/python detection/monitor_telegram.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
STATE = ROOT / "data" / "telegram_volume_state.json"
TG24_WARN, TG24_BAD = 300, 650
TG6_WARN, TG6_BAD = 100, 220
CH_WARN, CH_BAD = 100, 180
SHARE_WARN, SHARE_BAD = 0.05, 0.10


def load_env(path: Path):
    try:
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    except OSError:
        pass


def send_tg(text: str) -> bool:
    token = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("FIMI_OWNER_CHAT") or os.environ.get("FIMI_TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print("[tg-monitor] sin token/chat; no se envía", file=sys.stderr)
        return False
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({"chat_id": chat, "text": text,
                         "disable_web_page_preview": True}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except Exception as e:  # noqa: BLE001
        print(f"[tg-monitor] Telegram error: {e}", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tg", action="store_true", help="enviar aviso al dueño")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    load_env(ROOT / ".env")
    now = int(time.time())
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    total24 = con.execute("SELECT COUNT(*) FROM events WHERE timestamp>=?", (now - 86400,)).fetchone()[0]
    tg24 = con.execute("SELECT COUNT(*) FROM events WHERE source LIKE 'telegram:%' AND timestamp>=?", (now - 86400,)).fetchone()[0]
    tg6 = con.execute("SELECT COUNT(*) FROM events WHERE source LIKE 'telegram:%' AND timestamp>=?", (now - 6 * 3600,)).fetchone()[0]
    total6 = con.execute("SELECT COUNT(*) FROM events WHERE timestamp>=?", (now - 6 * 3600,)).fetchone()[0]
    by = con.execute(
        "SELECT source, COUNT(*) n FROM events WHERE source LIKE 'telegram:%' "
        "AND timestamp>=? GROUP BY source ORDER BY n DESC", (now - 86400,)).fetchall()
    con.close()
    share = (tg24 / total24) if total24 else 0.0
    level = "ok"
    reasons = []
    if tg24 >= TG24_BAD or tg6 >= TG6_BAD or share >= SHARE_BAD:
        level = "bad"
    elif tg24 >= TG24_WARN or tg6 >= TG6_WARN or share >= SHARE_WARN:
        level = "warn"
    if tg24 >= TG24_BAD:
        reasons.append(f"24h {tg24}≥{TG24_BAD}")
    if tg6 >= TG6_BAD:
        reasons.append(f"6h {tg6}≥{TG6_BAD}")
    if share >= SHARE_BAD:
        reasons.append(f"cuota {share:.1%}≥{SHARE_BAD:.0%}")
    if level == "ok":
        if tg24 >= TG24_WARN: reasons.append(f"24h {tg24}≥{TG24_WARN}")
        if tg6 >= TG6_WARN: reasons.append(f"6h {tg6}≥{TG6_WARN}")
        if share >= SHARE_WARN: reasons.append(f"cuota {share:.1%}≥{SHARE_WARN:.0%}")
    for src, n in by:
        ch = src.split(":", 1)[-1]
        if n >= CH_BAD:
            level = "bad"; reasons.append(f"{ch} {n}≥{CH_BAD}")
        elif n >= CH_WARN and level == "ok":
            level = "warn"; reasons.append(f"{ch} {n}≥{CH_WARN}")

    data = {"level": level, "tg_24h": tg24, "tg_6h": tg6, "total_24h": total24,
            "share": round(share, 4), "by_channel": [{"canal": s.split(":",1)[-1], "n": n} for s, n in by],
            "reasons": reasons, "at": now}
    prev = {}
    try:
        prev = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        pass
    state = {"level": level, "at": now, "reasons": reasons}
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps(data, ensure_ascii=False, indent=2) if a.json else
          f"[tg-monitor] {level.upper()} · 24h={tg24} · 6h={tg6} · {share:.1%} del corpus"
          + (f" · {'; '.join(reasons)}" if reasons else ""))
    if a.tg and level != prev.get("level", "ok") and level != "ok":
        msg = (f"⚠️ Telegram volumen {level.upper()}\n"
               f"24h: {tg24} · 6h: {tg6} · cuota: {share:.1%} ({tg24}/{total24})\n"
               f"{'; '.join(reasons)}\n"
               "Revisar canales en config.yaml y logs/capture.log")
        send_tg(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
