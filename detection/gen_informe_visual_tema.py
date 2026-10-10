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
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "radar.db")
CFG = os.path.join(ROOT, "config.yaml")
SALUD = os.path.join(ROOT, "data", "salud_temas.json")
OUT_DIR = "/var/www/fimi/informes/visual"
ACTIVOS = ["frontera_sur", "oriente_medio", "elecciones", "inteligencia_artificial",
           "eeuu_politica", "sahel", "energia", "defensa_espana", "espana_elecciones"]

# Hipotesis (attribution.py) -> etiqueta en espanol natural (coincide con gen_fimi_html.py)
HYP_ES = {
    "H2": "Coordinacion domestica (con estructura)",
    "H2b": "Sincronizacion sin atribucion de operador",
    "H5": "Sincronia sostenida (sin estructura)",
    "H1": "Viralizacion organica",
    "H3": "Influencia extranjera",
    "H4": "Amplificacion mediatica",
    "H6": "Sin evidencia concluyente",
}
BAND_ES = {"NORMAL": "Normal", "WATCH": "En observacion", "ANOMALOUS": "Amplificacion anomala",
           "HIGH": "Amplificacion alta", "CRITICAL": "Amplificacion muy alta"}
# color por banda (sobrio; rojo solo en CRITICAL)
BAND_COL = {"NORMAL": "#94a3b8", "WATCH": "#0891b2", "ANOMALOUS": "#d97706",
            "HIGH": "#ea580c", "CRITICAL": "#dc2626"}
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
        urls = [x[0] for x in con.execute("SELECT url FROM cluster_events WHERE cluster_id=?", (cid,)).fetchall()]
        doms = {}
        for u in urls:
            h = host(u)
            if h:
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
            "doms": sorted(doms.items(), key=lambda x: -x[1]), "hyps": hyps,
            "atr": atr or "UNKNOWN", "conf": conf or "NO_ATTRIBUTION", "asses": asses or "",
        })
    # KPIs de tema (misma definicion que informe_tema.py)
    ev = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT e.author) FROM events e"
        " JOIN event_temas et ON et.event_id=e.id WHERE et.tema_id=?", (tema,)).fetchone()
    n_ev, n_au = ev[0], ev[1]
    tmin = con.execute(
        "SELECT MIN(e.timestamp) FROM events e JOIN event_temas et ON et.event_id=e.id"
        " WHERE et.tema_id=?", (tema,)).fetchone()[0]
    # cuentas implicadas en CLUSTERS (no todos los autores del tema): misma definicion
    # que la referencia visual; evita la discrepancia autores-vs-cuentas.
    n_au_cl = con.execute(
        "SELECT COUNT(DISTINCT ce.author) FROM cluster_events ce"
        " JOIN clusters c ON c.id=ce.cluster_id WHERE c.tema_id=?", (tema,)).fetchone()[0]
    return clusters, {"n_ev": n_ev, "n_au": n_au, "n_au_cl": n_au_cl, "tmin": tmin}


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


def spider(series):
    # series: list of (label, value 0-100, color). Hexagono con 5 ejes (components).
    axes = [("Coordinacion", "coord"), ("Infraestructura", "infra"), ("Densidad", "dens"),
            ("Amplificacion", "amp"), ("Anomalia", "anom")]
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
            f"role='img' aria-label='Radar de componentes'>"
            f"{''.join(rings)}{''.join(spokes)}{''.join(polys)}{''.join(labels)}</svg>")


def render(tema, nombre, clusters, kpi, salud):
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    n = len(clusters)
    altos = [c for c in clusters if c["ov"] >= 60]
    top = clusters[0] if clusters else None
    mas_anom = max(clusters, key=lambda c: c["anom"]) if clusters else None
    dias = dias_desde(kpi.get("tmin"))
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
        ("clusters", n, "clusters"),
        ("cuentas", kpi.get("n_au_cl", kpi["n_au"]), "en clusters"),
        ("en banda alta", len(altos), "&ge;60"),
        ("hipotesis mas frecuente", dom_h, "%d de %d clusters" % (dom_h_n, n)),
        ("H3 como max", h3, "clusters"),
        ("dias operando", dias, "desde el 1.er evento"),
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
                         f"<div class='hbar'>{bar(sc, '#1d4ed8')}</div><div class='hval'>{sc:.0f}</div></div>")
    # cluster destacados (3)
    destac = clusters[:3]
    cards = ""
    for c in destac:
        ct, _ = hyp_top(c)
        doms_txt = " · ".join(f"{esc(d)}" for d, _ in c["doms"][:3]) or "—"
        cards += (
            f"<div class='ccard'><div class='cchead'><b>{esc(c['label'])}</b>"
            f"<span class='chip' style='background:{BAND_COL[c['banda']]}'>{c['ov']:.0f}/100 · {esc(c['banda'])}</span></div>"
            f"<p class='cs'>{esc(BAND_ES[c['banda']])} · {c['n_au']} cuentas · {c['n_ev']} eventos · nucleo k={c['kc']}</p>"
            f"<p class='cs'><b>Hipotesis top:</b> {esc(ct or '—')} — {esc(HYP_ES.get(ct, '—'))}</p>"
            f"<p class='cs'><b>De que habla:</b> {doms_txt}</p>"
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
    for lab, k in [("Amplificacion", "amp"), ("Coordinacion", "coord"), ("Anomalia", "anom"),
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
        mas_anom_txt = (f"<b>{esc(mas_anom['label'])}</b> "
                        f"<span class='chip' style='background:#fee2e2;color:#b91c1c'>anomalia {mas_anom['anom']:.0f}</span>")
    tot_ev = s.get("eventos", kpi["n_ev"])
    lectura = (f"El sistema observa <b>{n}</b> clusters en el tema. La hipotesis dominante del conjunto es "
               f"<b>{esc(dom_h)}</b> ({esc(HYP_ES.get(dom_h, ''))}) en {dom_h_n} de {n} clusters. "
               f"{h3} clusters muestran senal compatible con influencia extranjera (H3). "
               f"La infraestructura y la densidad de red son altas, pero <b>esto no permite atribuir actor</b>: "
               f"una banda alta es amplificacion medida, no campana confirmada.")
    concl = (f"{esc(BAND_ES[bd])} (max {top['ov']:.0f}/100) con {len(altos)} de {n} clusters en banda alta. "
             f"Senal NO atribuida (actor: UNKNOWN). La interpretacion final requiere validacion externa.")
    css = f"""
*{{box-sizing:border-box}} body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
color:{INK};background:#f5f7fa;line-height:1.5}} .wrap{{max-width:1080px;margin:0 auto;padding:0 18px}}
a{{color:{ACCENT};text-decoration:none}}
.hd{{background:{NAVY};color:#fff;padding:22px 0}} .hd .wrap{{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}}
.hd h1{{margin:0;font-size:1.55rem}} .hd .sub{{opacity:.8;font-size:.85rem;margin-top:4px}}
.btns a,.btns button{{display:inline-block;border:1px solid rgba(255,255,255,.5);color:#fff;background:transparent;
border-radius:8px;padding:9px 14px;font-size:.85rem;cursor:pointer;margin-left:8px}}
.btns a:hover,.btns button:hover{{background:rgba(255,255,255,.12)}}
.disc{{background:#fff7ed;border-bottom:1px solid #fed7aa;color:#9a3412;font-size:.82rem;padding:9px 0;text-align:center}}
section{{background:#fff;border:1px solid {LINE};border-radius:12px;padding:18px 20px;margin:16px 0}}
h2{{font-size:1.05rem;margin:0 0 12px;color:{NAVY}}} .grid{{display:grid;gap:14px}}
.tiles{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}}
.tile{{background:#f8fafc;border:1px solid {LINE};border-radius:10px;padding:12px;text-align:center}}
.tile .k{{font-size:1.5rem;font-weight:800;color:{NAVY}}} .tile .kl{{font-size:.78rem;font-weight:600}}
.tile .ks{{font-size:.68rem;color:{MUT}}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.three{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}
.hrow{{display:flex;align-items:center;gap:8px;margin:5px 0;font-size:.8rem}}
.hcode{{width:38px;font-weight:700;color:{NAVY}}} .hname{{width:210px;color:{MUT}}}
.hbar{{flex:1}} .hval{{width:34px;text-align:right;font-weight:700}}
.drow{{display:flex;align-items:center;gap:8px;margin:4px 0;font-size:.78rem}}
.dname{{width:150px;color:{INK}}} .dbar{{flex:1;background:#eef2f7;border-radius:6px}} .dval{{width:26px;text-align:right;color:{MUT}}}
.ccard{{border:1px solid {LINE};border-radius:10px;padding:12px}} .cchead{{display:flex;justify-content:space-between;align-items:center}}
.chip{{color:#fff;border-radius:999px;padding:2px 10px;font-size:.72rem;font-weight:700}}
.cs{{font-size:.78rem;color:#334155;margin:6px 0 0}} .cact{{margin-top:8px}} .cact a{{margin-right:10px;font-size:.75rem;font-weight:600}}
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
<meta name="description" content="Informe visual del tema {esc(nombre)}: que se observa, senales, hipotesis alternativas y limites. Senal, no atribucion.">
<link rel="canonical" href="https://fimi.viajeinteligencia.com/informes/visual/{esc(tema)}.html">
<meta property="og:type" content="article">
<meta property="og:title" content="Informe visual — {esc(nombre)}">
<meta property="og:description" content="Que se observa, senales, hipotesis alternativas y limites. Amplificacion medida, no coordinacion confirmada.">
<meta property="og:url" content="https://fimi.viajeinteligencia.com/informes/visual/{esc(tema)}.html">
<meta property="og:image" content="https://fimi.viajeinteligencia.com/informes/visual/og-{esc(tema)}.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Informe visual — {esc(nombre)}">
<meta name="twitter:image" content="https://fimi.viajeinteligencia.com/informes/visual/og-{esc(tema)}.png">
<style>{css}</style></head><body>
<div class="hd"><div class="wrap">
  <div><div class="sub">FIMI · Observatorio de amplificacion</div>
  <h1>{esc(nombre)}</h1>
  <div class="sub">Informe visual de observacion · generado {esc(now)}</div></div>
  <div class="btns">
    <a href="https://fimi.viajeinteligencia.com/#{esc(tema)}">&larr; Radar</a>
    <a href="/informes/{esc(tema)}/" target="_blank">Informe semanal</a>
    <button onclick="window.print()">Imprimir / Guardar PDF</button>
  </div>
</div></div>
<div class="disc">Senal detectada &ne; desinformacion confirmada &ne; atribucion de actor. Una banda alta es <b>amplificacion medida</b>, nunca coordinacion confirmada.</div>
<div class="wrap">

<section>
  <h2>Que esta pasando</h2>
  <div class="tiles">{tiles}</div>
  <div class="two" style="margin-top:14px">
    <div><b>Lo mas anomalo</b><p class="cs" style="margin-top:6px">{mas_anom_txt or '—'}</p></div>
    <div><b>Resumen del tema</b><p class="cs" style="margin-top:6px">
      Salud del tema: <b>{esc(s.get('max', '—'))}</b>/100 (max) · {len(altos)} en banda alta · {s.get('sync', 0)} sincronias ·
      fuente dominante {esc(s.get('fuente_top', '—'))} ({esc(s.get('dependencia_pct', '—'))}%).</p></div>
  </div>
</section>

<section><div class="two">
  <div><h2>Radar de componentes (media del tema)</h2>
    {spider([("Tema (media)", med, NAVY), ("Cluster top", (top or {{'coord':0}}), ACCENT)] if top else [("Tema (media)", med, NAVY)])}
    <p class="cs">Media de {n} clusters. El cluster top se dibuja en azul.</p></div>
  <div><h2>Cluster top (mayor score) — {esc(top['label']) if top else '—'}</h2>
    <p class="cs"><span class="chip" style="background:{BAND_COL[bd]}">score {top['ov']:.0f}/100 · {esc(top['banda'])}</span>
    {'' if not top else f"&nbsp; {top['n_au']} cuentas · {top['n_ev']} eventos · nucleo k={top['kc']}"}</p>
    <h3 style="font-size:.85rem;color:{MUT};margin:12px 0 4px">Hipotesis de ESTE cluster (0-100)</h3>
    {hyp_bars or '<p class="cs">Sin hipotesis registradas.</p>'}
    <p class="cs" style="margin-top:10px"><b>Atribucion:</b> {esc(top['atr']) if top else '—'} · confianza {esc(top['conf']) if top else '—'}
    &middot; <i>las puntuaciones son evaluacion interna del sistema; no son probabilidades.</i></p>
  </div>
</div></section>

<section>
  <h2>Lectura del tema y metricas</h2>
  <div class="two">
    <div><p class="cs">{lectura}</p>
      <div class="metric">
        <div><b>{tot_ev:,}</b>eventos</div><div><b>{esc(s.get('fuentes', '—'))}</b>fuentes</div>
        <div><b>{n}</b>clusters</div><div><b>{kpi.get('n_au_cl', kpi['n_au']):,}</b>cuentas</div></div></div>
    <div>
      <div class="hrow"><div class="hname" style="width:auto;flex:1">Banda de alerta</div>
        <span class="chip" style="background:{BAND_COL[bd]}">{esc(top['banda']) if top else '—'} (max {top['ov']:.0f}/100)</span></div>
      <div class="hrow"><div class="hname" style="width:auto;flex:1">Amplificacion global</div>
        <div class="hbar">{bar(med['amp'], ACCENT)}</div><div class="hval">{med['amp']:.0f}</div></div>
      <h3 style="font-size:.85rem;color:{MUT};margin:12px 0 4px">Senales clave del tema (medianas)</h3>
      {sen}
    </div>
  </div>
</section>

<section><h2>Clusters destacados</h2><div class="three">{cards}</div>
  <p class="cs" style="margin-top:10px">Cada hallazgo enlaza su evidencia exportable (CSV/JSON/GEXF). El detalle tecnico completo esta en el radar.</p></section>

<div class="two">
  <section><h2>Dominios que amplifican (top)</h2>{dom_bars}
    <p class="cs" style="margin-top:8px">Cuentas del cluster compartiendo enlaces del mismo dominio.</p></section>
  <section><h2>Hipotesis mas frecuente del tema</h2>
    <p class="cs" style="margin-top:0">Numero de clusters cuya hipotesis de <b>mayor puntuacion</b> es cada una.
    El tema puede tener una hipotesis mas frecuente distinta de la del <b>cluster top</b> (arriba).</p>
    {_dist_dom}
    <p class="cs" style="margin-top:8px">Mas frecuente: <b>{esc(dom_h)} · {esc(HYP_ES.get(dom_h,''))}</b> ({dom_h_n} de {n} clusters).</p></section>
</div>

<section style="border-left:5px solid {BAND_COL[bd]}"><h2>Conclusion</h2><p class="cs">{concl}</p>
  <p class="cs" style="margin-top:6px"><b>Senal, no atribucion.</b> Actor: UNKNOWN · evaluacion: no concluyente. La interpretacion final requiere validacion externa y analisis experto.</p></section>

</div>
<div class="ft wrap">Informe visual generado con datos del sistema FIMI ({esc(gen)}) · amplificacion medida, no coordinacion confirmada ·
<a href="https://fimi.viajeinteligencia.com/metodo.html">metodo y limites</a></div>
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
        html_out = render(tema, nombre, clusters, kpi, salud.get(tema))
        with open(os.path.join(a.out, tema + ".html"), "w", encoding="utf-8") as f:
            f.write(html_out)
        hechos.append((tema, nombre, len(clusters)))
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
