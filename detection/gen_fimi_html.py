#!/usr/bin/env python3
"""gen_fimi_html.py — Genera el dashboard HTML estático del radar FIMI.

Replica el patrón de nivel-embalses.html (HTML estático + SVG inline), leyendo
data/radar.db. Salida: /var/www/fimi/index.html (servido por nginx).
Sin RAM extra en runtime: lo genera el cron.
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/deploy/hybrid-fimi-radar")
DB = ROOT / "data" / "radar.db"
OUT = Path("/var/www/fimi/index.html")

BAND_COLORS = {
    "NORMAL": "#16a34a", "WATCH": "#0891b2", "ANOMALOUS": "#eab308",
    "HIGH": "#f97316", "CRITICAL": "#dc2626",
}


def band_of(score):
    if score >= 80: return "CRITICAL"
    if score >= 60: return "HIGH"
    if score >= 40: return "ANOMALOUS"
    if score >= 20: return "WATCH"
    return "NORMAL"


def kpi(label, value, sub, bg):
    return (f'<div style="flex:1 1 150px;background:{bg};border-radius:12px;padding:14px 16px;'
            f'box-shadow:0 1px 3px rgba(0,0,0,.06)">'
            f'<div style="font-size:.72rem;color:#475569;font-weight:600;text-transform:uppercase">{label}</div>'
            f'<div style="font-size:1.6rem;font-weight:800;color:#0f172a;line-height:1.2">{value}</div>'
            f'<div style="font-size:.78rem;color:#64748b">{sub}</div></div>')


def svg_score_bar(score, band):
    col = BAND_COLORS.get(band, "#94a3b8")
    w = int((score / 100) * 460)
    return (f'<div style="display:flex;align-items:center;gap:10px;margin:6px 0">'
            f'<div style="flex:1;height:14px;background:#f1f5f9;border-radius:7px;overflow:hidden">'
            f'<div style="width:{w}px;height:100%;background:{col};border-radius:7px"></div></div>'
            f'<b style="width:52px;text-align:right">{score:.0f}/100</b>'
            f'<span style="width:70px;color:{col};font-weight:700">{band}</span></div>')


def main():
    if not DB.exists():
        html = f"<html><body><h1>Sin datos aún</h1><p>El radar capturará en el próximo ciclo (6h).</p></body></html>"
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(html, encoding="utf-8")
        print("sin datos, pagina placeholder generada")
        return

    con = sqlite3.connect(DB)
    clusters = con.execute("SELECT * FROM clusters ORDER BY overall_score DESC").fetchall()
    assessments = con.execute("SELECT * FROM assessments").fetchall()
    n_events = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    n_sources = con.execute("SELECT COUNT(DISTINCT source) FROM events").fetchone()[0]
    con.close()

    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    # KPIs
    n_crit = sum(1 for c in clusters if c[11] and c[11] >= 80) if clusters else 0
    n_high = sum(1 for c in clusters if c[11] and 60 <= c[11] < 80) if clusters else 0
    n_anom = sum(1 for c in clusters if c[11] and 40 <= c[11] < 60) if clusters else 0
    cards = "".join([
        kpi("Eventos", n_events, "capturados", "#eff6ff"),
        kpi("Fuentes", n_sources, "activas", "#f0fdf4"),
        kpi("Clusters", len(clusters), "detectados", "#fafaf9"),
        kpi("CRITICAL", n_crit, "80-100", "#fee2e2"),
        kpi("HIGH", n_high, "60-79", "#ffedd5"),
        kpi("Anómalos", n_anom, "40-59", "#fef9c3"),
    ])

    # cuerpo de clusters
    body = ""
    if not clusters:
        body = ('<div class="card"><h3>Sin clusters activos</h3>'
                '<p class="caption">Con la historia acumulada hasta ahora no hay señal de '
                'coordinación. La ausencia de señal es un resultado válido del radar.</p></div>')
    else:
        for c in clusters:
            cid, created, label, ctype, coord, amp, anom, infra, net, overall, conf = c[:11]
            overall = overall or 0
            band = band_of(overall)
            col = BAND_COLORS[band]
            body += f'<div class="card"><h3>{label} — {overall:.0f}/100 <span style="color:{col}">({band})</span></h3>'
            body += svg_score_bar(overall, band)
            body += (f'<p class="caption">Coordinación {coord or 0:.0f} · Amplificación {amp or 0:.0f} · '
                     f'Anomalía {anom or 0:.0f} · Infraestructura {infra or 0:.0f} · '
                     f'Densidad red {net or 0:.0f} · Confianza: {conf}</p>')
            # buscar assessment
            for a in assessments:
                if a[1] == cid:
                    body += f'<p style="font-size:.9rem;color:#334155"><b>Atribución:</b> {a[11]} · confianza {a[12]}<br>'
                    body += f'<b>Evidencia:</b> {a[13]}<br><b>Falta:</b> {a[14]}</p>'
                    try:
                        hyp = json.loads(a[9]) if a[9] else []
                        if hyp:
                            body += '<p style="font-size:.82rem;color:#475569"><b>Hipótesis:</b> '
                            body += " · ".join(f"{h['hypothesis']} {h['label']} ({h['score']})" for h in hyp[:4])
                            body += "</p>"
                    except Exception:
                        pass
                    break
            body += "</div>"

    html = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>European Hybrid &amp; FIMI Radar · España-Marruecos</title>
<meta name="description" content="Radar OSINT agnóstico al actor: detección de coordinación, amplificación y FIMI en la frontera sur de Europa. Actualizado cada 6h.">
<link rel="canonical" href="https://fimi.viajeinteligencia.com/">
<meta property="og:type" content="website">
<meta property="og:title" content="European Hybrid &amp; FIMI Radar">
<meta property="og:description" content="Detección de coordinación y anomalías en la frontera sur de Europa. Agnóstico al actor.">
<meta property="og:locale" content="es_ES">
<meta property="og:url" content="https://fimi.viajeinteligencia.com/">
<style>
:root{{color-scheme:light}}
body{{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#f8fafc;color:#0f172a}}
main{{max-width:960px;margin:0 auto;padding:20px 16px 56px}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:20px;margin:16px 0;box-shadow:0 1px 2px rgba(15,23,42,.04)}}
.card h3{{margin-top:0;font-size:1.02rem}}
.caption{{font-size:.84rem;color:#64748b;margin:.3rem 0}}
.kpis{{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}}
a{{color:#c2410c}}
</style></head>
<body>
<main>
<p style="font-size:.85rem"><a href="https://radar.viajeinteligencia.com">← radar</a> ·
<a href="https://radar.viajeinteligencia.com/enjambre-granada.html">🌍 enjambre</a> ·
<a href="https://radar.viajeinteligencia.com/nivel-embalses.html">💧 embalses</a> ·
<a href="https://radar.viajeinteligencia.com/pulso-espana.html">💓 pulso</a></p>
<h1 style="font-size:1.5rem;margin:.2em 0">European Hybrid &amp; FIMI Radar</h1>
<p style="color:#475569">Detección de <strong>coordinación, amplificación y anomalías</strong> en la
frontera sur de Europa (España-Marruecos-Ceuta-Melilla-Canarias). <strong>Agnóstico al actor</strong>:
primero se observa la anomalía, después se evalúan hipótesis; la atribución nunca se presume.</p>

<div class="kpis">{cards}</div>

{body}

<div class="card">
<h3>Metodología</h3>
<p class="caption">
- Fuentes: Bluesky (autenticado), Telegram público, Google News RSS, medios internacionales y RSS oficiales.<br>
- Señales: sincronización temporal, contenido casi duplicado, amplificación, infraestructura compartida.<br>
- Scoring 0-100 con bandas NORMAL→CRITICAL. Cada cluster muestra sus componentes.<br>
- Atribución: módulo separado con taxonomía neutra y confianza NO/LOW/MEDIUM/HIGH.
  "No hay evidencia suficiente para atribuir" es un resultado válido.<br>
- Actualizado automáticamente cada 6h. Última actualización: {now}.
</p>
</div>

<footer style="border-top:1px solid #e5e5e5;margin-top:28px;padding-top:18px;text-align:center">
  <div style="font-size:.85rem;color:#666;line-height:1.9">
    <b>Ecosistema ViajeInteligencia</b><br>
    <a href="https://www.viajeinteligencia.com" style="color:#c2410c">Principal</a> ·
    <a href="https://nearme.viajeinteligencia.com" style="color:#c2410c">NearMe</a> ·
    <a href="https://radar.viajeinteligencia.com" style="color:#c2410c">Radar</a> ·
    <a href="https://radar.viajeinteligencia.com/estado.html" style="color:#c2410c">Estado de fuentes</a>
  </div>
  <a href="https://ko-fi.com/m_castillo" target="_blank" rel="noopener noreferrer"
     style="display:inline-flex;align-items:center;gap:8px;font-weight:700;font-size:13.5px;color:#fff;background:#13C3A5;border-radius:7px;padding:11px 18px;margin-top:14px;text-decoration:none">☕ Invítame a un café</a>
  <p style="font-size:.78rem;color:#888;margin:10px 0 0">Proyecto personal, sin rastreo ni cuentas. Los servidores los paga su autor.</p>
</footer>
</main>
</body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"OK: {OUT} — {n_events} eventos, {n_sources} fuentes, {len(clusters)} clusters")


if __name__ == "__main__":
    main()
