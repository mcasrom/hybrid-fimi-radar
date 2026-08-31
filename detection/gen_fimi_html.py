#!/usr/bin/env python3
"""gen_fimi_html.py — Genera el dashboard HTML estático del radar FIMI.

Replica el patrón de nivel-embalses.html (HTML estático + SVG inline), leyendo
data/radar.db. Salida: /var/www/fimi/index.html (servido por nginx).
Sin RAM extra en runtime: lo genera el cron.
"""
import json
import sqlite3
import sys
import pandas as pd
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
    # cargar config para inventario de fuentes y keywords
    try:
        import yaml
        cfg = yaml.safe_load(open(ROOT / "config.yaml"))
        feeds = cfg.get("feeds", [])
        keywords = cfg.get("keywords", [])
        telegram = cfg.get("telegram_canales", [])
        subreddits = cfg.get("subreddits", [])
    except Exception:
        feeds, keywords, telegram, subreddits = [], [], [], []

    feeds_html = ""
    for f in feeds:
        pais = f.get("pais", "")
        feeds_html += (f"<li>{f.get('nombre','?')} "
                       f"<span style='color:#94a3b8;font-size:.8rem'>· {f.get('url','')}"
                       f"{' · ' + pais if pais else ''}</span></li>")
    kw_html = ""
    for k in keywords:
        kw_html += (f"<li><code>{k.get('palabra','?')}</code> → "
                    f"{', '.join(k.get('plataformas', []))}</li>")
    tg_html = " · ".join(f"<code>{c}</code>" for c in telegram) or "—"
    sr_html = " · ".join(f"<code>r/{s}</code>" for s in subreddits) or "—"

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
    ev_df = pd.read_sql("SELECT timestamp, source, title, url, text FROM events", con)
    # historial persistido de hallazgos
    try:
        findings = con.execute(
            "SELECT id, fecha, tipo, titulo, detalle, n_sources, n_events, window_hours"
            " FROM findings ORDER BY fecha DESC LIMIT 30").fetchall()
    except Exception:
        findings = []
    # narrativas sostenidas (misma narrativa amplificada en >=3 dias = alerta)
    sostenidas = []
    try:
        import sys as _sys
        _sys.path.insert(0, str(ROOT))
        from detection.persistencia import detectar_sostenidas
        sostenidas = detectar_sostenidas(con, min_dias=3)
    except Exception:
        sostenidas = []
    con.close()

    # narrativas amplificadas (mismo titular en varias fuentes)
    narr_kpi = None  # se rellena en el bloque de narrativas amplificadas
    try:
        import sys as _sys
        _sys.path.insert(0, str(ROOT))
        from detection.fakenews import detect_narrative_amplification
        ev_df["ts"] = ev_df["timestamp"]  # la detección espera columna ts
        narr_html = ""
        narratives = detect_narrative_amplification(ev_df, {"thresholds": {"near_duplicate_threshold": 0.7, "min_amp_sources": 3}})
        if narratives:
            # KPI de narrativas amplificadas
            narr_kpi = kpi("Narrativas amplificadas", len(narratives),
                           f"top: {narratives[0]['seed'][:28]}...", "#fff7ed")
            # gráfico con BARRAS HTML/CSS (más fiables y legibles que SVG:
            # título completo sin cortar + barra con color por intensidad).
            # intensidad = eventos x fuentes / (ventana_horas + 1)
            top_n = narratives[:8]
            def _intensity(n):
                return n["n_events"] * n["n_sources"] / max(n["window_hours"] + 1, 0.5)
            max_i = max(_intensity(n) for n in top_n) or 1
            rows = ""
            for i, n in enumerate(top_n):
                pct = int((_intensity(n) / max_i) * 100)
                ratio = _intensity(n) / max_i
                if ratio >= 0.8:
                    col = "#dc2626"
                elif ratio >= 0.5:
                    col = "#f97316"
                elif ratio >= 0.3:
                    col = "#fbbf24"
                else:
                    col = "#22c55e"
                # escapar caracteres para HTML seguro
                import html as _html
                title = _html.escape(n["seed"][:80])
                # eventos completos de esta narrativa (desplegable)
                eventos_html = ""
                for ev in n.get("eventos", []):
                    txt = _html.escape(str(ev.get("texto", ""))[:220])
                    src = _html.escape(str(ev.get("fuente", "")))
                    url = _html.escape(str(ev.get("url", "")))
                    dt = ""
                    try:
                        import datetime as _dt
                        dt = _dt.datetime.utcfromtimestamp(ev["ts"]).strftime("%d/%m %H:%M")
                    except Exception:
                        pass
                    url_html = f" · <a href='{url}' target='_blank' style='color:#c2410c'>enlace</a>" if url else ""
                    eventos_html += (
                        f"<div style='padding:6px 8px;border-top:1px solid #f1f5f9;font-size:.8rem;color:#334155'>"
                        f"<b style='color:#c2410c'>{dt}</b> [{src}]{url_html}<br>{txt}</div>")
                rows += (
                    f"<div style='margin:14px 0;padding:10px 12px;border:1px solid #e2e8f0;"
                    f"border-radius:10px;background:#fff'>"
                    f"<div style='font-size:.9rem;font-weight:600;color:#1e293b;line-height:1.35'>{title}</div>"
                    f"<div style='font-size:.78rem;color:#64748b;margin:2px 0 8px'>"
                    f"{n['n_events']} eventos · {n['n_sources']} fuentes · ventana {n['window_hours']}h</div>"
                    f"<div style='background:#f1f5f9;border-radius:6px;height:14px;overflow:hidden'>"
                    f"<div style='width:{pct}%;height:100%;background:{col};border-radius:6px'></div></div>"
                    f"<details style='margin-top:8px'><summary style='font-size:.8rem;color:#c2410c;cursor:pointer'>"
                    f"Ver texto completo ({n['n_events']} eventos)</summary>{eventos_html}</details>"
                    f"</div>")
            narr_block = (f"<div class='card'><div style='display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap'>"
                          f"{narr_kpi}"
                          f"<div style='flex:1;min-width:280px'><h3 style='margin:0'>Narrativas amplificadas</h3>"
                          f"<p class='caption'>Mismo titular compartido por varias fuentes en una ventana. "
                          f"Indica amplificación de una noticia, no coordinación de cuentas. Sin atribución. "
                          f"Intensidad = eventos × fuentes ÷ ventana en horas (menos tiempo = más amplificación).</p>"
                          f"{rows}</div></div></div>")
        else:
            narr_kpi = kpi("Narrativas amplificadas", 0, "ninguna ≥3 fuentes", "#f8fafc")
            narr_block = (f"<div class='card'><div style='display:flex;gap:16px;align-items:center;flex-wrap:wrap'>"
                          f"{narr_kpi}"
                          f"<div style='flex:1;min-width:260px'><h3 style='margin:0'>Narrativas amplificadas</h3>"
                          f"<p class='caption'>Ninguna narrativa compartida por ≥3 fuentes distintas en la ventana actual.</p>"
                          f"</div></div></div>")
    except Exception as e:
        narr_block = ""
    # historial de hallazgos persistidos
    import html as _html
    hist_rows = ""
    for f in findings:
        hid, fecha, tipo, titulo, detalle, nsrc, nev, wh = f[:8]
        fecha_s = ""
        try:
            import datetime as _dt
            fecha_s = _dt.datetime.utcfromtimestamp(fecha).strftime("%d/%m")
        except Exception:
            pass
        ic = {"amplificacion_narrativa": "📣", "cluster": "🕸️", "cascada": "⚡"}.get(tipo, "•")
        col = "#f97316" if tipo == "amplificacion_narrativa" else ("#7c3aed" if tipo == "cluster" else "#0891b2")
        hist_rows += (f"<div style='display:flex;gap:10px;padding:8px 10px;border-left:3px solid {col};"
                      f"background:#f8fafc;border-radius:6px;margin:6px 0;align-items:center'>"
                      f"<span style='font-size:1rem'>{ic}</span>"
                      f"<div style='flex:1'><div style='font-size:.85rem;color:#1e293b;font-weight:600'>"
                      f"{_html.escape(str(titulo)[:70])}</div>"
                      f"<div style='font-size:.75rem;color:#64748b'>{_html.escape(str(detalle))} · "
                      f"{fecha_s}</div></div></div>")
    hist_html = ""
    if hist_rows:
        hist_html = (f"<div class='card'><h3>Historial de hallazgos ({len(findings)})</h3>"
                     f"<p class='caption'>Resultados positivos persistidos: no se pierden cuando el tema "
                     f"deja de ser noticia. Registro acumulado del radar.</p>{hist_rows}</div>")

    # ALERTA: narrativas sostenidas (>=3 dias) — señal de campaña sostenida
    sost_html = ""
    if sostenidas:
        sost_rows = ""
        for s in sostenidas[:8]:
            fechas = ", ".join(s["fechas"][-5:])
            sost_rows += (f"<div style='display:flex;gap:10px;padding:10px 12px;border-left:4px solid #dc2626;"
                          f"background:#fef2f2;border-radius:8px;margin:8px 0;align-items:center'>"
                          f"<span style='font-size:1.2rem'>🚨</span>"
                          f"<div style='flex:1'><div style='font-size:.88rem;color:#7f1d1d;font-weight:700'>"
                          f"{_html.escape(s['titulo'][:70])}</div>"
                          f"<div style='font-size:.75rem;color:#991b1b'>{s['dias']} días distintos · "
                          f"últimos: {fechas}</div></div>"
                          f"<span style='background:#dc2626;color:#fff;border-radius:6px;padding:3px 8px;"
                          f"font-size:.75rem;font-weight:700'>SOSTENIDA</span></div>")
        sost_html = (f"<div class='card' style='border:2px solid #dc2626'>"
                     f"<h3 style='color:#b91c1c;margin-top:0'>🚨 Narrativas sostenidas ({len(sostenidas)})</h3>"
                     f"<p class='caption'>La misma narrativa se ha amplificado en ≥3 días distintos. "
                     f"Señal de campaña sostenida (no un titular suelto). Requiere investigación prioritaria.</p>"
                     f"{sost_rows}</div>")
    else:
        sost_html = ("<div class='card'><h3>Narrativas sostenidas</h3>"
                     "<p class='caption'>Ninguna narrativa amplificada en ≥3 días distintos todavía. "
                     "El radar sigue acumulando historial para detectarlas.</p></div>")

    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    # KPIs
    n_crit = sum(1 for c in clusters if c[11] and c[11] >= 80) if clusters else 0
    n_high = sum(1 for c in clusters if c[11] and 60 <= c[11] < 80) if clusters else 0
    n_anom = sum(1 for c in clusters if c[11] and 40 <= c[11] < 60) if clusters else 0
    if narr_kpi is None:
        narr_kpi = kpi("Narrativas amplificadas", 0, "sin datos", "#f8fafc")
    cards = "".join([
        kpi("Eventos", n_events, "capturados", "#eff6ff"),
        kpi("Fuentes", n_sources, "activas", "#f0fdf4"),
        kpi("Clusters", len(clusters), "detectados", "#fafaf9"),
        narr_kpi,
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

{narr_block}

{sost_html}

{hist_html}

<div class="card">
<h3>Fuentes y búsquedas activas</h3>
<p class="caption">Inventario real de config.yaml: qué se vigila y con qué palabras. Para añadir o
quitar, edita <code>config.yaml</code> en el repo (docs/FUENTES.md lo documenta).</p>
<div style="display:flex;gap:24px;flex-wrap:wrap">
  <div style="flex:1;min-width:260px">
    <b style="font-size:.9rem">RSS / feeds ({len(feeds)})</b>
    <ul style="font-size:.82rem;color:#334155;padding-left:18px;line-height:1.7">{feeds_html}</ul>
  </div>
  <div style="flex:1;min-width:260px">
    <b style="font-size:.9rem">Palabras clave ({len(keywords)})</b>
    <ul style="font-size:.82rem;color:#334155;padding-left:18px;line-height:1.7">{kw_html}</ul>
    <b style="font-size:.9rem">Telegram</b>
    <p style="font-size:.82rem;color:#334155">{tg_html}</p>
    <b style="font-size:.9rem">Reddit</b>
    <p style="font-size:.82rem;color:#334155">{sr_html}</p>
  </div>
</div>
</div>

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
