#!/usr/bin/env python3
"""elecciones.py — Capítulo "Election Threat Landscape" (opción B, transversal).

Registro dirigido por datos: `data/elecciones.yaml` tiene una fila por proceso
electoral (pais, nombre, fecha, idioma, keywords, estado). Este motor:

  1. Calcula la FASE desde la fecha (modelo EEAS: meses antes / mes electoral /
     72 h / post).
  2. Cruza el corpus (`events`, ventana configurable) por el vocabulario de cada
     fila (país + proceso) y reporta COBERTURA (eventos, fuentes, idioma).
  3. Clasifica esos eventos por ACTOR (rusófono / China / EEUU) y objetivo 5D
     (Dismiss / Distort / Distract / Dismay / Divide) — señal LÉXICA, orientativa.
  4. Muestra en qué temas (`event_temas`) aterrizan.

Salida VISUAL: línea de tiempo (SVG) + barras/chips por elección.
Descriptivo y sin atribución: cuenta y clasifica por palabras, no afirma autoría.
Añadir una elección = añadir una fila (o `elecciones_cli.py alta`).
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

# Actores estatales (señal léxica, orientativa).
ACTORES = {
    "rusófono": ["rusia", "ruso", "rusa", "russian", "russe", "kremlin", "putin",
                 "moscú", "moscow", "sputnik", "lavrov", "actualidad.rt"],
    "China": ["china", "chino", "chinese", "chinois", "beijing", "pequín",
              "xi jinping", "cgtn", "pcch"],
    "EEUU": ["estados unidos", "eeuu", "ee.uu", "united states", "usa", "washington",
             "trump", "casa blanca", "white house"],
}
_ACT_COL = {"rusófono": "#dc2626", "China": "#ea580c", "EEUU": "#2563eb"}

# Objetivos 5D (framework EEAS).
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


def detectar(dias=90, registro_path=None, conn=None):
    cerrar = conn is None
    if conn is None:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
    ahora = int(conn.execute("SELECT strftime('%s','now')").fetchone()[0])
    desde = ahora - dias * 86400

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
            "ejemplo": "",
        })

    eventos = conn.execute(
        "SELECT id, source, title, text FROM events WHERE timestamp >= ?",
        (desde,)).fetchall()
    temas_ev = {}
    for r in conn.execute(
            "SELECT et.event_id, et.tema_id FROM event_temas et JOIN events e"
            " ON e.id=et.event_id WHERE e.timestamp >= ?", (desde,)).fetchall():
        temas_ev.setdefault(r["event_id"], []).append(r["tema_id"])
    if cerrar:
        conn.close()

    for e in eventos:
        txt = (e["title"] or "") + " " + (e["text"] or "")
        tn = _norm(txt)
        toks = _tokens_norm(txt)
        act_hits = [a for a, ap in ACT_PRE.items() if _match_vocab(tn, toks, ap)]
        d_hits = [d for d, dp in D_PRE.items() if _match_vocab(tn, toks, dp)]
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
            if not p["ejemplo"]:
                p["ejemplo"] = (e["title"] or e["text"] or "").strip()[:150]

    salida = []
    for p in prep:
        if p["estado"] == "cerrado":
            continue
        n_ev, n_fu = p["n_ev"], len(p["fuentes"])
        cob, cob_col = _cobertura(n_ev, n_fu)
        salida.append({
            "pais": p["pais"], "nombre": p["nombre"], "fecha": p["fecha"],
            "idioma": p["idioma"], "fase": _fase(p["fecha"], ahora),
            "n_ev": n_ev, "fuentes": n_fu,
            "cobertura": cob, "cobertura_color": cob_col,
            "actores": dict(p["actores"].most_common()),
            "cinco_d": dict(p["cinco_d"].most_common()),
            "temas": dict(p["temas"].most_common(4)),
            "ejemplo": p["ejemplo"],
        })
    salida.sort(key=lambda x: (x["fase"]["dias"] is None,
                               abs(x["fase"]["dias"] or 9e9)))
    return {"dias": dias, "n_eventos": len(eventos), "elecciones": salida}


def _timeline_svg(els, ancho=1000, alto=132):
    """Línea de tiempo: cada elección un punto (color = fase) + marca de 'hoy'."""
    pts = [e for e in els if e["fase"]["dias"] is not None]
    if not pts:
        return ""
    dias = [e["fase"]["dias"] for e in pts]
    lo = min(dias + [0]) - 30
    hi = max(dias + [0]) + 30
    L, R = 90, 70
    W, H = ancho, alto
    y0 = H - 30
    def x(d):
        return L + (d - lo) / (hi - lo) * (W - L - R)
    s = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="display:block" '
         f'font-family="system-ui,sans-serif">']
    s.append(f'<line x1="{x(lo):.0f}" y1="{y0}" x2="{x(hi):.0f}" y2="{y0}" '
             f'stroke="#cbd5e1" stroke-width="2"/>')
    s.append(f'<line x1="{x(0):.0f}" y1="14" x2="{x(0):.0f}" y2="{y0+7}" '
             f'stroke="#dc2626" stroke-width="1.5" stroke-dasharray="4 3"/>')
    s.append(f'<text x="{x(0):.0f}" y="11" font-size="11" fill="#dc2626" '
             f'text-anchor="middle" font-weight="700">hoy</text>')
    for i, e in enumerate(sorted(pts, key=lambda z: z["fase"]["dias"])):
        d = e["fase"]["dias"]
        col = e["fase"]["color"]
        cx = x(d)
        arriba = (i % 2 == 0)
        ly = 34 if arriba else y0 - 12
        s.append(f'<circle cx="{cx:.0f}" cy="{y0}" r="7" fill="{col}" '
                 f'stroke="#fff" stroke-width="2"/>')
        s.append(f'<line x1="{cx:.0f}" y1="{y0-7 if arriba else y0+7}" '
                 f'x2="{cx:.0f}" y2="{ly+4 if arriba else ly-11}" stroke="{col}" '
                 f'stroke-width="1"/>')
        lbl = f'{e["pais"]} · {e["nombre"][:20]}'
        s.append(f'<text x="{cx:.0f}" y="{ly}" font-size="11" fill="#334155" '
                 f'text-anchor="middle" font-weight="700">{lbl}</text>')
        s.append(f'<text x="{cx:.0f}" y="{ly+12}" font-size="10" fill="#94a3b8" '
                 f'text-anchor="middle">{e["fecha"]}</text>')
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


def _html(res):
    els = res.get("elecciones", [])
    if not els:
        return ("<div class='card' id='elecciones'><h3>Election Threat Landscape</h3>"
                "<p class='caption'>Sin elecciones en el registro "
                "(<code>data/elecciones.yaml</code>). Añade una con "
                "<code>elecciones_cli.py alta</code>.</p></div>")
    max_ev = max((e["n_ev"] for e in els), default=1) or 1
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
            f"<div style='font-size:.76rem;color:#64748b;margin-top:4px'>"
            f"<b>actores</b> {_chips(e['actores'], '#2563eb')}</div>"
            f"<div style='font-size:.76rem;color:#64748b;margin-top:2px'>"
            f"<b>5D</b> {_chips(e['cinco_d'], '#7c3aed')}</div>"
            f"<div style='font-size:.76rem;color:#64748b;margin-top:2px'>"
            f"<b>aterriza en</b> {temas}</div>"
            f"<div style='font-size:.74rem;color:#94a3b8;margin-top:4px;"
            f"font-style:italic'>{e['ejemplo']}…</div></div>")
    return (
        f"<div class='card' id='elecciones'><h3>Election Threat Landscape "
        f"(calendario electoral)</h3>"
        f"<p class='caption'>Registro de procesos electorales "
        f"(<code>data/elecciones.yaml</code>). <b>Línea de tiempo</b> por fecha "
        f"(el punto = elección, color = fase; línea roja = hoy). Por elección: "
        f"<b>fase</b> (modelo EEAS: meses antes / mes electoral / 72 h / post), "
        f"<b>cobertura</b> (barra = eventos, color = alta/media/baja), <b>actor</b> "
        f"(rusófono/China/EEUU) y objetivo <b>5D</b> por señal léxica, y en qué temas "
        f"aterriza. <b>Descriptivo, sin atribución</b>: cuenta y clasifica por palabras, "
        f"no afirma autoría. Cobertura baja = faltan feeds de ese país, no ausencia de "
        f"campaña. Ventana: últimos {res.get('dias', 90)} días.</p>"
        f"{_timeline_svg(els)}{filas}"
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
