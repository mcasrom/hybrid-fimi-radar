#!/usr/bin/env python3
"""transversal.py — Pulso transversal: ¿migra una narrativa de dominio? (Fase C).

El informe de la matriz de temas pone el foco en el análisis transversal:
una misma narrativa puede desplazarse entre ámbitos a lo largo del tiempo

    conflicto → energía → economía → migración → política → polarización

Esta capa lo hace OBSERVABLE de forma honesta: para un conjunto de narrativas
ancla (actores/temas que viajan), calcula en cada ventana semanal en qué FAMILIA
temática (A–E, ver docs/TAXONOMIA.md) aterrizan sus eventos, y marca MIGRACIÓN
cuando la familia dominante cambia entre la primera y la última ventana.

Es descriptivo, sin atribución ni causalidad: no dice que A causó B, sino que
la conversación sobre un ancla pasó de concentrarse en un dominio a otro. El
sistema no decide; señala dónde mirar.
"""
import argparse
import collections
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
sys.path.insert(0, str(ROOT))

try:
    from detection.tema_reglas import (
        normalizar as _cl_norm, _tokens as _cl_toks, _matches as _cl_match,
        STOP as _CL_STOP)
except Exception:  # pragma: no cover
    _cl_norm = _cl_toks = _cl_match = None
    _CL_STOP = set()


def _prep_kws(kws):
    """Precalcula tokens de cada keyword UNA vez (evita re-normalizar por evento)."""
    out = []
    for k in kws or []:
        kw = str((k or {}).get("palabra") or "").strip()
        if not kw:
            continue
        out.append(((k or {}).get("tema") or "frontera_sur", _cl_norm(kw), _cl_toks(kw)))
    return out


def _temas_fast(texto, prep):
    """Replica temas_por_contenido pero con keywords ya precalculadas."""
    nt = _cl_norm(texto)
    ntok = [t for t in nt.split() if len(t) > 2 and t not in _CL_STOP]
    temas = set()
    for tema, kw_norm, kw_toks in prep:
        if _cl_match(kw_norm, kw_toks, nt, ntok):
            temas.add(tema)
    return temas

# Familia temática por tema (coincide con narrativas_alineadas / docs/TAXONOMIA.md).
_FAMILIAS = {
    "frontera_sur": "A/E crisis·sociedad",
    "geopolitica_ue_marruecos": "B/C instituciones·recursos",
    "politica_nacional": "B/E instituciones·sociedad",
    "eeuu_politica": "B/D instituciones·tecnología",
    "oriente_medio": "A/C crisis·recursos",
    "sahel": "A/E crisis·sociedad",
}

# Narrativas ancla: actores/temas que tienden a viajar entre dominios. Se
# comparan normalizadas (sin acentos, minúsculas) y por palabra completa.
ANCLAS = [
    "petróleo", "gas", "ormuz", "inflación", "precios", "energía",
    "ucrania", "rusia", "putin", "otan", "sanciones",
    "gaza", "irán", "israel", "hezbollah", "hamas",
    "migración", "inmigración", "ceuta", "melilla", "canarias", "frontera",
    "elecciones", "ultraderecha", "sánchez", "trump", "gobierno",
    "marruecos", "argelia", "sahel", "mali", "níger",
    "ciberseguridad", "ciberataque", "taiwán", "embalses", "incendios", "sequía",
]


def _norm(s):
    s = unicodedata.normalize("NFD", str(s).lower())
    return "".join(c for c in s if not unicodedata.combining(c))


_ANCLAS_N = sorted({_norm(a) for a in ANCLAS})
_ANCLA_RE = re.compile(r"\b(" + "|".join(re.escape(a) for a in _ANCLAS_N) + r")\b")


def cargar_config():
    from detection import tema_reglas
    return tema_reglas.cargar_config()


def _familia_evento(temas):
    """Familia del evento. Sin match de keyword => 'sin clasificar' (no se inventa dominio).

    Prioriza un tema que NO sea el default frontera_sur (que se asigna a los RSS que
    no matchean ninguna keyword), para no leer el default como si fuera 'sociedad'.
    """
    if not temas:
        return "sin clasificar"
    otros = sorted(t for t in temas if t != "frontera_sur")
    t = otros[0] if otros else "frontera_sur"
    return _FAMILIAS.get(t, t)


def detectar(semanas=4, min_eventos=5, min_vol=4, conn=None):
    cerrar = conn is None
    if conn is None:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
    cfg = cargar_config()
    prep = _prep_kws(cfg.get("keywords") or []) if _cl_norm else []
    ahora = int(conn.execute("SELECT strftime('%s','now')").fetchone()[0])
    desde = ahora - semanas * 7 * 86400
    eventos = conn.execute(
        "SELECT id, source, title, text, timestamp FROM events WHERE timestamp >= ?",
        (desde,)).fetchall()
    if cerrar:
        conn.close()

    # term x semana x familia
    conta = collections.defaultdict(lambda: collections.Counter())
    total_sem = collections.Counter()
    for e in eventos:
        txt = (e["title"] or "") + " " + (e["text"] or "")
        tn = _norm(txt)
        encontrados = set(_ANCLA_RE.findall(tn))
        if not encontrados:
            continue
        sem = int((e["timestamp"] - desde) // (7 * 86400))  # 0 = más antiguo
        total_sem[sem] += 1
        fam = _familia_evento(_temas_fast(txt, prep)) if prep else _FAMILIAS["frontera_sur"]
        for a in encontrados:
            conta[a][(sem, fam)] += 1

    filas = []
    for ancla, c in conta.items():
        por_sem = {}
        agg = collections.Counter()
        for sem in range(semanas):
            fams = {k[1]: v for k, v in c.items() if k[0] == sem}
            clasif = {f: v for f, v in fams.items() if f != "sin clasificar"}
            dom = max(clasif, key=clasif.get) if clasif else None
            por_sem[sem] = {"total": sum(fams.values()), "clasif": sum(clasif.values()),
                            "dominante": dom, "fams": fams}
            agg.update(clasif)
        tot_c = sum(agg.values())
        multi = tot_c > 0 and len([f for f, v in agg.items() if v >= 0.2 * tot_c]) >= 2
        # Umbral ADAPTATIVO por ancla: una semana solo cuenta si tiene al menos
        # el 25% del volumen clasificado de su mejor semana (evita que la rampa
        # inicial del corpus o semanas casi vacías marquen falsas migraciones).
        maxsem = max((por_sem[s]["clasif"] for s in range(semanas)), default=0)
        umbral = max(min_vol, int(0.25 * maxsem))
        # Cadena de dominios (solo ventanas por encima del umbral).
        cadena = []
        for s in range(semanas):
            if por_sem[s]["clasif"] >= umbral and por_sem[s]["dominante"]:
                d = por_sem[s]["dominante"]
                if not cadena or cadena[-1] != d:
                    cadena.append(d)
        # Migración: comparación de las DOS semanas más recientes comparables.
        recientes = [s for s in (semanas - 2, semanas - 1)
                     if por_sem[s]["clasif"] >= umbral and por_sem[s]["dominante"]]
        migra = (len(recientes) == 2 and
                 por_sem[recientes[0]]["dominante"] != por_sem[recientes[1]]["dominante"])
        total = sum(por_sem[s]["total"] for s in range(semanas))
        if total < min_eventos:
            continue
        filas.append({
            "ancla": ancla,
            "total": total,
            "por_semana": [por_sem[s] for s in range(semanas)],
            "familias": sorted(agg),
            "multi_dominio": multi,
            "cadena": cadena,
            "migra": migra,
        })
    # Primero las que migran, luego por volumen
    filas.sort(key=lambda f: (not f["migra"], -f["total"]))
    return {"semanas": semanas, "n_eventos": len(eventos),
            "total_ancla_sem": dict(total_sem), "filas": filas[:14]}


def _html(res):
    filas = res.get("filas", [])
    migran = [f for f in filas if f["migra"]]
    if not filas:
        return ("<div class='card'><h3>Pulso transversal (¿migra la narrativa de dominio?)</h3>"
                "<p class='caption'>Sin narrativas ancla con volumen suficiente en la ventana.</p></div>")
    rows = ""
    for f in filas:
        sems = " → ".join(
            f"<span title='{(f['por_semana'][i]['dominante'] or 'sin clasificar')} · "
            f"{f['por_semana'][i]['total']} ev'>{f['por_semana'][i]['total']}</span>"
            for i in range(len(f["por_semana"])))
        badges = ""
        if f.get("multi_dominio"):
            badges += ("<span style='font-size:.7rem;font-weight:700;color:#0e7490;background:#ecfeff;"
                       "border:1px solid #a5f3fc;border-radius:999px;padding:2px 9px;margin-left:6px'>"
                       "◧ multi-dominio</span>")
        if f["migra"]:
            badges += ("<span style='font-size:.7rem;font-weight:700;color:#7c3aed;background:#f5f3ff;"
                       "border:1px solid #ddd6fe;border-radius:999px;padding:2px 9px;margin-left:6px'>"
                       "⚡ migra de dominio</span>")
        cadena = " → ".join(f["cadena"]) if f["cadena"] else "—"
        fams = ", ".join(f["familias"]) if f.get("familias") else "—"
        rows += (f"<div style='margin:8px 0;padding:8px 12px;border:1px solid #e2e8f0;border-radius:8px'>"
                 f"<div style='display:flex;justify-content:space-between;gap:10px;align-items:baseline;flex-wrap:wrap'>"
                 f"<b style='font-size:.88rem;color:#1e293b'>{f['ancla']}</b>"
                 f"<span style='font-size:.78rem;color:#c2410c;font-weight:700'>{f['total']} eventos</span>"
                 f"{badges}</div>"
                 f"<div style='font-size:.74rem;color:#64748b;margin-top:3px'>eventos/semana (antiguo → reciente): "
                 f"{sems}</div>"
                 f"<div style='font-size:.74rem;color:#475569;margin-top:2px'>dominio: {cadena}</div>"
                 f"<div style='font-size:.72rem;color:#94a3b8;margin-top:2px'>familias presentes: {fams}</div></div>")
    n_mig = len(migran)
    return (f"<div class='card' id='pulso-transversal'><h3>Pulso transversal "
            f"(¿migra la narrativa de dominio?)</h3>"
            f"<p class='caption'>Para cada narrativa ancla se cuenta cuántos eventos tiene por semana y en qué "
            f"<b>familia temática</b> aterrizan (A–E, ver docs/TAXONOMIA.md). <b>◧ multi-dominio</b> = el ancla "
            f"vive en ≥2 familias a la vez; <b>⚡ migra de dominio</b> = la familia dominante cambió entre las "
            f"dos semanas más recientes comparables (7d vs 7d): la conversación pasó de un ámbito a otro "
            f"(p. ej. energía → política). Los eventos sin keyword no cuentan como dominio (bucket 'sin "
            f"clasificar'). <b>Descriptivo, no causal</b>: no dice que A causó B. Ventana: "
            f"{res.get('semanas', 4)} semanas · {n_mig} de {len(filas)} anclas migran.</p>"
            f"{rows}</div>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--semanas", type=int, default=4)
    ap.add_argument("--html", action="store_true")
    args = ap.parse_args()
    res = detectar(semanas=args.semanas)
    if args.html:
        print(_html(res))
    else:
        import json
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
