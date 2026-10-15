#!/usr/bin/env python3
"""parte_caso.py — Parte diario del caso «Marruecos · Frontera Sur» por Telegram.

Lee el último snapshot diario (data/caso_frontera_sur_hibridos/historial.jsonl)
y lo envía como «parte». Dedup: una vez por día. No toca la BD ni scoring.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "data" / "caso_frontera_sur_hibridos" / "historial.jsonl"
ESTADO = ROOT / "data" / "caso_frontera_sur_hibridos" / ".parte_estado.json"
URL = "https://fimi.viajeinteligencia.com/casos/frontera_sur_hibridos/"


def _load_env(filepath: Path) -> None:
    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except Exception as e:  # noqa: BLE001
        print(f"[parte_caso] no pude leer {filepath}: {e}", file=sys.stderr)


def _telegram(texto: str) -> bool:
    from urllib.request import Request, urlopen
    _load_env(ROOT / ".env")
    token = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("FIMI_OWNER_CHAT") or os.environ.get("FIMI_TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print("[parte_caso] sin FIMI_TELEGRAM_BOT_TOKEN/CHAT_ID", file=sys.stderr)
        return False
    data = json.dumps({"chat_id": chat, "text": texto, "parse_mode": "Markdown",
                       "disable_web_page_preview": True}).encode()
    req = Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=20) as resp:
            return resp.status == 200
    except Exception as e:  # noqa: BLE001
        print(f"[parte_caso] Telegram fallo: {e}", file=sys.stderr)
        return False


def _leer() -> list:
    if not HIST.exists():
        return []
    try:
        return [json.loads(l) for l in HIST.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception as e:  # noqa: BLE001
        print(f"[parte_caso] historial ilegible: {e}", file=sys.stderr)
        return []


def _msg(rows: list) -> str:
    h = rows[-1]
    prev = rows[-2]["nucleo"] if len(rows) >= 2 else None
    d = ""
    if prev is not None:
        dif = h.get("nucleo", 0) - prev
        d = f" ({'+' if dif >= 0 else ''}{dif} vs día anterior)"
    ind = h.get("indic") or {}
    top = sorted(((k, v) for k, v in ind.items() if v), key=lambda kv: -kv[1])[:8]
    ind_txt = " · ".join(f"{k.split(' (')[0].split(' /')[0]}: {v}" for k, v in top)
    return (
        "*Parte del caso · Marruecos / Frontera Sur*\n"
        f"Día {h.get('fecha', '')} · *núcleo {h.get('nucleo', 0)}*{d} · "
        f"autores {h.get('autores', 0)} · clústeres {h.get('clusters', 0)} · "
        f"URLs comp. {h.get('urls_compartidas', 0)}\n"
        f"*Indicadores (top):* {ind_txt}\n"
        f"_Señal, no atribución._ {URL}"
    )


def main() -> int:
    rows = _leer()
    if not rows:
        print("[parte_caso] sin historial todavía", file=sys.stderr)
        return 1
    hoy = rows[-1]
    est = {}
    if ESTADO.exists():
        try:
            est = json.loads(ESTADO.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"[parte_caso] estado ilegible: {e}", file=sys.stderr)
    if est.get("ultimo") == hoy.get("fecha"):
        print("[parte_caso] ya enviado hoy:", hoy.get("fecha"), file=sys.stderr)
        return 0
    ok = _telegram(_msg(rows))
    if ok:
        ESTADO.parent.mkdir(parents=True, exist_ok=True)
        ESTADO.write_text(json.dumps({"ultimo": hoy.get("fecha")}), encoding="utf-8")
        print("[parte_caso] enviado:", hoy.get("fecha"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
