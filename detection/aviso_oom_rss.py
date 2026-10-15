#!/usr/bin/env python3
"""aviso_oom_rss.py — Avisa por Telegram del pico RSS del run mayor tras cada ciclo.

Lee logs/fimi_rss.log (lo escribe el cron con /usr/bin/time -f "%M KB RSS"),
toma la ultima linea de oriente_medio y de elecciones, la compara con la anterior
y avisa UNA vez por marca nueva (dedup en data/.oom_rss_estado.json).

Objetivo: confirmar que la ventana 30 d de oriente_medio bajo el pico (~-450 MB).
No toca BD ni scoring.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "logs" / "fimi_rss.log"
ESTADO = ROOT / "data" / ".oom_rss_estado.json"
TEMAS = ("oriente_medio", "elecciones")


def _load_env(fp: Path) -> None:
    try:
        for line in fp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except Exception as e:  # noqa: BLE001
        print(f"[oom-aviso] no leo {fp}: {e}", file=sys.stderr)


def _telegram(txt: str) -> bool:
    from urllib.request import Request, urlopen
    _load_env(ROOT / ".env")
    tok = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("FIMI_OWNER_CHAT") or os.environ.get("FIMI_TELEGRAM_CHAT_ID", "")
    if not tok or not chat:
        print("[oom-aviso] sin token/chat", file=sys.stderr)
        return False
    data = json.dumps({"chat_id": chat, "text": txt}).encode()
    req = Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=20) as r:
            return r.status == 200
    except Exception as e:  # noqa: BLE001
        print(f"[oom-aviso] telegram fallo: {e}", file=sys.stderr)
        return False


def _ultimos() -> dict:
    """Ultima medicion por tema (KB) + su numero de linea (marca de ciclo)."""
    if not LOG.exists():
        return {}
    out = {}
    for i, ln in enumerate(LOG.read_text(encoding="utf-8").splitlines()):
        m = re.search(r"run tema=(\w+): [\d.]+ s\s+(\d+) KB RSS", ln)
        if m and m.group(1) in TEMAS:
            out[m.group(1)] = (int(m.group(2)), i)
    return out


def main() -> int:
    ult = _ultimos()
    if not ult:
        print("[oom-aviso] sin mediciones en el log", file=sys.stderr)
        return 1
    marca = max(v[1] for v in ult.values())
    est = {}
    if ESTADO.exists():
        try:
            est = json.loads(ESTADO.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"[oom-aviso] estado ilegible: {e}", file=sys.stderr)
    if est.get("marca") == marca and "--force" not in sys.argv:
        print("[oom-aviso] sin ciclo nuevo", file=sys.stderr)
        return 0
    lin = []
    for t in TEMAS:
        if t in ult:
            kb = ult[t][0]
            lin.append(f"- {t}: {kb/1024:.0f} MB")
    txt = ("Pico RSS tras el ciclo (ventana oriente_medio=30 d)\n"
           + "\n".join(lin) + "\nEsperado oriente_medio ~1.900 MB (antes ~2.340)."
           " Si bajo y no hay OOM -> confirmado.")
    ok = _telegram(txt)
    if ok:
        ESTADO.parent.mkdir(parents=True, exist_ok=True)
        ESTADO.write_text(json.dumps({"marca": marca}), encoding="utf-8")
        print("[oom-aviso] enviado")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
