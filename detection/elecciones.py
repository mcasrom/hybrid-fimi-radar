#!/usr/bin/env python3
"""elecciones.py — Capítulo "Election Threat Landscape" (opción B, transversal).

Registro dirigido por datos: `data/elecciones.yaml` tiene una fila por proceso
electoral (pais, nombre, fecha, idioma, keywords, estado). Este motor:

  1. Calcula la FASE desde la fecha (modelo EEAS: meses antes / mes electoral /
     72 h / post).
  2. Cruza el corpus (`events`) por el vocabulario de cada fila (país + proceso)
     y reporta COBERTURA (eventos, fuentes, idioma).
  3. **Cruza con los CLUSTERS** (coordinación): cuántos de esos eventos forman
     parte de un cluster detectado y el score top. ESTA es la señal del radar
     (amplificación coordinada), no el simple recuento.
  4. Clasifica por ACTOR (rusófono / China / EEUU) y objetivo 5D — señal léxica.
  5. Muestra en qué temas (`event_temas`) aterrizan.

Salida VISUAL: línea de tiempo (SVG) + barras/chips por elección.
Descriptivo y sin atribución: cuenta y clasifica por palabras, no afirma autoría.
"""
import argparse
import collections
import datetime
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
REGISTRO = ROOT / "data" / "elecciones.yaml"

ACTORES = {
    "rusófono": ["rusia", "ruso", "rusa", "russian", "russe", "kremlin", "putin",
                 "moscú", "moscow", "sputnik", "lavrov", "actualidad.rt"],
    "China": ["china", "chino", "chinese", "chinois", "beijing", "pequín",
              "xi jinping", "cgtn", "pcch"],
    "EEUU": ["estados unidos", "eeuu", "ee.uu", "united states", "usa", "washington",
             "trump", "casa blanca", "white house"],
}
_ACT_COL = {"rusófono": "#dc2626", "China": "#ea580c", "EEUU": "#2563eb"}

CINCO_D = {
    "Dismiss": ["desmentir", "desmiente", "desmentido", "niega", "falso", "bulo",
                "bulos", "hoax", "fake", "debunk", "desinformación", "mentira"],
    "Distort": ["tergiversa", "manipula", "manipulación", "fuera de contexto",
                "recicla", "deepfake", "descontextualiz", "distorsiona", "montaje"],
    "Distract": ["desvía", "desviar", "cortina de humo", "whataboutism",
                 "señala a", "culpa a"],
    "Dismay": ["amenaza", "amenazas", "miedo", "pánico", "inminente", "terror",
               "alerta"],
    "Divide": ["divide", "división", "polariza", "enfrenta", "crispación",
               "extrem", "ultra"],
}
_BAND_COL = {"CRITICAL": "#dc2626", "HIGH": "#ea580c", "ANOMALOUS": "#d97706",
             "WATCH": "#0e7490", "NORMAL": "#64748b"}

_GREEN = "22c55e"
_GREY = "94a3b8"


def _norm(s):
    s = unicodedata.normalize("NFD", str(s).lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _tokens_norm(texto):
    tn = re.sub(r"[^a-z0-9 ]", " ", _norm(texto))
    return {t for t in tn.split() if len(t) > 1}


def _prep_vocab(vocab):
    out = []
    for term in vocab or []:
        tn = _norm(term)
        if tn:
            out.append((term, tn, " " in tn))
    return out


def _match_vocab(texto_norm, tokens_set, vocab_pre):
    hits = []
    for term, tn, multi in vocab_pre:
        if multi:
            if tn in texto_norm:
                hits.append(term)
        elif tn in tokens_set:
            hits.append(term)
    return hits


ACT_PRE = {a: _prep_vocab(v) for a, v in ACTORES.items()}
D_PRE = {d: _prep_vocab(v) for d, v in CINCO_D.items()}


def _bands():
    try:
        c = yaml.safe_load(open(ROOT / "config.yaml"))
        b = c.get("scoring", {}).get("bands", {})
        return {k: (v[0], v[1]) for k, v in b.items()}
    except Exception:
        return {"NORMAL": (0, 19), "WATCH": (20, 39), "ANOMALOUS": (40, 59),
                "HIGH": (60, 79), "CRITICAL": (80, 100)}


def _banda(score, bands):
    for k in ("CRITICAL", "HIGH", "ANOMALOUS", "WATCH", "NORMAL"):
        lo, hi = bands.get(k, (0, 0))
        if lo <= score <= hi:
            return k
    return "NORMAL"


# Segundo nivel (clasificación, no captura): léxico de "interferencia" para
# separar señal (desinformación/injerencia/coordinación inauténtica) de la
# cobertura electoral normal. Fallback si config.yaml no trae `senal`.
DEFAULT_SENAL = [
    "desinformación", "disinformation", "misinformation", "manipulación",
    "manipular", "interferencia", "interference", "injerencia", "propaganda",
    "operación de influencia", "influence operation", "noticias falsas",
    "fake news", "fake", "bulo", "bulos", "hoax", "troll", "trolls", "bot",
    "bots", "granja de trolls", "troll farm", "coordinado inauténtico",
    "coordinated inauthentic", "inauténtico", "deepfake", "hackeo",
    "ciberataque", "cyberattack", "pucherazo", "fraude electoral",
    "election interference", "foreign interference",
]


def _senal_terms():
    """Léxico de 'interferencia' (2º nivel) desde config; fallback al default."""
    try:
        c = yaml.safe_load(open(ROOT / "config.yaml"))
        s = c.get("temas", {}).get("elecciones", {}).get("senal")
        if s:
            return list(s)
    except Exception:
        pass
    return DEFAULT_SENAL


def cargar_registro(path=None):
    p = Path(path) if path else REGISTRO
    try:
        data = yaml.safe_load(open(p)) or []
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("elecciones") or []
    return [e for e in data if isinstance(e, dict)]


def _fase(fecha, ahora_ts):
    if not fecha:
        return {"nombre": "sin fecha", "dias": None, "color": "#64748b"}
    try:
        d = datetime.datetime.strptime(str(fecha), "%Y-%m-%d").replace(
            tzinfo=datetime.timezone.utc)
    except Exception:
        return {"nombre": "fecha inválida", "dias": None, "color": "#64748b"}
    dias = (d.timestamp() - ahora_ts) / 86400.0
    if dias > 30:
        return {"nombre": "meses antes", "dias": dias, "color": "#0369a1"}
    if dias > 3:
        return {"nombre": "mes electoral", "dias": dias, "color": "#7c3aed"}
    if dias > 0:
        return {"nombre": "72 h antes", "dias": dias, "color": "#dc2626"}
    if dias >= -3:
        return {"nombre": "día de voto / post inmediato", "dias": dias, "color": "#b91c1c"}
    if dias >= -30:
        return {"nombre": "post-electoral", "dias": dias, "color": "#16a34a"}
    return {"nombre": "post-electoral (>1 mes)", "dias": dias, "color": "#64748b"}


def _cobertura(n_ev, n_fu):
    if n_ev >= 100 and n_fu >= 5:
        return "alta", "#16a34a"
    if n_ev >= 30:
        return "media", "#d97706"
    return "baja", "#dc2626"


# Explicaciones alternativas "benignas" (eco/feed/sindicación/movilización): NO deben
# ser el "top" representativo de un proceso electoral (sí cuentan para la cobertura).
BENIGN = {
    "single_source_feed", "syndicated_wire", "mainstream_echo", "single_piece_echo",
    "sustained_amplification", "organic_viral", "automated_non_malicious",
    "legitimate_mobilization", "graph_artifact",
}


def _principal_expl(raw):
    """Código de la explicación principal soportada (o ''), desde el JSON del cluster."""
    try:
        items = json.loads(raw or "[]")
    except Exception:
        return ""
    for it in items:
        if it.get("status") == "supported":
            return it.get("code", "")
    return ""


def detectar(dias=90, registro_path=None, conn=None):
    cerrar = conn is None
    if conn is None:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
    ahora = int(conn.execute("SELECT strftime('%s','now')").fetchone()[0])
    desde = ahora - dias * 86400
    bands = _bands()
    senal_pre = _prep_vocab(_senal_terms())

    prep = []
    for f in cargar_registro(registro_path):
        prep.append({
            "pais": f.get("pais") or "?",
            "nombre": f.get("nombre") or "",
            "fecha": f.get("fecha"),
            "idioma": f.get("idioma") or "?",
            "estado": f.get("estado") or "activo",
            "kw_pre": _prep_vocab(f.get("keywords") or []),
            "n_ev": 0, "fuentes": set(), "temas": collections.Counter(),
            "actores": collections.Counter(), "cinco_d": collections.Counter(),
            "n_cluster": 0, "cluster_ids": set(), "ejemplo": "",
        })

    eventos = conn.execute(
        "SELECT id, timestamp, source, author, url, title, text FROM events"
        " WHERE timestamp >= ?", (desde,)).fetchall()
    temas_ev = {}
    for r in conn.execute(
            "SELECT et.event_id, et.tema_id FROM event_temas et JOIN events e"
            " ON e.id=et.event_id WHERE e.timestamp >= ?", (desde,)).fetchall():
        temas_ev.setdefault(r["event_id"], []).append(r["tema_id"])
    # Clusters actuales (coordinación) + firmas para enlazar evento↔cluster.
    clusters = {}
    for r in conn.execute("SELECT id, cluster_label, tema_id, overall_score,"
                          " alternative_explanations FROM clusters"):
        sc = round(float(r["overall_score"] or 0), 1)
        clusters[r["id"]] = {"label": r["cluster_label"], "tema": r["tema_id"],
                             "score": sc, "banda": _banda(sc, bands),
                             "alt": _principal_expl(r["alternative_explanations"])}
    sig_url, sig_ts = {}, {}
    for r in conn.execute("SELECT cluster_id, author, url, ts FROM cluster_events"):
        a = r["author"] or ""
        if r["url"]:
            sig_url[(a, r["url"])] = r["cluster_id"]
        sig_ts[(a, r["ts"])] = r["cluster_id"]
    # Top clusters del tema `elecciones` (detección real de coordinación electoral)
    # clasificados en 2º nivel: "interferencia" (señal) vs "cobertura" (ruido).
    elec_top = []
    for cid, info in clusters.items():
        if info["tema"] != "elecciones":
            continue
        agg = conn.execute(
            "SELECT COUNT(*) n, COUNT(DISTINCT author) a, COUNT(DISTINCT url) u"
            " FROM cluster_events WHERE cluster_id=?", (cid,)).fetchone()
        evs = conn.execute("SELECT title, text FROM cluster_events WHERE cluster_id=?",
                           (cid,)).fetchall()
        hl, textos = "", []
        for ev in evs:
            t = ((ev["title"] or ev["text"] or "") if ev else "").strip()
            if t:
                textos.append(t)
            if not hl and t:
                hl = t[:130]
        todo = _norm(" ".join(textos))
        hits = _match_vocab(todo, _tokens_norm(todo), senal_pre)
        elec_top.append({"label": info["label"], "score": info["score"],
                         "banda": info["banda"], "cuentas": agg["a"],
                         "ev": agg["n"], "urls": agg["u"], "headline": hl,
                         "tipo": "interferencia" if hits else "cobertura",
                         "senal_hits": hits[:3]})
    # Señal (interferencia) primero; dentro de cada grupo, por score.
    elec_top.sort(key=lambda z: (0 if z["tipo"] == "interferencia" else 1,
                                 -z["score"]))
    _n_int = sum(1 for c in elec_top if c["tipo"] == "interferencia")
    elec_resumen = {"n": len(elec_top), "interferencia": _n_int,
                    "cobertura": len(elec_top) - _n_int}
    if cerrar:
        conn.close()

    for e in eventos:
        txt = (e["title"] or "") + " " + (e["text"] or "")
        tn = _norm(txt)
        toks = _tokens_norm(txt)
        act_hits = [a for a, ap in ACT_PRE.items() if _match_vocab(tn, toks, ap)]
        d_hits = [d for d, dp in D_PRE.items() if _match_vocab(tn, toks, dp)]
        cid = None
        if e["url"]:
            cid = sig_url.get((e["author"] or "", e["url"]))
        if cid is None:
            cid = sig_ts.get((e["author"] or "", e["timestamp"]))
        for p in prep:
            if not _match_vocab(tn, toks, p["kw_pre"]):
                continue
            p["n_ev"] += 1
            p["fuentes"].add(e["source"])
            for t in temas_ev.get(e["id"], ["frontera_sur"]):
                p["temas"][t] += 1
            for a in act_hits:
                p["actores"][a] += 1
            for d in d_hits:
                p["cinco_d"][d] += 1
            if cid is not None and clusters.get(cid, {}).get("tema") == "elecciones":
                p["n_cluster"] += 1
                p["cluster_ids"].add(cid)
            if not p["ejemplo"]:
                p["ejemplo"] = (e["title"] or e["text"] or "").strip()[:150]

    vivas = [p for p in prep if p["estado"] != "cerrado"]
    # Pass 1: top bruto por proceso -> detectar clusters "generales" (top de >=2 procesos).
    _top_count = collections.Counter()
    for p in vivas:
        _raw = [clusters[c] for c in p["cluster_ids"] if c in clusters]
        if _raw:
            _top_count[max(_raw, key=lambda z: z["score"])["label"]] += 1
    generales = {lab for lab, ct in _top_count.items() if ct >= 2}
    salida = []
    for p in vivas:
        n_ev, n_fu = p["n_ev"], len(p["fuentes"])
        cob, cob_col = _cobertura(n_ev, n_fu)
        _raw = [clusters[c] for c in p["cluster_ids"] if c in clusters]
        top_bruto = max(_raw, key=lambda z: z["score"]) if _raw else None
        # Top ESPECÍFICO: excluye clusters generales (top de varios procesos) y de
        # explicación benigna (eco/feed/sindicación). Si no queda ninguno -> None.
        _cands = [c for c in _raw if c["label"] not in generales and c.get("alt") not in BENIGN]
        top = max(_cands, key=lambda z: z["score"]) if _cands else None
        salida.append({
            "pais": p["pais"], "nombre": p["nombre"], "fecha": p["fecha"],
            "idioma": p["idioma"], "fase": _fase(p["fecha"], ahora),
            "n_ev": n_ev, "fuentes": n_fu,
            "cobertura": cob, "cobertura_color": cob_col,
            "n_cluster": p["n_cluster"], "n_clusters": len(p["cluster_ids"]),
            "top": top, "top_bruto": top_bruto,
            "actores": dict(p["actores"].most_common()),
            "cinco_d": dict(p["cinco_d"].most_common()),
            "temas": dict(p["temas"].most_common(4)),
            "ejemplo": p["ejemplo"],
        })
    salida.sort(key=lambda x: (x["fase"]["dias"] is None,
                               abs(x["fase"]["dias"] or 9e9)))
    return {"dias": dias, "n_eventos": len(eventos), "elecciones": salida,
            "elec_top": elec_top[:8], "elec_resumen": elec_resumen}


def _timeline_svg(els, ancho=1000, alto=170):
    pts = [e for e in els if e["fase"]["dias"] is not None]
    if not pts:
        return ""
    # Agrupar por fecha exacta (mismo offset en días): los procesos que caen el
    # mismo día (p. ej. Bosnia + Brasil el 04-oct, Bulgaria + Serbia el 25-oct)
    # comparten marcador para no solapar etiquetas.
    grupos = {}
    for e in pts:
        grupos.setdefault(round(e["fase"]["dias"], 3), []).append(e)
    ds = sorted(grupos.keys())
    lo = min(ds + [0]) - 30
    hi = max(ds + [0]) + 30
    L, R = 84, 84
    W, H = ancho, alto
    y0 = H - 22

    def x(d):
        return L + (d - lo) / (hi - lo) * (W - L - R)

    def _corto(p, n=16):
        p = str(p)
        return p if len(p) <= n else p[:n - 1].rstrip() + "…"

    s = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="display:block" '
         f'font-family="system-ui,sans-serif">']
    s.append(f'<line x1="{x(lo):.0f}" y1="{y0}" x2="{x(hi):.0f}" y2="{y0}" '
             f'stroke="#cbd5e1" stroke-width="2"/>')
    s.append(f'<line x1="{x(0):.0f}" y1="10" x2="{x(0):.0f}" y2="{y0+6}" '
             f'stroke="#dc2626" stroke-width="1.5" stroke-dasharray="4 3"/>')
    s.append(f'<text x="{x(0):.0f}" y="8" font-size="10" fill="#dc2626" '
             f'text-anchor="middle" font-weight="700">hoy</text>')

    FS = 11.0
    CH = FS * 0.58          # ancho medio de carácter (estimación para el layout)
    ROW = 30                # alto de fila
    placed = []             # (fila, x1, x2) ya colocadas, para evitar solapes
    for d in ds:
        g = sorted(grupos[d], key=lambda z: str(z["pais"]))
        cx = x(d)
        paises = " · ".join(_corto(e["pais"]) for e in g)
        fecha = str(g[0]["fecha"])
        wl = max(len(paises), len(fecha)) * CH + 10
        x1, x2 = cx - wl / 2, cx + wl / 2
        fila = 0
        while any(r == fila and not (x2 < px1 - 4 or x1 > px2 + 4)
                  for r, px1, px2 in placed):
            fila += 1
        placed.append((fila, x1, x2))
        col = g[0]["fase"]["color"]
        ly = y0 - 18 - fila * ROW
        full = " · ".join(
            f'{e["pais"]}: {e["nombre"]} ({e["fecha"]}, {e["fase"]["nombre"]})'
            for e in g)
        _has_cl = e.get("n_cluster", 0) > 0
        _cl_color = "#22c55e" if _has_cl else "#94a3b8"
        s.append(f'<circle cx="{cx:.0f}" cy="{y0}" r="7" fill="{col}" '
                 f'stroke="#fff" stroke-width="2"/>')
        s.append(f'<circle cx="{cx:.0f}" cy="{y0}" r="3" fill="{_cl_color}" '
                 f'stroke="#fff" stroke-width="1"/>')
        s.append(f'<line x1="{cx:.0f}" y1="{y0-7}" x2="{cx:.0f}" y2="{ly+3}" '
                 f'stroke="{col}" stroke-width="1"/>')
        s.append(f'<text x="{cx:.0f}" y="{ly}" font-size="{FS}" fill="#334155" '
                 f'text-anchor="middle" font-weight="700"><title>{full}</title>'
                 f'{paises}</text>')
        s.append(f'<text x="{cx:.0f}" y="{ly-12}" font-size="9.5" fill="#94a3b8" '
                 f'text-anchor="middle">{fecha}</text>')
    s.append('</svg>')
    return "".join(s)


def _chips(d, col):
    if not d:
        return "<span style='color:#94a3b8'>—</span>"
    out = []
    for k, v in d.items():
        c = _ACT_COL.get(k, col)
        out.append(f"<span style='font-size:.72rem;font-weight:700;color:{c};"
                   f"background:{c}12;border:1px solid {c}44;border-radius:999px;"
                   f"padding:1px 8px;margin:0 5px 3px 0;display:inline-block'>{k} {v}</span>")
    return "".join(out)


def _coordinacion_html(e):
    if e["n_ev"] == 0:
        return "<span style='color:#94a3b8'>—</span>"
    if e["n_cluster"] == 0:
        return (f"<span style='color:#16a34a;font-weight:700'>sin coordinación "
                f"detectada</span> <span style='color:#94a3b8'>(0 de {e['n_ev']} eventos "
                f"en clusters)</span>")
    tb = e["top"]
    pct = 100.0 * e["n_cluster"] / e["n_ev"]
    if tb is None:
        _br = e.get("top_bruto")
        _brtxt = (f"mayor: <b>{_br['score']:.0f}/100 {_br['banda']}</b> ({_br['label']}) — "
                  f"<b>no específico</b>: general o eco") if _br else "sin cluster específico"
        return (f"<b style='color:#c2410c'>{e['n_cluster']} de {e['n_ev']}</b> ({pct:.0f}%) en "
                f"<b>{e['n_clusters']}</b> cluster(s) · <span style='color:#94a3b8'>{_brtxt}</span>")
    bcol = _BAND_COL.get(tb["banda"], "#64748b")
    extra = (f" · mayor: <b style='color:{bcol}'>{tb['score']:.0f}/100 {tb['banda']}</b> "
             f"<span style='color:#94a3b8'>({tb['label']}, específico)</span>")
    return (f"<b style='color:#c2410c'>{e['n_cluster']} de {e['n_ev']}</b> "
            f"({pct:.0f}%) en <b>{e['n_clusters']}</b> cluster(s){extra}")


def _html(res):
    els = res.get("elecciones", [])
    if not els:
        return ("<div class='card' id='elecciones'><h3>Election Threat Landscape</h3>"
                "<p class='caption'>Sin elecciones en el registro "
                "(<code>data/elecciones.yaml</code>). Añade una con "
                "<code>elecciones_cli.py alta</code>.</p></div>")
    max_ev = max((e["n_ev"] for e in els), default=1) or 1
    # Plain-language executive summary
    _n_with_cl = sum(1 for e in els if e.get("n_cluster", 0) > 0)
    _n_cov = len(els) - _n_with_cl
    _n_clusters_total = sum(e.get("n_cluster", 0) for e in els)
    _n_specific = sum(1 for e in els if e.get("top"))
    exec_txt = (
        f"<div style='margin:0 0 10px;padding:10px 13px;background:#f8fafc;"
        f"border:1px solid #e2e8f0;border-left:5px solid #64748b;border-radius:9px'>"
        f"<b style='color:#1e293b'>Resumen ejecutivo</b> · "
        f"<span style='color:#475569'>"
        f"De <b>{len(els)}</b> procesos en el calendario, "
        f"<b>{_n_with_cl}</b> tienen eventos en clusters del tema "
        f"({_n_clusters_total} eventos; <b>en su mayoría cobertura o eco</b> de prensa). "
        f"De ellos, <b style='color:#c2410c'>{_n_specific}</b> presentan una <b>señal de "
        f"coordinación específica</b> entre cuentas distintas; el resto es difusión "
        f"editorial. <b>{_n_cov}</b> no tienen clusters. "
        f'<span style="color:#b91c1c;font-weight:600">'
        f"⚠ 'menciona interferencia' = el texto contiene términos de "
        f"desinformación (es mención, no prueba de operación).</span></span>"
        f"</div>")
    filas = ""
    for e in els:
        f = e["fase"]
        fase_txt = f["nombre"]
        if f["dias"] is not None:
            fase_txt += (f" · faltan {abs(int(f['dias']))} d"
                         if f["dias"] > 0 else f" · hace {abs(int(f['dias']))} d")
        pct = max(3, int(100 * e["n_ev"] / max_ev))
        temas = " ".join(
            f"<span style='font-size:.72rem;color:#475569;background:#f1f5f9;"
            f"border:1px solid #e2e8f0;border-radius:999px;padding:1px 8px;"
            f"margin:0 5px 3px 0;display:inline-block'>{t} · {n}</span>"
            for t, n in e["temas"].items()) or "<span style='color:#94a3b8'>—</span>"
        filas += (
            f"<div style='margin:10px 0;padding:11px 13px;border:1px solid #e2e8f0;"
            f"border-left:5px solid {f['color']};border-radius:9px'>"
            f"<div style='display:flex;justify-content:space-between;gap:10px;"
            f"align-items:baseline;flex-wrap:wrap'>"
            f"<b style='font-size:.95rem;color:#1e293b'>{e['pais']} · {e['nombre']}</b>"
            f"<span style='font-size:.72rem;font-weight:700;color:{f['color']};"
            f"background:{f['color']}15;border:1px solid {f['color']}44;"
            f"border-radius:999px;padding:2px 10px'>{fase_txt}</span></div>"
            f"<div style='display:flex;align-items:center;gap:10px;margin:8px 0 4px'>"
            f"<div style='flex:1;background:#f1f5f9;border-radius:6px;height:16px;"
            f"overflow:hidden'><div style='width:{pct}%;height:100%;"
            f"background:{e['cobertura_color']};opacity:.75'></div></div>"
            f"<span style='font-size:.8rem;color:#334155;white-space:nowrap'>"
            f"<b>{e['n_ev']}</b> eventos · {e['fuentes']} fuentes · "
            f"<b style='color:{e['cobertura_color']}'>{e['cobertura']}</b></span></div>"
            f"<div style='font-size:.8rem;color:#334155;margin-top:4px;padding:5px 8px;"
            f"background:#fff7ed;border:1px solid #fed7aa;border-radius:7px'>"
            f"<b>coordinación</b> · {_coordinacion_html(e)}</div>"
            f"<div style='font-size:.76rem;color:#64748b;margin-top:4px'>"
            f"<b>actores</b> {_chips(e['actores'], '#2563eb')}</div>"
            f"<div style='font-size:.76rem;color:#64748b;margin-top:2px'>"
            f"<b>5D</b> {_chips(e['cinco_d'], '#7c3aed')}</div>"
            f"<div style='font-size:.76rem;color:#64748b;margin-top:2px'>"
            f"<b>aterriza en</b> {temas}</div>"
            f"<div style='font-size:.74rem;color:#94a3b8;margin-top:4px;"
            f"font-style:italic'>{e['ejemplo']}…</div></div>")
    top_rows = ""
    for c in res.get("elec_top", []):
        bc = _BAND_COL.get(c["banda"], "#64748b")
        interf = c.get("tipo") == "interferencia"
        chip = ("<span style='font-size:.68rem;font-weight:700;color:#b91c1c;"
                "background:#fef2f2;border:1px solid #fecaca;border-radius:999px;"
                "padding:1px 8px'>⚠ menciona interferencia</span>" if interf else
                "<span style='font-size:.68rem;font-weight:700;color:#475569;"
                "background:#f1f5f9;border:1px solid #e2e8f0;border-radius:999px;"
                "padding:1px 8px'>○ cobertura</span>")
        hits = " · ".join(c.get("senal_hits", []))
        extra = (f"<div style='font-size:.7rem;color:#b91c1c;margin-top:2px'>"
                 f"señal: {hits}</div>") if (interf and hits) else ""
        top_rows += (
            f"<div style='margin:6px 0;padding:8px 11px;border:1px solid #e2e8f0;"
            f"border-left:4px solid {bc};border-radius:8px'>"
            f"<div style='display:flex;justify-content:space-between;gap:8px;"
            f"flex-wrap:wrap;align-items:baseline'>"
            f"<b style='font-size:.84rem;color:#1e293b'>{c['label']}</b>"
            f"<span style='display:flex;gap:6px;align-items:center'>{chip}"
            f"<span style='font-size:.78rem;font-weight:700;color:{bc}'>"
            f"{c['score']:.0f}/100 {c['banda']}</span></span></div>"
            f"<div style='font-size:.74rem;color:#64748b;margin-top:2px'>"
            f"{c['cuentas']} cuentas · {c['ev']} eventos · {c['urls']} URLs</div>"
            f"<div style='font-size:.74rem;color:#94a3b8;font-style:italic'>"
            f"{c['headline']}…</div>{extra}</div>")
    if not top_rows:
        top_rows = ("<p class='caption'>Aún no hay clusters del tema "
                    "<code>elecciones</code> (se generan en el ciclo del cron; piloto).</p>")
    rs = res.get("elec_resumen") or {}
    resumen_txt = ""
    if rs:
        _n_uni = res.get("clusters_activos", rs.get("n", 0))
        resumen_txt = (
            f"<div style='margin:0 0 6px'><span style='font-size:.78rem;"
            f"color:#334155;background:#fff7ed;border:1px solid #fed7aa;"
            f"border-radius:7px;padding:2px 9px'>de <b>{_n_uni}</b> clusters activos del "
            f"tema <code>elecciones</code>: "
            f"<b>{rs.get('interferencia', 0)}</b> mencionan interferencia (léxico) · "
            f"<b>{rs.get('cobertura', 0)}</b> cobertura electoral (se listan los "
            f"principales)</span></div>")
    det = ("<h4 style='margin:14px 0 4px;font-size:.9rem;color:#c2410c'>"
           "Coordinación detectada (clusters del tema <code>elecciones</code>)</h4>"
           "<p class='caption' style='margin:0 0 6px'>Coordinación observada en el "
           "contenido electoral (no en el sumidero general). Score/banda = amplificación "
           "coordinada. <b style='color:#b91c1c'>⚠ 2º nivel (léxico)</b>: cada cluster "
           "se marca como <b>menciona interferencia</b> (su texto contiene términos de "
           "desinformación/injerencia — es <b>mención</b>, no prueba de operación) o "
           "<b>cobertura electoral</b> (ruido esperable de campaña). "
           "Un score alto no atribuye: el radar detecta patrones, no actores.</p>"
           + resumen_txt + top_rows)
    return (
        f"<div class='card' id='elecciones'><h3>Election Threat Landscape "
        f"(calendario electoral)</h3>"
        f"<p class='caption'>Registro de procesos electorales "
        f"(<code>data/elecciones.yaml</code>). <b>Línea de tiempo</b> por fecha "
        f"(punto = elección, color = fase; línea roja = hoy). Cada punto lleva "
        f"un indicador: <b style='color:#22c55e'>verde</b> = coordinación detectada, "
        f"<b style='color:#94a3b8'>gris</b> = solo cobertura editorial. "
        f"Por elección: <b>fase</b> (modelo EEAS: meses antes / mes electoral / 72 h / post), "
        f"<b>cobertura</b> (barra = eventos, color = alta/media/baja) y la señal clave: "
        f"<b>coordinación</b> — cuántos de sus eventos forman parte de un <b>cluster "
        f"detectado</b> y el score top. Además, <b>actor</b> (rusófono/China/EEUU) y "
        f"<b>5D</b> por señal léxica, y temas de aterrizaje. "
        f"<b>Descriptivo, sin atribución</b>: cuenta y clasifica por palabras, no afirma "
        f"autoría. Cobertura baja = faltan feeds de ese país, no ausencia de campaña. "
        f"Ventana: últimos {res.get('dias', 90)} días.</p>"
        f"{exec_txt}"
        f"{_timeline_svg(els)}{det}{filas}"
        f"<p class='caption' style='margin-top:6px'>Añadir una elección: "
        f"<code>elecciones_cli.py alta --pais … --nombre … --fecha AAAA-MM-DD "
        f"--keywords \"…\"</code>.</p></div>")



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=90)
    ap.add_argument("--registro", default=None)
    ap.add_argument("--html", action="store_true")
    args = ap.parse_args()
    res = detectar(dias=args.dias, registro_path=args.registro)
    if args.html:
        print(_html(res))
    else:
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
