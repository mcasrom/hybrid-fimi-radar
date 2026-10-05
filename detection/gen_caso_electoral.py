#!/usr/bin/env python3
"""gen_caso_electoral.py — genera /var/www/fimi/casos/electoral/index.html:
un PANORAMA de la amplificación en los procesos electorales (no un caso único).
Lee data/radar.db (tema `elecciones` por event_temas, regla 7) y
data/elecciones.yaml (procesos activos). Señal por proceso = eventos/autores que
matchean las keywords del proceso. Se regenera en el ciclo de 6 h.
"""
from __future__ import annotations

import html
import os
import sqlite3
from datetime import date, datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "radar.db")
YAML = os.path.join(ROOT, "data", "elecciones.yaml")
OUT = "/var/www/fimi/casos/electoral/index.html"
TEMA = "elecciones"
DIAS = 30

BAND_ES = {"NORMAL": "Normal", "WATCH": "En observación",
           "ANOMALOUS": "Amplificación anómala", "HIGH": "Amplificación alta",
           "CRITICAL": "Amplificación muy alta"}


def band(score):
    if score >= 80: return "CRITICAL"
    if score >= 60: return "HIGH"
    if score >= 40: return "ANOMALOUS"
    if score >= 20: return "WATCH"
    return "NORMAL"


def n(x):
    return f"{int(round(float(x or 0))):,}".replace(",", ".")


def proc_signal(con, kws, since):
    kws = [str(k).lower() for k in (kws or []) if k]
    if not kws:
        return 0, 0
    wh = " OR ".join(["lower(e.text) LIKE ?"] * len(kws))
    row = con.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT e.author) FROM events e "
        f"JOIN event_temas et ON et.event_id=e.id "
        f"WHERE et.tema_id=? AND e.timestamp>=? AND ({wh})",
        [TEMA, since] + [f"%{k}%" for k in kws]).fetchone()
    return row[0], row[1]


def main():
    hoy = date.today()
    since = datetime.now(timezone.utc).timestamp() - DIAS * 86400
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    ev = con.execute(
        "SELECT COUNT(*) n, COUNT(DISTINCT e.author) a, COUNT(DISTINCT e.source) s "
        "FROM events e JOIN event_temas et ON et.event_id=e.id "
        "WHERE et.tema_id=? AND e.timestamp>=?", (TEMA, since)).fetchone()
    ncl = con.execute("SELECT COUNT(*) FROM clusters WHERE tema_id=?", (TEMA,)).fetchone()[0]
    nhigh = con.execute("SELECT COUNT(*) FROM clusters WHERE tema_id=? AND overall_score>=60", (TEMA,)).fetchone()[0]
    top = con.execute(
        "SELECT c.cluster_label, c.overall_score, c.anomaly_score, "
        "(SELECT COUNT(DISTINCT author) FROM cluster_events ce WHERE ce.cluster_id=c.id) cuentas "
        "FROM clusters c WHERE c.tema_id=? ORDER BY c.overall_score DESC LIMIT 8", (TEMA,)).fetchall()

    procs = []
    try:
        import yaml
        for r in (yaml.safe_load(open(YAML, encoding="utf-8")) or []):
            if r.get("estado") != "activo":
                continue
            f = str(r.get("fecha"))[:10]
            try:
                dias = (date.fromisoformat(f) - hoy).days
            except ValueError:
                dias = None
            fase = "—"
            if dias is not None:
                fase = "fase electoral" if -3 <= dias <= 30 else ("pasado" if dias < -3 else "próximo")
            pev, pau = proc_signal(con, r.get("keywords"), since)
            procs.append({"pais": r.get("pais", ""), "nombre": r.get("nombre", ""),
                          "fecha": f, "dias": dias, "fase": fase, "ev": pev, "au": pau})
        procs.sort(key=lambda x: -x["ev"])
    except Exception as e:  # noqa: BLE001
        print("elecciones.yaml:", e)

    filas_p = "".join(
        f"<tr><td>{html.escape(p['pais'])}</td><td>{html.escape(p['nombre'])}</td>"
        f"<td>{p['fecha']}</td>"
        f"<td class='num'>{'' if p['dias'] is None else (str(p['dias']) + ' d')}</td>"
        f"<td>{p['fase']}</td>"
        f"<td class='num'><b>{n(p['ev'])}</b></td><td class='num'>{n(p['au'])}</td></tr>"
        for p in procs)
    filas_c = "".join(
        f"<tr><td><code>{html.escape(t['cluster_label'])}</code></td>"
        f"<td>{BAND_ES.get(band(t['overall_score'] or 0), '')} "
        f"<span class='mut'>({band(t['overall_score'] or 0)})</span></td>"
        f"<td class='num'>{n(t['overall_score'])}</td>"
        f"<td class='num'>{n(t['anomaly_score'])}</td>"
        f"<td class='num'>{n(t['cuentas'])}</td></tr>"
        for t in top)

    page = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Panorama electoral 2026 — Observatorio de amplificación</title>
<meta name="description" content="Panorama de la amplificación medida en varios procesos electorales de 2026. No confirma coordinación ni campaña: agrega señal, con los límites a la vista.">
<link rel="canonical" href="https://fimi.viajeinteligencia.com/casos/electoral/">
<meta property="og:title" content="Panorama electoral 2026 — amplificación medida">
<meta property="og:description" content="Varios procesos electorales, una mirada de conjunto: amplificación medida; no coordinación confirmada.">
<meta property="og:type" content="article">
<style>
 :root{{--ink:#1e293b;--mut:#64748b;--acc:#c2410c;--line:#e2e8f0}}
 body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:var(--ink);background:#fff;line-height:1.6}}
 .wrap{{max-width:920px;margin:0 auto;padding:22px 18px 60px}}
 nav{{font-size:.82rem;color:var(--mut);margin-bottom:14px}}
 nav a{{color:var(--acc);text-decoration:none;font-weight:600}}
 h1{{font-size:1.6rem;margin:0 0 4px}} .tag{{color:var(--mut);margin:0 0 14px}}
 .box{{background:#fff7ed;border:1px solid #fdba74;border-left:5px solid var(--acc);border-radius:10px;padding:12px 16px;font-size:.9rem;margin:12px 0}}
 .kpis{{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}}
 .kpi{{flex:1 1 120px;background:#f8fafc;border:1px solid var(--line);border-radius:10px;padding:10px 14px;text-align:center}}
 .kpi b{{display:block;font-size:1.5rem;color:var(--acc)}} .kpi span{{font-size:.76rem;color:var(--mut)}}
 table{{border-collapse:collapse;width:100%;font-size:.85rem;margin:8px 0 18px}}
 th,td{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left}}
 th{{background:#f8fafc;color:var(--mut);font-size:.76rem;text-transform:uppercase}}
 .num{{text-align:right}} .mut{{color:#94a3b8}}
 .fase{{color:#c2410c;font-weight:700}}
 .pie{{color:var(--mut);font-size:.8rem;border-top:1px solid var(--line);margin-top:20px;padding-top:10px}}
 a{{color:var(--acc)}}
</style></head><body><div class="wrap">
<nav><a href="/">Observatorio</a> · <a href="/casos/electoral/">Electoral</a> · <a href="/casos/ceuta/">Ceuta</a> · <a href="/metodo.html">Método</a> · <a href="/api.html">API</a> · <a href="/glosario.html">Glosario</a></nav>
<h1>Panorama electoral 2026</h1>
<p class="tag">Amplificación medida en varios procesos electorales — <b>panorama, no un caso</b>.</p>
<div class="box"><b>Encuadre.</b> Esto <b>no</b> dice si hay una campaña ni quién está detrás. Agrega la <b>amplificación</b> medida (varias cuentas repiten lo mismo a la vez) en el tema <code>elecciones</code>, que cubre varios países y procesos. Una banda alta es <b>amplificación</b>, no coordinación confirmada.</div>
<div class="kpis">
  <div class="kpi"><b>{n(ev['n'])}</b><span>eventos (30 d)</span></div>
  <div class="kpi"><b>{n(ev['a'])}</b><span>autores distintos</span></div>
  <div class="kpi"><b>{n(ev['s'])}</b><span>fuentes</span></div>
  <div class="kpi"><b>{n(ncl)}</b><span>clústeres del tema</span></div>
  <div class="kpi"><b>{n(nhigh)}</b><span>en banda alta</span></div>
</div>
<p class="mut" style="font-size:.78rem">Ventana de {DIAS} días; se actualiza cada 6 h desde la base del observatorio.</p>

<h2 style="font-size:1.1rem">Procesos electorales (ordenado por señal)</h2>
<table><thead><tr><th>País</th><th>Proceso</th><th>Fecha</th><th class="num">Días</th><th>Estado</th><th class="num">Menciones</th><th class="num">Autores</th></tr></thead>
<tbody>{filas_p or '<tr><td colspan=7>Sin procesos activos.</td></tr>'}</tbody></table>
<p class="mut" style="font-size:.78rem">«Menciones» y «autores» = publicaciones (30 d) que coinciden con las <b>palabras del proceso</b> (país + proceso). La <b>cobertura depende de los feeds</b> (idioma/país): un proceso con poco volumen puede reflejar menor cobertura, no ausencia de conversación.</p>

<h2 style="font-size:1.1rem">Clústeres de mayor señal (tema <code>elecciones</code>)</h2>
<table><thead><tr><th>Clúster</th><th>Banda</th><th class="num">Score</th><th class="num">Anomalía</th><th class="num">Cuentas</th></tr></thead><tbody>{filas_c or '<tr><td colspan=5>Sin clústeres.</td></tr>'}</tbody></table>

<h2 style="font-size:1.1rem">Qué es y qué no</h2>
<ul>
 <li><b>Es</b> un <b>tema ancho</b>: varios países y procesos a la vez, sin un clúster dominante único.</li>
 <li><b>No es</b> un expediente como el de <a href="/casos/ceuta/">Ceuta</a> (un hilo único, profundo y sostenido). Aquí se mira el <b>conjunto</b>.</li>
 <li>Para el detalle de un proceso concreto, se puede abrir un <b>subcaso</b> cuando emerja una narrativa con señal sostenida.</li>
</ul>
<div class="box" style="background:#f8fafc;border-color:#cbd5e1;border-left-color:#64748b">
 <b>Cómo leer este panorama.</b> <b>Se puede citar:</b> el volumen relativo por proceso y el patrón (amplificación medida). <b>No citar como:</b> «campaña coordinada» o «injerencia confirmada»: <b>no está medido</b>. <b>Datos:</b> <a href="/api/v1/tema/elecciones">API del tema</a> · <a href="/metodo.html">método</a> · <a href="/casos/ceuta/">caso Ceuta</a> (contraste con un caso único).
</div>
<p class="pie">Observatorio de amplificación · datos de fuentes públicas · generado {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC.</p>
</div></body></html>"""

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(page)
    print("OK", OUT)


if __name__ == "__main__":
    raise SystemExit(main())
