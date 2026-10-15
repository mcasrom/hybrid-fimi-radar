#!/usr/bin/env python3
"""parte_caso.py — Parte diario del caso «Marruecos · Frontera Sur» (Telegram + correo).

Lee el último snapshot diario (data/caso_frontera_sur_hibridos/historial.jsonl) y lo
envía como «parte» por Telegram y por email (Resend). Dedup: una vez por día.
No toca la BD ni scoring.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "data" / "caso_frontera_sur_hibridos" / "historial.jsonl"
ESTADO = ROOT / "data" / "caso_frontera_sur_hibridos" / ".parte_estado.json"
NEWSLETTER_ENV = Path("/home/deploy/newsletter/.env")
URL = "https://fimi.viajeinteligencia.com/casos/frontera_sur_hibridos/"
OWNER_EMAIL = os.environ.get("FIMI_OWNER_EMAIL", "mcasrom@gmail.com")


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


def _correo(subject: str, html: str) -> bool:
    from urllib.request import Request, urlopen
    _load_env(NEWSLETTER_ENV)
    key = os.environ.get("RESEND_API_KEY", "")
    frm = os.environ.get("RESEND_FROM", "")
    if not key or not frm:
        print("[parte_caso] sin RESEND_API_KEY/RESEND_FROM", file=sys.stderr)
        return False
    payload = json.dumps({"from": frm, "to": [OWNER_EMAIL], "subject": subject, "html": html}).encode()
    h = {"Authorization": "Bearer " + key, "Content-Type": "application/json",
         "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120"}
    req = Request("https://api.resend.com/emails", data=payload, headers=h, method="POST")
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.status in (200, 201)
    except Exception as e:  # noqa: BLE001
        print(f"[parte_caso] correo fallo: {e}", file=sys.stderr)
        return False


def _leer() -> list:
    if not HIST.exists():
        return []
    try:
        return [json.loads(l) for l in HIST.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception as e:  # noqa: BLE001
        print(f"[parte_caso] historial ilegible: {e}", file=sys.stderr)
        return []


def _datos(rows: list):
    h = rows[-1]
    prev = rows[-2]["nucleo"] if len(rows) >= 2 else None
    d = ""
    if prev is not None:
        dif = h.get("nucleo", 0) - prev
        d = f" ({'+' if dif >= 0 else ''}{dif} vs día anterior)"
    ind = [(k, v) for k, v in (h.get("indic") or {}).items() if v]
    ind.sort(key=lambda kv: -kv[1])
    return h, d, ind


def _msg(rows: list) -> str:
    h, d, ind = _datos(rows)
    top = " · ".join(f"{k.split(' (')[0].split(' /')[0]}: {v}" for k, v in ind[:8])
    return (
        "*Parte del caso · Marruecos / Frontera Sur*\n"
        f"Día {h.get('fecha', '')} · *núcleo {h.get('nucleo', 0)}*{d} · "
        f"autores {h.get('autores', 0)} · clústeres {h.get('clusters', 0)} · "
        f"URLs comp. {h.get('urls_compartidas', 0)}\n"
        f"*Indicadores (top):* {top}\n"
        f"_Señal, no atribución._ {URL}"
    )


def _html(rows: list) -> str:
    h, d, ind = _datos(rows)
    filas = "".join(
        f"<tr><td>{k}</td><td style='text-align:right'>{v}</td></tr>" for k, v in ind)
    return (
        "<div style='font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:620px'>"
        "<h2 style='margin:0 0 4px'>Parte del caso · Marruecos / Frontera Sur</h2>"
        f"<p style='color:#5c6b7a;margin:0 0 12px'>Día <b>{h.get('fecha', '')}</b></p>"
        f"<p><b>Núcleo: {h.get('nucleo', 0)}</b>{d} · autores {h.get('autores', 0)} · "
        f"clústeres {h.get('clusters', 0)} · URLs compartidas {h.get('urls_compartidas', 0)}</p>"
        "<table style='border-collapse:collapse;width:100%'>"
        "<thead><tr><th style='text-align:left;border-bottom:1px solid #dbe2ea'>Indicador</th>"
        "<th style='text-align:right;border-bottom:1px solid #dbe2ea'>Eventos</th></tr></thead>"
        f"<tbody>{filas}</tbody></table>"
        f"<p style='color:#5c6b7a;font-size:.9rem'>Señal, no atribución. "
        f"<a href='{URL}'>Ver el caso</a> · "
        f"<a href='{URL}datos.csv'>CSV</a></p></div>"
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
    if est.get("ultimo") == hoy.get("fecha") and "--force" not in sys.argv:
        print("[parte_caso] ya enviado hoy:", hoy.get("fecha"), file=sys.stderr)
        return 0
    tg = _telegram(_msg(rows))
    em = _correo(f"Parte del caso · Marruecos/Frontera Sur · {hoy.get('fecha', '')}", _html(rows))
    if tg or em:
        ESTADO.parent.mkdir(parents=True, exist_ok=True)
        ESTADO.write_text(json.dumps({"ultimo": hoy.get("fecha"), "tg": tg, "email": em}), encoding="utf-8")
        print(f"[parte_caso] enviado {hoy.get('fecha')} · telegram={tg} · email={em}")
    return 0 if (tg or em) else 1


if __name__ == "__main__":
    raise SystemExit(main())
