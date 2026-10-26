#!/usr/bin/env python3
"""protestas.py — ficha curada + señal visual del piloto `protestas_juveniles`.

Qué hace:
  - Lee `data/protestas.yaml` (episodios, demandas y llamadas documentadas).
  - Lee `data/radar.db` (eventos/clusters del tema) SIN tocar scoring.
  - Escribe `data/protestas.json` y `/var/www/fimi/casos/protestas/index.html`.
  - Los gráficos son SVG inline: no hay JS ni dependencias externas.

Límites:
  - No atribuye autoría ni intención.
  - Las demandas/llamadas son citas curadas, no extracción automática.
  - La señal del radar mide eventos y amplificación, no hechos verificados.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import sqlite3
import sys
import textwrap
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
YAML_PATH = ROOT / "data" / "protestas.yaml"
JSON_OUT = Path("/var/www/fimi/datos/protestas.json")
SCHEMA_OUT = Path("/var/www/fimi/datos/protestas.schema.json")
HTML_OUT = Path("/var/www/fimi/casos/protestas/index.html")
TEMA = "protestas_juveniles"

sys.path.insert(0, str(ROOT))
from detection.bandas import BAND_ES, banda  # noqa: E402
from detection.mainstream import MAINSTREAM  # noqa: E402

BAND_COL = {
    "CRITICAL": "#dc2626",
    "HIGH": "#f97316",
    "ANOMALOUS": "#f59e0b",
    "WATCH": "#38bdf8",
    "NORMAL": "#94a3b8",
}
BAND_ORDER = ["CRITICAL", "HIGH", "ANOMALOUS", "WATCH", "NORMAL"]


def n(x) -> str:
    return f"{int(round(float(x or 0))):,}".replace(",", ".")


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def fecha(x) -> str:
    if hasattr(x, "isoformat"):
        return x.isoformat()
    return str(x or "")


def dmy(x) -> str:
    s = fecha(x)
    try:
        y, m, d = s.split("-")
        return f"{d}/{m}/{y}"
    except ValueError:
        return s


def tipo_dominio(h: str) -> str:
    h = (h or "").lower()
    if h in {"news.google.com", "news.google.es"}:
        return "agregador"
    if h in {"youtube.com", "youtu.be", "tiktok.com", "x.com", "twitter.com",
             "instagram.com", "facebook.com", "reddit.com"}:
        return "plataforma"
    if h in MAINSTREAM:
        return "medio"
    return "otro"


def dm(x) -> str:
    s = str(x)
    try:
        return s[8:10] + "/" + s[5:7]
    except Exception:
        return s


def dt(ts):
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%m/%Y")


def wrap(t: str, width: int) -> list[str]:
    return textwrap.wrap(str(t or ""), width=width) or [""]


def arc_path(cx, cy, r1, r2, a0, a1) -> str:
    """Cuña de donut entre dos ángulos en grados."""
    def p(r, a):
        rad = math.radians(a)
        return cx + r * math.cos(rad), cy + r * math.sin(rad)

    x0, y0 = p(r1, a0); x1, y1 = p(r1, a1)
    x2, y2 = p(r2, a1); x3, y3 = p(r2, a0)
    large = 1 if (a1 - a0) > 180 else 0
    return (f"M {x0:.2f} {y0:.2f} A {r1} {r1} 0 {large} 1 {x1:.2f} {y1:.2f} "
            f"L {x2:.2f} {y2:.2f} A {r2} {r2} 0 {large} 0 {x3:.2f} {y3:.2f} Z")


def cargar_episodios() -> list:
    return yaml.safe_load(YAML_PATH.read_text(encoding="utf-8")) or []


def señal(conn) -> dict:
    row = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT e.author), MIN(e.timestamp), MAX(e.timestamp) "
        "FROM events e JOIN event_temas et ON et.event_id=e.id WHERE et.tema_id=?",
        (TEMA,),
    ).fetchone()
    n_ev, n_aut, t0, t1 = row
    cl = [dict(r) for r in conn.execute(
        "SELECT c.cluster_label, c.overall_score, c.created_at, "
        "COUNT(ce.rowid) AS n_ev, COUNT(DISTINCT ce.author) AS n_au "
        "FROM clusters c LEFT JOIN cluster_events ce ON ce.cluster_id=c.id "
        "WHERE c.tema_id=? GROUP BY c.id ORDER BY c.overall_score DESC",
        (TEMA,),
    )]
    bandas = {b: 0 for b in BAND_ORDER}
    for r in cl:
        b = banda(r["overall_score"] or 0)
        bandas[b] = bandas.get(b, 0) + 1
    # ritmo diario de los últimos 14 días, con ceros incluidos
    hoy = datetime.now(timezone.utc).date()
    start = hoy - timedelta(days=13)
    raw = {r[0]: r[1] for r in conn.execute(
        "SELECT date(e.timestamp,'unixepoch') d, COUNT(*) "
        "FROM events e JOIN event_temas et ON et.event_id=e.id "
        "WHERE et.tema_id=? AND e.timestamp>=strftime('%s', ?) GROUP BY d",
        (TEMA, start.isoformat()),
    )}
    daily = []
    for i in range(14):
        d = start + timedelta(days=i)
        daily.append({"fecha": d.isoformat(), "eventos": raw.get(d.isoformat(), 0)})
    # dominios (solo URL; no cuentas)
    doms = {}
    for r in conn.execute(
        "SELECT e.url FROM events e JOIN event_temas et ON et.event_id=e.id "
        "WHERE et.tema_id=? AND e.url IS NOT NULL AND e.url<>''", (TEMA,)
    ):
        try:
            host = urllib.parse.urlparse(r[0]).netloc.lower().replace("www.", "")
        except Exception:
            host = ""
        if host:
            doms[host] = doms.get(host, 0) + 1
    top_doms = sorted(doms.items(), key=lambda x: -x[1])[:8]
    src = {r[0]: r[1] for r in conn.execute(
        "SELECT e.source, COUNT(*) FROM events e JOIN event_temas et ON et.event_id=e.id "
        "WHERE et.tema_id=? GROUP BY e.source ORDER BY 2 DESC", (TEMA,))}
    stot = sum(src.values()) or 1
    fuentes = [{"fuente": k, "n": v, "pct": round(100 * v / stot, 1)} for k, v in src.items()]
    prow = conn.execute(
        "SELECT COUNT(*), MAX(n_ciclos), AVG(n_ciclos) FROM cluster_lineage WHERE tema_id=?",
        (TEMA,)).fetchone()
    persistencia = {"linajes": int(prow[0] or 0), "max_ciclos": int(prow[1] or 0),
                    "media_ciclos": round(float(prow[2] or 0), 2)}
    top_clusters = []
    for r in cl:
        b = banda(r["overall_score"] or 0)
        top_clusters.append({
            "label": r["cluster_label"],
            "score": round(r["overall_score"] or 0, 1),
            "banda": b,
            "banda_es": BAND_ES.get(b, b),
            "eventos": int(r["n_ev"] or 0),
            "cuentas": int(r["n_au"] or 0),
            "urls": 0,
        })
    return {
        "eventos": n_ev or 0,
        "cuentas": n_aut or 0,
        "desde": int(t0) if t0 else None,
        "hasta": int(t1) if t1 else None,
        "clusters": len(cl),
        "signal_clusters": sum(1 for r in cl if int(r["n_au"] or 0) >= 3),
        "small_clusters": sum(1 for r in cl if int(r["n_au"] or 0) < 3),
        "bandas": bandas,
        "max_score": round(max((r["overall_score"] or 0 for r in cl), default=0), 1),
        "top_clusters": top_clusters[:16],
        "daily": daily,
        "fuentes": fuentes,
        "persistencia": persistencia,
        "top_dominios": [{"dominio": d, "eventos": c, "tipo": tipo_dominio(d)} for d, c in top_doms],
    }


def svg_timeline(epis: list) -> str:
    if not epis:
        return "<p class='meta'>Sin episodios.</p>"
    eps = sorted(epis, key=lambda e: (fecha(e.get("fecha")), str(e.get("pais"))))
    W, H = 1040, 390
    x0, x1, y = 74, 966, 190
    step = (x1 - x0) / max(1, len(eps) - 1)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="tlt tl" class="chart">',
           '<title id="tlt">Cronología de los episodios curados</title>',
           '<desc id="tl">Cinco hitos de la ola, ordenados de 2025 a 2026.</desc>',
           f'<defs><linearGradient id="tg" gradientUnits="userSpaceOnUse" x1="{x0}" y1="{y}" x2="{x1}" y2="{y}"><stop offset="0" stop-color="#38bdf8"/><stop offset="1" stop-color="#f97316"/></linearGradient></defs>',
           f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="url(#tg)" stroke-width="4" stroke-linecap="round"/>']
    for i, e in enumerate(eps):
        x = x0 + i * step
        up = i % 2 == 0
        col = "#f97316" if i == len(eps) - 1 else "#0ea5e9"
        label = f"{e.get('ciudad')} · {e.get('pais')}"
        lines = wrap(e.get("nombre"), 23)
        if up:
            out.append(f'<line x1="{x:.1f}" y1="{y-12}" x2="{x:.1f}" y2="118" stroke="#94a3b8"/>')
            out.append(f'<text x="{x:.1f}" y="36" text-anchor="middle" class="tl-date">{dmy(e.get("fecha"))}</text>')
            out.append(f'<text x="{x:.1f}" y="54" text-anchor="middle" class="tl-place">{esc(label)}</text>')
            for j, line in enumerate(lines[:3]):
                out.append(f'<text x="{x:.1f}" y="{72+j*18}" text-anchor="middle" class="tl-name">{esc(line)}</text>')
        else:
            out.append(f'<line x1="{x:.1f}" y1="{y+12}" x2="{x:.1f}" y2="254" stroke="#94a3b8"/>')
            out.append(f'<text x="{x:.1f}" y="268" text-anchor="middle" class="tl-date">{dmy(e.get("fecha"))}</text>')
            out.append(f'<text x="{x:.1f}" y="286" text-anchor="middle" class="tl-place">{esc(label)}</text>')
            for j, line in enumerate(lines[:3]):
                out.append(f'<text x="{x:.1f}" y="{304+j*18}" text-anchor="middle" class="tl-name">{esc(line)}</text>')
        out.append(f'<circle cx="{x:.1f}" cy="{y}" r="9" fill="{col}" stroke="#fff" stroke-width="3"><title>{esc(e.get("nombre"))}</title></circle>')
    out.append(f'<text x="{x0}" y="374" class="tl-note">Secuencia editorial de los episodios curados · no es una escala temporal</text>')
    out.append("</svg>")
    return "".join(out)


def svg_bands(bands: dict) -> str:
    total = sum((bands.get(b, 0) or 0) for b in BAND_ORDER)
    W, H = 480, 260
    cx, cy, r1, r2 = 132, 128, 92, 58
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Reparto de clústeres por banda" class="chart">',
           f'<circle cx="{cx}" cy="{cy}" r="{r1}" fill="#f1f5f9"/>']
    if total:
        a = -90
        for b in BAND_ORDER:
            c = bands.get(b, 0) or 0
            if not c:
                continue
            sweep = 360 * c / total
            out.append(f'<path d="{arc_path(cx, cy, r1, r2, a, a+sweep)}" fill="{BAND_COL[b]}"><title>{esc(BAND_ES.get(b,b))}: {c}</title></path>')
            a += sweep
    out.append(f'<text x="{cx}" y="{cy-4}" text-anchor="middle" class="donut-num">{total}</text>')
    out.append(f'<text x="{cx}" y="{cy+18}" text-anchor="middle" class="donut-lab">clústeres</text>')
    yy = 42
    for b in BAND_ORDER:
        c = bands.get(b, 0) or 0
        out.append(f'<rect x="252" y="{yy-10}" width="10" height="10" rx="2" fill="{BAND_COL[b]}"/>')
        out.append(f'<text x="270" y="{yy}" class="legend">{esc(BAND_ES.get(b,b))}</text>')
        out.append(f'<text x="458" y="{yy}" text-anchor="end" class="legend-n">{c}</text>')
        yy += 35
    out.append("</svg>")
    return "".join(out)


def svg_scatter(clusters: list) -> str:
    pts = [c for c in clusters if c.get("cuentas", 0) > 0][:16]
    W, H = 980, 360
    L, R, T, B = 64, 26, 24, 58
    pw, ph = W - L - R, H - T - B
    xmax = max([5] + [c["cuentas"] for c in pts])
    ymax = 100
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Clústeres: cuentas frente a score" class="chart">',
           '<defs><linearGradient id="sg" x1="0" x2="1"><stop offset="0" stop-color="#38bdf8"/><stop offset="1" stop-color="#f97316"/></linearGradient></defs>']
    for yv in (0, 20, 40, 60, 80, 100):
        y = T + ph * (1 - yv / ymax)
        out.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W-R}" y2="{y:.1f}" stroke="#e2e8f0"/>')
        out.append(f'<text x="{L-10}" y="{y+4:.1f}" text-anchor="end" class="axis">{yv}</text>')
    y60 = T + ph * 0.4
    out.append(f'<line x1="{L}" y1="{y60:.1f}" x2="{W-R}" y2="{y60:.1f}" stroke="#f97316" stroke-dasharray="5 5"/>')
    out.append(f'<text x="{W-R-8}" y="{y60-8:.1f}" text-anchor="end" class="axis-hot">banda alta ≥60</text>')
    for xv in range(0, xmax + 1, max(1, xmax // 5)):
        x = L + pw * xv / xmax
        out.append(f'<text x="{x:.1f}" y="{H-B+22}" text-anchor="middle" class="axis">{xv}</text>')
    out.append(f'<text x="{L+pw/2}" y="{H-16}" text-anchor="middle" class="axis-title">cuentas en el clúster</text>')
    for c in pts:
        x = L + pw * min(c["cuentas"], xmax) / xmax
        y = T + ph * (1 - min(c["score"], ymax) / ymax)
        r = 5 + min(10, math.sqrt(max(1, c.get("eventos", 0))) * 2.2)
        col = BAND_COL.get(c.get("banda"), "#94a3b8")
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{col}" fill-opacity=".78" stroke="#fff" stroke-width="1.5"><title>{esc(c["label"])} · {c["score"]} · {c["cuentas"]} cuentas · {c["eventos"]} eventos</title></circle>')
    if pts:
        c = max(pts, key=lambda x: x["score"])
        x = L + pw * min(c["cuentas"], xmax) / xmax
        y = T + ph * (1 - min(c["score"], ymax) / ymax)
        out.append(f'<text x="{x+12:.1f}" y="{y-10:.1f}" class="point-lab">máx {c["score"]:.0f} · {c["cuentas"]} cuentas</text>')
    out.append("</svg>")
    return "".join(out)


def svg_daily(daily: list, epis: list) -> str:
    W, H = 980, 240
    L, R, T, B = 56, 24, 22, 44
    pw, ph = W - L - R, H - T - B
    vals = [d["eventos"] for d in daily]
    vmax = max([1] + vals)
    pts = []
    for i, d in enumerate(daily):
        x = L + (pw * i / max(1, len(daily) - 1))
        y = T + ph * (1 - d["eventos"] / vmax)
        pts.append((x, y, d))
    line = " L ".join(f"{x:.1f},{y:.1f}" for x, y, _ in pts)
    area = f"{L},{T+ph} L {line} L {L+pw},{T+ph} Z"
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Eventos por día en los últimos 14 días" class="chart">',
           '<defs><linearGradient id="dg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f97316" stop-opacity=".35"/><stop offset="1" stop-color="#f97316" stop-opacity="0"/></linearGradient></defs>',
           f'<path d="{area}" fill="url(#dg)"/>',
           f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x,y,_ in pts)}" fill="none" stroke="#f97316" stroke-width="3" stroke-linejoin="round"/>']
    for yv in (0, vmax // 2, vmax):
        y = T + ph * (1 - yv / vmax)
        out.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W-R}" y2="{y:.1f}" stroke="#e2e8f0"/>')
        out.append(f'<text x="{L-8}" y="{y+4:.1f}" text-anchor="end" class="axis">{yv}</text>')
    for i, (x, y, d) in enumerate(pts):
        if i in (0, len(pts) - 1) or d["eventos"] == vmax:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#f97316" stroke="#fff" stroke-width="2"><title>{d["fecha"]}: {d["eventos"]}</title></circle>')
            out.append(f'<text x="{x:.1f}" y="{H-B+20}" text-anchor="middle" class="axis">{dm(d["fecha"])}</text>')
    # hitos curados dentro de la ventana
    by_day = {}
    for e in epis or []:
        d = fecha(e.get("fecha"))[:10]
        if any(x["fecha"] == d for x in daily):
            by_day.setdefault(d, []).append(e)
    for d, es in by_day.items():
        i = next((j for j, x in enumerate(daily) if x["fecha"] == d), None)
        if i is None:
            continue
        x = L + pw * i / max(1, len(daily) - 1)
        label = f"{dm(d)} · {len(es)} episodio" + ("s" if len(es) != 1 else "")
        anchor = "end" if x > W - 140 else ("start" if x < L + 100 else "middle")
        tx = x - 4 if anchor == "end" else (x + 4 if anchor == "start" else x)
        out.append(f'<line x1="{x:.1f}" y1="{T}" x2="{x:.1f}" y2="{T+ph}" stroke="#0ea5e9" stroke-width="1.5" stroke-dasharray="4 5"/>')
        out.append(f'<text x="{tx:.1f}" y="{T-7}" text-anchor="{anchor}" class="axis-mark">{esc(label)}</text>')
    out.append(f'<text x="{L}" y="{H-8}" class="axis-title">eventos etiquetados por día · marcas = episodios curados en la ventana</text>')
    out.append("</svg>")
    return "".join(out)


def svg_domains(doms: list) -> str:
    if not doms:
        return "<p class='meta'>Sin dominios.</p>"
    W, H = 900, 285
    x0, x1, y0, row = 218, 872, 38, 30
    vmax = max((d["eventos"] for d in doms), default=1)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Dominios con más eventos" class="chart">']
    for i, d in enumerate(doms):
        y = y0 + i * row
        w = max(3, (x1 - x0) * d["eventos"] / vmax)
        out.append(f'<text x="{x0-10}" y="{y+16}" text-anchor="end" class="dom-lab">{esc(d["dominio"][:25])} · {esc(d.get("tipo", "otro"))}</text>')
        out.append(f'<rect x="{x0}" y="{y+4}" width="{x1-x0}" height="17" rx="8" fill="#f1f5f9"/>')
        out.append(f'<rect x="{x0}" y="{y+4}" width="{w:.1f}" height="17" rx="8" fill="#0ea5e9"><title>{esc(d["dominio"])}: {d["eventos"]}</title></rect>')
        out.append(f'<text x="{x0+w+8:.1f}" y="{y+17}" class="dom-num">{n(d["eventos"])}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_mechanism() -> str:
    W, H = 1000, 300
    labels = [
        ("1", "Malestar", ["vivienda, escuela,", "coste de vida, empleo"]),
        ("2", "Detonante", ["un caso concreto", "que cabe en 30 s"]),
        ("3", "Plataforma", ["TikTok / Instagram", "+ mensajería cerrada"]),
        ("4", "Símbolo", ["blocus, «como en", "Francia», One Piece"]),
        ("5", "Respuesta", ["detenciones, límites,", "ley y orden"]),
    ]
    bw, gap, x0, y = 172, 25, 25, 54
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Mecanismo de propagación en cinco piezas" class="chart">',
           '<defs><marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#334155"/></marker></defs>']
    cols = ["#e0f2fe", "#fef3c7", "#ede9fe", "#ffe4e6", "#dcfce7"]
    strokes = ["#0ea5e9", "#f59e0b", "#8b5cf6", "#e11d48", "#16a34a"]
    for i, (num, title, lines) in enumerate(labels):
        x = x0 + i * (bw + gap)
        out.append(f'<rect x="{x}" y="{y}" width="{bw}" height="132" rx="13" fill="{cols[i]}" stroke="{strokes[i]}" stroke-width="1.5"/>')
        out.append(f'<circle cx="{x+22}" cy="{y+22}" r="13" fill="{strokes[i]}"/><text x="{x+22}" y="{y+27}" text-anchor="middle" class="mech-num">{num}</text>')
        out.append(f'<text x="{x+43}" y="{y+27}" class="mech-title">{title}</text>')
        for j, line in enumerate(lines):
            out.append(f'<text x="{x+18}" y="{y+57+j*19}" class="mech-text">{esc(line)}</text>')
        if i < len(labels) - 1:
            out.append(f'<line x1="{x+bw+4}" y1="{y+66}" x2="{x+bw+gap-4}" y2="{y+66}" stroke="#334155" stroke-width="2" marker-end="url(#arr)"/>')
    out.append(f'<path d="M {x0+4*bw+4*gap-6} {y+142} C {x0+4*bw+4*gap-6} {y+208} {x0+2*bw+2*gap} {y+208} {x0+2*bw+2*gap} {y+190}" fill="none" stroke="#f97316" stroke-width="2" stroke-dasharray="5 5" marker-end="url(#arr)"/>')
    out.append(f'<text x="{W/2}" y="{H-10}" text-anchor="middle" class="mech-note">La respuesta puede convertirse en un nuevo detonante · marco analítico, no secuencia causal</text>')
    out.append("</svg>")
    return "".join(out)


CSS = """
:root{--navy:#0b1220;--ink:#1e293b;--muted:#64748b;--line:#e2e8f0;--orange:#f97316;--blue:#38bdf8;--bg:#f3f6fb;--teal:#0e9f6e}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:#c2410c}
header{background:#0b1220;color:#fff;padding:16px 0;border-top:4px solid var(--orange)}
.wrap{max-width:1100px;margin:0 auto;padding:0 22px}
.brand{font-weight:800;letter-spacing:.02em;text-decoration:none;color:#fff}
.brand span{color:var(--blue)}
.kicker{color:#fdba74;font-size:.76rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase}
.hero{position:relative;overflow:hidden;background:radial-gradient(900px 400px at 10% -10%,#1d4ed8 0,#0b1220 55%),#0b1220;color:#fff;border-radius:0 0 28px 28px;padding:48px 0 34px;margin-bottom:22px}
.hero:after{content:"";position:absolute;right:-90px;top:-90px;width:360px;height:360px;border:1px solid #f9731655;border-radius:50%;box-shadow:0 0 0 35px #f9731611,0 0 0 70px #f9731609}
.hero h1{font-size:clamp(2.1rem,5.4vw,4.1rem);line-height:1.02;margin:.2em 0 .18em;letter-spacing:-.04em;max-width:900px}
.hero .lead{color:#cbd5e1;font-size:1.08rem;max-width:780px}
.hero .badge{background:#ffffff12;color:#fed7aa;border-color:#ffffff25}
.hero-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:22px 0 0;max-width:850px}
.hero-stat{border:1px solid #ffffff1c;background:#ffffff0b;border-radius:12px;padding:11px 13px}
.hero-stat b{display:block;font-size:1.55rem;line-height:1.1;color:#fff}
.hero-stat span{font-size:.74rem;color:#9fb0c8}
h2{font-size:1.45rem;margin:2.1rem 0 .55rem;letter-spacing:-.02em}
h3{font-size:1.04rem;margin:0 0 .35rem}
.lead{font-size:1.08rem;color:#334155;max-width:820px}
.badge{display:inline-block;background:#fff7ed;color:#9a3412;border:1px solid #fed7aa;border-radius:999px;padding:4px 10px;font-size:.76rem;font-weight:800;margin:0 6px 6px 0}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}
.kpi{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px 15px;box-shadow:0 8px 18px #0f172a08}
.kpi b{display:block;font-size:1.55rem;line-height:1.1;color:var(--navy)}
.kpi span{font-size:.76rem;color:var(--muted)}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px;margin:14px 0;box-shadow:0 8px 20px #0f172a06}
.note{background:#fff7ed;border-left:4px solid var(--orange);padding:13px 16px;border-radius:0 10px 10px 0;margin:16px 0}
.takeaways{background:#fff;border:1px solid var(--line);border-radius:16px;padding:16px 20px;margin:16px 0;box-shadow:0 8px 18px #0f172a06}
.takeaways h2{margin:0 0 6px;font-size:1.1rem}
.takeaways ul{margin:0 0 0 1.1rem;padding:0}
.takeaways li{margin:3px 0}
.term{border-bottom:1px dotted #f97316;cursor:help}
.glossary{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:12px 0;font-size:.9rem}
.glossary summary{cursor:pointer;font-weight:700;color:#0f172a}
.glossary p{margin:8px 0 0;color:#475569}
.axis-mark{font-size:10px;fill:#0ea5e9;font-weight:700}
.meta{font-size:.82rem;color:var(--muted)}
.tag{display:inline-block;background:#f1f5f9;border:1px solid var(--line);border-radius:6px;padding:2px 7px;font-size:.74rem;margin:2px 4px 2px 0}
.chart-card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:16px 18px;margin:14px 0;box-shadow:0 8px 20px #0f172a06}
.chart-card h3{margin-bottom:4px}
.chart{width:100%;height:auto;display:block;overflow:visible}
.two{display:grid;grid-template-columns:1.05fr .95fr;gap:14px;align-items:start}
.two-charts{grid-template-columns:.72fr 1.28fr}
.three{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.episode{background:#fff;border:1px solid var(--line);border-left:5px solid var(--orange);border-radius:14px;padding:17px;margin:12px 0;box-shadow:0 8px 18px #0f172a06}
.episode .num{float:right;color:#cbd5e1;font-weight:800;font-size:1.1rem}
.episode h3{margin-top:2px}
.episode p{margin:.35em 0}
.episode ul{margin:.3em 0 .5em 1.15rem;padding:0}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;font-size:.88rem}
th{background:#f1f5f9;color:#334155;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em}
tr:last-child td{border-bottom:0}
ul{margin:.4rem 0 .4rem 1.15rem;padding:0}
.tl-date{font-size:13px;font-weight:800;fill:#0f172a}
.tl-place{font-size:11px;fill:#64748b}
.tl-name{font-size:11px;fill:#334155}
.tl-note{font-size:10px;fill:#94a3b8}
.donut-num{font-size:32px;font-weight:800;fill:#0f172a}
.donut-lab{font-size:10px;fill:#64748b}
.legend{font-size:11px;fill:#334155;font-weight:600}
.legend-n{font-size:11px;fill:#64748b;font-weight:700}
.axis{font-size:10px;fill:#94a3b8}
.axis-title{font-size:10px;fill:#64748b}
.axis-hot{font-size:10px;fill:#f97316;font-weight:700}
.point-lab{font-size:10px;fill:#334155;font-weight:700}
.dom-lab{font-size:10px;fill:#334155}
.dom-num{font-size:10px;fill:#64748b;font-weight:700}
.mech-num{font-size:12px;fill:#fff;font-weight:800}
.mech-title{font-size:12px;fill:#0f172a;font-weight:800}
.mech-text{font-size:10px;fill:#334155}
.mech-note{font-size:10px;fill:#64748b}
footer{border-top:1px solid var(--line);margin-top:30px;padding:20px 0 40px;color:var(--muted);font-size:.85rem}
@media(max-width:850px){.two,.two-charts,.three{grid-template-columns:1fr}.hero-stats{grid-template-columns:repeat(2,1fr)}}
@media(max-width:600px){.grid{grid-template-columns:repeat(2,1fr)}.hero{padding-top:32px}table{display:block;overflow-x:auto}}
"""


def render(epis: list, s: dict, ahora: str) -> str:
    eps_html = []
    for i, e in enumerate(sorted(epis, key=lambda x: (fecha(x.get("fecha")), str(x.get("pais")))), 1):
        dem = e.get("demandas") or []
        dem_html = "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in dem) + "</ul>" if dem else "<p class='meta'>Sin pliego público localizado.</p>"
        fuentes = "".join(
            f"<a href='{esc(u)}' target='_blank' rel='noopener noreferrer'>fuente</a> "
            for u in (e.get("fuentes") or [])
        )
        eps_html.append(f"""
        <article class="episode">
          <span class="num">{i:02d}</span>
          <div class="meta">{dmy(e.get('fecha'))} · {esc(e.get('pais'))} · {esc(e.get('ciudad'))}</div>
          <h3>{esc(e.get('nombre'))}</h3>
          <p class="meta"><b>Estado:</b> {esc(e.get('estado'))}</p>
          <p><b>Detonante:</b> {esc(e.get('detonante'))}</p>
          <p><b>Quién convoca:</b> {esc(e.get('convocantes'))}</p>
          <p><b>Demandas declaradas:</b></p>{dem_html}
          <p><b>Llamada / acción:</b> {esc(e.get('llamada'))}</p>
          <p class="meta"><b>Alcance:</b> {esc(e.get('alcance'))}</p>
          <p class="meta"><b>Límite:</b> {esc(e.get('nota'))}</p>
          <p class="meta">Fuentes: {fuentes or '—'}</p>
        </article>""")

    banda_rows = "".join(
        f"<tr><td>{esc(BAND_ES.get(b, b))}</td><td>{n(s['bandas'].get(b, 0))}</td></tr>"
        for b in BAND_ORDER if s["bandas"].get(b, 0)
    ) or "<tr><td colspan='2'>Sin clusters todavía.</td></tr>"
    top = "".join(
        f"<tr><td>{esc(c['label'])}</td><td>{c['score']:.1f}</td><td>{esc(c['banda_es'])}</td><td>{n(c['cuentas'])}</td><td>{n(c['eventos'])}</td></tr>"
        for c in s["top_clusters"][:8]
    ) or "<tr><td colspan='5'>Sin clusters todavía.</td></tr>"
    doms = "".join(
        f"<tr><td>{esc(d['dominio'])}</td><td>{esc(d.get('tipo','otro'))}</td><td>{n(d['eventos'])}</td></tr>"
        for d in s["top_dominios"]
    ) or "<tr><td colspan='3'>Sin dominios todavía.</td></tr>"
    high = s["bandas"].get("HIGH", 0) + s["bandas"].get("CRITICAL", 0)
    top_src = " · ".join(f"{f['fuente']} {f['pct']}%" for f in s.get("fuentes", [])[:2])
    pers = s.get("persistencia", {})
    takeaways = [
        f"<b>{n(s.get('signal_clusters', 0))} de {n(s['clusters'])}</b> clústeres tienen señal (≥3 cuentas); {n(s.get('small_clusters', 0))} son grupos pequeños.",
        f"<b>{n(high)}</b> en banda alta y <b>0</b> sincronías entre cuentas distintas. La banda alta mide amplificación, no autoría.",
        f"La conversación viene sobre todo de <b>{esc(top_src or '—')}</b>.",
        f"Persistencia: <b>{n(pers.get('max_ciclos', 0))} ciclo</b> por linaje. Con un solo ciclo no hay vida media fiable.",
    ]

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Protestas juveniles · piloto FIMI</title>
<meta name="robots" content="noindex,follow">
<meta name="description" content="Cronología, señal de amplificación, mecanismo y episodios curados de la ola de protestas juveniles 2025-26.">
<style>{CSS}</style></head><body>
<header><div class="wrap"><a class="brand" href="/">📡 Observatorio <span>/ protestas juveniles</span></a></div></header>
<main class="wrap">
<section class="hero">
  <p class="kicker">Piloto · señal de amplificación</p>
  <h1>La ola juvenil, en una página</h1>
  <p class="lead">Del malestar a la calle y de la calle al feed. Qué está documentado, qué se repite y qué sigue siendo atribución. El radar mide amplificación y extensión; no identifica autores ni intención.</p>
  <p><span class="badge">Piloto</span><span class="badge">Sin atribución</span><span class="badge">Fuentes enlazadas</span></p>
  <div class="hero-stats">
    <div class="hero-stat"><b>{n(s['eventos'])}</b><span>eventos etiquetados</span></div>
    <div class="hero-stat"><b>{n(s['cuentas'])}</b><span>cuentas distintas</span></div>
    <div class="hero-stat"><b>{n(s['clusters'])}</b><span>clústeres</span></div>
    <div class="hero-stat"><b>{n(high)}</b><span>en banda alta</span></div>
  </div>
</section>

<div class="note"><b>Cómo leer esta página.</b> Los KPIs y los clústeres salen de <code>event_temas</code> del tema <code>{TEMA}</code>. Las demandas y llamadas son una selección curada de fuentes públicas, no una extracción automática. Una <span class="term" title="Banda de score que indica amplificación anómala; no confirma coordinación ni autoría.">banda alta</span> significa <b>amplificación anómala</b>, no coordinación confirmada. Actualizado: {esc(ahora)} UTC · última observación: {dt(s['hasta'])}.</div>

<div class="takeaways"><h2>Lo esencial</h2><ul>{''.join(f'<li>{x}</li>' for x in takeaways)}</ul></div>

<details class="glossary"><summary>Qué significan «banda alta», «clúster», «score» y «persistencia»</summary>
<p><b>Clúster:</b> grupo de eventos que el sistema conecta por contenido, enlaces, tiempo o cuentas. No es una prueba de coordinación. <b>Score:</b> combinación de coordinación, similitud, amplificación, infraestructura y anomalía (0–100); no es una probabilidad. <b>Banda alta:</b> score ≥60; indica amplificación anómala. <b>Amplificación anómala:</b> patrón de repetición o extensión fuera de lo esperado; no identifica autor. <b>Persistencia:</b> número de ciclos en los que sobrevive un linaje; con un solo ciclo no hay vida media fiable. <a href="/glosario.html#casa">Glosario completo</a>.</p>
</details>

<section>
  <h2>Cronología: de Katmandú a Barcelona</h2>
  <p class="meta">Cinco episodios curados para separar el hecho, la demanda y la llamada. El orden es editorial; no es una escala temporal.</p>
  <div class="chart-card">{svg_timeline(epis)}</div>
</section>

<section>
  <h2>La señal, en tres planos</h2>
  <div class="two two-charts">
    <div class="chart-card"><h3>Reparto por banda</h3><p class="meta">Todos los clústeres del tema; la mayoría son grupos pequeños.</p>{svg_bands(s['bandas'])}</div>
    <div class="chart-card"><h3>Cuentas frente a score</h3><p class="meta">Cada círculo es un clúster. Tamaño = eventos; color = banda.</p>{svg_scatter(s['top_clusters'])}</div>
  </div>
  <div class="chart-card"><h3>Ritmo de conversación</h3><p class="meta">Eventos etiquetados por día en la ventana del piloto.</p>{svg_daily(s['daily'], epis)}</div>
</section>

<section>
  <h2>Episodios curados</h2>
  <p class="meta">No todas las protestas tienen un pliego público: cuando no lo hay, se dice. La ficha no atribuye autoría ni intención.</p>
  {''.join(eps_html)}
</section>

<section>
  <h2>El mecanismo: cinco piezas</h2>
  <div class="chart-card">{svg_mechanism()}</div>
</section>

<section>
  <h2>Quién amplifica</h2>
  <div class="chart-card"><h3>Dominios con más eventos</h3><p class="meta">Presencia en enlaces del tema; no implica coordinación ni participación del medio.</p>{svg_domains(s["top_dominios"])}<div style="overflow:auto;margin-top:10px"><table><thead><tr><th>Dominio</th><th>Tipo</th><th>Eventos</th></tr></thead><tbody>{doms}</tbody></table></div></div>
    <div class="chart-card"><h3>Clústeres con más señal</h3>
      <div style="overflow:auto"><table><thead><tr><th>Clúster</th><th>Score</th><th>Banda</th><th>Cuentas</th><th>Eventos</th></tr></thead><tbody>{top}</tbody></table></div>
      <p class="meta" style="margin-top:10px">Cifras calculadas desde <code>radar.db</code>; no son hechos verificados.</p>
    </div>
</section>

<section>
  <h2>Qué vigilar</h2>
  <div class="three">
    <div class="card"><h3>Extensión</h3><p class="meta">Si las mismas consignas saltan de país sin un detonante local.</p></div>
    <div class="card"><h3>Amplificación</h3><p class="meta">Si crecen cuentas y dominios que repiten el mismo contenido en una ventana corta.</p></div>
    <div class="card"><h3>Atribución</h3><p class="meta">Solo con evidencia independiente. El radar no la proporciona.</p></div>
  </div>
</section>

<p><a href="/datos/protestas.json">Datos abiertos (JSON)</a> · <a href="/datos/protestas.schema.json">Esquema JSON</a> · <a href="/informes/visual/protestas_juveniles.html">Informe visual</a> · <a href="/">Volver al radar</a> · <a href="/casos/electoral/">Panorama electoral</a></p>
<footer>Elaborado con asistencia de IA y revisión humana. Fuentes enlazadas en el texto. — @pruebapublica<br>
Piloto <code>{TEMA}</code> · no indexado hasta revisión · {esc(ahora)} UTC</footer>
</main></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-only", action="store_true")
    a = ap.parse_args()
    epis = cargar_episodios()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    s = señal(conn)
    conn.close()
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    data = {"tema": TEMA, "actualizado": ahora, "episodios": epis, "senal": s}
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Observatorio 29N · protestas juveniles",
        "type": "object",
        "required": ["tema", "actualizado", "episodios", "senal"],
        "properties": {
            "tema": {"type": "string", "const": TEMA},
            "actualizado": {"type": "string"},
            "episodios": {"type": "array", "items": {"type": "object"}},
            "senal": {
                "type": "object",
                "properties": {
                    "eventos": {"type": "integer"},
                    "cuentas": {"type": "integer"},
                    "clusters": {"type": "integer"},
                    "signal_clusters": {"type": "integer"},
                    "small_clusters": {"type": "integer"},
                    "bandas": {"type": "object"},
                    "top_clusters": {"type": "array"},
                    "daily": {"type": "array"},
                    "fuentes": {"type": "array"},
                    "persistencia": {"type": "object"},
                    "top_dominios": {"type": "array"},
                },
            },
        },
    }
    SCHEMA_OUT.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[protestas] JSON -> {JSON_OUT} ({len(epis)} episodios, {s['eventos']} eventos)")
    if not a.json_only:
        HTML_OUT.parent.mkdir(parents=True, exist_ok=True)
        HTML_OUT.write_text(render(epis, s, ahora), encoding="utf-8")
        print(f"[protestas] HTML -> {HTML_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
