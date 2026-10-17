#!/usr/bin/env python3
"""gen_dominios.py — Ranking de dominios + linea base por tema (read-only).

No toca scoring, captura ni crons. Solo lee radar.db en modo ro y escribe
/var/www/fimi/dominios.html. Uso: /usr/bin/python3 detection/gen_dominios.py
"""
import html
import json
import sqlite3
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DB = "/home/deploy/hybrid-fimi-radar/data/radar.db"
OUT = Path("/var/www/fimi/dominios.html")
DIAS = 90
TEMAS = [
    ("frontera_sur", "Frontera Sur (España–Marruecos)"),
    ("oriente_medio", "Oriente Medio"),
    ("elecciones", "Elecciones (panorama internacional)"),
    ("inteligencia_artificial", "Inteligencia artificial"),
    ("eeuu_politica", "EE. UU. — política"),
    ("sahel", "Sahel"),
    ("energia", "Energía"),
    ("defensa_espana", "España — defensa y amenazas híbridas"),
    ("espana_elecciones", "España — elecciones generales"),
]
SLUGS = {s for s, _ in TEMAS}
NOMBRE = dict(TEMAS)
AGG = {
    "news.google.com", "dlvr.it", "t.co", "bit.ly", "ow.ly", "buff.ly",
    "feedproxy.google.com", "feeds.feedburner.com", "feedburner.com",
    "flipboard.com",
}


def dominio(url):
    if not url:
        return None
    i = url.find("://")
    if i < 0:
        return None
    host = url[i + 3:].split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    host = host.split("@")[-1].split(":")[0].strip().lower()
    if host.startswith("www."):
        host = host[4:]
    if "." not in host or host == "fimi.viajeinteligencia.com":
        return None
    return host


def pct(n, d):
    return f"{100.0 * n / d:.1f}%" if d else "—"


def cuantiles(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None, None, None
    if len(vals) == 1:
        v = vals[0]
        return v, v, v
    if len(vals) < 4:
        return min(vals), statistics.median(vals), max(vals)
    q = statistics.quantiles(vals, n=4)
    return q[0], statistics.median(vals), q[2]


def spark(vals, w=240, h=44):
    vals = list(vals)
    if not vals:
        return ""
    mx = max(vals) or 1
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = 4 + (w - 8) * i / max(n - 1, 1)
        y = h - 4 - (h - 8) * (v / mx)
        pts.append(f"{x:.1f},{y:.1f}")
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" role="img" '
        f'aria-label="Actividad de los últimos 14 días">'
        f'<polyline points="{" ".join(pts)}" fill="none" stroke="#c2410c" '
        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        f"</svg>"
    )


def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")

    # --- dominios por tema (agregación en SQL; no carga 284k filas) ---
    dominios = {}
    q = """
    WITH u AS (
      SELECT et.tema_id AS tema, e.author AS author,
             lower(substr(e.url, instr(e.url,'://')+3)) AS host
      FROM event_temas et JOIN events e ON e.id = et.event_id
      WHERE e.url LIKE 'http%'
        AND e.timestamp >= strftime('%s','now','-90 days')
    )
    SELECT tema,
           CASE WHEN instr(host,'/')>0 THEN substr(host,1,instr(host,'/')-1) ELSE host END AS dom,
           COUNT(*) AS n, COUNT(DISTINCT author) AS cuentas
    FROM u GROUP BY 1,2
    """
    for r in con.execute(q):
        if r["tema"] not in SLUGS:
            continue
        d = dominio("http://" + r["dom"]) if r["dom"] else None
        if not d:
            continue
        cur = dominios.setdefault(r["tema"], {})
        e = cur.setdefault(d, [0, 0])
        e[0] += r["n"]
        e[1] = max(e[1], r["cuentas"])

    # --- baseline diaria ---
    base = {}
    q2 = """
    SELECT et.tema_id AS tema, date(e.timestamp,'unixepoch') AS d, COUNT(*) AS n
    FROM event_temas et JOIN events e ON e.id = et.event_id
    WHERE e.timestamp >= strftime('%s','now','-90 days')
    GROUP BY 1,2
    """
    for r in con.execute(q2):
        if r["tema"] in SLUGS:
            base.setdefault(r["tema"], {})[r["d"]] = r["n"]

    # --- % eco / feed de una fuente (clusters) ---
    eco = {}
    for r in con.execute(
        "SELECT tema_id, alternative_explanations FROM clusters "
        "WHERE tema_id IN (%s)" % ",".join("?" * len(SLUGS)), tuple(SLUGS)
    ):
        t = r["tema_id"]
        try:
            items = json.loads(r["alternative_explanations"] or "[]")
        except Exception:
            items = []
        d = eco.setdefault(t, {"total": 0, "eco": 0, "feed": 0})
        d["total"] += 1
        for it in items if isinstance(items, list) else []:
            if it.get("status") == "supported":
                if it.get("code") == "mainstream_echo":
                    d["eco"] += 1
                elif it.get("code") == "single_source_feed":
                    d["feed"] += 1

    con.close()

    hoy = date.today()
    ayer = hoy - timedelta(days=1)
    ts = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    secciones = []
    for slug, nombre in TEMAS:
        doms = dominios.get(slug, {})
        rank = {d: v for d, v in doms.items() if d not in AGG}
        aggs = {d: v for d, v in doms.items() if d in AGG}
        total = sum(v[0] for v in rank.values())
        total_agg = sum(v[0] for v in aggs.values())
        top = sorted(rank.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[:10]

        filas = "\n".join(
            f"<tr><td>{html.escape(d)}</td>"
            f"<td class='num'>{n:,}</td>"
            f"<td class='num'>{c:,}</td>"
            f"<td class='num'>{pct(n, total)}</td></tr>"
            for d, (n, c) in top
        ) or "<tr><td colspan='4'>Sin URLs de medios en la ventana.</td></tr>"

        # baseline: días desde el inicio del tema (últimos 90) hasta ayer
        serie = base.get(slug, {})
        fechas = sorted(serie)
        inicio = max(
            datetime.strptime(fechas[0], "%Y-%m-%d").date() if fechas else ayer - timedelta(days=DIAS - 1),
            ayer - timedelta(days=DIAS - 1),
        )
        dias = []
        d = inicio
        while d <= ayer:
            dias.append(serie.get(d.isoformat(), 0))
            d += timedelta(days=1)
        p25, med, p75 = cuantiles(dias)
        ult = serie.get(ayer.isoformat(), 0)
        iqr = (p75 - p25) if (p25 is not None and p75 is not None) else 0
        if p25 is None:
            estado, clase = "sin datos", "warn"
        elif iqr > 0 and ult > p75 + 1.5 * iqr:
            estado, clase = "pico", "hot"
        elif iqr > 0 and ult < p25 - 1.5 * iqr:
            estado, clase = "bajo", "cool"
        else:
            estado, clase = "normal", "ok"
        ult14 = [serie.get((ayer - timedelta(days=i)).isoformat(), 0) for i in range(13, -1, -1)]

        e = eco.get(slug, {"total": 0, "eco": 0, "feed": 0})
        agg_html = (f"<span><b>{total_agg:,}</b> vía agregadores</span>"
                    if total_agg else "")
        secciones.append(f"""
<section class="card">
  <div class="head">
    <h2>{html.escape(nombre)}</h2>
    <div class="kpis">
      <span><b>{total:,}</b> publicaciones de medios</span>
      <span><b>{len(rank):,}</b> dominios de medios</span>
      {agg_html}
      <span><b>{pct(e['eco'], e['total'])}</b> eco de prensa*</span>
      <span><b>{pct(e['feed'], e['total'])}</b> feed de 1 fuente*</span>
    </div>
  </div>
  <div class="grid">
    <div>
      <h3>Top dominios</h3>
      <table>
        <thead><tr><th>Dominio</th><th class="num">Publicaciones</th><th class="num">Cuentas</th><th class="num">% tema</th></tr></thead>
        <tbody>{filas}</tbody>
      </table>
    </div>
    <div>
      <h3>Línea base (90 d)</h3>
      <div class="base">
        <div><span>p25</span><b>{p25 if p25 is not None else '—'}</b></div>
        <div><span>mediana</span><b>{med if med is not None else '—'}</b></div>
        <div><span>p75</span><b>{p75 if p75 is not None else '—'}</b></div>
        <div><span>último día completo</span><b>{ult}</b></div>
        <div><span>estado</span><b class="{clase}">{estado}</b></div>
      </div>
      <div class="spark">{spark(ult14)}</div>
      <p class="mini">Últimos 14 días completos · eventos/día</p>
    </div>
  </div>
</section>""")

    doc = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dominios y líneas base — Observatorio de amplificación</title>
<meta name="description" content="Ranking de dominios por tema y línea base de actividad (p25–p75) del Observatorio de amplificación. Qué se amplifica y si el día es normal o un pico. Señal, no atribución.">
<link rel="canonical" href="https://fimi.viajeinteligencia.com/dominios.html">
<meta property="og:title" content="Dominios y líneas base — Observatorio de amplificación">
<meta property="og:description" content="Qué dominios se amplifican en cada tema y si la actividad es normal o un pico. Señal, no atribución.">
<meta property="og:type" content="website">
<meta property="og:image" content="https://fimi.viajeinteligencia.com/og-preview.jpg">
<meta name="robots" content="index, follow">
<style>
:root{{--navy:#0d1b2a;--ink:#1b263b;--mut:#5c6b7a;--line:#dbe2ea;--bg:#f7f9fc;--acc:#c2410c}}
*{{box-sizing:border-box}}body{{margin:0;font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:var(--ink);background:var(--bg)}}
header{{position:sticky;top:0;z-index:20;background:var(--navy);color:#fff;padding:20px 18px}}
header .bar{{max-width:1080px;margin:0 auto;display:flex;gap:14px;flex-wrap:wrap;align-items:center}}
header a{{color:#ffd7b0;text-decoration:none;font-weight:600;font-size:.9rem}}
header .brand{{font-weight:800;color:#fff;font-size:1.05rem;margin-right:auto}}
header a.back{{background:#fff7ed;color:#c2410c!important;border:1px solid #fdba74;border-radius:999px;padding:6px 12px;font-weight:800}}
.wrap{{max-width:1080px;margin:0 auto;padding:22px 18px 60px}}
h1{{font-size:1.55rem;margin:0 0 6px}}.lead{{color:#334155;max-width:820px}}
.card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin:18px 0;box-shadow:0 1px 3px rgba(15,23,42,.05)}}
.head{{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:baseline;border-bottom:1px solid var(--line);padding-bottom:8px;margin-bottom:12px}}
h2{{font-size:1.15rem;margin:0}}h3{{font-size:.82rem;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin:0 0 8px}}
.kpis{{display:flex;gap:12px;flex-wrap:wrap;font-size:.8rem;color:#475569}}
.kpis b{{color:var(--acc)}}
.grid{{display:grid;grid-template-columns:1.35fr 1fr;gap:20px}}
@media(max-width:760px){{.grid{{grid-template-columns:1fr}}}}
table{{width:100%;border-collapse:collapse;font-size:.86rem}}
th,td{{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left}}
th{{font-size:.7rem;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);background:#f8fafc}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.base{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;font-size:.85rem}}
.base div{{background:#f8fafc;border:1px solid var(--line);border-radius:8px;padding:8px 10px;display:flex;justify-content:space-between;gap:8px}}
.base span{{color:var(--mut)}}.base b{{color:var(--ink)}}
.ok{{color:#166534}}.hot{{color:#b91c1c}}.cool{{color:#1d4ed8}}.warn{{color:#92400e}}
.spark{{margin-top:10px}}.mini{{font-size:.74rem;color:var(--mut);margin:2px 0 0}}.meta{{font-size:.78rem;color:var(--mut);margin:2px 0 0}}
.note{{font-size:.8rem;color:#475569;background:#fff7ed;border:1px solid #fdba74;border-radius:10px;padding:10px 12px;margin:14px 0}}
footer{{font-size:.78rem;color:var(--mut);border-top:1px solid var(--line);margin-top:22px;padding-top:12px}}
</style></head><body>
<header><div class="bar">
  <a class="back" href="/" title="Volver al radar">← Volver al radar</a>
  <a class="brand" href="/">📡 Observatorio</a>
  <a href="/consulta.html">Consulta</a><a href="/metodo.html">Método</a>
</div></header>
<div class="wrap">
<h1>Quién amplifica y qué es normal</h1>
<p class="lead">Ranking de dominios por tema y línea base de actividad de los últimos 90 días.
Mide <b>publicaciones y amplificación</b>; no mide opinión, intención de voto ni atribuye actores.</p>
<p class="meta">Actualizado: {ts} · ventana 90 días</p>

<div class="note"><b>Cómo leerlo.</b> «Publicaciones» = eventos con URL (una misma URL compartida cuenta varias veces).
El ranking es de <b>dominios enlazados</b>, no de audiencia. <b>Google News, dlvr.it y t.co se excluyen</b>
del ranking (son agregadores/proxies) y se cuentan aparte. «Eco de prensa / feed de 1 fuente» =
<b>explicación compatible</b> del cluster (pueden coexistir), no un veredicto.</div>

{''.join(secciones)}

<p class="mini">* % sobre clusters del tema con explicación compatible. Línea base: p25/mediana/p75 de eventos/día; estado = pico si supera p75 + 1,5·IQR; bajo si queda por debajo de p25 − 1,5·IQR. Sin X/TikTok/Instagram/Facebook/WhatsApp: la cobertura es principalmente Bluesky, Google News, Telegram, Reddit, Mastodon y RSS.</p>
<footer><a href="/" style="color:#c2410c;font-weight:700">← Volver al radar</a> · Actualizado: {ts} · Datos: <code>radar.db</code> (ventana 90 d) · CC BY 4.0 · señal, no atribución · <a href="/metodo.html">método y límites</a></footer>
</div></body></html>"""
    OUT.write_text(doc, encoding="utf-8")
    print(f"OK {OUT} — {len(doc):,} bytes, {len(secciones)} temas")


if __name__ == "__main__":
    main()
