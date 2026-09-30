#!/usr/bin/env python3
"""Tracción real (no vanity): personas, asistentes IA, API y suscriptores.
Uso: cd hybrid-fimi-radar && .venv/bin/python scripts/traccion.py [--dias N] [--tg]
Lee data/accesos.db (FIMI) + data/radar.db (suscripciones) + blog analisis.db.
"""
import sqlite3, sys, os
from datetime import datetime, timedelta, timezone

DIAS = 28
if "--dias" in sys.argv:
    DIAS = int(sys.argv[sys.argv.index("--dias") + 1])
TG = "--tg" in sys.argv
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACC = os.path.join(BASE, "data/accesos.db")
RADAR = os.path.join(BASE, "data/radar.db")
BLOG = "/home/deploy/analisis-pruebapublica/data/analisis.db"

desde = (datetime.now(timezone.utc) - timedelta(days=DIAS)).strftime("%Y-%m-%d")
c = sqlite3.connect(ACC)


def semana(dia):
    y, m, d = map(int, dia.split("-"))
    wk = datetime(y, m, d).isocalendar()
    return f"{wk[0]}-W{wk[1]:02d}"


rows = c.execute("SELECT dia, categoria, ip_pseudo, ruta FROM accesos WHERE dia>=?", (desde,)).fetchall()
sem = {}
ceuta_h = set(); ceuta_ia = set()
api_ips = set(); export_ips = set()
for dia, cat, ip, ruta in rows:
    w = semana(dia)
    s = sem.setdefault(w, {"hum": set(), "ia": set(), "api": set()})
    if cat == "HUMANO_PROBABLE":
        s["hum"].add(ip)
    elif cat == "ASISTENTE_IA":
        s["ia"].add(ip)
    elif cat == "API":
        s["api"].add(ip); api_ips.add(ip)
        if ruta and ruta.startswith("/api/export"):
            export_ips.add(ip)
    if ruta and "/casos/ceuta" in ruta:
        if cat == "HUMANO_PROBABLE":
            ceuta_h.add(ip)
        elif cat == "ASISTENTE_IA":
            ceuta_ia.add(ip)


def n_sus(path, tabla):
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        return con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
    except Exception:
        return "?"


sus_fimi = n_sus(RADAR, "suscripciones")
sus_blog = n_sus(BLOG, "subscribers")

lineas = [f"=== Tracción real · últimos {DIAS} d (desde {desde}) ===",
          f"{'semana':10} {'humanos':>8} {'IA-gente':>9} {'API-IPs':>8}"]
for w in sorted(sem):
    s = sem[w]
    lineas.append(f"{w:10} {len(s['hum']):8} {len(s['ia']):9} {len(s['api']):8}")
lineas += [
    f"\nSuscriptores: resumen FIMI={sus_fimi} · blog={sus_blog}",
    f"API: {len(api_ips)} IPs distintas | de ellas /api/export (raspado): {len(export_ips)}",
    f"/casos/ceuta/: humanos={len(ceuta_h)} · IA-gente={len(ceuta_ia)}",
]
texto = "\n".join(lineas)
print(texto)


def _telegram(msg):
    from urllib.request import Request, urlopen
    env = os.path.join(BASE, ".env")
    try:
        for line in open(env):
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass
    token = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("FIMI_OWNER_CHAT") or os.environ.get("FIMI_TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print("[traccion] sin token/chat Telegram", file=sys.stderr)
        return False
    from json import dumps
    data = dumps({"chat_id": chat, "text": msg}).encode()
    req = Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=20) as r:
            return r.status == 200
    except Exception as e:  # noqa: BLE001
        print(f"[traccion] Telegram fallo: {e}", file=sys.stderr)
        return False


if TG:
    print("telegram:", _telegram("📈 Tracción real · %d d\n%s" % (DIAS, texto)))
