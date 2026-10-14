#!/usr/bin/env python3
"""consulta.py — «¿esto es orgánico, eco de prensa o amplificación anómala?»

Dada una URL (o un dominio), busca en el radar los grupos que la contienen y
devuelve una LECTURA EN LENGUAJE LLANO: cuántas cuentas DISTINTAS la comparten,
la banda, si es un medio conocido (y si es estatal) y la explicación dominante
(eco de prensa, feed de una fuente, amplificación entre cuentas…). Read-only.

Uso:
  .venv/bin/python detection/consulta.py "https://ejemplo.com/noticia"
  .venv/bin/python detection/consulta.py ejemplo.com --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "radar.db"
BASE_URL = "https://fimi.viajeinteligencia.com"

BAND_ES = {"NORMAL": "Normal", "WATCH": "En observación", "ANOMALOUS": "Amplificación anómala",
           "HIGH": "Amplificación alta", "CRITICAL": "Amplificación muy alta"}

LECTURA = {
    "single_source_feed": ("Difusión de una sola fuente", "Una cuenta o dominio concentra el contenido: suele ser alguien compartiendo su propio sitio, NO coordinación.", "bajo"),
    "syndicated_wire": ("Sindicación de prensa", "El mismo texto de agencia republicado por varios medios. Eco informativo, no coordinación.", "bajo"),
    "mainstream_echo": ("Eco de prensa", "Medios establecidos cubriendo el mismo tema. La señal más habitual y benigna.", "bajo"),
    "single_piece_echo": ("Eco de una pieza", "Un solo contenido difundido; sin patrón de red.", "bajo"),
    "cross_account_synchrony": ("Amplificación anómala entre cuentas", "Varias cuentas DISTINTAS, ninguna dominante, repiten lo mismo a la vez. Es la señal que MÁS merece revisión (no es prueba de campaña).", "alta"),
    "sustained_amplification": ("Amplificación sostenida", "Mismo patrón, pero extendido en el tiempo (eco lento).", "media"),
    "synchronized_without_operator": ("Sincronía sin operador", "Coincidencia temporal sin estructura organizada aparente.", "media"),
    "automated_non_malicious": ("Automatización no maliciosa", "Bot o publicación automática, sin intención de campaña.", "bajo"),
    "organic_viral": ("Viralización orgánica", "Muchas cuentas distintas difunden de forma dispersa; el patrón de lo espontáneo.", "bajo"),
    "legitimate_mobilization": ("Movilización legítima", "Cuentas activistas/ciudadanas compartiendo una causa.", "bajo"),
    "unresolved": ("Sin causa clara", "Ninguna explicación benigna lo cubre del todo → en revisión humana.", "media"),
}


def _dominio(entrada):
    e = (entrada or "").strip()
    if "://" not in e:
        e = "http://" + e
    return (urlparse(e).netloc or "").lower().replace("www.", "")


def _es_medio(dom):
    try:
        from detection import mainstream as _ms
        return any(dom == m or dom.endswith("." + m) for m in _ms.MAINSTREAM)
    except Exception:
        return False


def _es_estatal(dom):
    try:
        d = json.loads((ROOT / "data" / "medios_estatales.json").read_text(encoding="utf-8"))
        return any(dom == k or dom.endswith("." + k) for k in (d.get("dominios") or {}))
    except Exception:
        return False


def _principal(expl_raw):
    try:
        items = json.loads(expl_raw or "[]")
    except Exception:
        items = []
    return (next((x for x in items if x.get("status") == "supported"), None)
            or next((x for x in items if x.get("status") == "plausible"), None)
            or {"code": "unresolved", "label": "Sin causa clara", "evidence": {}})


def consulta(entrada):
    dom = _dominio(entrada)
    r = {"entrada": entrada, "dominio": dom, "es_medio": _es_medio(dom), "es_estatal": _es_estatal(dom),
         "grupos": [], "n_eventos": 0, "n_cuentas": 0, "explicaciones": {}, "veredicto": None}
    if not dom:
        r["veredicto"] = {"titulo": "Entrada vacía", "texto": "Pasa una URL o un dominio.", "riesgo": "n/a"}
        return r
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    r["n_cuentas"] = con.execute(
        "SELECT COUNT(DISTINCT author) FROM cluster_events WHERE url LIKE ?", (f"%{dom}%",)).fetchone()[0]
    filas = con.execute(
        "SELECT ce.cluster_id cid, COUNT(*) n_ev, COUNT(DISTINCT ce.author) n_aut "
        "FROM cluster_events ce WHERE ce.url LIKE ? GROUP BY ce.cluster_id", (f"%{dom}%",)).fetchall()
    for f in filas:
        cl = con.execute("SELECT cluster_label, tema_id, overall_score, narrative_subtype, "
                         "alternative_explanations FROM clusters WHERE id=?", (f["cid"],)).fetchone()
        if not cl:
            continue
        expl = _principal(cl["alternative_explanations"])
        lect = LECTURA.get(expl.get("code"), LECTURA["unresolved"])
        try:
            sub = json.loads(cl["narrative_subtype"] or "{}")
        except Exception:
            sub = {}
        r["n_eventos"] += f["n_ev"]
        r["grupos"].append({
            "label": cl["cluster_label"], "tema": cl["tema_id"], "score": round(float(cl["overall_score"] or 0)),
            "explicacion": expl.get("code"), "explicacion_label": expl.get("label"),
            "rol": (sub or {}).get("dominant"), "lectura": lect[0], "detalle": lect[1], "riesgo": lect[2],
            "n_eventos": f["n_ev"], "n_cuentas": f["n_aut"]})
    con.close()
    r["explicaciones"] = dict(Counter(g["explicacion_label"] for g in r["grupos"]).most_common())
    r["roles"] = dict(Counter(g["rol"] for g in r["grupos"] if g["rol"]).most_common())
    r["grupos"].sort(key=lambda g: -g["score"])

    if not r["grupos"]:
        r["veredicto"] = {"titulo": "No aparece en el radar", "riesgo": "n/a", "banda": "—", "score": 0,
                          "texto": "Ningún grupo de esta captura contiene enlaces a ese dominio. NO es una valoración de su veracidad: el radar solo mira donde puede (Bluesky + prensa) y una parte de esta web es desconocida para él."}
    elif r["es_medio"] or r["es_estatal"]:
        r["veredicto"] = {"titulo": "Eco informativo de un medio" + (" estatal" if r["es_estatal"] else ""),
                          "riesgo": "bajo", "banda": "—", "score": r["grupos"][0]["score"],
                          "texto": "Es un medio de prensa conocido: su contenido circula como cobertura informativa (eco), no como coordinación. Es el patrón más habitual en el radar."}
    else:
        top = r["explicaciones"] and next(iter(r["explicaciones"])) or "Sin causa clara"
        code = next((g["explicacion"] for g in r["grupos"] if g["explicacion_label"] == top), "unresolved")
        lect = LECTURA.get(code, LECTURA["unresolved"])
        g = r["grupos"][0]
        r["veredicto"] = {"titulo": lect[0], "texto": lect[1], "riesgo": lect[2],
                          "banda": BAND_ES.get("CRITICAL" if g["score"] >= 80 else "HIGH" if g["score"] >= 60
                                               else "ANOMALOUS" if g["score"] >= 40 else "WATCH" if g["score"] >= 20 else "NORMAL"),
                          "score": g["score"]}
    return r


def _print(r):
    dom = r["dominio"]
    typ = "medio de prensa" if r["es_medio"] else "dominio no listado como medio"
    if r["es_estatal"]:
        typ += " · estatal"
    print(f"🔗 Consulta: {r['entrada']}")
    print(f"   Dominio: {dom}  ({typ})")
    if not r["grupos"]:
        print(f"\n{r['veredicto']['titulo']}.\n   {r['veredicto']['texto']}")
    else:
        print(f"\n   Compartido por {r['n_cuentas']} cuentas distintas · {r['n_eventos']} piezas · "
              f"{len(r['grupos'])} grupos\n   Explicaciones: " +
              " · ".join(f"{k} ({v})" for k, v in r["explicaciones"].items()))
        if r["roles"]:
            print("   Rol narrativo: " + " · ".join(f"{k} ({v})" for k, v in r["roles"].items()))
        print(f"\n📣 Lectura: {r['veredicto']['titulo']}\n   {r['veredicto']['texto']}")
        if r["veredicto"].get("banda") and r["veredicto"]["banda"] != "—":
            print(f"   Banda del grupo principal: {r['veredicto']['banda']} ({r['veredicto']['score']}/100).")
    print("\n⚖️ Señal, no atribución. El radar mide comportamiento (amplificación), no veracidad ni autoría.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entrada")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = consulta(a.entrada)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        _print(r)


if __name__ == "__main__":
    main()
