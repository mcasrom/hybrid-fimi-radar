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
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
YAML_PATH = ROOT / "data" / "protestas.yaml"
EN_YAML_PATH = ROOT / "data" / "protestas_en.yaml"
JSON_OUT = Path("/var/www/fimi/datos/protestas.json")
SCHEMA_OUT = Path("/var/www/fimi/datos/protestas.schema.json")
SALUD_PATH = ROOT / "data" / "salud_temas.json"
HTML_OUT = Path("/var/www/fimi/casos/protestas/index.html")
HTML_EN = Path("/var/www/fimi/casos/protestas/en.html")
TEMA = "protestas_juveniles"

sys.path.insert(0, str(ROOT))
from detection.bandas import BAND_ES, banda  # noqa: E402
from detection.mainstream import MAINSTREAM  # noqa: E402
from detection import metricas_tema as _mt  # noqa: E402
from detection.protestas_extension import calcular as calcular_extension  # noqa: E402
from detection.convocatorias import cargar_registro  # noqa: E402


CONV_TIPO_ES = {"red_anonima": "Red anónima", "sindicato": "Sindicato",
                "partido_juvenil": "Partido juvenil", "movimiento_estudiantil": "Movimiento estudiantil",
                "plataforma": "Plataforma", "desconocido": "Desconocido"}
CONV_ADSC_ES = {"sin_adscripcion": "Sin adscripción", "autodeclarada": "Autodeclarada",
                "oficial": "Oficial", "atribuida_por_medio": "Atribuida por medio"}
CONV_MARCO_ES = {"educacion": "educación", "coste_vida": "coste de vida",
                 "vivienda": "vivienda", "corrupcion": "corrupción",
                 "anti_gobierno": "anti-gobierno", "anti_policia": "anti-policía",
                 "sin_pliego_publico": "sin pliego público"}
CONV_TIPO_EN = {"red_anonima": "Anonymous network", "sindicato": "Union",
                "partido_juvenil": "Youth party", "movimiento_estudiantil": "Student movement",
                "plataforma": "Platform", "desconocido": "Unknown"}
CONV_ADSC_EN = {"sin_adscripcion": "No declared affiliation", "autodeclarada": "Self-declared",
                "oficial": "Official", "atribuida_por_medio": "Media-attributed"}
CONV_MARCO_EN = {"educacion": "education", "coste_vida": "cost of living",
                 "vivienda": "housing", "corrupcion": "corruption",
                 "anti_gobierno": "anti-government", "anti_policia": "anti-police",
                 "sin_pliego_publico": "no public demands"}
CONV_ESTADO_EN = {"celebrada": "held", "desconvocada": "called off", "anunciada": "announced"}

BAND_COL = {
    "CRITICAL": "#dc2626",
    "HIGH": "#f97316",
    "ANOMALOUS": "#f59e0b",
    "WATCH": "#38bdf8",
    "NORMAL": "#94a3b8",
}
BAND_ORDER = ["CRITICAL", "HIGH", "ANOMALOUS", "WATCH", "NORMAL"]
BAND_EN = {"CRITICAL": "Very high amplification", "HIGH": "High amplification",
           "ANOMALOUS": "Anomalous amplification", "WATCH": "Under observation", "NORMAL": "Normal"}
PAIS_EN = {"España": "Spain", "Francia": "France", "Italia": "Italy", "Albania": "Albania", "Nepal": "Nepal"}
CIUDAD_EN = {"Barcelona": "Barcelona", "Varias ciudades": "Several cities", "Milán": "Milan",
             "Tirana": "Tirana", "Katmandú": "Kathmandu"}


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


AGENCIAS = {"efe.com", "europapress.es", "reuters.com", "apnews.com", "afp.com",
            "ansa.it", "dpa.com", "afpforum.com"}
MEDIOS_EXTRA = {"infobae.com", "tovima.com", "diarioestrategia.cl", "dw.com"}
ORGANIZACIONES = {"civicus.org", "publications.civicus.org"}


def nivel_fuente(h: str) -> str:
    h = (h or "").lower().replace("www.", "")
    if "wikipedia.org" in h:
        return "wiki"
    if h in AGENCIAS:
        return "agencia"
    if h in MAINSTREAM or h in MEDIOS_EXTRA:
        return "medio"
    if h in ORGANIZACIONES:
        return "organización"
    if h in {"news.google.com", "news.google.es"}:
        return "agregador"
    if h in {"youtube.com", "youtu.be", "tiktok.com", "x.com", "twitter.com",
             "instagram.com", "facebook.com", "reddit.com"}:
        return "plataforma"
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
    eps = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8")) or []
    try:
        en = yaml.safe_load(EN_YAML_PATH.read_text(encoding="utf-8")) or {}
    except OSError:
        en = {}
    for e in eps:
        e["en"] = en.get(e.get("id"), {})
    return eps


def base_comparacion(signal_clusters: int, high: int) -> dict:
    try:
        d = json.loads(SALUD_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    peers = []
    for t in d.get("temas") or []:
        if not isinstance(t, dict) or t.get("tema") == TEMA:
            continue
        try:
            pc = int(t.get("clusters") or 0)
            ph = int(t.get("high") or 0)
        except (TypeError, ValueError):
            continue
        if pc > 0:
            peers.append((pc, ph))
    ncl = sum(pc for pc, _ in peers)
    nhi = sum(ph for _, ph in peers)
    if not ncl:
        return {}
    return {"temas": len(peers), "clusters": ncl, "high": nhi,
            "rate": round(100 * nhi / ncl, 1),
            "tema_rate": round(100 * high / signal_clusters, 1) if signal_clusters else 0.0}


def validar_senal(s: dict) -> list:
    errs = []
    for k in ("eventos", "cuentas", "cuentas_cluster", "clusters",
              "signal_clusters", "small_clusters", "bandas", "bandas_signal"):
        if k not in s:
            errs.append("falta %s" % k)
    if errs:
        return errs
    if s["signal_clusters"] + s["small_clusters"] != s["clusters"]:
        errs.append("señal + pequeños != clusters")
    if sum(int(v) for v in s["bandas"].values()) != s["clusters"]:
        errs.append("suma de bandas != clusters")
    if sum(int(v) for v in s["bandas_signal"].values()) != s["signal_clusters"]:
        errs.append("suma de bandas_signal != signal_clusters")
    for b, v in s["bandas_signal"].items():
        if int(v) > int(s["bandas"].get(b, 0)):
            errs.append("banda_signal %s > banda total" % b)
    if int(s["cuentas_cluster"]) > int(s["cuentas"]):
        errs.append("cuentas_cluster > cuentas")
    top = s.get("top_signal") or []
    if any(int(c.get("cuentas") or 0) < 3 for c in top):
        errs.append("top_signal incluye un cluster con <3 cuentas")
    if top != sorted(top, key=lambda c: -float(c.get("score") or 0)):
        errs.append("top_signal no está ordenado por score")
    ties = sum(1 for c in top if 58.9 <= float(c.get("score") or 0) <= 59.1)
    if int(s.get("tie59_signal") or 0) != ties:
        errs.append("tie59_signal no coincide con top_signal")
    if int(s.get("tie59_all") or 0) < int(s.get("tie59_signal") or 0):
        errs.append("tie59_all < tie59_signal")
    return errs


def señal(conn) -> dict:
    row = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT e.author), MIN(e.timestamp), MAX(e.timestamp) "
        "FROM events e JOIN event_temas et ON et.event_id=e.id WHERE et.tema_id=?",
        (TEMA,),
    ).fetchone()
    n_ev, n_aut, t0, t1 = row
    cl = [dict(r) for r in conn.execute(
        "SELECT c.cluster_label, c.overall_score, c.created_at, "
        "c.coordination_score, c.amplification_score, c.infrastructure_score, c.anomaly_score, "
        "COUNT(ce.rowid) AS n_ev, COUNT(DISTINCT ce.author) AS n_au "
        "FROM clusters c LEFT JOIN cluster_events ce ON ce.cluster_id=c.id "
        "WHERE c.tema_id=? GROUP BY c.id ORDER BY c.overall_score DESC",
        (TEMA,),
    )]
    bandas = {b: 0 for b in BAND_ORDER}
    bandas_signal = {b: 0 for b in BAND_ORDER}
    for r in cl:
        b = banda(r["overall_score"] or 0)
        bandas[b] = bandas.get(b, 0) + 1
        if int(r["n_au"] or 0) >= 3:
            bandas_signal[b] = bandas_signal.get(b, 0) + 1
    tie59_all = sum(1 for r in cl if 58.9 <= float(r["overall_score"] or 0) <= 59.1)
    tie59_signal = sum(1 for r in cl
                       if int(r["n_au"] or 0) >= 3
                       and 58.9 <= float(r["overall_score"] or 0) <= 59.1)
    n_au_cl = _mt.cuentas_en_clusters(conn, TEMA)
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
    weekly = [{"week": r[0], "eventos": r[1]} for r in conn.execute(
        "SELECT strftime('%Y-W%W', e.timestamp, 'unixepoch') w, COUNT(*) "
        "FROM events e JOIN event_temas et ON et.event_id=e.id "
        "WHERE et.tema_id=? AND e.timestamp>=strftime('%s', ?) GROUP BY w ORDER BY w",
        (TEMA, (hoy - timedelta(days=56)).isoformat()))]
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
            "coord": round(float(r["coordination_score"] or 0), 1),
            "amp": round(float(r["amplification_score"] or 0), 1),
            "infra": round(float(r["infrastructure_score"] or 0), 1),
            "anom": round(float(r["anomaly_score"] or 0), 1),
        })
    high = bandas.get("HIGH", 0) + bandas.get("CRITICAL", 0)
    base = base_comparacion(sum(1 for r in cl if int(r["n_au"] or 0) >= 3), high)
    return {
        "eventos": n_ev or 0,
        "cuentas": n_aut or 0,
        "cuentas_cluster": n_au_cl,
        "base": base,
        "desde": int(t0) if t0 else None,
        "hasta": int(t1) if t1 else None,
        "clusters": len(cl),
        "signal_clusters": sum(1 for r in cl if int(r["n_au"] or 0) >= 3),
        "small_clusters": sum(1 for r in cl if int(r["n_au"] or 0) < 3),
        "bandas": bandas,
        "bandas_signal": bandas_signal,
        "tie59_all": tie59_all,
        "tie59_signal": tie59_signal,
        "max_score": round(max((r["overall_score"] or 0 for r in cl), default=0), 1),
        "top_clusters": top_clusters[:16],
        "top_signal": [c for c in top_clusters if c["cuentas"] >= 3],
        "daily": daily,
        "weekly": weekly,
        "fuentes": fuentes,
        "persistencia": persistencia,
        "top_dominios": [{"dominio": d, "eventos": c, "tipo": tipo_dominio(d)} for d, c in top_doms],
    }


def svg_timeline(epis: list, lang: str = "es") -> str:
    if not epis:
        return "<p class='meta'>Sin episodios.</p>"
    eps = sorted(epis, key=lambda e: (fecha(e.get("fecha")), str(e.get("pais"))))
    W, H = 1040, 390
    x0, x1, y = 74, 966, 190
    step = (x1 - x0) / max(1, len(eps) - 1)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="tlt tl" class="chart">',
           '<title id="tlt">Cronología de los episodios curados</title>',
           '<desc id="tl">Episodios de la ola, ordenados de 2025 a 2026.</desc>',
           f'<defs><linearGradient id="tg" gradientUnits="userSpaceOnUse" x1="{x0}" y1="{y}" x2="{x1}" y2="{y}"><stop offset="0" stop-color="#38bdf8"/><stop offset="1" stop-color="#f97316"/></linearGradient></defs>',
           f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="url(#tg)" stroke-width="4" stroke-linecap="round"/>']
    for i, e in enumerate(eps):
        x = x0 + i * step
        up = i % 2 == 0
        col = "#f97316" if i == len(eps) - 1 else "#0ea5e9"
        if lang == "en":
            label = f"{CIUDAD_EN.get(str(e.get('ciudad')), e.get('ciudad'))} · {PAIS_EN.get(str(e.get('pais')), e.get('pais'))}"
            lines = wrap(e.get("en", {}).get("nombre") or e.get("nombre"), 23)
        else:
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
    out.append(f'<text x="{x0}" y="374" class="tl-note">{"Editorial sequence of curated episodes · not a time scale" if lang == "en" else "Secuencia editorial de los episodios curados · no es una escala temporal"}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_bands(bands: dict, lang: str = "es") -> str:
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
    out.append(f'<text x="{cx}" y="{cy+18}" text-anchor="middle" class="donut-lab">{"clusters" if lang == "en" else "clústeres"}</text>')
    yy = 42
    for b in BAND_ORDER:
        c = bands.get(b, 0) or 0
        out.append(f'<rect x="252" y="{yy-10}" width="10" height="10" rx="2" fill="{BAND_COL[b]}"/>')
        out.append(f'<text x="270" y="{yy}" class="legend">{esc((BAND_EN if lang == "en" else BAND_ES).get(b,b))}</text>')
        out.append(f'<text x="458" y="{yy}" text-anchor="end" class="legend-n">{c}</text>')
        yy += 35
    out.append("</svg>")
    return "".join(out)


def svg_scatter(clusters: list, lang: str = "es") -> str:
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
    out.append(f'<text x="{W-R-8}" y="{y60-8:.1f}" text-anchor="end" class="axis-hot">{"high band ≥60" if lang == "en" else "banda alta ≥60"}</text>')
    for xv in range(0, xmax + 1, max(1, xmax // 5)):
        x = L + pw * xv / xmax
        out.append(f'<text x="{x:.1f}" y="{H-B+22}" text-anchor="middle" class="axis">{xv}</text>')
    out.append(f'<text x="{L+pw/2}" y="{H-16}" text-anchor="middle" class="axis-title">{"accounts in cluster" if lang == "en" else "cuentas en el clúster"}</text>')
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
        out.append(f'<text x="{x+12:.1f}" y="{y-10:.1f}" class="point-lab">{"max" if lang == "en" else "máx"} {c["score"]:.0f} · {c["cuentas"]} {"accounts" if lang == "en" else "cuentas"}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_daily(daily: list, epis: list, lang: str = "es") -> str:
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
        label = f"{dm(d)} · {len(es)} {'episode' if lang == 'en' else 'episodio'}" + ("" if lang == "en" or len(es) == 1 else "s")
        anchor = "end" if x > W - 140 else ("start" if x < L + 100 else "middle")
        tx = x - 4 if anchor == "end" else (x + 4 if anchor == "start" else x)
        out.append(f'<line x1="{x:.1f}" y1="{T}" x2="{x:.1f}" y2="{T+ph}" stroke="#0ea5e9" stroke-width="1.5" stroke-dasharray="4 5"/>')
        out.append(f'<text x="{tx:.1f}" y="{T-7}" text-anchor="{anchor}" class="axis-mark">{esc(label)}</text>')
    out.append(f'<text x="{L}" y="{H-8}" class="axis-title">{"events/day · marks = curated episodes in window" if lang == "en" else "eventos etiquetados por día · marcas = episodios curados en la ventana"}</text>')
    out.append("</svg>")
    return "".join(out)



def svg_weeks(weeks: list, lang: str = "es") -> str:
    """Barras semanales; contexto de captura, no tendencia del fenómeno."""
    if not weeks:
        return "<p class='meta'>Sin semanas.</p>"
    W, H = 980, 250
    L, R, T, B = 62, 24, 26, 48
    pw, ph = W - L - R, H - T - B
    vmax = max([1] + [w["eventos"] for w in weeks])
    bw = pw / max(1, len(weeks))
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Eventos por semana; contexto de captura" class="chart">']
    for yv in (0, vmax // 2, vmax):
        y = T + ph * (1 - yv / vmax)
        out.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W-R}" y2="{y:.1f}" stroke="#e2e8f0"/>')
        out.append(f'<text x="{L-8}" y="{y+4:.1f}" text-anchor="end" class="axis">{yv}</text>')
    for i, w in enumerate(weeks):
        x = L + i * bw + bw * 0.18
        hh = max(2, ph * w["eventos"] / vmax)
        y = T + ph - hh
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw*0.64:.1f}" height="{hh:.1f}" rx="5" fill="#38bdf8" fill-opacity=".8"><title>{w["week"]}: {w["eventos"]}</title></rect>')
        out.append(f'<text x="{x+bw*0.32:.1f}" y="{H-B+18}" text-anchor="middle" class="axis">{w["week"].split("-")[-1]}</text>')
    out.append(f'<text x="{L}" y="{H-8}" class="axis-title">{"events/week · capture context; not a baseline of the phenomenon" if lang == "en" else "eventos por semana · captura; no es una línea base del fenómeno"}</text>')
    out.append("</svg>")
    return "".join(out)

def svg_domains(doms: list, lang: str = "es") -> str:
    if not doms:
        return "<p class='meta'>Sin dominios.</p>"
    plot = [d for d in doms if d.get("tipo") != "agregador"][:8] or doms[:8]
    W, H = 900, 285
    x0, x1, y0, row = 218, 872, 38, 30
    vmax = max((d["eventos"] for d in plot), default=1)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Dominios con más eventos" class="chart">']
    for i, d in enumerate(plot):
        y = y0 + i * row
        w = max(3, (x1 - x0) * d["eventos"] / vmax)
        tt = {"medio": "media", "agregador": "aggregator", "plataforma": "platform", "otro": "other"}.get(d.get("tipo"), d.get("tipo", "other")) if lang == "en" else d.get("tipo", "otro")
        out.append(f'<text x="{x0-10}" y="{y+16}" text-anchor="end" class="dom-lab">{esc(d["dominio"][:25])} · {esc(tt)}</text>')
        out.append(f'<rect x="{x0}" y="{y+4}" width="{x1-x0}" height="17" rx="8" fill="#f1f5f9"/>')
        out.append(f'<rect x="{x0}" y="{y+4}" width="{w:.1f}" height="17" rx="8" fill="#0ea5e9"><title>{esc(d["dominio"])}: {d["eventos"]}</title></rect>')
        out.append(f'<text x="{x0+w+8:.1f}" y="{y+17}" class="dom-num">{n(d["eventos"])}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_mechanism(lang: str = "es") -> str:
    W, H = 1000, 300
    labels = [
        ("1", "Malestar", ["vivienda, escuela,", "coste de vida, empleo"]),
        ("2", "Detonante", ["un caso concreto", "que cabe en 30 s"]),
        ("3", "Plataforma", ["TikTok / Instagram", "+ mensajería cerrada"]),
        ("4", "Símbolo", ["blocus, «como en", "Francia», One Piece"]),
        ("5", "Respuesta", ["detenciones, límites,", "ley y orden"]),
    ] if lang != "en" else [
        ("1", "Grievance", ["housing, schools,", "cost of living, jobs"]),
        ("2", "Trigger", ["one concrete case", "that fits in 30 s"]),
        ("3", "Platform", ["TikTok / Instagram", "+ closed messaging"]),
        ("4", "Symbol", ["blocus, 'like in", "France', One Piece"]),
        ("5", "Response", ["arrests, limits,", "law and order"]),
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
    out.append(f'<text x="{W/2}" y="{H-10}" text-anchor="middle" class="mech-note">{"The response can become a new trigger · analytical frame, not a causal sequence" if lang == "en" else "La respuesta puede convertirse en un nuevo detonante · marco analítico, no secuencia causal"}</text>')
    out.append("</svg>")
    return "".join(out)


JS_FILTER = """
<script>
(function(){
  const cards = Array.from(document.querySelectorAll('.episode'));
  const pais = document.getElementById('f-pais');
  const tipo = document.getElementById('f-tipo');
  const count = document.getElementById('f-count');
  function apply(){
    let n=0;
    cards.forEach(c=>{
      const ok = (!pais.value || c.dataset.pais===pais.value) && (!tipo.value || c.dataset.tipo===tipo.value);
      c.hidden = !ok; if(ok) n++;
    });
    if(count) count.textContent = n + ' de ' + cards.length + ' episodios';
  }
  if(pais&&tipo){ pais.addEventListener('change',apply); tipo.addEventListener('change',apply); apply(); }
})();
</script>
"""

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
.conclusion{background:#0b1220;color:#e2e8f0;border-radius:16px;padding:16px 20px;margin:16px 0;line-height:1.6}
.conclusion b{color:#fdba74}
.limits{background:#fff;border:1px solid var(--line);border-radius:16px;padding:16px 20px;margin:16px 0}
.limits h2{margin:0 0 6px;font-size:1.1rem}
.limits li{margin:3px 0}
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
.filters{display:flex;flex-wrap:wrap;gap:12px;align-items:center;background:#fff;border:1px solid var(--line);border-radius:14px;padding:12px 15px;margin:12px 0}.filters label{font-size:.8rem;color:#475569;font-weight:700}.filters select{margin-left:6px;padding:5px 7px;border:1px solid #cbd5e1;border-radius:7px;background:#fff;color:#0f172a;font:inherit}.episode{background:#fff;border:1px solid var(--line);border-left:5px solid var(--orange);border-radius:14px;padding:17px;margin:12px 0;box-shadow:0 8px 18px #0f172a06}
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


def _verif(e: dict, lang: str = "es") -> dict:
    if lang == "en":
        v = (e.get("en") or {}).get("verificacion")
        if isinstance(v, dict):
            return v
    v = e.get("verificacion")
    return v if isinstance(v, dict) else {}


def _verif_summary(epis: list, lang: str = "es") -> str:
    c = Counter(str(_verif(e, lang).get("estado") or "sin_auditar") for e in epis)
    if lang == "en":
        return (f"Source audit: {c.get('oficial', 0)}/{len(epis)} official, {c.get('agencia', 0)}/{len(epis)} agency, "
                f"{c.get('secundaria', 0)}/{len(epis)} secondary, 0/{len(epis)} primary.")
    return (f"Auditoría de fuentes: {c.get('oficial', 0)}/{len(epis)} oficial, {c.get('agencia', 0)}/{len(epis)} agencia, "
            f"{c.get('secundaria', 0)}/{len(epis)} secundaria, 0/{len(epis)} primaria.")


SHARE_JS = """<script>
function fimiShareMin(btn){
  var u = new URL(location.href);
  u.searchParams.set("utm_source","compartir");
  u.searchParams.set("utm_medium","web-share");
  var h = document.querySelector("h1");
  var data = {title: document.title, text: h ? h.textContent : document.title, url: u.toString()};
  if (navigator.share) { navigator.share(data).catch(function(){}); return; }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(data.url).then(function(){
      var t=btn.textContent; btn.textContent="Enlace copiado";
      setTimeout(function(){btn.textContent=t;},2000);
    }).catch(function(){ prompt("Copia el enlace", data.url); });
  } else { prompt("Copia el enlace", data.url); }
}
</script>"""

def render(epis: list, s: dict, ahora: str, conv: dict | None = None) -> str:
    eps_html = []
    for i, e in enumerate(sorted(epis, key=lambda x: (fecha(x.get("fecha")), str(x.get("pais")))), 1):
        dem = e.get("demandas") or []
        dem_html = "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in dem) + "</ul>" if dem else "<p class='meta'>Sin pliego público localizado.</p>"
        fuentes = "".join(
            f"<a href='{esc(u)}' target='_blank' rel='noopener noreferrer'>"
            f"{esc(urllib.parse.urlparse(u).netloc.replace('www.', ''))}</a> "
            f"<span class='meta'>({esc(nivel_fuente(urllib.parse.urlparse(u).netloc))})</span> "
            for u in (e.get("fuentes") or [])
        )
        refs = e.get("lineage_refs") or []
        if refs:
            map_html = " · ".join(
                f"<a href='https://fimi.viajeinteligencia.com/n/{esc(r)}' target='_blank' rel='noopener noreferrer'>{esc(r.split('@')[0])}</a>"
                for r in refs)
            map_html = "Clúster asociado: " + map_html
        else:
            map_html = "No observado en la ventana del piloto."
        eps_html.append(f"""
        <article class="episode" data-pais="{esc(e.get('pais'))}" data-tipo="{esc(e.get('tipo_detonante') or 'otro')}">
          <span class="num">{i:02d}</span>
          <div class="meta">{dmy(e.get('fecha'))} · {esc(e.get('pais'))} · {esc(e.get('ciudad'))}</div>
          <h3>{esc(e.get('nombre'))}</h3>
          <p class="meta"><b>Señal del radar:</b> {map_html}</p>
          <p class="meta"><b>Estado:</b> {esc(e.get('estado'))}</p>
          <p><b>Detonante:</b> {esc(e.get('detonante'))}</p>
          <p><b>Quién convoca:</b> {esc(e.get('convocantes'))}</p>
          <p><b>Demandas declaradas:</b></p>{dem_html}
          <p><b>Llamada / acción:</b> {esc(e.get('llamada'))}</p>
          <p class="meta"><b>Alcance:</b> {esc(e.get('alcance'))}</p>
          <p class="meta"><b>Límite:</b> {esc(e.get('nota'))}</p>
          <p class="meta"><b>Fuente primaria:</b> {esc(e.get('fuente_primaria') or 'No localizada')}</p>
          <p class="meta"><b>Verificación:</b> {esc(_verif(e).get('estado', 'sin auditar'))} — {esc(_verif(e).get('nota', ''))}</p>
          <p class="meta">Fuentes consultadas: {fuentes or '—'}</p>
        </article>""")

    banda_rows = "".join(
        f"<tr><td>{esc(BAND_ES.get(b, b))}</td><td>{n(s['bandas'].get(b, 0))}</td></tr>"
        for b in BAND_ORDER if s["bandas"].get(b, 0)
    ) or "<tr><td colspan='2'>Sin clusters todavía.</td></tr>"
    top = "".join(
        f"<tr><td>{esc(c['label'])}</td><td>{c['score']:.1f}</td><td>{esc(c['banda_es'])}{' <span class=meta>· evidencia baja</span>' if c['banda'] == 'HIGH' and (c['cuentas'] < 8 or c['eventos'] < 30) else (' <span class=meta>· muestra pequeña</span>' if c['cuentas'] < 8 or c['eventos'] < 30 else '')}</td><td>{n(c['cuentas'])}</td><td>{n(c['eventos'])}</td><td>{c.get('coord',0):.0f}</td><td>{c.get('amp',0):.0f}</td><td>{c.get('infra',0):.0f}</td><td>{c.get('anom',0):.0f}</td></tr>"
        for c in (s.get("top_signal") or [c for c in s["top_clusters"] if c["cuentas"] >= 3])[:8]
    ) or "<tr><td colspan='9'>Sin clusters con señal.</td></tr>"
    doms = "".join(
        f"<tr><td>{esc(d['dominio'])}</td><td>{esc(d.get('tipo','otro'))}</td><td>{n(d['eventos'])}</td></tr>"
        for d in s["top_dominios"]
    ) or "<tr><td colspan='3'>Sin dominios todavía.</td></tr>"
    high = s["bandas"].get("HIGH", 0) + s["bandas"].get("CRITICAL", 0)
    top_src = " · ".join(f"{f['fuente']} {f['pct']}%" for f in s.get("fuentes", [])[:2])
    pers = s.get("persistencia", {})
    peak = max(s.get("daily", []), key=lambda x: x.get("eventos", 0), default=None)
    peak_txt = dmy(peak["fecha"]) if peak else "—"
    tie59 = int(s.get("tie59_signal") or 0)
    tie59_all = int(s.get("tie59_all") or 0)
    hi_accounts = (s.get("top_signal") or s.get("top_clusters") or [{}])[0].get("cuentas", 0)
    hi_events = (s.get("top_signal") or s.get("top_clusters") or [{}])[0].get("eventos", 0)
    hi_low = hi_events < 30 or hi_accounts < 8
    _high_cases = [c for c in (s.get("top_signal") or s.get("top_clusters") or [])
                   if c.get("banda") in ("HIGH", "CRITICAL")]
    high_low_n = sum(1 for c in _high_cases if c.get("cuentas", 0) < 8 or c.get("eventos", 0) < 30)
    cuentas_cluster = int(s.get("cuentas_cluster") or 0)
    bandas_signal = s.get("bandas_signal") or {}
    small_bands = {b: max(0, int(s["bandas"].get(b, 0)) - int(bandas_signal.get(b, 0)))
                   for b in BAND_ORDER}
    _btxt = lambda d: ", ".join(f"{n(v)} {BAND_ES.get(b, b).lower()}"
                                for b, v in ((b, int(d.get(b, 0))) for b in BAND_ORDER) if v)
    bandas_all_txt = _btxt(s["bandas"])
    bandas_sig_txt = _btxt(bandas_signal)
    bandas_small_txt = _btxt(small_bands)
    agg = next((d for d in s.get("top_dominios", []) if d.get("tipo") == "agregador"), None)
    agg_txt = (f"Google News ({n(agg['eventos'])}) se excluye del gráfico por ser agregador: es eco de prensa, no una fuente independiente."
               if agg else "Los agregadores se excluyen del gráfico: son eco de prensa, no fuentes independientes.")
    conv = conv or {}
    _conv_rows = "".join(
        f"<tr><td>{dmy(x.get('fecha_evento'))}</td><td>{esc(x.get('ciudad'))}</td>"
        f"<td>{esc(x.get('convocante'))}</td>"
        f"<td>{esc(CONV_TIPO_ES.get(x.get('convocante_tipo'), x.get('convocante_tipo') or '—'))}</td>"
        f"<td>{esc(CONV_ADSC_ES.get(x.get('adscripcion'), x.get('adscripcion') or '—'))}</td>"
        f"<td>{esc(' · '.join(CONV_MARCO_ES.get(m, m) for m in (x.get('marco') or [])) or '—')}</td>"
        f"<td>{esc(x.get('estado'))}</td><td>{esc(x.get('evidencia') or '—')}</td>"
        f"<td><a href='{esc(x.get('url_publica'))}' target='_blank' rel='noopener noreferrer'>{esc(x.get('fuente'))}</a></td></tr>"
        for x in (conv.get("convocatorias") or []))
    conv_html = (f"<section><h2>Convocatorias públicas</h2>"
                 f"<p class='meta'>Registro curado de llamadas públicas. No se accede a grupos privados, DMs ni cuentas personales. "
                 f"Estado según la fuente, no confirmación del hecho. Actualizado: {esc(conv.get('actualizado') or '—')}.</p>"
                 f"<div style='overflow:auto'><table><thead><tr><th>Fecha</th><th>Ciudad</th><th>Convoca</th><th>Tipo</th>"
                 f"<th>Adscripción</th><th>Marco</th><th>Estado</th><th>Evidencia</th><th>Fuente</th></tr></thead><tbody>{_conv_rows or '<tr><td colspan=9>Sin convocatorias registradas.</td></tr>'}</tbody></table></div>"
                 f"<p class='meta'>La adscripción y el marco son del convocante, no de todos los participantes; no se usa un eje izquierda-derecha.</p>"
                 f"<p class='meta'><a href='/datos/convocatorias.json'>Datos abiertos de convocatorias (JSON)</a></p></section>")
    conv = conv or {}
    _conv_rows_en = "".join(
        f"<tr><td>{dmy(x.get('fecha_evento'))}</td><td>{esc(x.get('ciudad'))}</td>"
        f"<td>{esc(x.get('convocante'))}</td>"
        f"<td>{esc(CONV_TIPO_EN.get(x.get('convocante_tipo'), x.get('convocante_tipo') or '—'))}</td>"
        f"<td>{esc(CONV_ADSC_EN.get(x.get('adscripcion'), x.get('adscripcion') or '—'))}</td>"
        f"<td>{esc(' · '.join(CONV_MARCO_EN.get(m, m) for m in (x.get('marco') or [])) or '—')}</td>"
        f"<td>{esc(CONV_ESTADO_EN.get(x.get('estado'), x.get('estado')))}</td><td>{esc(x.get('evidencia') or '—')}</td>"
        f"<td><a href='{esc(x.get('url_publica'))}' target='_blank' rel='noopener noreferrer'>{esc(x.get('fuente'))}</a></td></tr>"
        for x in (conv.get("convocatorias") or []))
    conv_html_en = (f"<section><h2>Public calls</h2>"
                    f"<p class='meta'>Curated registry of public calls. No private groups, DMs or personal accounts. "
                    f"Status follows the source, not confirmation of the event. Updated: {esc(conv.get('actualizado') or '—')}.</p>"
                    f"<div style='overflow:auto'><table><thead><tr><th>Date</th><th>City</th><th>Caller</th><th>Type</th>"
                    f"<th>Affiliation</th><th>Frame</th><th>Status</th><th>Evidence</th><th>Source</th></tr></thead><tbody>{_conv_rows_en or '<tr><td colspan=9>No calls registered.</td></tr>'}</tbody></table></div>"
                    f"<p class='meta'>Affiliation and frame describe the caller, not all participants; no left-right axis is used.</p>"
                    f"<p class='meta'><a href='/datos/convocatorias.json'>Open call data (JSON)</a></p></section>")
    _ext = s.get("extension") or {}
    _ext_rows = "".join(
        f"<tr><td>{esc(r.get('simbolo'))}</td><td>{esc(r.get('tipo'))}</td>"
        f"<td>{esc(', '.join(r.get('paises_72h') or []) or '—')}</td>"
        f"<td>{n(r.get('eventos', 0))}</td><td>{n(r.get('cuentas', 0))}</td>"
        f"<td>{esc(r.get('estado', '—'))}</td></tr>"
        for r in _ext.get("filas", []) if r.get("tipo") != "término genérico")
    ext_html = (f"<section><h2>Extensión entre países (exploratoria)</h2>"
                f"<p class='meta'>{esc(_ext.get('nota', ''))} Ventana: {n(_ext.get('ventana_h', 72))} h. Se omiten términos genéricos.</p>"
                f"<div style='overflow:auto'><table><thead><tr><th>Símbolo</th><th>Tipo</th>"
                f"<th>Países en 72 h</th><th>Eventos</th><th>Cuentas</th><th>Estado</th></tr></thead>"
                f"<tbody>{_ext_rows}</tbody></table></div>"
                f"<p class='meta'>«Extensión observada» = ≥2 países y ≥10 eventos; no implica coordinación. "
                f"Los términos genéricos se muestran para contexto, no como símbolos de campaña.</p>"
                f"<p class='meta'><b>Blocus</b> es también una palabra francesa («bloqueo»): la coincidencia en Francia e Italia puede ser léxica, no la misma consigna. No se interpreta como extensión coordinada.</p></section>")
    takeaways = [
        f"<b>{n(s.get('signal_clusters', 0))} de {n(s['clusters'])}</b> clústeres tienen señal (≥3 cuentas); {n(s.get('small_clusters', 0))} son grupos pequeños.",
        f"<b>{n(high)}</b> en banda alta y <b>0</b> sincronías entre cuentas distintas. "
        f"<b>{n(high_low_n)} de {n(high)}</b> tienen evidencia baja; el de mayor score "
        f"({n(hi_events)} eventos, {n(hi_accounts)} cuentas) es un candidato, no una conclusión.",
        f"<b>{n(s.get('cuentas', 0))}</b> cuentas distintas en el tema; <b>{n(cuentas_cluster)}</b> dentro de clústeres.",
        f"Bandas: <b>{esc(bandas_sig_txt)}</b> sobre {n(s.get('signal_clusters', 0))} con señal. "
        f"Los {n(s.get('small_clusters', 0))} grupos pequeños aportan <b>{esc(bandas_small_txt)}</b>; total, {esc(bandas_all_txt)}.",
        f"La conversación viene sobre todo de <b>{esc(top_src or '—')}</b>.",
        f"Persistencia: hasta <b>{n(pers.get('max_ciclos', 0))} ciclos de pipeline</b> por linaje; "
        f"hasta cinco pueden caer en menos de 24 h. No equivale a una línea base de ocho semanas.",
    ]
    _base = s.get("base") or {}
    if _base:
        takeaways.append(
            f"<b>Base de comparación:</b> {n(_base.get('high', 0))} de {n(_base.get('clusters', 0))} "
            f"clusters en banda alta en otros {n(_base.get('temas', 0))} temas "
            f"({_base.get('rate', 0):.1f} %); este tema, {n(high)} de {n(s.get('signal_clusters', 0))} "
            f"({_base.get('tema_rate', 0):.1f} %). Referencia operativa, no control neutral. "
            f"Diferencia descriptiva, no tendencia: {n(high)} clústeres y {n(high_low_n)} de {n(high)} con evidencia baja."
        )

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Protestas juveniles: eco en plataformas capturadas (piloto)</title>
<meta name="robots" content="noindex,follow">
<meta name="description" content="Piloto de amplificación: qué se observa en Bluesky y Google News sobre las protestas juveniles, qué es contexto y qué no puede concluirse.">
<link rel="canonical" href="https://fimi.viajeinteligencia.com/casos/protestas/">
<meta property="og:type" content="article">
<meta property="og:title" content="Protestas juveniles: eco en plataformas capturadas">
<meta property="og:description" content="Piloto de amplificación: eco en Bluesky y Google News, contexto curado y límites. Sin atribución de actor.">
<meta property="og:url" content="https://fimi.viajeinteligencia.com/casos/protestas/">
<meta property="og:image" content="https://fimi.viajeinteligencia.com/informes/visual/og-protestas_juveniles.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Protestas juveniles: eco en plataformas capturadas">
<meta name="twitter:card" content="summary_large_image">
<link rel="alternate" hreflang="es" href="https://fimi.viajeinteligencia.com/casos/protestas/">
<link rel="alternate" hreflang="en" href="https://fimi.viajeinteligencia.com/casos/protestas/en.html">
<style>{CSS}</style></head><body>
<header><div class="wrap"><a class="brand" href="/">📡 Observatorio <span>/ protestas juveniles</span></a></div></header>
<main class="wrap">
<section class="hero">
  <p class="kicker">Piloto de amplificación</p>
  <h1>Protestas juveniles: eco en plataformas capturadas</h1>
  <p class="lead">Del malestar a la calle y de la calle al feed. Qué está documentado, qué se repite y qué sigue siendo atribución. El radar mide amplificación y extensión; no identifica autores ni intención.</p>
  <p><span class="badge">Piloto</span><span class="badge">Sin atribución</span><span class="badge">Fuentes enlazadas</span><a class="badge" href="en.html">English</a></p>
  <div class="hero-stats">
    <div class="hero-stat"><b>{n(s['eventos'])}</b><span>eventos etiquetados</span></div>
    <div class="hero-stat"><b>{n(s['cuentas'])} / {n(cuentas_cluster)}</b><span>cuentas tema / clústeres</span></div>
    <div class="hero-stat"><b>{n(s['clusters'])}</b><span>clústeres</span></div>
    <div class="hero-stat"><b>{n(high)}</b><span>en banda alta</span></div>
  </div>
  <p><button type="button" onclick="fimiShareMin(this)" style="border:1px solid #475569;background:#fff;color:#0b1220;border-radius:999px;padding:8px 14px;font:inherit;cursor:pointer">Compartir</button></p>
</section>

<div class="note"><b>Cómo leer esta página.</b> Los KPIs y los clústeres salen del etiquetado temático del piloto. Las demandas y llamadas son una selección curada de fuentes públicas, no una extracción automática. Una <span class="term" title="Banda de score que indica amplificación anómala; no confirma coordinación ni autoría.">banda alta</span> significa <b>amplificación anómala</b>, no coordinación confirmada. Actualizado: {esc(ahora)} UTC · última observación: {dt(s['hasta'])}.</div>

<div class="takeaways"><h2>Lo esencial</h2><ul>{''.join(f'<li>{x}</li>' for x in takeaways)}</ul></div>

<div class="conclusion"><b>Lectura de hoy.</b> El pico de actividad capturada es del <b>{peak_txt}</b>, posterior a los disturbios del 24-oct. <b>No hay sincronías entre cuentas distintas</b>. {("El único clúster en banda alta es" if high == 1 else f"De los {n(high)} clústeres en banda alta, el de mayor score es")} un <b>{("candidato de evidencia baja" if hi_low else "clúster de evidencia suficiente")}</b> ({n(hi_events)} eventos, {n(hi_accounts)} cuentas): su H2 mide estructura de URLs compartidas, no autoría, y la explicación automática queda <b>no concluyente</b>. No se lee como coordinación confirmada. La cobertura es Bluesky + Google News, no la convocatoria original. El corte en 60 es convencional: <b>{tie59} de los {n(s.get('signal_clusters', 0))} con señal empatan en 59</b> ({tie59_all} de {n(s['clusters'])}; el de 2 cuentas queda fuera de la tabla). <b>No se puede concluir</b> que la ola esté orquestada.</div>

<details class="glossary"><summary>Qué significan «banda alta», «clúster», «score» y «persistencia»</summary>
<p><b>Clúster:</b> grupo de eventos que el sistema conecta por contenido, enlaces, tiempo o cuentas. No es una prueba de coordinación. <b>Score:</b> combinación de coordinación, similitud, amplificación, infraestructura y anomalía (0–100); no es una probabilidad. <b>Banda alta:</b> score ≥60; indica amplificación anómala. <b>Amplificación anómala:</b> patrón de repetición o extensión fuera de lo esperado; no identifica autor. <b>Persistencia:</b> número de ciclos en los que sobrevive un linaje; con pocos ciclos no hay vida media fiable. <a href="/glosario.html#casa">Glosario completo</a>.</p>
</details>

<div class="limits"><h2>Qué no ve este radar</h2><ul>
<li><b>La convocatoria original.</b> TikTok, Instagram, WhatsApp y Discord no se capturan. Telegram solo se lee en canales públicos, no en grupos ni mensajes privados; el radar no observa dónde se organiza la protesta.</li>
<li><b>La calle.</b> No hay asistentes, detenciones ni heridos propios: las cifras de los episodios son citas provisionales, no medición del radar.</li>
<li><b>Fuentes primarias.</b> No se localizó fuente primaria en {len(epis)} de {len(epis)} episodios. Las cifras de víctimas y detenidos proceden de fuentes secundarias y no están verificadas por el radar; se muestran para contexto, no como dato propio.</li>
<li><b>Representatividad.</b> Bluesky y Google News dominan la captura; no es una muestra representativa de la conversación juvenil.</li>
<li><b>Personas.</b> No se identifican menores ni cuentas individuales. Los datos de detenciones son agregados y provisionales.</li>
<li><b>Línea base.</b> El contexto de ocho semanas es histórico de captura del sistema, no una línea base del tema. El piloto acumula hasta diez ciclos de pipeline por linaje; hasta cinco pueden caer en menos de 24 h. «Anómalo» es relativo a esta ventana y un cambio de pesos movería el corte de 60.</li>
</ul></div>

<section>
  <h2>Cronología: de Katmandú a Barcelona</h2>
  <p class="meta">Episodios curados para separar el hecho, la demanda y la llamada; los anteriores al 26/10 son contexto, no corpus del piloto. El orden es editorial; no es una escala temporal.</p>
  <div class="chart-card">{svg_timeline(epis)}</div>
</section>

{conv_html}

{ext_html}

<section>
  <h2>La señal, en tres planos</h2>
  <div class="two two-charts">
    <div class="chart-card"><h3>Reparto por banda</h3><p class="meta">{n(s.get('signal_clusters', 0))} con señal y {n(s.get('small_clusters', 0))} grupos pequeños. Los pequeños aportan {esc(bandas_small_txt)}; no hay banda alta entre ellos.</p>{svg_bands(s['bandas'])}</div>
    <div class="chart-card"><h3>Cuentas frente a score</h3><p class="meta">Cada círculo es un clúster. Tamaño = eventos; color = banda.</p>{svg_scatter(s['top_clusters'])}</div>
  </div>
  <div class="chart-card"><h3>Ritmo de conversación</h3><p class="meta">Eventos etiquetados por día en la ventana del piloto.</p>{svg_daily(s['daily'], epis)}</div>
  <div class="chart-card"><h3>Contexto de captura · 8 semanas + actual</h3><p class="meta">El salto de la semana 42 refleja sobre todo el cambio de cobertura del radar, no un aumento súbito de protestas. Se muestra como contexto, no como línea base.</p>{svg_weeks(s['weekly'])}</div>
</section>

<section>
  <h2>Episodios curados</h2>
  <p class="meta">No todas las protestas tienen un pliego público: cuando no lo hay, se dice. La correspondencia entre un episodio y un clúster es <b>manual y revisable</b>: no confirma el episodio ni se inventa. Fuentes consultadas el 26/10/2026.</p>
  <p class="meta"><b>Criterio de inclusión:</b> episodios con componente juvenil/estudiantil, detonante local identificable y cobertura internacional. Es una selección editorial, no aleatoria ni exhaustiva; el orden no implica continuidad temporal. <b>Nivel de fuente:</b> agencia/oficial &gt; medio &gt; agregador/wiki; las cifras sensibles sin agencia u oficial quedan como provisionales.</p>
  <p class="meta"><b>{_verif_summary(epis)}</b></p>
  <div class="filters">
    <label>Región <select id="f-pais"><option value="">Todas</option>{''.join(f'<option value="{esc(x)}">{esc(x)}</option>' for x in sorted({str(e.get('pais')) for e in epis}))}</select></label>
    <label>Tipo de detonante <select id="f-tipo"><option value="">Todos</option>{''.join(f'<option value="{v}">{esc(k)}</option>' for v,k in [('redes','Redes / plataformas'),('educacion','Educación'),('coste','Coste de vida'),('corrupcion','Corrupción')])}</select></label>
    <span id="f-count" class="meta"></span>
  </div>
  {''.join(eps_html)}
</section>

<section>
  <h2>El mecanismo: cinco piezas</h2>
  <div class="chart-card">{svg_mechanism()}</div>
</section>

<section>
  <h2>Quién amplifica</h2>
  <div class="chart-card"><h3>Dominios con más eventos</h3><p class="meta">Unidad: eventos (no clústeres); el informe visual usa clústeres. No implica coordinación ni participación del medio. <b>{agg_txt}</b></p>{svg_domains(s["top_dominios"])}<div style="overflow:auto;margin-top:10px"><table><thead><tr><th>Dominio</th><th>Tipo</th><th>Eventos</th></tr></thead><tbody>{doms}</tbody></table></div></div>
    <div class="chart-card"><h3>Clústeres con más señal</h3>
      <div style="overflow:auto"><table><thead><tr><th>Clúster</th><th>Score</th><th>Banda</th><th>Cuentas</th><th>Eventos</th><th>Coord.</th><th>Amp.</th><th>Infra.</th><th>Anom.</th></tr></thead><tbody>{top}</tbody></table></div>
      <p class="meta" style="margin-top:10px">Solo clústeres con señal (≥3 cuentas). Cifras calculadas desde la base del radar; no son hechos verificados.</p>
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

<p><a href="/datos/protestas.json">Datos abiertos (JSON)</a> · <a href="/datos/protestas.schema.json">Esquema JSON</a> · <a href="/informes/visual/protestas_juveniles.html">Informe visual</a> · <a href="/">Volver al radar</a></p>
<footer>Elaborado con asistencia de IA y revisión humana. Fuentes enlazadas en el texto. — @pruebapublica<br>
Piloto de amplificación · no indexado hasta revisión · {esc(ahora)} UTC</footer>
</main>
{SHARE_JS}
{JS_FILTER}
</body></html>"""


def _en(e, key, fallback=""):
    v = (e.get("en") or {}).get(key)
    return v if v not in (None, "") else (e.get(key) or fallback)


def render_en(epis: list, s: dict, ahora: str, conv: dict | None = None) -> str:
    rows = []
    for e in sorted(epis, key=lambda x: (fecha(x.get("fecha")), str(x.get("pais")))):
        dem = _en(e, "demandas", []) or []
        dem_txt = "<br>".join(f"• {esc(x)}" for x in dem) or "<span class='meta'>No public list located.</span>"
        refs = e.get("lineage_refs") or []
        radar = " · ".join(
            f"<a href='https://fimi.viajeinteligencia.com/n/{esc(r)}' target='_blank' rel='noopener noreferrer'>{esc(r.split('@')[0])}</a>"
            for r in refs) or "<span class='meta'>Not observed in this window</span>"
        src = "".join(
            f"<a href='{esc(u)}' target='_blank' rel='noopener noreferrer'>{esc(urllib.parse.urlparse(u).netloc.replace('www.', ''))}</a> "
            f"<span class='meta'>({esc(nivel_fuente(urllib.parse.urlparse(u).netloc))})</span> "
            for u in (e.get("fuentes") or [])
        )
        place = f"{CIUDAD_EN.get(str(e.get('ciudad')), e.get('ciudad'))}, {PAIS_EN.get(str(e.get('pais')), e.get('pais'))}"
        rows.append(f"""<tr>
          <td>{dmy(e.get('fecha'))}</td>
          <td>{esc(place)}</td>
          <td>{esc(_en(e, 'nombre'))}<br><span class="meta">{esc(_en(e, 'estado'))}</span></td>
          <td>{esc(_en(e, 'detonante'))}</td>
          <td>{dem_txt}</td>
          <td>{esc(_en(e, 'llamada'))}<br><span class="meta">Radar: {radar} · Sources: {src or '—'} · Verification: {esc(_verif(e, 'en').get('estado', 'not audited'))}</span></td>
        </tr>""")

    high = s["bandas"].get("HIGH", 0) + s["bandas"].get("CRITICAL", 0)
    top_src = " · ".join(f"{f['fuente']} {f['pct']}%" for f in s.get("fuentes", [])[:2])
    peak = max(s.get("daily", []), key=lambda x: x.get("eventos", 0), default=None)
    peak_txt = dmy(peak["fecha"]) if peak else "—"
    pers = s.get("persistencia", {})
    hi_accounts = (s.get("top_signal") or s.get("top_clusters") or [{}])[0].get("cuentas", 0)
    hi_events = (s.get("top_signal") or s.get("top_clusters") or [{}])[0].get("eventos", 0)
    hi_low = hi_events < 30 or hi_accounts < 8
    _high_cases = [c for c in (s.get("top_signal") or s.get("top_clusters") or [])
                   if c.get("banda") in ("HIGH", "CRITICAL")]
    high_low_n = sum(1 for c in _high_cases if c.get("cuentas", 0) < 8 or c.get("eventos", 0) < 30)
    cuentas_cluster = int(s.get("cuentas_cluster") or 0)
    tie59 = int(s.get("tie59_signal") or 0)
    tie59_all = int(s.get("tie59_all") or 0)
    bandas_signal = s.get("bandas_signal") or {}
    small_bands = {b: max(0, int(s["bandas"].get(b, 0)) - int(bandas_signal.get(b, 0)))
                   for b in BAND_ORDER}
    _ben = lambda d: ", ".join(f"{n(v)} {(BAND_EN.get(b, b)).lower()}"
                               for b, v in ((b, int(d.get(b, 0))) for b in BAND_ORDER) if v)
    bandas_all_txt = _ben(s["bandas"])
    bandas_sig_txt = _ben(bandas_signal)
    bandas_small_txt = _ben(small_bands)
    conv = conv or {}
    _conv_rows_en = "".join(
        f"<tr><td>{dmy(x.get('fecha_evento'))}</td><td>{esc(x.get('ciudad'))}</td>"
        f"<td>{esc(x.get('convocante'))}</td>"
        f"<td>{esc(CONV_TIPO_EN.get(x.get('convocante_tipo'), x.get('convocante_tipo') or '—'))}</td>"
        f"<td>{esc(CONV_ADSC_EN.get(x.get('adscripcion'), x.get('adscripcion') or '—'))}</td>"
        f"<td>{esc(' · '.join(CONV_MARCO_EN.get(m, m) for m in (x.get('marco') or [])) or '—')}</td>"
        f"<td>{esc(CONV_ESTADO_EN.get(x.get('estado'), x.get('estado')))}</td><td>{esc(x.get('evidencia') or '—')}</td>"
        f"<td><a href='{esc(x.get('url_publica'))}' target='_blank' rel='noopener noreferrer'>{esc(x.get('fuente'))}</a></td></tr>"
        for x in (conv.get("convocatorias") or []))
    conv_html_en = (f"<section><h2>Public calls</h2>"
                    f"<p class='meta'>Curated registry of public calls. No private groups, DMs or personal accounts. "
                    f"Status follows the source, not confirmation of the event. Updated: {esc(conv.get('actualizado') or '—')}.</p>"
                    f"<div style='overflow:auto'><table><thead><tr><th>Date</th><th>City</th><th>Caller</th><th>Type</th>"
                    f"<th>Affiliation</th><th>Frame</th><th>Status</th><th>Evidence</th><th>Source</th></tr></thead><tbody>{_conv_rows_en or '<tr><td colspan=9>No calls registered.</td></tr>'}</tbody></table></div>"
                    f"<p class='meta'>Affiliation and frame describe the caller, not all participants; no left-right axis is used.</p>"
                    f"<p class='meta'><a href='/datos/convocatorias.json'>Open call data (JSON)</a></p></section>")
    _ext = s.get("extension") or {}
    _ext_rows = "".join(
        f"<tr><td>{esc(r.get('simbolo'))}</td><td>{esc(r.get('tipo'))}</td>"
        f"<td>{esc(', '.join(r.get('paises_72h') or []) or '—')}</td>"
        f"<td>{n(r.get('eventos', 0))}</td><td>{n(r.get('cuentas', 0))}</td>"
        f"<td>{esc(r.get('estado', '—'))}</td></tr>"
        for r in _ext.get("filas", []) if r.get("tipo") != "término genérico")
    ext_html_en = (f"<section><h2>Cross-country extension (exploratory)</h2>"
                   f"<p class='meta'>{esc(_ext.get('nota', ''))} Window: {n(_ext.get('ventana_h', 72))} h. Generic terms are omitted.</p>"
                   f"<div style='overflow:auto'><table><thead><tr><th>Symbol</th><th>Type</th>"
                   f"<th>Countries in 72 h</th><th>Events</th><th>Accounts</th><th>Status</th></tr></thead>"
                   f"<tbody>{_ext_rows}</tbody></table></div>"
                   f"<p class='meta'>“Observed extension” = ≥2 countries and ≥10 events; it does not imply coordination. "
                   f"Generic terms are shown for context, not as campaign symbols.</p></section>")
    _base = s.get("base") or {}
    _base_en = (f"<li><b>Comparison baseline:</b> {n(_base.get('high', 0))} of {n(_base.get('clusters', 0))} "
                f"clusters in the high band across {n(_base.get('temas', 0))} other topics "
                f"({_base.get('rate', 0):.1f} %); this topic, {n(high)} of {n(s.get('signal_clusters', 0))} "
                f"({_base.get('tema_rate', 0):.1f} %). Operational reference, not a neutral control.</li>"
                if _base else "")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Youth protests: amplification in captured platforms (pilot)</title>
<meta name="robots" content="noindex,follow">
<meta name="description" content="What is documented about the youth protest wave, what repeats in the radar, and what cannot be concluded.">
<link rel="canonical" href="https://fimi.viajeinteligencia.com/casos/protestas/en.html">
<meta property="og:type" content="article">
<meta property="og:title" content="Youth protests: amplification in captured platforms">
<meta property="og:description" content="Pilot: echo in Bluesky and Google News, curated context and limits. No actor attribution.">
<meta property="og:url" content="https://fimi.viajeinteligencia.com/casos/protestas/en.html">
<meta property="og:image" content="https://fimi.viajeinteligencia.com/informes/visual/og-protestas_juveniles.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Youth protests: amplification in captured platforms">
<meta name="twitter:card" content="summary_large_image">
<link rel="alternate" hreflang="es" href="https://fimi.viajeinteligencia.com/casos/protestas/">
<link rel="alternate" hreflang="en" href="https://fimi.viajeinteligencia.com/casos/protestas/en.html">
<style>{CSS}</style></head><body>
<header><div class="wrap"><a class="brand" href="/">📡 Observatory <span>/ youth protests</span></a></div></header>
<main class="wrap">
<section class="hero">
  <p class="kicker">Amplification pilot</p>
  <h1>Youth protests: amplification in captured platforms</h1>
  <p class="lead">From grievance to the street and from the street to the feed. What is documented, what is repeated, and what remains attribution. The radar measures amplification and reach; it does not identify authors or intent.</p>
  <p><span class="badge">Pilot</span><span class="badge">No attribution</span><span class="badge">Linked sources</span><a class="badge" href="./">Español</a></p>
  <div class="hero-stats">
    <div class="hero-stat"><b>{n(s['eventos'])}</b><span>tagged events</span></div>
    <div class="hero-stat"><b>{n(s['cuentas'])} / {n(cuentas_cluster)}</b><span>topic / cluster accounts</span></div>
    <div class="hero-stat"><b>{n(s['clusters'])}</b><span>clusters</span></div>
    <div class="hero-stat"><b>{n(high)}</b><span>in high band</span></div>
  </div>
  <p><button type="button" onclick="fimiShareMin(this)" style="border:1px solid #475569;background:#fff;color:#0b1220;border-radius:999px;padding:8px 14px;font:inherit;cursor:pointer">Share</button></p>
</section>

<div class="note"><b>How to read this page.</b> KPIs and clusters come from the pilot's topic tagging. Demands and calls are curated citations, not automatic extraction. A <span class="term" title="A score band that indicates anomalous amplification; it does not confirm coordination or authorship.">high band</span> means <b>anomalous amplification</b>, not confirmed coordination. Updated: {esc(ahora)} UTC · last observation: {dt(s['hasta'])}.</div>

<div class="takeaways"><h2>Key takeaways</h2><ul>
<li><b>{n(s.get('signal_clusters', 0))} of {n(s['clusters'])}</b> clusters have signal (≥3 accounts); {n(s.get('small_clusters', 0))} are small groups.</li>
<li><b>{n(high)}</b> in high band and <b>0</b> cross-account synchronies. <b>{n(high_low_n)} of {n(high)}</b> have low evidence; the highest-scoring one ({n(hi_events)} events, {n(hi_accounts)} accounts) is a candidate, not a conclusion.</li>
<li><b>{n(s.get('cuentas', 0))}</b> distinct topic accounts; <b>{n(cuentas_cluster)}</b> inside clusters.</li>
<li>Bands: <b>{esc(bandas_sig_txt)}</b> across {n(s.get('signal_clusters', 0))} with signal. The {n(s.get('small_clusters', 0))} small groups add <b>{esc(bandas_small_txt)}</b>; total, {esc(bandas_all_txt)}.</li>
<li>Coverage is dominated by <b>{esc(top_src or '—')}</b>.</li>
<li>Persistence: up to <b>{n(pers.get('max_ciclos', 0))} pipeline cycles</b> per lineage; up to five may fall within 24 h. This is not an eight-week baseline.</li>
{_base_en}
</ul></div>

<div class="conclusion"><b>Today's reading.</b> The captured activity peaks on <b>{peak_txt}</b>, after the 24 Oct riots. <b>No cross-account synchronies</b>. {("The only high-band cluster is" if high == 1 else f"Of the {n(high)} high-band clusters, the highest-scoring one is")} a <b>{("low-evidence candidate" if hi_low else "sufficient-evidence cluster")}</b> ({n(hi_events)} events, {n(hi_accounts)} accounts): its H2 measures shared-URL structure, not authorship, and the automatic explanation is <b>inconclusive</b>. It is not confirmed coordination. Coverage is Bluesky + Google News, not the original call. The cut at 60 is conventional: <b>{tie59} of the {n(s.get('signal_clusters', 0))} with signal tie at 59</b> ({tie59_all} of {n(s['clusters'])}; the one with 2 accounts is outside the table). <b>We cannot conclude</b> that the wave is orchestrated.</div>

<details class="glossary"><summary>What do “high band”, “cluster”, “score” and “persistence” mean?</summary>
<p><b>Cluster:</b> a group of events connected by content, links, time or accounts. It is not proof of coordination. <b>Score:</b> a combination of coordination, similarity, amplification, infrastructure and anomaly (0–100); it is not a probability. <b>High band:</b> score ≥60; it indicates anomalous amplification. <b>Persistence:</b> number of cycles a lineage survives; a few cycles are not enough for a half-life.</p>
</details>

<div class="limits"><h2>What this radar does not see</h2><ul>
<li><b>The original call.</b> TikTok, Instagram, WhatsApp and Discord are not captured. Telegram is read only in public channels, not groups or private messages; the radar does not observe where the protest is organised.</li>
<li><b>The street.</b> No own counts of attendees, arrests or injuries: episode figures are provisional quotes, not radar measurements.</li>
<li><b>Primary sources.</b> No primary source was located for 5 of 5 episodes. Victim and arrest figures come from secondary sources and are not verified by the radar; they are shown as context, not as our own data.</li>
<li><b>Representativeness.</b> Bluesky and Google News dominate capture; this is not a representative sample of youth conversation.</li>
<li><b>People.</b> No minors or individual accounts are identified.</li>
<li><b>Baseline.</b> The eight-week context is system capture history, not a topic baseline. The pilot has up to five pipeline cycles in under 24 hours; “anomalous” is relative to this window and weight changes would move the 60 cut.</li>
</ul></div>

<section>
  <h2>Chronology: from Kathmandu to Barcelona</h2>
  <p class="meta">Five curated episodes separate the fact, the demand and the call. The order is editorial, not a time scale.</p>
  <div class="chart-card">{svg_timeline(epis, 'en')}</div>
</section>

{conv_html_en}

{ext_html_en}

<section>
  <h2>The signal, in three views</h2>
  <div class="two two-charts">
    <div class="chart-card"><h3>Clusters by band</h3><p class="meta">{n(s.get('signal_clusters', 0))} with signal and {n(s.get('small_clusters', 0))} small groups. Small groups add {esc(bandas_small_txt)}; none is in the high band.</p>{svg_bands(s['bandas'], 'en')}</div>
    <div class="chart-card"><h3>Accounts vs score</h3><p class="meta">Each circle is a cluster. Size = events; colour = band.</p>{svg_scatter(s['top_clusters'], 'en')}</div>
  </div>
  <div class="chart-card"><h3>Conversation rhythm</h3><p class="meta">Tagged events per day in the pilot window.</p>{svg_daily(s['daily'], epis, 'en')}</div>
  <div class="chart-card"><h3>Capture context · 8 weeks + current</h3><p class="meta">The jump in week 42 mostly reflects a change in radar coverage, not a sudden rise in protests. It is context, not a baseline.</p>{svg_weeks(s['weekly'], 'en')}</div>
</section>

<section>
  <h2>Curated episodes</h2>
  <p class="meta">No public list of demands is invented. The episode-to-cluster link is manual and revisable; it does not confirm the episode. Sources accessed 26 Oct 2026.</p>
  <p class="meta"><b>Inclusion criterion:</b> curated episodes with a youth/student component, an identifiable local trigger and international coverage. This is an editorial selection, neither random nor exhaustive; order does not imply continuity. <b>Source level:</b> agency/official &gt; media &gt; aggregator/wiki; sensitive figures without an agency or official source remain provisional.</p>
  <p class="meta"><b>{_verif_summary(epis, 'en')}</b></p>
  <div style="overflow:auto"><table>
    <thead><tr><th>Date</th><th>Place</th><th>Episode / status</th><th>Trigger</th><th>Declared demands</th><th>Call / radar</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table></div>
</section>

<section><h2>The mechanism: five pieces</h2><div class="chart-card">{svg_mechanism('en')}</div></section>

<section><h2>Who amplifies</h2>
  <div class="chart-card"><h3>Domains with more events</h3><p class="meta">Unit: events (not clusters); the visual report uses clusters. Google News is excluded from the chart as an aggregator; it is press echo, not an independent source.</p>{svg_domains(s['top_dominios'], 'en')}</div>
</section>

<section><h2>What to watch</h2><div class="three">
  <div class="card"><h3>Reach</h3><p class="meta">Whether the same slogans cross borders without a local trigger.</p></div>
  <div class="card"><h3>Amplification</h3><p class="meta">Whether accounts and domains repeat the same content in a short window.</p></div>
  <div class="card"><h3>Attribution</h3><p class="meta">Only with independent evidence. The radar does not provide it.</p></div>
</div></section>

<p><a href="/datos/protestas.json">Open data (JSON)</a> · <a href="/datos/protestas.schema.json">JSON schema</a> · <a href="/informes/visual/protestas_juveniles.html">Visual report</a> · <a href="./">Español</a> · <a href="/">Back to radar</a></p>
<footer>Produced with AI assistance and human review. Linked sources. — @pruebapublica<br>
Amplification pilot · noindex until review · {esc(ahora)} UTC</footer>
</main>
{SHARE_JS}
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-only", action="store_true")
    a = ap.parse_args()
    epis = cargar_episodios()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    s = señal(conn)
    s["extension"] = calcular_extension(conn)
    conv = cargar_registro()
    conn.close()
    errores = validar_senal(s)
    if errores:
        print("[protestas] consistencia rota: " + "; ".join(errores), file=sys.stderr)
        return 2
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    data = {"tema": TEMA, "actualizado": ahora, "episodios": epis, "senal": s, "convocatorias": conv}
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Observatorio 29N · protestas juveniles (eco en plataformas capturadas)",
        "type": "object",
        "required": ["tema", "actualizado", "episodios", "senal"],
        "properties": {
            "tema": {"type": "string", "const": TEMA},
            "actualizado": {"type": "string"},
            "episodios": {"type": "array", "items": {"type": "object"}},
            "convocatorias": {"type": "object"},
            "senal": {
                "type": "object",
                "properties": {
                    "eventos": {"type": "integer"},
                    "cuentas": {"type": "integer"},
                    "cuentas_cluster": {"type": "integer"},
                    "base": {"type": "object"},
                    "extension": {"type": "object"},
                    "clusters": {"type": "integer"},
                    "signal_clusters": {"type": "integer"},
                    "small_clusters": {"type": "integer"},
                    "bandas": {"type": "object"},
                    "bandas_signal": {"type": "object"},
                    "tie59_all": {"type": "integer"},
                    "tie59_signal": {"type": "integer"},
                    "top_clusters": {"type": "array"},
                    "top_signal": {"type": "array"},
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
        HTML_OUT.write_text(render(epis, s, ahora, conv), encoding="utf-8")
        HTML_EN.write_text(render_en(epis, s, ahora, conv), encoding="utf-8")
        print(f"[protestas] HTML -> {HTML_OUT} (+ EN)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
