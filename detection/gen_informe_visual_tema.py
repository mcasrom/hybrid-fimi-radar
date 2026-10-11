#!/usr/bin/env python3
"""gen_informe_visual_tema.py — SEMILLA del informe visual de una pagina por tema.

Reutiliza datos ya calculados (clusters + assessments + cluster_events; misma
fuente que el dashboard y que informe_tema.py). NO recalcula scoring ni toca la
metodologia: solo presenta. Determinista, stdlib only.

Salida: /var/www/fimi/informes/visual/<tema>.html  (+ index.html)
Uso:    .venv/bin/python detection/gen_informe_visual_tema.py --tema frontera_sur
        .venv/bin/python detection/gen_informe_visual_tema.py --todos
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metricas_tema as _mt  # noqa: E402  (definiciones canonicas por tema)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "radar.db")
CFG = os.path.join(ROOT, "config.yaml")
SALUD = os.path.join(ROOT, "data", "salud_temas.json")
OUT_DIR = "/var/www/fimi/informes/visual"
ACTIVOS = ["frontera_sur", "oriente_medio", "elecciones", "inteligencia_artificial",
           "eeuu_politica", "sahel", "energia", "defensa_espana", "espana_elecciones"]

# Hipotesis (attribution.py) -> etiqueta en espanol natural (coincide con gen_fimi_html.py)
HYP_ES = {
    "H2": "Compatible con coordinación doméstica (con estructura)",
    "H2b": "Sincronización sin atribución de operador",
    "H5": "Sincronía sostenida (sin estructura)",
    "H1": "Viralización orgánica",
    "H3": "Influencia extranjera",
    "H4": "Amplificación mediática",
    "H6": "Sin evidencia concluyente",
}
BAND_ES = {"NORMAL": "Normal", "WATCH": "En observación", "ANOMALOUS": "Amplificación anómala",
           "HIGH": "Amplificación alta", "CRITICAL": "Amplificación muy alta"}
# color por banda (sobrio; rojo solo en CRITICAL)
BAND_COL = {"NORMAL": "#94a3b8", "WATCH": "#0891b2", "ANOMALOUS": "#d97706",
            "HIGH": "#ea580c", "CRITICAL": "#dc2626"}
# Países (para el desglose multinacional del tema "elecciones") — por ccTLD y medios conocidos.
PAIS_TLD = {"de": "Alemania", "se": "Suecia", "es": "España", "it": "Italia", "fr": "Francia",
            "pl": "Polonia", "nl": "Países Bajos", "at": "Austria", "gr": "Grecia", "pt": "Portugal",
            "ro": "Rumanía", "bg": "Bulgaria", "rs": "Serbia", "ba": "Bosnia", "hu": "Hungría",
            "cz": "Chequia", "dk": "Dinamarca", "fi": "Finlandia", "no": "Noruega", "be": "Bélgica",
            "ie": "Irlanda", "ch": "Suiza", "us": "EE. UU.", "ru": "Rusia", "ua": "Ucrania",
            "br": "Brasil", "ar": "Argentina", "mx": "México", "uk": "Reino Unido"}
PAIS_DOM = {"spiegel.de": "Alemania", "zeit.de": "Alemania", "faz.net": "Alemania", "welt.de": "Alemania",
            "tagesschau.de": "Alemania", "sueddeutsche.de": "Alemania", "taz.de": "Alemania",
            "nytimes.com": "EE. UU.", "washingtonpost.com": "EE. UU.", "wsj.com": "EE. UU.",
            "cnn.com": "EE. UU.", "politico.com": "EE. UU.", "npr.org": "EE. UU.", "pbs.org": "EE. UU.",
            "foxnews.com": "EE. UU.", "theguardian.com": "Reino Unido", "bbc.com": "Reino Unido",
            "bbc.co.uk": "Reino Unido", "dn.se": "Suecia", "aftonbladet.se": "Suecia",
            "expressen.se": "Suecia", "svt.se": "Suecia", "eldiario.es": "España", "elpais.com": "España",
            "publico.es": "España", "infolibre.es": "España", "efe.com": "España", "elconfidencial.com": "España"}


# Acortadores, plataformas y dominios propios: NO cuentan como "dominio" ni como país.
DOM_EXCL = {"youtu.be", "youtube.com", "bit.ly", "t.co", "flip.it", "dlvr.it", "ow.ly", "lnkd.in",
            "buff.ly", "ift.tt", "bsky.app", "x.com", "twitter.com", "facebook.com", "instagram.com",
            "t.me", "telegram.me", "briefly.co", "reddit.com", "news.google.com", "goo.gl", "shorturl.at",
            "pruebapublica.com", "analisis.pruebapublica.com", "viajeinteligencia.com", "diario-red.com"}


def mil(n):
    return "{:,}".format(int(round(float(n or 0)))).replace(",", ".")


def _pais_de(host):
    h = (host or "").lower()
    if h in PAIS_DOM:
        return PAIS_DOM[h]
    parts = h.split(".")
    if len(parts) >= 2 and ".".join(parts[-2:]) == "co.uk":
        return "Reino Unido"
    return PAIS_TLD.get(parts[-1] if parts else "", "Internacional/otros")


PAIS_KW = {
    "Alemania": ["afd", "landtagswahl", "bundestagswahl", "wahlkampf", "europawahl", "scholz",
                 "merz", "spd", "cdu", "gruene", "bundestag"],
    "Suecia": ["sverige", "riksdag", "sverigedemokraterna", "moderaterna", "valet"],
    "España": ["elecciones generales", "feijoo", "sanchez", "vox", "moncloa", "29n", "psoe"],
    "Brasil": ["lula", "bolsonaro", "tse", "planalto", "segundo turno", "balotagem"],
    "EE. UU.": ["midterms", "harris", "biden", "republican", "democrat", "gop"],
    "Francia": ["assemblee", "macron", "le pen", "legislativas"],
    "Italia": ["meloni", "elezioni", "fratelli d italia"],
    "Reino Unido": ["westminster", "labour", "tory", "tories", "snap election"],
}


def _sint(s):
    import unicodedata as _u
    return "".join(c for c in _u.normalize("NFD", (s or "").lower()) if not _u.combining(c))


NAVY = "#1e3a5f"
ACCENT = "#2563eb"
INK = "#0f172a"
MUT = "#64748b"
LINE = "#e2e8f0"


def esc(s):
    return html.escape(str(s if s is not None else ""))


def band_for(score):
    if score is None:
        return "NORMAL"
    s = float(score)
    if s >= 80:
        return "CRITICAL"
    if s >= 60:
        return "HIGH"
    if s >= 40:
        return "ANOMALOUS"
    if s >= 20:
        return "WATCH"
    return "NORMAL"


def host(url):
    if not url:
        return ""
    m = re.match(r"https?://([^/]+)", str(url))
    if not m:
        return ""
    return m.group(1).lower().replace("www.", "")


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    n = len(xs)
    if not n:
        return 0.0
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def load_names():
    try:
        import yaml
        cfg = yaml.safe_load(open(CFG, encoding="utf-8")) or {}
    except Exception:
        cfg = {}
    names = {}
    for k, v in (cfg.get("temas") or {}).items():
        if isinstance(v, dict):
            names[k] = v.get("nombre") or v.get("name") or k
    return names


def load_salud():
    try:
        d = json.load(open(SALUD, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for t in d.get("temas") or []:
        if isinstance(t, dict) and t.get("tema"):
            out[t["tema"]] = t
    return out


def load_keywords(tema):
    try:
        import yaml
        cfg = yaml.safe_load(open(CFG, encoding="utf-8")) or {}
    except (OSError, ValueError):
        return []
    out = []
    for k in (cfg.get("keywords") or []):
        if (k.get("tema") or "frontera_sur") == tema:
            w = k.get("palabra")
            if w:
                out.append(w)
    return out


def load_elecciones():
    """Fechas electorales activas (data/elecciones.yaml) para marcarlas en el timeline."""
    try:
        import yaml
        d = yaml.safe_load(open(os.path.join(ROOT, "data", "elecciones.yaml"), encoding="utf-8")) or []
    except (OSError, ValueError):
        return []
    out = []
    for row in d:
        if not isinstance(row, dict) or row.get("estado") == "cerrado":
            continue
        f = str(row.get("fecha") or "")[:10]
        if len(f) == 10 and f[4] == "-" and f[7] == "-":
            out.append((f, str(row.get("pais") or "")))
    return out


def cargar_tema(con, tema):
    cl = con.execute(
        "SELECT c.id, c.cluster_label, c.overall_score, c.coordination_score,"
        " c.amplification_score, c.anomaly_score, c.infrastructure_score,"
        " c.network_density, c.alternative_explanations, c.narrative_subtype,"
        " a.hypotheses_json, a.attribution, a.attribution_confidence,"
        " a.kcore, a.kcore_size, a.assessment"
        " FROM clusters c LEFT JOIN assessments a ON a.cluster_id=c.id"
        " WHERE c.tema_id=? ORDER BY c.overall_score DESC", (tema,)).fetchall()
    clusters = []
    for r in cl:
        (cid, label, ov, coord, amp, anom, infra, dens, alt, narr,
         hyps, atr, conf, kc, kcs, asses) = r
        n_ev = con.execute("SELECT COUNT(*) FROM cluster_events WHERE cluster_id=?", (cid,)).fetchone()[0]
        n_au = con.execute("SELECT COUNT(DISTINCT author) FROM cluster_events WHERE cluster_id=?", (cid,)).fetchone()[0]
        t0 = con.execute("SELECT MIN(ts) FROM cluster_events WHERE cluster_id=?", (cid,)).fetchone()[0]
        rows_ct = con.execute("SELECT url, ts FROM cluster_events WHERE cluster_id=?", (cid,)).fetchall()
        urls = [x[0] for x in rows_ct]
        daily = {}
        for _u, _ts in rows_ct:
            if _ts:
                d = day_key(_ts)
                daily[d] = daily.get(d, 0) + 1
        _tt = con.execute("SELECT title, text FROM cluster_events WHERE cluster_id=? LIMIT 40", (cid,)).fetchall()
        txt = (" ".join((str(x[0] or "") + " " + str(x[1] or "")) for x in _tt))[:6000]
        doms = {}
        for u in urls:
            h = host(u)
            if h and h not in DOM_EXCL:
                doms[h] = doms.get(h, 0) + 1
        try:
            hyps = json.loads(hyps) if hyps else []
        except (ValueError, TypeError):
            hyps = []
        clusters.append({
            "id": cid, "label": label, "ov": float(ov or 0), "banda": band_for(ov),
            "coord": float(coord or 0), "amp": float(amp or 0), "anom": float(anom or 0),
            "infra": float(infra or 0), "dens": float(dens or 0),
            "kc": kc or 0, "kcs": kcs or 0, "n_ev": n_ev, "n_au": n_au, "t0": t0,
            "doms": sorted(doms.items(), key=lambda x: -x[1]), "hyps": hyps, "daily": daily, "txt": txt,
            "atr": atr or "UNKNOWN", "conf": conf or "NO_ATTRIBUTION", "asses": asses or "",
        })
    # KPIs de tema (misma definicion que informe_tema.py)
    ev = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT e.author) FROM events e"
        " JOIN event_temas et ON et.event_id=e.id WHERE et.tema_id=?", (tema,)).fetchone()
    n_ev, n_au = ev[0], ev[1]
    # linea base de noticias: volumen diario del TEMA (todos sus eventos)
    theme_daily = {}
    _src = {}
    for (_ts, _s) in con.execute(
            "SELECT e.timestamp, e.source FROM events e JOIN event_temas et ON et.event_id=e.id"
            " WHERE et.tema_id=?", (tema,)).fetchall():
        if _ts:
            d = day_key(_ts)
            theme_daily[d] = theme_daily.get(d, 0) + 1
        if _s:
            _src[_s] = _src.get(_s, 0) + 1
    tmin = con.execute(
        "SELECT MIN(e.timestamp) FROM events e JOIN event_temas et ON et.event_id=e.id"
        " WHERE et.tema_id=?", (tema,)).fetchone()[0]
    # cuentas implicadas en CLUSTERS (distintas) e inicio de ingesta: fuente
    # canonica compartida (metricas_tema), igual que el dashboard y el semanal.
    n_au_cl = _mt.cuentas_en_clusters(con, tema)
    _ini = _mt.inicio_ingesta(con, tema)
    return clusters, {"n_ev": n_ev, "n_au": n_au, "n_au_cl": n_au_cl, "tmin": tmin,
                      "inicio": _ini, "theme_daily": theme_daily, "sources": _src}


def hyp_top(c):
    if not c["hyps"]:
        return None, 0.0
    h = max(c["hyps"], key=lambda x: x.get("score", 0))
    return h.get("hypothesis"), float(h.get("score", 0)) * 100


def dias_desde(ts):
    if not ts:
        return 0
    # admite epoch (int/str numerico) o ISO/'YYYY-MM-DD HH:MM:SS'
    if str(ts).strip().isdigit():
        v = int(ts)
        if v > 10_000_000:
            t = datetime.fromtimestamp(v, tz=timezone.utc)
            return max(0, (datetime.now(timezone.utc) - t).days)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            t = datetime.strptime(str(ts)[:19], fmt).replace(tzinfo=timezone.utc)
            return max(0, (datetime.now(timezone.utc) - t).days)
        except ValueError:
            continue
    return 0


def bar(pct, color=ACCENT, w=100):
    pct = max(0.0, min(100.0, float(pct)))
    return (f"<div style='position:relative;height:10px;background:#eef2f7;border-radius:6px'>"
            f"<div style='position:absolute;left:0;top:0;height:10px;width:{pct:.1f}%;"
            f"background:{color};border-radius:6px'></div></div>")


_ASCII_BAD = ["Senal", "Amplificacion", "Coordinacion", "Anomalia", "hipotesis", "Hipotesis",
              "Que esta", "observacion", "informacion", "atribucion", "Conclusion",
              "nucleo", "metodo y", "dias operando", "senales"]


def day_key(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")


def _cont_days(dmin, dmax):
    a = datetime.strptime(dmin, "%Y-%m-%d")
    b = datetime.strptime(dmax, "%Y-%m-%d")
    out = []
    while a <= b:
        out.append(a.strftime("%Y-%m-%d"))
        a += timedelta(days=1)
    return out


def timeline_svg(days, cl, th, w=760, h=130, marks=None):
    n = max(1, len(days))
    cmax = max([cl.get(d, 0) for d in days] + [1])
    tmax = max([th.get(d, 0) for d in days] + [1])
    bw = w / n
    bars = []
    for i, d in enumerate(days):
        v = cl.get(d, 0)
        if v:
            bh = (h - 26) * v / cmax
            bars.append(f"<rect x='{i * bw:.1f}' y='{h - 16 - bh:.1f}' width='{max(1, bw - 1.5):.1f}' "
                        f"height='{bh:.1f}' fill='{ACCENT}' rx='1'/>")
    pts = " ".join(f"{i * bw + bw / 2:.1f},{h - 16 - (h - 26) * th.get(d, 0) / tmax:.1f}"
                   for i, d in enumerate(days))
    line = f"<polyline points='{pts}' fill='none' stroke='{NAVY}' stroke-opacity='.35' stroke-width='1.6'/>"
    axis = f"<line x1='0' y1='{h - 16}' x2='{w}' y2='{h - 16}' stroke='{LINE}'/>"
    labels = (f"<text x='0' y='{h - 3}' font-size='10' fill='{MUT}'>{days[0][5:]}</text>"
              f"<text x='{w}' y='{h - 3}' font-size='10' fill='{MUT}' text-anchor='end'>{days[-1][5:]}</text>")
    marks_html = ""
    for _d, _lab in (marks or []):
        if _d in days:
            _x = days.index(_d) * bw + bw / 2
            marks_html += (f"<line x1='{_x:.1f}' y1='12' x2='{_x:.1f}' y2='{h - 16}' stroke='#dc2626' "
                           f"stroke-width='1' stroke-dasharray='3 3'/>"
                           f"<text x='{_x:.1f}' y='10' font-size='9' fill='#b91c1c' text-anchor='middle'>{esc(_lab[:9])}</text>")
    return (f"<svg viewBox='0 0 {w} {h}' width='100%' style='max-width:760px;display:block' role='img' "
            f"aria-label='Eventos por día del cluster (barras) frente al volumen diario del tema (línea)'>"
            f"<title>Ritmo del cluster top y línea base del tema</title>"
            f"<desc>Barras: eventos por día del cluster de mayor score. Línea: volumen diario del tema (línea base).</desc>"
            f"{axis}{line}{''.join(bars)}{marks_html}{labels}</svg>")


def _qual(sc):
    return "compatible" if sc >= 66 else ("débil" if sc >= 33 else "sin soporte")


def spider(series):
    # series: list of (label, value 0-100, color). Hexagono con 5 ejes (components).
    axes = [("Coordinación", "coord"), ("Infraestructura", "infra"), ("Densidad", "dens"),
            ("Amplificación", "amp"), ("Anomalía", "anom")]
    import math
    cx, cy, R = 150, 130, 95
    n = len(axes)
    rings = []
    for frac in (0.25, 0.5, 0.75, 1.0):
        pts = []
        for i in range(n):
            a = -math.pi / 2 + 2 * math.pi * i / n
            pts.append(f"{cx + R * frac * math.cos(a):.1f},{cy + R * frac * math.sin(a):.1f}")
        rings.append(f"<polygon points='{' '.join(pts)}' fill='none' stroke='{LINE}' stroke-width='1'/>")
    spokes = []
    labels = []
    for i in range(n):
        a = -math.pi / 2 + 2 * math.pi * i / n
        x, y = cx + R * math.cos(a), cy + R * math.sin(a)
        spokes.append(f"<line x1='{cx}' y1='{cy}' x2='{x:.1f}' y2='{y:.1f}' stroke='{LINE}' stroke-width='1'/>")
    polys = []
    for lab, key, col in series:
        pts = []
        for i, (_, k) in enumerate(axes):
            a = -math.pi / 2 + 2 * math.pi * i / n
            v = max(0.0, min(100.0, float(key.get(k, 0))))
            pts.append(f"{cx + R * v / 100 * math.cos(a):.1f},{cy + R * v / 100 * math.sin(a):.1f}")
        polys.append(f"<polygon points='{' '.join(pts)}' fill='{col}' fill-opacity='0.18' stroke='{col}' stroke-width='2'/>")
    for i, (ax, _) in enumerate(axes):
        a = -math.pi / 2 + 2 * math.pi * i / n
        lx, ly = cx + (R + 20) * math.cos(a), cy + (R + 18) * math.sin(a)
        anch = "middle"
        labels.append(f"<text x='{lx:.0f}' y='{ly:.0f}' text-anchor='{anch}' font-size='11' fill='{MUT}'>{esc(ax)}</text>")
    return (f"<svg viewBox='0 0 300 260' width='100%' style='max-width:340px;display:block;margin:0 auto' "
            f"role='img' aria-label='Radar de componentes: tema (mediana) y cluster de mayor score'>"
            f"<title>Radar de componentes</title>"
            f"<desc>Coordinación, infraestructura, densidad, amplificación y anomalía, del tema (mediana) y del cluster de mayor score. Los valores están en la tabla alternativa siguiente.</desc>"
            f"{''.join(rings)}{''.join(spokes)}{''.join(polys)}{''.join(labels)}</svg>")


def render(tema, nombre, clusters, kpi, salud, keywords=None):
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    n = len(clusters)
    altos = [c for c in clusters if c["ov"] >= 60]
    top = clusters[0] if clusters else None
    mas_anom = max(clusters, key=lambda c: c["anom"]) if clusters else None
    _ini = kpi.get("inicio") or kpi.get("tmin")
    try:
        _ini_s = datetime.fromtimestamp(int(_ini), tz=timezone.utc).strftime("%d/%m/%Y") if _ini else "—"
    except (TypeError, ValueError):
        _ini_s = "—"
    dias = dias_desde(_ini)
    # hipotesis dominante del tema (moda del top de cada cluster)
    from collections import Counter
    cnt = Counter()
    for c in clusters:
        ct, _ = hyp_top(c)
        if ct:
            cnt[ct] += 1
    dom_h = cnt.most_common(1)[0][0] if cnt else "—"
    dom_h_n = cnt.most_common(1)[0][1] if cnt else 0
    h3 = sum(1 for c in clusters if hyp_top(c)[0] == "H3")
    # medianas de componentes del tema
    med = {k: median([c[k] for c in clusters]) for k in ("coord", "infra", "dens", "amp", "anom")}
    # dominios top del tema (por apariciones agregadas en clusters destacados)
    dom_agg = Counter()
    for c in clusters[:20]:
        for d, k in c["doms"][:5]:
            dom_agg[d] += 1
    top_doms = dom_agg.most_common(7)
    bd = band_for(top["ov"]) if top else "NORMAL"
    s = salud or {}
    # ---- bloques html ----
    kpi_tiles = [
        ("clusters", n, "activos"),
        ("cuentas", kpi.get("n_au_cl", kpi["n_au"]), "en clusters"),
        ("en banda alta", len(altos), "≥60"),
        ("hipótesis más frecuente", dom_h, "%d de %d clusters" % (dom_h_n, n)),
        ("H3 como máx", h3, "del tema"),
        ("días operando", dias, f"desde {_ini_s}"),
    ]
    tiles = "".join(
        f"<div class='tile'><div class='k'>{esc(v)}</div><div class='kl'>{esc(l)}</div><div class='ks'>{esc(sub)}</div></div>"
        for (l, v, sub) in kpi_tiles)
    # cluster top hypotheses
    hyp_bars = ""
    if top and top["hyps"]:
        for h in sorted(top["hyps"], key=lambda x: -x.get("score", 0)):
            code = h.get("hypothesis", "?")
            sc = float(h.get("score", 0)) * 100
            star = "★ " if code == hyp_top(top)[0] else ""
            hyp_bars += (f"<div class='hrow'><div class='hcode'>{star}{esc(code)}</div>"
                         f"<div class='hname'>{esc(HYP_ES.get(code, h.get('label', code)))}</div>"
                         f"<div class='hbar'>{bar(sc, '#1d4ed8')}</div><div class='hval'>{sc:.0f}</div><div class='hqual'>{_qual(sc)}</div></div>")
    # destacados: top por score SIN 'muestra pequeña' (<30 eventos) salvo que no haya 3
    _big = [c for c in clusters if c['n_ev'] >= 30]
    destac = (_big[:3] if len(_big) >= 3 else (_big + [c for c in clusters if c['n_ev'] < 30])[:3])
    cards = ""
    for c in destac:
        ct, _ = hyp_top(c)
        doms_txt = " · ".join(f"{esc(d)}" for d, _ in c["doms"][:3]) or "—"
        _small = (" · <span style='color:#b45309;font-weight:700'>muestra pequeña</span>"
                  if c["n_ev"] < 30 else "")
        cards += (
            f"<div class='ccard'><div class='cchead'><b>{esc(c['label'])}</b>"
            f"<span class='chip' style='background:{BAND_COL[c['banda']]}'>{c['ov']:.0f}/100 · {esc(c['banda'])}</span></div>"
            f"<p class='cs'>{esc(BAND_ES[c['banda']])} · {c['n_au']} cuentas · {c['n_ev']} eventos · núcleo k={c['kc']}{_small}</p>"
            f"<p class='cs'><b>Hipótesis top:</b> {esc(ct or '—')} — {esc(HYP_ES.get(ct, '—'))}</p>"
            f"<p class='cs'><b>De qué habla:</b> {doms_txt}</p>"
            f"<div class='cact'>"
            f"<a href='https://fimi.viajeinteligencia.com/api/export?cluster={esc(c['label'])}&fmt=csv'>CSV</a>"
            f"<a href='https://fimi.viajeinteligencia.com/api/export?cluster={esc(c['label'])}&fmt=json'>JSON</a>"
            f"<a href='https://fimi.viajeinteligencia.com/api/export?cluster={esc(c['label'])}&fmt=gexf'>GEXF</a>"
            f"</div></div>")
    # dominio bars
    dmax = max((v for _, v in top_doms), default=1)
    dom_bars = "".join(
        f"<div class='drow'><div class='dname'>{esc(d)}</div>"
        f"<div class='dbar'><div style='width:{100*v/dmax:.0f}%;background:{NAVY};height:9px;border-radius:6px'></div></div>"
        f"<div class='dval'>{v}</div></div>" for d, v in top_doms)
    # senales clave (medianas)
    sen = ""
    for lab, k in [("Amplificación", "amp"), ("Coordinación", "coord"), ("Anomalía", "anom"),
                   ("Infraestructura", "infra"), ("Densidad de red", "dens")]:
        sen += (f"<div class='hrow'><div class='hname' style='width:auto;flex:1'>{lab}</div>"
                f"<div class='hbar'>{bar(med[k], NAVY)}</div><div class='hval'>{med[k]:.0f}</div></div>")
    # distribucion de la hipotesis de mayor puntuacion por cluster (frecuencia del tema)
    _dist_dom = ""
    for code, c in sorted(cnt.items(), key=lambda x: -x[1]):
        _dist_dom += (f"<div class='hrow'><div class='hcode'>{esc(code)}</div>"
                      f"<div class='hname'>{esc(HYP_ES.get(code, ''))}</div>"
                      f"<div class='hbar'>{bar(100 * c / max(1, n), NAVY)}</div><div class='hval'>{c}</div></div>")
    mas_anom_txt = ""
    if mas_anom:
        _mal = esc(mas_anom["label"])
        mas_anom_txt = (f"<b>{_mal}</b> "
                        f"<span class='chip' style='background:#fee2e2;color:#b91c1c'>anomalía {mas_anom['anom']:.0f}</span>"
                        f" <span style='font-size:.72rem;color:#64748b'>· {mas_anom['n_ev']} eventos · {mas_anom['n_au']} cuentas</span>"
                        f" <span style='font-size:.72rem'>· "
                        f"<a href='https://fimi.viajeinteligencia.com/api/export?cluster={_mal}&fmt=csv'>CSV</a> "
                        f"<a href='https://fimi.viajeinteligencia.com/api/export?cluster={_mal}&fmt=json'>JSON</a> "
                        f"<a href='https://fimi.viajeinteligencia.com/api/export?cluster={_mal}&fmt=gexf'>GEXF</a></span>")
    tot_ev = s.get("eventos", kpi["n_ev"])
    lectura = (f"El sistema observa <b>{n}</b> clusters en el tema. La hipótesis dominante del conjunto es "
               f"<b>{esc(dom_h)}</b> ({esc(HYP_ES.get(dom_h, ''))}) en {dom_h_n} de {n} clusters. "
               f"{h3} clusters muestran señal compatible con influencia extranjera (H3). "
               f"La infraestructura y la densidad de red son altas, pero <b>esto no permite atribuir actor</b>: "
               f"una banda alta es amplificación medida, no campaña confirmada.")
    concl = (f"{esc(BAND_ES[bd])} (max {top['ov']:.0f}/100) con {len(altos)} de {n} clusters en banda alta.")
    # ritmo del cluster top + linea base del tema (noticias)
    tl_svg = ""
    ritmo = ""
    _elec_note = ""
    _thd = kpi.get("theme_daily", {})
    if top and top.get("daily"):
        _dd = sorted(top["daily"])
        _days = _cont_days(_dd[0], _dd[-1])
        _mk = [(f, p) for f, p in (load_elecciones() if tema == "elecciones" else []) if f in _days]
        _elec_note = " Las <b>líneas rojas</b> marcan fechas electorales (data/elecciones.yaml)." if _mk else ""
        tl_svg = timeline_svg(_days, top["daily"], _thd, marks=_mk)
        _vals = sorted(_thd.get(x, 0) for x in _days)
        _p90 = _vals[int(len(_vals) * 0.9)] if _vals else 0
        _peak = [x for x in _days if _thd.get(x, 0) >= _p90 and _p90 > 0]
        _cl_on = sum(top["daily"].get(x, 0) for x in _peak)
        _cl_tot = sum(top["daily"].values()) or 1
        _th_on = sum(_thd.get(x, 0) for x in _peak)
        _th_tot = sum(_thd.get(x, 0) for x in _days) or 1
        _cl_pct = 100 * _cl_on / _cl_tot
        _th_pct = 100 * _th_on / _th_tot
        _ratio = (_cl_pct / _th_pct) if _th_pct else 1.0
        _base = (f"el cluster concentra el <b>{_cl_pct:.0f}%</b> de su actividad en esos días y el tema en conjunto el <b>{_th_pct:.0f}%</b>")
        if _ratio >= 1.3:
            ritmo = (f"En los «picos del tema» (días con volumen ≥ p90), {_base} → el cluster está <b>sobrerrepresentado</b>: "
                     f"sigue el ciclo informativo (posible <b>eco</b>), no necesariamente coordinación.")
        elif _ratio <= 0.7:
            ritmo = (f"En los «picos del tema» (días con volumen ≥ p90), {_base} → el cluster está <b>infrarrepresentado</b>: "
                     f"patrón <b>más propio del cluster</b> que del ciclo de noticias.")
        else:
            ritmo = (f"En los «picos del tema» (días con volumen ≥ p90), {_base} → el cluster <b>sigue el tema de forma similar al conjunto</b>: "
                     f"sin señal clara de reacción ni de patrón propio.")
    # reparto por plataforma (cobertura)
    _srca = kpi.get("sources", {})
    _src_tot = sum(_srca.values()) or 1
    _src_all = sorted(_srca.items(), key=lambda x: -x[1])
    _src_top = _src_all[:5]
    _otras = len(_src_all) - len(_src_top)
    _src_txt = " · ".join(f"{esc(_s)} {100 * _v / _src_tot:.0f}%" for _s, _v in _src_top) or "—"
    if _otras > 0:
        _src_txt += f" · otras ({_otras})"
    _dsrc, _dn = (_src_top[0] if _src_top else ("—", 0))
    _dpct = 100 * _dn / _src_tot
    cobertura = (f"<b>Cobertura por plataforma:</b> {_src_txt}. " +
                 (f"Este informe refleja sobre todo <b>{esc(_dsrc)}</b> ({_dpct:.0f}% del corpus del tema); "
                  f"no representa por sí solo todo el debate público." if _dpct >= 50
                  else "Ninguna plataforma domina por completo el corpus del tema."))
    # distribucion de tamaños de cluster
    _nacs = sorted(c["n_au"] for c in clusters)
    _alta_small = sum(1 for c in altos if c["n_ev"] < 30)
    tamano = (f"Tamaño: mediana <b>{median(_nacs):.0f}</b> cuentas por cluster (n={n}); de los "
              f"<b>{len(altos)}</b> en banda alta, <b>{_alta_small}</b> tienen &lt;30 eventos (muestra pequeña).")
    # como se define el tema (transparencia)
    _kws = keywords or []
    _dd_all = sorted(kpi.get("theme_daily", {}))
    _tmin_s = _dd_all[0] if _dd_all else "—"
    _tmax_s = _dd_all[-1] if _dd_all else "—"
    tema_def = ""
    if _kws:
        tema_def = (f"<details class='tdef'><summary>Cómo se define «{esc(nombre)}»: términos y ventana</summary>"
                    f"<p class='cs'>Términos de seguimiento ({len(_kws)}): <code>{esc(' · '.join(_kws))}</code></p>"
                    f"<p class='cs'>Periodo del corpus: {_tmin_s} → {_tmax_s} (incluye <b>backfill</b> retrospectivo). "
                    f"Ingesta del tema (primer hallazgo persistido): desde {_ini_s}. Ventana de análisis: 60 días. El corpus llega "
                    f"también por búsqueda en las plataformas con estos términos y sus variantes.</p></details>")
    _tp = top or {}
    _radar_tabla = ("<details class='tdef'><summary>Ver los valores del radar (tabla)</summary>"
                    "<table style='width:100%;border-collapse:collapse;font-size:.78rem'>"
                    "<tr><th style='text-align:left;padding:3px 6px'>Componente</th>"
                    "<th style='text-align:right;padding:3px 6px'>Tema (mediana)</th>"
                    "<th style='text-align:right;padding:3px 6px'>Cluster top</th></tr>"
                    + "".join(f"<tr><td style='padding:3px 6px'>{lab}</td>"
                              f"<td style='text-align:right;padding:3px 6px'>{med[k]:.0f}</td>"
                              f"<td style='text-align:right;padding:3px 6px'>{float(_tp.get(k, 0) or 0):.0f}</td></tr>"
                              for lab, k in [("Coordinación", "coord"), ("Infraestructura", "infra"),
                                             ("Densidad de red", "dens"), ("Amplificación", "amp"),
                                             ("Anomalía", "anom")])
                    + "</table></details>")
    # desglose por país (solo tema multinacional "elecciones")
    paises_html = ""
    if tema == "elecciones":
        _pai = {}
        for _c in clusters:
            _v = {}
            for _d, _n in _c["doms"][:5]:
                _k = _pais_de(_d)
                _v[_k] = _v.get(_k, 0) + 1
            _k = max(_v, key=_v.get) if _v else "Internacional/otros"
            if _k == "Internacional/otros" and _c.get("txt"):
                _t = _sint(_c["txt"])
                _kv = {}
                for _pn, _kl in PAIS_KW.items():
                    _n2 = sum(_t.count(_sint(_w)) for _w in _kl)
                    if _n2:
                        _kv[_pn] = _n2
                if _kv:
                    _k = max(_kv, key=_kv.get)
            _pai.setdefault(_k, []).append(_c)
        _rows = []
        for _pai_n, _cs in sorted(_pai.items(), key=lambda kv: -sum(c["n_au"] for c in kv[1])):
            _alta = sum(1 for _x in _cs if _x["ov"] >= 60)
            _mx = max(_x["ov"] for _x in _cs)
            _acct = sum(c["n_au"] for c in _cs)
            _dmc = Counter()
            for _x in _cs:
                for _d, _n in _x["doms"][:3]:
                    _dmc[_d] += _n
            _dm = " · ".join(_d for _d, _ in _dmc.most_common(6))
            _rows.append(f"<tr><td style='padding:4px 8px'>{esc(_pai_n)}</td>"
                         f"<td style='text-align:right'>{len(_cs)}</td>"
                         f"<td style='text-align:right'>{mil(_acct)}</td>"
                         f"<td style='text-align:right'>{_alta}</td>"
                         f"<td style='text-align:right'>{_mx:.0f}</td>"
                         f"<td style='padding:4px 8px;color:#94a3b8'>{esc(_dm)}</td></tr>")
        paises_html = ("<section><h2>Desglose por país (aproximado, por dominios)</h2>"
                       "<p class='cs'>Tema <b>multinacional</b>: el país se asigna por los <b>dominios</b> que comparten las "
                       "cuentas del cluster (ccTLD y medios conocidos) y, si no, por <b>palabras del país</b>. Se excluyen "
                       "acortadores, plataformas y dominios propios. Es <b>orientativo</b>, no una clasificación estricta.</p>"
                       "<table style='width:100%;border-collapse:collapse;font-size:.8rem'>"
                       "<tr><th style='text-align:left;padding:4px 8px'>País</th><th style='text-align:right'>Clusters</th>"
                       "<th style='text-align:right'>Cuentas</th><th style='text-align:right'>En banda alta</th>"
                       "<th style='text-align:right'>Máx</th>"
                       "<th style='text-align:left;padding:4px 8px'>Dominios ejemplo</th></tr>"
                       + "".join(_rows) + "</table></section>")
    css = f"""
*{{box-sizing:border-box}} body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
color:{INK};background:#f5f7fa;line-height:1.5}} .wrap{{max-width:1080px;margin:0 auto;padding:0 18px}}
a{{color:{ACCENT};text-decoration:none}}
.hd{{background:{NAVY};color:#fff;padding:26px 0}} .hd .wrap{{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}}
.hd .brand{{display:flex;align-items:center;gap:15px}}
.hd .eyebrow{{font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:#93c5fd;font-weight:800;margin-bottom:4px}}
.hd h1{{margin:0;font-size:1.62rem;letter-spacing:-.01em}} .hd .sub{{opacity:.82;font-size:.85rem;margin-top:5px}}
.btns a,.btns button{{display:inline-block;border:1px solid rgba(255,255,255,.5);color:#fff;background:transparent;
border-radius:9px;padding:9px 15px;font-size:.85rem;cursor:pointer;margin-left:8px}}
.btns a:hover,.btns button:hover{{background:rgba(255,255,255,.12)}}
.disc{{background:#fff7ed;border-bottom:1px solid #fed7aa;color:#9a3412;font-size:.82rem;padding:10px 0;text-align:center}}
section{{background:#fff;border:1px solid {LINE};border-radius:14px;padding:22px 24px;margin:18px 0;box-shadow:0 1px 2px rgba(15,23,42,.04)}}
h2{{font-size:1.08rem;margin:0 0 14px;color:{NAVY};padding-left:12px;border-left:4px solid {ACCENT};line-height:1.2}} .grid{{display:grid;gap:14px}}
.tiles{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}}
.tile{{background:#f8fafc;border:1px solid {LINE};border-radius:10px;padding:12px;text-align:center}}
.tile .k{{font-size:1.5rem;font-weight:800;color:{NAVY}}} .tile .kl{{font-size:.78rem;font-weight:600}}
.tile .ks{{font-size:.68rem;color:{MUT}}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.three{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}
.hrow{{display:flex;align-items:center;gap:8px;margin:5px 0;font-size:.8rem}}
.hcode{{width:38px;font-weight:700;color:{NAVY}}} .hname{{width:210px;color:{MUT}}}
.hbar{{flex:1}} .hval{{width:34px;text-align:right;font-weight:700}}
.hqual{{width:86px;font-size:.68rem;color:{MUT};text-align:right}}
.drow{{display:flex;align-items:center;gap:8px;margin:4px 0;font-size:.78rem}}
.dname{{width:150px;color:{INK}}} .dbar{{flex:1;background:#eef2f7;border-radius:6px}} .dval{{width:26px;text-align:right;color:{MUT}}}
.ccard{{border:1px solid {LINE};border-radius:10px;padding:12px}} .cchead{{display:flex;justify-content:space-between;align-items:center}}
.chip{{color:#fff;border-radius:999px;padding:2px 10px;font-size:.72rem;font-weight:700}}
.cs{{font-size:.78rem;color:#334155;margin:6px 0 0}} .cact{{margin-top:8px}} .cact a{{margin-right:10px;font-size:.75rem;font-weight:600}}
.tdef{{margin-top:12px;border-top:1px solid {LINE};padding-top:10px}} .tdef summary{{cursor:pointer;font-size:.8rem;color:{NAVY};font-weight:700}} .tdef code{{font-size:.74rem;color:#334155;background:#f1f5f9;border-radius:4px;padding:1px 5px}}
.metric{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:8px}}
.metric div{{background:#f8fafc;border:1px solid {LINE};border-radius:8px;padding:8px;text-align:center}}
.metric b{{display:block;font-size:1.1rem;color:{NAVY}}}
.ft{{color:{MUT};font-size:.75rem;text-align:center;padding:18px 0}}
@media print{{body{{background:#fff}} .btns{{display:none}} section{{break-inside:avoid;border-color:#ddd}} .hd{{-webkit-print-color-adjust:exact}}}}
@media(max-width:760px){{.tiles{{grid-template-columns:repeat(3,1fr)}} .two,.three{{grid-template-columns:1fr}} .metric{{grid-template-columns:repeat(2,1fr)}}}}
"""
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Informe visual — {esc(nombre)} · Observatorio de amplificación</title>
<meta name="description" content="Informe visual del tema {esc(nombre)}: qué se observa, señales, hipótesis alternativas y límites. Señal, no atribución.">
<link rel="canonical" href="https://fimi.viajeinteligencia.com/informes/visual/{esc(tema)}.html">
<meta property="og:type" content="article">
<meta property="og:title" content="Informe visual — {esc(nombre)}">
<meta property="og:description" content="Qué se observa, señales, hipótesis alternativas y límites. Amplificación medida, no coordinación confirmada.">
<meta property="og:url" content="https://fimi.viajeinteligencia.com/informes/visual/{esc(tema)}.html">
<meta property="og:image" content="https://fimi.viajeinteligencia.com/informes/visual/og-{esc(tema)}.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Informe visual — {esc(nombre)}">
<meta name="twitter:image" content="https://fimi.viajeinteligencia.com/informes/visual/og-{esc(tema)}.png">
<style>{css}</style></head><body>
<div class="hd"><div class="wrap">
  <div class="brand">
    <svg width="46" height="46" viewBox="0 0 44 44" aria-hidden="true">
      <g stroke="#93c5fd" stroke-width="1.6" fill="none" opacity=".9">
        <line x1="22" y1="8" x2="9" y2="22"/><line x1="22" y1="8" x2="35" y2="22"/>
        <line x1="9" y1="22" x2="35" y2="22"/><line x1="9" y1="22" x2="16" y2="36"/>
        <line x1="35" y1="22" x2="28" y2="36"/><line x1="16" y1="36" x2="28" y2="36"/>
      </g>
      <g fill="#fff"><circle cx="22" cy="8" r="4"/><circle cx="9" cy="22" r="3.4"/>
        <circle cx="35" cy="22" r="3.4"/><circle cx="16" cy="36" r="3.4"/>
        <circle cx="28" cy="36" r="3.4"/><circle cx="22" cy="22" r="3"/></g>
    </svg>
    <div>
      <div class="eyebrow">FIMI · Inteligencia de fuentes abiertas</div>
      <h1>{esc(nombre)}</h1>
      <div class="sub">Informe visual de observación · generado {esc(now)}</div>
    </div>
  </div>
  <div class="btns">
    <a href="https://fimi.viajeinteligencia.com/#{esc(tema)}">&larr; Radar</a>
    <a href="/informes/{esc(tema)}/" target="_blank">Informe semanal</a>
    <button onclick="window.print()">Imprimir / Guardar PDF</button>
  </div>
</div></div>
<div class="disc">Señal detectada &ne; desinformación confirmada &ne; atribución de actor. Una banda alta es <b>amplificación medida</b>, nunca coordinación confirmada.</div>
<div class="wrap">

<section>
  <h2>Qué está pasando</h2>
  <div class="tiles">{tiles}</div>
  <div class="two" style="margin-top:14px">
    <div><b>Lo más anómalo</b><p class="cs" style="margin-top:6px">{mas_anom_txt or '—'}</p></div>
    <div><b>Resumen del tema</b><p class="cs" style="margin-top:6px">
      Salud del tema: <b>{esc(s.get('max', '—'))}</b>/100 (max) · {len(altos)} en banda alta · {s.get('sync', 0)} sincronías entre cuentas distintas ·
      fuente dominante {esc(_dsrc)} ({_dpct:.0f}%).</p>
      <p class="cs" style="margin-top:2px;color:#94a3b8">«Sincronías entre cuentas distintas» no es lo mismo que la hipótesis H2b (sincronía sin operador): pueden coexistir 0 sincronías y una H2b frecuente.</p></div>
  </div>
  {tema_def}
</section>

<section><div class="two">
  <div><h2>Radar de componentes (mediana del tema)</h2>
    {spider([("Tema (mediana)", med, NAVY), ("Cluster top", (top or {{'coord':0}}), ACCENT)] if top else [("Tema (mediana)", med, NAVY)])}
    <p class="cs">Mediana de {n} clusters. El cluster top se dibuja en azul. Los componentes miden
    dimensiones distintas (0-100) y <b>no</b> suman el score global. <b>Infraestructura y densidad suelen saturar</b> (tope de normalización): valores altos pueden reflejar una comunidad que comparte prensa, no necesariamente un operador.</p>{_radar_tabla}</div>
  <div><h2>Cluster top (mayor score) — {esc(top['label']) if top else '—'}</h2>
    <p class="cs"><span class="chip" style="background:{BAND_COL[bd]}">score {top['ov']:.0f}/100 · {esc(top['banda'])}</span>
    {'' if not top else f"&nbsp; {top['n_au']} cuentas · {top['n_ev']} eventos · núcleo k={top['kc']}"}</p>
    <h3 style="font-size:.85rem;color:{MUT};margin:12px 0 4px">Hipótesis de ESTE cluster (evaluación interna; no probabilidad)</h3>
    {hyp_bars or '<p class="cs">Sin hipótesis registradas.</p>'}
    <p class="cs" style="margin-top:4px;color:#94a3b8">A qué se parece: <b>compatible</b> ≥66 · <b>débil</b> 33–65 · <b>sin soporte</b> &lt;33. No son probabilidades. Las hipótesis se puntúan de forma independiente (pueden aparecer varias como compatibles); no son mutuamente excluyentes.</p>
    <p class="cs" style="margin-top:10px"><b>Atribución:</b> {esc(top['atr']) if top else '—'} · confianza {esc(top['conf']) if top else '—'}
    &middot; <i>las puntuaciones son evaluación interna del sistema; no son probabilidades.</i></p>
  </div>
</div></section>

<section>
  <h2>Ritmo del cluster top y línea base del tema</h2>
  {tl_svg}
  <p class="cs">{ritmo}</p>
  <p class="cs" style="color:#94a3b8">Barras = eventos/día de <b>{esc(top['label']) if top else '—'}</b>; línea = volumen diario del tema (línea base, escala propia). El contraste con la línea base ayuda a separar una <b>reacción al ciclo de noticias</b> de una actividad propia del cluster. «Pico del tema» = día con volumen ≥ percentil 90 del periodo; la línea va en escala propia (independiente de las barras).{_elec_note}</p>
</section>

<section>
  <h2>Lectura del tema y métricas</h2>
  <div class="two">
    <div><p class="cs">{lectura}</p>
      <div class="metric">
        <div><b>{mil(tot_ev)}</b>eventos del tema</div><div><b>{esc(s.get('fuentes', '—'))}</b>fuentes</div>
        <div><b>{n}</b>clusters</div>        <div><b>{mil(kpi.get('n_au_cl', kpi['n_au']))}</b>cuentas</div></div>
      <p class="cs" style="margin-top:10px">{cobertura}</p>
      <p class="cs" style="margin-top:4px;color:#94a3b8">{tamano}</p></div>
    <div>
      <div class="hrow"><div class="hname" style="width:auto;flex:1">Banda de alerta</div>
        <span class="chip" style="background:{BAND_COL[bd]}">{esc(top['banda']) if top else '—'} (max {top['ov']:.0f}/100)</span></div>
      <p class="cs" style="color:#94a3b8">Bandas (score 0-100): Normal &lt;20 · En observación 20-39 · Amplificación anómala 40-59 · Alta 60-79 · Muy alta 80+. La banda es el <b>score global compuesto</b> (sincronía, anomalía, infraestructura y densidad), <b>no</b> el componente de amplificación: un cluster puede estar en banda alta por infraestructura/densidad, no por difusión.</p>
      <div class="hrow"><div class="hname" style="width:auto;flex:1">Amplificación global</div>
        <div class="hbar">{bar(med['amp'], ACCENT)}</div><div class="hval">{med['amp']:.0f}</div></div>
      <h3 style="font-size:.85rem;color:{MUT};margin:12px 0 4px">Señales clave del tema (medianas)</h3>
      {sen}
    </div>
  </div>
</section>

<section><h2>Clusters destacados</h2><div class="three">{cards}</div>
  <p class="cs" style="margin-top:10px">Cada hallazgo enlaza su evidencia exportable (CSV/JSON/GEXF). El detalle técnico completo está en el radar. «<b>muestra pequeña</b>» = menos de 30 eventos: con n bajo la puntuación es más sensible al ruido (mostramos el tamaño de muestra en lugar de un intervalo de confianza, porque la puntuación no es una probabilidad). Los exports (CSV/JSON/GEXF) <b>pseudonimizan</b> las cuentas («cuenta-N») y <b>redactan</b> textos; no incluyen identificadores de cuenta.</p></section>

{paises_html}

<div class="two">
  <section><h2>Dominios que amplifican (top)</h2>{dom_bars}
    <p class="cs" style="margin-top:8px">Dominios más compartidos por las cuentas de los <b>20 clusters de mayor score</b> del tema (no solo del cluster top). Cuentas del cluster compartiendo enlaces del mismo dominio.</p></section>
  <section><h2>Hipótesis más frecuente del tema</h2>
    <p class="cs" style="margin-top:0">Número de clusters cuya hipótesis de <b>mayor puntuación</b> es cada una.
    El tema puede tener una hipótesis más frecuente distinta de la del <b>cluster top</b> (arriba).</p>
    {_dist_dom}
    <p class="cs" style="margin-top:8px">Más frecuente: <b>{esc(dom_h)} · {esc(HYP_ES.get(dom_h,''))}</b> ({dom_h_n} de {n} clusters).</p>
    <p class="cs" style="margin-top:4px;color:#94a3b8">H2b = <b>sincronía temporal alta SIN evidencia de estructura organizada</b> (no atribuye operador). Por eso puede ser la más frecuente del tema y, a la vez, valer 0 en un cluster concreto con estructura —ese puntúa H2 (compatible con coordinación doméstica).</p></section>
</div>

<section style="border-left:5px solid {BAND_COL[bd]}"><h2>Conclusión</h2><p class="cs">{concl}</p>
  <p class="cs" style="margin-top:6px"><b>Señal, no atribución.</b> Actor: UNKNOWN · evaluación: no concluyente. La interpretación final requiere validación externa y análisis experto.</p></section>

</div>
<div class="ft wrap">Informe visual generado con datos del sistema FIMI ({esc(gen)}) ·
<a href="https://fimi.viajeinteligencia.com/metodo.html">método y límites</a></div>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema")
    ap.add_argument("--todos", action="store_true")
    ap.add_argument("--out", default=OUT_DIR)
    a = ap.parse_args()
    names = load_names()
    salud = load_salud()
    temas = ACTIVOS if a.todos else ([a.tema] if a.tema else [])
    if not temas:
        print("indica --tema <slug> o --todos")
        return 2
    os.makedirs(a.out, exist_ok=True)
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    hechos = []
    for tema in temas:
        clusters, kpi = cargar_tema(con, tema)
        if not clusters:
            print("sin clusters:", tema)
            continue
        nombre = names.get(tema, tema)
        html_out = render(tema, nombre, clusters, kpi, salud.get(tema), load_keywords(tema))
        with open(os.path.join(a.out, tema + ".html"), "w", encoding="utf-8") as f:
            f.write(html_out)
        hechos.append((tema, nombre, len(clusters)))
        _h = [w for w in _ASCII_BAD if w in html_out]
        if _h:
            print("AVISO acentos ASCII en %s: %s" % (tema, ", ".join(sorted(set(_h)))), file=sys.stderr)
        print("OK:", os.path.join(a.out, tema + ".html"), len(clusters), "clusters")
    if a.todos and hechos:
        links = "".join(f"<li><a href='{esc(t)}.html'>{esc(nm)}</a> — {n} clusters</li>" for t, nm, n in hechos)
        with open(os.path.join(a.out, "index.html"), "w", encoding="utf-8") as f:
            f.write(f"<!doctype html><meta charset='utf-8'><title>Informes visuales por tema</title>"
                    f"<body style='font-family:sans-serif;max-width:720px;margin:40px auto'>"
                    f"<h1>Informes visuales por tema</h1><ul>{links}</ul>"
                    f"<p><a href='https://fimi.viajeinteligencia.com/'>Volver al radar</a></p>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
