#!/usr/bin/env python3
"""indicadores.py — Ejes transversales e indicadores explícitos (Fase A).

Dos capas de lectura, ambas de solo lectura sobre la BD:

1. EJES TRANSVERSALES (taxonomía, ver docs/TAXONOMIA.md): lentes que cruzan
   temas. Se escanea el volumen reciente buscando vocabulario de cada eje
   (elecciones, energía, clima/agua, ciberseguridad) y se reporta cuánto
   volumen hay, en cuántas fuentes y en qué temas aterriza. Un eje NO es un
   tema: sirve para ver una dimensión compartida sin ampliar la captura.

2. INDICADORES EXPLÍCITOS de amplificación y coordinación: se resumen los
   clusters activos por su forma (eco de una pieza / ráfaga / coordinación
   sostenida), separado del score. Es la misma semántica que ya usan las
   tarjetas del dashboard, aquí agregada como indicador.

El sistema no atribuye: solo describe forma y volumen. La decisión (añadir un
tema, investigar) es humana.
"""
import argparse
import collections
import re
import sqlite3
import unicodedata
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"

# Ejes transversales: vocabulario de la dimensión. Normalizado en runtime.
EJES = {
    "Elecciones e interferencia democrática": [
        "elecciones", "electoral", "voto", "votantes", "urnas", "fraude electoral",
        "midterms", "interferencia electoral", "desinformación electoral",
        "deslegitimar resultados", "election interference", "ballot", "voting fraud",
        "elecciones generales", "campaña electoral",
    ],
    "Energía / precios": [
        "petróleo", "gas", "gasoducto", "lng", "brent", "opep", "opec", "energía",
        "electricidad", "tarifa eléctrica", "precio del gas", "inflación",
        "oil", "pipeline", "ormuz", "gas natural",
    ],
    "Clima / agua / incendios": [
        "sequía", "embalse", "embalses", "agua", "incendio", "incendios", "dana",
        "inundación", "inundaciones", "clima", "temperatura", "wildfire", "drought",
        "flood", "ola de calor",
    ],
    "Ciberseguridad e información": [
        "ciberataque", "ciberataques", "ransomware", "phishing", "hackeo", "hackers",
        "sabotaje", "ciberseguridad", "ciberdefensa", "cyberattack", "brecha de datos",
        "filtración de datos",
    ],
}


def _norm(s):
    s = unicodedata.normalize("NFD", str(s).lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _prep_vocab(vocab):
    """Precalcula (término, normalizado, es_multipalabra) UNA vez (no por evento)."""
    out = []
    for term in vocab:
        tn = _norm(term)
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


EJES_PRE = {nombre: _prep_vocab(v) for nombre, v in EJES.items()}


def cargar_config():
    try:
        return yaml.safe_load(open(ROOT / "config.yaml"))
    except Exception:
        return {}


def _tokens_norm(texto):
    tn = re.sub(r"[^a-z0-9 ]", " ", _norm(texto))
    return {t for t in tn.split() if len(t) > 1}


def _indicadores_clusters(conn):
    """Resume los clusters activos por su forma (no por su score)."""
    try:
        rows = conn.execute(
            "SELECT c.cluster_label, c.tema_id, c.overall_score,"
            " COUNT(*) n_ev, COUNT(DISTINCT ce.author) n_cuentas,"
            " COUNT(DISTINCT ce.url) n_urls,"
            " (MAX(ce.ts)-MIN(ce.ts))/3600.0 horas"
            " FROM clusters c JOIN cluster_events ce ON ce.cluster_id=c.id"
            " GROUP BY c.id").fetchall()
    except Exception:
        return {"resumen": {}, "top": []}
    resumen = collections.Counter()
    top = []
    for r in rows:
        n_ev, n_c, n_u = r["n_ev"], r["n_cuentas"], r["n_urls"]
        horas = r["horas"] or 0
        if n_u <= 1 and n_ev >= 2:
            tipo = "eco_1_pieza"
        elif n_ev >= 10 and horas >= 24 and n_u >= 3:
            tipo = "coordinacion_sostenida"
        elif n_ev >= 5 and horas <= 6:
            tipo = "rafaga"
        else:
            continue
        resumen[tipo] += 1
        top.append({
            "label": r["cluster_label"], "tema": r["tema_id"],
            "score": round(float(r["overall_score"] or 0), 1),
            "n_ev": n_ev, "n_cuentas": n_c, "n_urls": n_u,
            "horas": round(horas, 1), "tipo": tipo,
        })
    top.sort(key=lambda x: -x["score"])
    return {"resumen": dict(resumen), "top": top[:6]}


def detectar(dias=14, conn=None):
    cerrar = conn is None
    if conn is None:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
    ahora = int(conn.execute("SELECT strftime('%s','now')").fetchone()[0])
    desde = ahora - dias * 86400

    eventos = conn.execute(
        "SELECT id, source, title, text FROM events WHERE timestamp >= ?",
        (desde,)).fetchall()
    # mapa event_id -> temas
    temas_ev = {}
    for r in conn.execute(
            "SELECT et.event_id, et.tema_id FROM event_temas et JOIN events e"
            " ON e.id=et.event_id WHERE e.timestamp >= ?", (desde,)).fetchall():
        temas_ev.setdefault(r["event_id"], []).append(r["tema_id"])
    ind = _indicadores_clusters(conn)
    if cerrar:
        conn.close()

    ejes = {}
    for e in eventos:
        txt = (e["title"] or "") + " " + (e["text"] or "")
        tn = _norm(txt)
        toks = _tokens_norm(txt)
        for nombre, vocab_pre in EJES_PRE.items():
            hits = _match_vocab(tn, toks, vocab_pre)
            if not hits:
                continue
            d = ejes.setdefault(nombre, {
                "eje": nombre, "eventos": 0, "fuentes": set(),
                "temas": collections.Counter(), "terminos": collections.Counter(),
                "ejemplo": ""})
            d["eventos"] += 1
            d["fuentes"].add(e["source"])
            for t in temas_ev.get(e["id"], ["frontera_sur"]):
                d["temas"][t] += 1
            for h in hits:
                d["terminos"][h] += 1
            if not d["ejemplo"]:
                d["ejemplo"] = (e["title"] or e["text"] or "").strip()[:150]

    salida = []
    for nombre, d in ejes.items():
        salida.append({
            "eje": nombre,
            "eventos": d["eventos"],
            "fuentes": len(d["fuentes"]),
            "temas": dict(d["temas"].most_common(4)),
            "terminos": [t for t, _ in d["terminos"].most_common(6)],
            "ejemplo": d["ejemplo"],
        })
    salida.sort(key=lambda x: -x["eventos"])
    return {"dias": dias, "ejes": salida, "indicadores": ind}


def _html(res):
    ejes = res.get("ejes", [])
    ind = res.get("indicadores", {})
    ind_rows = ""
    resumen = ind.get("resumen", {})
    _lbl = {"eco_1_pieza": ("eco de 1 pieza", "#7c3aed"),
            "rafaga": ("ráfaga", "#dc2626"),
            "coordinacion_sostenida": ("coordinación sostenida", "#d97706")}
    chips = ""
    for k, (lab, col) in _lbl.items():
        n = resumen.get(k, 0)
        if n:
            chips += (f"<span style='font-size:.74rem;font-weight:700;color:{col};"
                      f"background:#f8fafc;border:1px solid {col}33;border-radius:999px;"
                      f"padding:2px 10px;margin-right:6px'>{lab}: {n}</span>")
    if not chips:
        chips = "<span class='caption'>Sin clusters activos con forma relevante.</span>"
    ind_rows = (f"<div style='margin:4px 0 12px'>{chips}</div>")

    eje_rows = ""
    for e in ejes:
        temas = " · ".join(f"{t} ({n})" for t, n in e["temas"].items())
        terms = ", ".join(f"<i>{t}</i>" for t in e["terminos"][:5])
        eje_rows += (
            f"<div style='margin:8px 0;padding:8px 12px;border:1px solid #e2e8f0;border-radius:8px'>"
            f"<div style='display:flex;justify-content:space-between;gap:10px;align-items:baseline;flex-wrap:wrap'>"
            f"<b style='font-size:.88rem;color:#1e293b'>{e['eje']}</b>"
            f"<span style='font-size:.78rem;color:#c2410c;font-weight:700'>{e['eventos']} eventos · "
            f"{e['fuentes']} fuentes</span></div>"
            f"<div style='font-size:.74rem;color:#64748b;margin-top:3px'>aterriza en: {temas or '—'}</div>"
            f"<div style='font-size:.74rem;color:#64748b;margin-top:2px'>vocabulario: {terms}</div>"
            f"<div style='font-size:.76rem;color:#94a3b8;margin-top:3px;font-style:italic'>"
            f"{e['ejemplo']}…</div></div>")
    if not eje_rows:
        eje_rows = ("<p class='caption'>Sin volumen transversal detectado en la ventana "
                    "(o el vocabulario no matchea).</p>")

    return (
        f"<div class='card' id='ejes-transversales'><h3>Ejes transversales e indicadores</h3>"
        f"<p class='caption'>Los <b>ejes</b> son lentes que cruzan temas (un eje NO es un tema): "
        f"se cuenta el volumen reciente que usa su vocabulario, en cuántas fuentes y en qué temas "
        f"aterriza. Los <b>indicadores</b> resumen la forma de los clusters activos (separada del "
        f"score): eco de una pieza, ráfaga o coordinación sostenida. Dato descriptivo, sin "
        f"atribución. Ventana: últimos {res.get('dias', 14)} días.</p>"
        f"{ind_rows}{eje_rows}"
        f"<p class='caption' style='margin-top:6px'>Un eje con volumen alto y multi-fuente es "
        f"candidato a <b>tema propio</b> (decisión humana, <code>config.yaml</code>).</p>"
        f"</div>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=14)
    ap.add_argument("--html", action="store_true")
    args = ap.parse_args()
    res = detectar(dias=args.dias)
    if args.html:
        print(_html(res))
    else:
        import json
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
