#!/usr/bin/env python3
"""Tracción real (no vanity): personas, asistentes IA, API y suscriptores.
Uso: cd hybrid-fimi-radar && .venv/bin/python scripts/traccion.py [--dias N]
Lee data/accesos.db (FIMI) + data/radar.db (suscripciones) + blog analisis.db.
"""
import sqlite3, sys, os
from datetime import datetime, timedelta, timezone

DIAS = 28
if "--dias" in sys.argv:
    DIAS = int(sys.argv[sys.argv.index("--dias") + 1])
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
        s["api"].add(ip)
        api_ips.add(ip)
        if ruta and ruta.startswith("/api/export"):
            export_ips.add(ip)
    if ruta and "/casos/ceuta" in ruta:
        if cat == "HUMANO_PROBABLE":
            ceuta_h.add(ip)
        elif cat == "ASISTENTE_IA":
            ceuta_ia.add(ip)

print(f"=== Tracción real · últimos {DIAS} d (desde {desde}) ===")
print(f"{'semana':10} {'humanos':>8} {'IA-gente':>9} {'API-IPs':>8}")
for w in sorted(sem):
    s = sem[w]
    print(f"{w:10} {len(s['hum']):8} {len(s['ia']):9} {len(s['api']):8}")

def n_sus(path, tabla):
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        return con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
    except Exception:
        return "?"

print(f"\nSuscriptores: resumen FIMI={n_sus(RADAR,'suscripciones')} · blog={n_sus(BLOG,'subscribers')}")
print(f"API: {len(api_ips)} IPs distintas | de ellas /api/export (raspado): {len(export_ips)}")
print(f"/casos/ceuta/: humanos={len(ceuta_h)} · IA-gente={len(ceuta_ia)}")
