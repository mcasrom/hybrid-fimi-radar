#!/usr/bin/env python3
"""update_caso_ceuta_live.py — inyecta las «cifras vivas» del caso Ceuta en la
página estática /var/www/fimi/casos/ceuta/index.html.

Reescribe SOLO lo que va entre marcadores:
  - <!-- LIVE_TABLA_START --> … <!-- LIVE_TABLA_END -->  → tabla de KPIs derivables
  - <!-- LIVE_START --> … <!-- LIVE_END -->              → cifras vivas (bloque)
La PROSA y los HECHOS con fuente son curados a mano: NO se tocan.
Los eventos del tema se cuentan por `event_temas` (regla 7), no por events.tema_id.
Se ejecuta tras gen_fimi_html en el ciclo de 6 h.
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "radar.db")
PAGE = "/var/www/fimi/casos/ceuta/index.html"
TEMA = "frontera_sur"
LINEAGE = "frontera_sur_cluster_011"  # linaje del caso (estable)
TS_CASE = int(datetime(2026, 7, 30, tzinfo=timezone.utc).timestamp())  # inicio del caso

_MES = {1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
        7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic"}


def _n(x):
    return f"{int(round(float(x or 0))):,}".replace(",", ".")


def _fecha(ts):
    if not ts:
        return "—"
    d = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return f"{d.day}-{_MES[d.month]}-{d.year}"


def _kpi(n, lbl):
    return f'    <div class="kpi"><b>{_n(n)}</b><span>{lbl}</span></div>\n'


def main():
    if not os.path.exists(PAGE):
        print("[caso-live] página no encontrada:", PAGE)
        return 1
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    now = int(time.time())

    # --- tabla viva (derivables) por event_temas (regla 7) ---
    ev = con.execute(
        "SELECT COUNT(*) n, COUNT(DISTINCT e.author) a, COUNT(DISTINCT e.source) s, "
        "COUNT(DISTINCT e.url) u FROM events e JOIN event_temas et ON et.event_id=e.id "
        "WHERE et.tema_id=? AND e.timestamp>=?", (TEMA, TS_CASE)).fetchone()
    ncl = con.execute("SELECT COUNT(*) FROM clusters WHERE tema_id=?", (TEMA,)).fetchone()[0]
    nhigh = con.execute(
        "SELECT COUNT(*) FROM clusters WHERE tema_id=? AND overall_score>=60", (TEMA,)).fetchone()[0]
    tabla = ('  <div class="kpis">\n'
             + _kpi(ev["n"], "eventos del tema (30-jul → hoy)")
             + _kpi(ev["a"], "autores distintos")
             + _kpi(ev["s"], "fuentes activas")
             + _kpi(ev["u"], "URLs distintas")
             + _kpi(ncl, "clústeres del tema")
             + _kpi(nhigh, "en banda alta")
             + "  </div>")

    # --- clúster sostenido del caso (por linaje) ---
    sust = None
    try:
        row = con.execute(
            "SELECT cluster_label FROM cluster_lineage WHERE lineage_id LIKE ? "
            "ORDER BY first_seen DESC LIMIT 1", (LINEAGE + "@%",)).fetchone()
        if row:
            c = con.execute("SELECT id, anomaly_score FROM clusters WHERE cluster_label=?",
                            (row["cluster_label"],)).fetchone()
            if c:
                s = con.execute(
                    "SELECT COUNT(*) n, COUNT(DISTINCT author) a, MIN(ts) i, MAX(ts) f "
                    "FROM cluster_events WHERE cluster_id=?", (c["id"],)).fetchone()
                sust = {"n": s["n"], "a": s["a"], "i": s["i"], "f": s["f"],
                        "anom": c["anomaly_score"] or 0}
    except Exception as e:  # noqa: BLE001
        print("[caso-live] sostenido falló:", e)

    parts = [f'<b>Cifras vivas (actualizado {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC).</b>']
    parts.append(f'Tema <code>{TEMA}</code>: <b>{_n(ev["n"])}</b> eventos en el caso (30-jul → hoy) · '
                 f'<b>{_n(ncl)}</b> clústeres · <b>{_n(nhigh)}</b> en banda alta.')
    if sust and sust["n"]:
        parts.append(f'Clúster sostenido del caso: <b>{_n(sust["a"])} cuentas</b> · '
                     f'<b>{_n(sust["n"])} mensajes</b> · anomalía <b>{_n(sust["anom"])}/100</b> · '
                     f'ventana {_fecha(sust["i"])} → {_fecha(sust["f"])}.')
    parts.append('Es <b>amplificación sostenida</b>; no se confirma coordinación ni autoría.')
    bloque = '  <div class="box">\n    ' + " ".join(parts) + "\n  </div>"

    html = open(PAGE, encoding="utf-8").read()
    for start, end, body in (
        ("<!-- LIVE_TABLA_START -->", "<!-- LIVE_TABLA_END -->", tabla),
        ("<!-- LIVE_START -->", "<!-- LIVE_END -->", bloque),
    ):
        pat = re.escape(start) + r".*?" + re.escape(end)
        new = re.sub(pat, start + "\n" + body + "\n  " + end, html, count=1, flags=re.S)
        if new == html:
            print(f"[caso-live] marcador {start} no encontrado")
        html = new
    tmp = PAGE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(html)
    os.replace(tmp, PAGE)
    print("[caso-live] actualizado:", PAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
