#!/usr/bin/env python3
"""update_caso_ceuta_live.py — inyecta las «cifras vivas» del caso Ceuta en la
página estática /var/www/fimi/casos/ceuta/index.html, entre los marcadores
<!-- LIVE_START --> y <!-- LIVE_END -->.

- La PROSA y los HECHOS con fuente son curados a mano: NO se tocan.
- Solo se reescribe la sección viva (eventos/día, clusters, banda alta y el
  clúster sostenido del caso), leída de data/radar.db.
- Se ejecuta tras gen_fimi_html en el ciclo de 6 h.
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

_MES = {1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
        7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic"}


def _n(x):
    return f"{int(round(float(x or 0))):,}".replace(",", ".")


def _fecha(ts):
    if not ts:
        return "—"
    d = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return f"{d.day}-{_MES[d.month]}-{d.year}"


def main():
    if not os.path.exists(PAGE):
        print("[caso-live] página no encontrada:", PAGE)
        return 1
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    now = int(time.time())
    ev30 = con.execute(
        "SELECT COUNT(*) FROM events WHERE tema_id=? AND timestamp>=?",
        (TEMA, now - 30 * 86400)).fetchone()[0]
    ncl = con.execute("SELECT COUNT(*) FROM clusters WHERE tema_id=?", (TEMA,)).fetchone()[0]
    nhigh = con.execute(
        "SELECT COUNT(*) FROM clusters WHERE tema_id=? AND overall_score>=60", (TEMA,)).fetchone()[0]
    sust = None
    try:
        row = con.execute(
            "SELECT cluster_label FROM cluster_lineage WHERE lineage_id LIKE ? "
            "ORDER BY first_seen DESC LIMIT 1", (LINEAGE + "@%",)).fetchone()
        if row:
            c = con.execute(
                "SELECT id, anomaly_score FROM clusters WHERE cluster_label=?",
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
    parts.append(f'Tema <code>{TEMA}</code>: <b>{_n(ev30)}</b> eventos en los últimos 30 días · '
                 f'<b>{_n(ncl)}</b> clústeres · <b>{_n(nhigh)}</b> en banda alta.')
    if sust and sust["n"]:
        parts.append(f'Clúster sostenido del caso: <b>{_n(sust["a"])} cuentas</b> · '
                     f'<b>{_n(sust["n"])} mensajes</b> · anomalía <b>{_n(sust["anom"])}/100</b> · '
                     f'ventana {_fecha(sust["i"])} → {_fecha(sust["f"])}.')
    parts.append('Es <b>amplificación sostenida</b>; no se confirma coordinación ni autoría.')

    block = '  <div class="box">\n    ' + " ".join(parts) + "\n  </div>"
    html = open(PAGE, encoding="utf-8").read()
    new = re.sub(r"<!-- LIVE_START -->.*?<!-- LIVE_END -->",
                 "<!-- LIVE_START -->\n" + block + "\n  <!-- LIVE_END -->",
                 html, count=1, flags=re.S)
    if new == html:
        print("[caso-live] marcadores no encontrados (nada que hacer)")
        return 1
    tmp = PAGE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(new)
    os.replace(tmp, PAGE)
    print("[caso-live] actualizado:", PAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
