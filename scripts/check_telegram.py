#!/usr/bin/env python3
"""check_telegram.py — valida canales públicos de Telegram del piloto.

Lee data/telegram_protestas.yaml, descarga t.me/s/<canal> y comprueba
HTTP 200, canal identificable y al menos un mensaje visible.
No escribe en la base ni envía nada.
"""
from __future__ import annotations

import re
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "data" / "telegram_protestas.yaml"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"


def main() -> int:
    rows = yaml.safe_load(CFG.read_text(encoding="utf-8")) or []
    bad = 0
    for r in rows:
        ch = r.get("canal", "")
        try:
            req = urllib.request.Request(f"https://t.me/s/{ch}", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", "ignore")
                status = resp.status
            n = len(re.findall(r'data-post="', html))
            title = re.search(r'class="tgme_channel_info_header_title"[^>]*>(.*?)</div>', html, re.S)
            title = re.sub(r"<[^>]+>", "", title.group(1)).strip() if title else ""
            ok = status == 200 and n > 0
            print(f"{'OK ' if ok else 'BAD'} {ch:20} HTTP {status} · {n:2} mensajes · {title[:55]}")
            if not ok:
                bad += 1
        except Exception as e:  # noqa: BLE001
            print(f"BAD {ch:20} {type(e).__name__}: {str(e)[:80]}")
            bad += 1
    print(f"\n{len(rows) - bad}/{len(rows)} canales OK")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
