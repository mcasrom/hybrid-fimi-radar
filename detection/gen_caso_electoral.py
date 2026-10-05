#!/usr/bin/env python3
"""gen_caso_electoral.py — genera /var/www/fimi/casos/electoral/index.html:
un PANORAMA de la amplificación en los procesos electorales (no un caso único).
- Señal por proceso: menciones/autores que coinciden con las palabras del proceso.
- Interés: Σ likes de Bluesky (engagement persistido), NO coordinación.
- Mapa (Leaflet) y timeline (sep-nov 2026); CSV por proceso.
Lee data/radar.db (tema `elecciones` por event_temas, regla 7) y data/elecciones.yaml.
Se regenera en el ciclo de 6 h.
"""
from __future__ import annotations

import csv
import html
import json
import os
import sqlite3
from datetime import date, datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "radar.db")
YAML = os.path.join(ROOT, "data", "elecciones.yaml")
OUT = "/var/www/fimi/casos/electoral/index.html"
OUTDIR = os.path.dirname(OUT)
TEMA = "elecciones"
DIAS = 30

BAND_ES = {"NORMAL": "Normal", "WATCH": "En observación",
           "ANOMALOUS": "Amplificación anómala", "HIGH": "Amplificación alta",
           "CRITICAL": "Amplificación muy alta"}
FASE_TXT = {"fase": "fase electoral", "pasado": "pasado", "proximo": "próximo", "—": "—"}
MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
COORD = {"Brasil": (-15.8, -47.9), "EEUU": (38.9, -77.0), "Suecia": (59.3, 18.1),
         "Rusia": (55.75, 37.6), "Letonia": (56.9, 24.1), "Bosnia y Herzegovina": (43.9, 18.4),
         "Serbia": (44.8, 20.5), "Bulgaria": (42.7, 23.3)}


def coord(pais, nombre):
    n = (nombre or "").lower()
    if pais == "Alemania":
        return (52.5, 13.4) if "berlin" in n else (52.1, 11.6)
    return COORD.get(pais)


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
        return 0, 0, 0
    wh = " OR ".join(["lower(e.text) LIKE ?"] * len(kws))
    row = con.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT e.author), COALESCE(SUM(e.bsky_likes),0) "
        f"FROM events e JOIN event_temas et ON et.event_id=e.id "
        f"WHERE et.tema_id=? AND e.timestamp>=? AND ({wh})",
        [TEMA, since] + [f"%{k}%" for k in kws]).fetchone()
    return row[0], row[1], row[2]


def timeline_svg(procs, hoy):
    d0, d1 = date(2026, 9, 1), date(2026, 11, 30)
    W, x0, x1 = 860, 60, 820
    total = max((d1 - d0).days, 1)

    def xp(ds):
        try:
            d = date.fromisoformat(ds)
        except ValueError:
            return None
        return x0 + (d - d0).days / total * (x1 - x0)

    p = [f'<svg viewBox="0 0 {W} 150" style="width:100%;height:auto" role="img" aria-label="Calendario electoral septiembre-noviembre 2026">']
    p.append(f'<line x1="{x0}" y1="100" x2="{x1}" y2="100" stroke="#cbd5e1" stroke-width="1"/>')
    for m in (9, 10, 11):
        t = date(2026, m, 1); tx = xp(t.isoformat())
        p.append(f'<line x1="{tx:.0f}" y1="96" x2="{tx:.0f}" y2="104" stroke="#94a3b8"/>')
        p.append(f'<text x="{tx:.0f}" y="122" font-size="12" fill="#64748b" text-anchor="middle">{MES[m-1]}</text>')
    if d0 <= hoy <= d1:
        tx = xp(hoy.isoformat())
        p.append(f'<line x1="{tx:.0f}" y1="70" x2="{tx:.0f}" y2="108" stroke="#c2410c" stroke-width="1" stroke-dasharray="3 3"/>')
        p.append(f'<text x="{tx:.0f}" y="66" font-size="11" fill="#c2410c" text-anchor="middle">hoy</text>')
    col = {"fase": "#c2410c", "pasado": "#64748b", "proximo": "#2563eb"}
    for i, pr in enumerate(procs):
        px = xp(pr["fecha"])
        if px is None:
            continue
        up = (i % 2 == 0)
        cy = 84 if up else 116
        c = col.get(pr["fase"], "#64748b")
        p.append(f'<circle cx="{px:.0f}" cy="{cy}" r="5" fill="{c}"/>')
        ty = cy - 9 if up else cy + 17
        p.append(f'<text x="{px:.0f}" y="{ty:.0f}" font-size="10.5" fill="#334155" text-anchor="middle">{html.escape(pr["pais"])}</text>')
    p.append("</svg>")
    return "".join(p)


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
                fase = "fase" if -3 <= dias <= 30 else ("pasado" if dias < -3 else "proximo")
            pev, pau, plikes = proc_signal(con, r.get("keywords"), since)
            procs.append({"pais": r.get("pais", ""), "nombre": r.get("nombre", ""),
                          "fecha": f, "dias": dias, "fase": fase, "ev": pev, "au": pau,
                          "likes": plikes, "coord": coord(r.get("pais", ""), r.get("nombre", ""))})
        procs.sort(key=lambda x: -x["ev"])
    except Exception as e:  # noqa: BLE001
        print("elecciones.yaml:", e)

    filas_p = "".join(
        f"<tr><td>{html.escape(p['pais'])}</td><td>{html.escape(p['nombre'])}</td>"
        f"<td>{p['fecha']}</td>"
        f"<td class='num'>{'' if p['dias'] is None else (str(p['dias']) + ' d')}</td>"
        f"<td{' class=fase' if p['fase'] == 'fase' else ''}>{FASE_TXT.get(p['fase'], p['fase'])}</td>"
        f"<td class='num'><b>{n(p['ev'])}</b></td><td class='num'>{n(p['au'])}</td>"
        f"<td class='num'>{n(p['likes'])}</td></tr>"
        for p in procs)
    filas_c = "".join(
        f"<tr><td><code>{html.escape(t['cluster_label'])}</code></td>"
        f"<td>{BAND_ES.get(band(t['overall_score'] or 0), '')} "
        f"<span class='mut'>({band(t['overall_score'] or 0)})</span></td>"
        f"<td class='num'>{n(t['overall_score'])}</td>"
        f"<td class='num'>{n(t['anomaly_score'])}</td>"
        f"<td class='num'>{n(t['cuentas'])}</td></tr>"
        for t in top)
    puntos = [{"lat": p["coord"][0], "lon": p["coord"][1], "pais": p["pais"],
               "nombre": p["nombre"], "fase": p["fase"], "ev": p["ev"]}
              for p in procs if p["coord"]]
    puntos_js = json.dumps(puntos, ensure_ascii=False)
    tl = timeline_svg(procs, hoy)

    # CSV por proceso
    try:
        os.makedirs(OUTDIR, exist_ok=True)
        with open(os.path.join(OUTDIR, "procesos.csv"), "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["pais", "proceso", "fecha", "dias", "fase", "menciones", "autores", "likes_bluesky"])
            for p in procs:
                w.writerow([p["pais"], p["nombre"], p["fecha"],
                            "" if p["dias"] is None else p["dias"],
                            FASE_TXT.get(p["fase"], p["fase"]), p["ev"], p["au"], p["likes"]])
        print("CSV", os.path.join(OUTDIR, "procesos.csv"))
    except Exception as e:  # noqa: BLE001
        print("CSV:", e)

    page = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Panorama electoral 2026 — Observatorio de amplificación</title>
<meta name="description" content="Panorama de la amplificación medida en varios procesos electorales de 2026. No confirma coordinación ni campaña: agrega señal, con los límites a la vista.">
<link rel="canonical" href="https://fimi.viajeinteligencia.com/casos/electoral/">
<meta property="og:title" content="Panorama electoral 2026 — amplificación medida">
<meta property="og:description" content="Varios procesos electorales, una mirada de conjunto: amplificación medida; no coordinación confirmada.">
<meta property="og:type" content="article">
<link rel="stylesheet" href="/assets/leaflet/leaflet.css"/>
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
 .num{{text-align:right}} .mut{{color:#94a3b8}} .fase{{color:#c2410c;font-weight:700}}
 #map{{height:400px;border:1px solid var(--line);border-radius:10px;background:#e6f0fb}}
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

<h2 style="font-size:1.1rem">Calendario (sep–nov 2026)</h2>
{tl}
<p class="mut" style="font-size:.78rem">Fecha de cada proceso; línea «hoy» en naranja. <a href="/casos/electoral/procesos.csv">Descargar CSV por proceso</a>.</p>

<h2 style="font-size:1.1rem">Mapa de procesos</h2>
<div id="map"></div>
<p class="mut" style="font-size:.78rem">Un punto por proceso (tamaño = menciones; color = <span style="color:#c2410c">fase electoral</span> · <span style="color:#2563eb">próximo</span> · <span style="color:#64748b">pasado</span>). Muestra <b>dónde</b> se habla, no de dónde sale una campaña.</p>

<h2 style="font-size:1.1rem">Procesos electorales (ordenado por señal)</h2>
<table><thead><tr><th>País</th><th>Proceso</th><th>Fecha</th><th class="num">Días</th><th>Estado</th><th class="num">Menciones</th><th class="num">Autores</th><th class="num">Interés (Σ ❤)</th></tr></thead>
<tbody>{filas_p or '<tr><td colspan=8>Sin procesos activos.</td></tr>'}</tbody></table>
<p class="mut" style="font-size:.78rem">«Menciones»/«autores» = publicaciones (30 d) que coinciden con las <b>palabras del proceso</b>. «Interés» = suma de <b>likes de Bluesky</b> (engagement, no coordinación). Cobertura <b>depende de los feeds</b> (idioma/país). <a href="/casos/electoral/procesos.csv">CSV</a>.</p>

<h2 style="font-size:1.1rem">Clústeres de mayor señal (tema <code>elecciones</code>)</h2>
<table><thead><tr><th>Clúster</th><th>Banda</th><th class="num">Score</th><th class="num">Anomalía</th><th class="num">Cuentas</th></tr></thead><tbody>{filas_c or '<tr><td colspan=5>Sin clústeres.</td></tr>'}</tbody></table>

<h2 style="font-size:1.1rem">Qué es y qué no</h2>
<ul>
 <li><b>Es</b> un <b>tema ancho</b>: varios países y procesos a la vez, sin un clúster dominante único.</li>
 <li><b>No es</b> un expediente como el de <a href="/casos/ceuta/">Ceuta</a> (un hilo único, profundo y sostenido). Aquí se mira el <b>conjunto</b>.</li>
 <li>Para el detalle de un proceso concreto, se puede abrir un <b>subcaso</b> cuando emerja una narrativa con señal sostenida.</li>
</ul>
<div class="box" style="background:#f8fafc;border-color:#cbd5e1;border-left-color:#64748b">
 <b>Cómo leer este panorama.</b> <b>Se puede citar:</b> el volumen relativo por proceso y el patrón (amplificación medida). <b>No citar como:</b> «campaña coordinada» o «injerencia confirmada»: <b>no está medido</b>. <b>Datos:</b> <a href="/api/v1/tema/elecciones">API del tema</a> · <a href="/casos/electoral/procesos.csv">CSV</a> · <a href="/metodo.html">método</a> · <a href="/casos/ceuta/">caso Ceuta</a>.
</div>
<p class="pie">Observatorio de amplificación · datos de fuentes públicas · generado {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC.</p>
</div>
<script src="/assets/leaflet/leaflet.js"></script>
<script>
(function(){{
  var P = {puntos_js};
  var map = L.map('map', {{scrollWheelZoom:false, attributionControl:false}}).setView([22, 5], 2);
  fetch('/assets/world.geo.json').then(function(r){{return r.json();}}).then(function(g){{
    L.geoJSON(g, {{style:{{color:'#94a3b8', weight:.5, fillColor:'#f1f5f9', fillOpacity:1}}}}).addTo(map);
  }}).catch(function(){{}});
  var COL = {{'fase':'#c2410c','proximo':'#2563eb','pasado':'#64748b'}};
  var max = Math.max.apply(null, P.map(function(p){{return p.ev;}}).concat([1]));
  P.forEach(function(p){{
    var r = 4 + 16*Math.sqrt(p.ev/max);
    L.circleMarker([p.lat, p.lon], {{radius:r, color:COL[p.fase]||'#64748b',
      fillColor:COL[p.fase]||'#64748b', fillOpacity:.6, weight:1.5}})
     .bindTooltip(p.pais, {{direction:'top', offset:[0,-4]}})
     .bindPopup('<b>'+p.pais+'</b><br>'+p.nombre+'<br>Menciones: <b>'+p.ev+'</b>')
     .addTo(map);
  }});
}})();
</script>
</body></html>"""

    os.makedirs(OUTDIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(page)
    print("OK", OUT)


if __name__ == "__main__":
    raise SystemExit(main())
