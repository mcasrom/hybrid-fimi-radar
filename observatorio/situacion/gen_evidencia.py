#!/usr/bin/env python3
"""Índice de evidencia documental por tema. No añade hechos: ordena estados y vacíos."""
import argparse
import html
import json
import yaml
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OBS = HERE.parent
ROOT = OBS.parent
SIT = OBS / "situacion"
DATA = ROOT / "data"
CAL = OBS / "calendario/calendario_oficial.json"
FRONTERA = SIT / "situacion_frontera_sur.json"
TEMAS = SIT / "situacion_temas.json"
EPS = DATA / "caso_frontera_sur_hibridos/episodios_curados.json"
PROTESTAS = DATA / "protestas.yaml"
OUT_HTML = HERE / "index.html"
OUT_JSON = HERE / "evidencia_temas.json"


def e(x):
    return html.escape(str(x or ""))


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build():
    fr = load(FRONTERA)
    tm = load(TEMAS)
    eps = {x["id"]: x for x in load(EPS)["episodios"]}
    cal = load(CAL)
    youth = yaml.safe_load(PROTESTAS.read_text(encoding="utf-8")) or []
    infra = tm["topics"]["infraestructuras"]

    front = []
    for eid in fr["episode_order"]:
        ep = eps[eid]
        status = fr["episode_status"][eid]
        front.append({
            "id": eid,
            "title": ep.get("titulo") or ep.get("nombre") or eid,
            "status": status,
            "status_label": fr["status_labels"][status],
            "missing": fr["episode_missing"][eid],
        })
    fr_counts = {}
    for x in front:
        fr_counts[x["status"]] = fr_counts.get(x["status"], 0) + 1

    youth_rows = []
    for ep in sorted(youth, key=lambda x: str(x.get("fecha"))):
        ver = ep.get("verificacion") or {}
        youth_rows.append({
            "id": ep.get("id"),
            "title": ep.get("nombre"),
            "date": str(ep.get("fecha")),
            "place": f'{ep.get("ciudad")} · {ep.get("pais")}',
            "state": ver.get("estado", "sin clasificar"),
            "level": ver.get("nivel", ""),
            "primary": ep.get("fuente_primaria") or "No localizada",
            "limit": ver.get("nota") or "Sin nota de verificación.",
            "sources": len(ep.get("fuentes") or []),
        })

    campaign = [{
        "date": h["fecha"],
        "title": h["hito"],
        "document": "BOE · RD 806/2026",
        "url": h["fuente"],
    } for h in cal["hitos"]]

    topics = {
        "frontera_sur": {
            "label": "Frontera Sur",
            "unit": "fichas",
            "n": len(front),
            "primary": 0,
            "pending": fr_counts.get("reportado_sin_primaria", 0) + fr_counts.get("reportado_cifras_prensa", 0),
            "declared": fr_counts.get("declaracion_publica", 0),
            "relations": len(fr.get("relations", [])),
            "reviewed": fr.get("actualizado"),
            "note": "Ninguna de las seis afirmaciones tiene fuente primaria localizada.",
            "items": front,
        },
        "juventud": {
            "label": "Protestas juveniles",
            "unit": "episodios",
            "n": len(youth_rows),
            "primary": 0,
            "pending": len(youth_rows),
            "declared": 0,
            "relations": 0,
            "reviewed": tm.get("actualizado"),
            "note": "Los seis episodios se sostienen en prensa o agencia; no hay documento primario localizado.",
            "items": youth_rows,
        },
        "campana": {
            "label": "Elecciones generales",
            "unit": "hitos",
            "n": len(campaign),
            "primary": 1,
            "pending": 0,
            "declared": 0,
            "relations": 0,
            "reviewed": "2026-11-02",
            "note": "El calendario está acreditado por el BOE; no hay actos de campaña documentados.",
            "items": campaign,
        },
        "infraestructuras": {
            "label": "Infraestructuras",
            "unit": "fuentes oficiales",
            "n": len(infra.get("official_sources", [])),
            "primary": len(infra.get("official_sources", [])),
            "pending": 0,
            "declared": 0,
            "relations": 0,
            "reviewed": tm.get("actualizado"),
            "note": "Una fuente oficial acredita su propia documentación; no confirma que la incidencia haya ocurrido ni su causa.",
            "items": [{"name": x["name"], "url": x["url"], "role": x.get("role", "oficial")} for x in infra.get("official_sources", [])],
        },
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "unit_warning": "Ficha, episodio, hito y fuente oficial no son la misma unidad. No se suman.",
        "topics": topics,
    }


def page(data):
    t = data["topics"]
    fr = t["frontera_sur"]
    yu = t["juventud"]
    ca = t["campana"]
    inf = t["infraestructuras"]

    summary = f'''<table><thead><tr><th>Tema</th><th>Unidad</th><th>Registros</th><th>Documento primario</th><th>Pendientes</th><th>Relaciones</th><th>Revisión</th></tr></thead><tbody>
<tr><td><b>Frontera Sur</b></td><td>fichas</td><td>{fr["n"]}</td><td>{fr["primary"]}</td><td>{fr["pending"]} + {fr["declared"]} declaración</td><td>{fr["relations"]}</td><td>{e(fr["reviewed"])}</td></tr>
<tr><td><b>Protestas juveniles</b></td><td>episodios</td><td>{yu["n"]}</td><td>{yu["primary"]}</td><td>{yu["pending"]}</td><td>{yu["relations"]}</td><td>{e(yu["reviewed"])}</td></tr>
<tr><td><b>Elecciones generales</b></td><td>hitos</td><td>{ca["n"]}</td><td>{ca["primary"]} BOE</td><td>0 actos</td><td>{ca["relations"]}</td><td>{e(ca["reviewed"])}</td></tr>
<tr><td><b>Infraestructuras</b></td><td>fuentes oficiales</td><td>{inf["n"]}</td><td>{inf["primary"]} documentos propios</td><td>no evalúa incidencias</td><td>{inf["relations"]}</td><td>{e(inf["reviewed"])}</td></tr>
</tbody></table>'''

    fr_rows = "".join(
        f'<tr><td><b>{e(x["id"])}</b></td><td>{e(x["title"])}</td><td>{e(x["status_label"])}</td><td>{e(x["missing"])}</td></tr>'
        for x in fr["items"]
    )
    yu_rows = "".join(
        f'<tr><td><b>{e(x["id"])}</b><br><span class="muted">{e(x["date"])} · {e(x["place"])}</span></td><td>{e(x["title"])}</td><td>{e(x["state"])}</td><td>{e(x["primary"])}</td><td>{e(x["limit"])}</td></tr>'
        for x in yu["items"]
    )
    ca_rows = "".join(
        f'<tr><td>{e(x["date"])}</td><td>{e(x["title"])}</td><td><a href="{e(x["url"])}" target="_blank" rel="noopener">{e(x["document"])}</a></td></tr>'
        for x in ca["items"]
    )
    inf_rows = "".join(
        f'<tr><td><a href="{e(x["url"])}" target="_blank" rel="noopener">{e(x["name"])}</a></td><td>Documento propio</td></tr>'
        for x in inf["items"]
    )

    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Evidencia documental — Observatorio de lo publicado</title>
<meta name="description" content="Qué está documentado, qué es secundario y qué falta en Frontera Sur, Protestas juveniles, Elecciones e Infraestructuras.">
<link rel="canonical" href="https://fimi.viajeinteligencia.com/observatorio/evidencia/">
<meta property="og:type" content="article"><meta property="og:title" content="Evidencia documental — Observatorio de lo publicado">
<meta property="og:description" content="Estados de evidencia y vacíos, sin convertir una fuente oficial en prueba de una incidencia.">
<meta property="og:url" content="https://fimi.viajeinteligencia.com/observatorio/evidencia/">
<meta property="og:image" content="https://fimi.viajeinteligencia.com/observatorio/og.png">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="https://fimi.viajeinteligencia.com/observatorio/og.png">
<style>
:root{{--a:#b45309;--i:#1e293b;--m:#64748b;--l:#fde68a;--bg:#fffaf5}}*{{box-sizing:border-box}}body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:linear-gradient(180deg,#fff,var(--bg));color:var(--i);line-height:1.6}}.wrap{{max-width:1040px;margin:0 auto;padding:28px 18px 60px}}a{{color:var(--a)}}h1{{font-size:1.8rem;line-height:1.2;margin:0 0 6px}}h2{{font-size:1.15rem;border-bottom:2px solid var(--l);padding-bottom:5px;margin:30px 0 10px}}.lead{{font-size:1rem;color:#334155;max-width:74ch}}.muted{{color:var(--m);font-size:.84rem}}.box{{background:#fff7ed;border-left:4px solid var(--a);padding:10px 14px;border-radius:7px;margin:12px 0}}table{{width:100%;border-collapse:collapse;font-size:.88rem}}th,td{{border-bottom:1px solid #e2e8f0;padding:8px;text-align:left;vertical-align:top}}th{{background:#f8fafc;font-size:.76rem;text-transform:uppercase;letter-spacing:.04em;color:#475569}}ul{{padding-left:20px}}li{{margin:5px 0}}.foot{{display:grid;grid-template-columns:1.4fr 1fr 1.2fr;gap:20px;margin-top:40px;border-top:2px solid var(--l);padding-top:22px;color:#334155;font-size:.86rem}}.foot b{{display:block;color:var(--i);margin-bottom:6px}}.foot a{{display:block;text-decoration:none;margin:4px 0}}.foot p{{margin:0 0 8px;color:var(--m)}}@media(max-width:760px){{h1{{font-size:1.45rem}}table{{font-size:.8rem}}th,td{{padding:6px}}.foot{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">
<div class="sitehead"><a class="brand" href="/observatorio/">Observatorio de lo publicado</a><nav><a href="/observatorio/">Inicio</a><a href="/observatorio/ceuta/">Frontera Sur</a><a href="/observatorio/juventud/">Protestas juveniles</a><a href="/observatorio/campana/">Elecciones generales</a><a href="/observatorio/infraestructuras/">Infraestructuras</a><a href="/observatorio/eventos/">Acontecimientos</a><a href="/observatorio/metodo/">Método</a><a href="/observatorio/fuentes/">Fuentes</a><a href="/observatorio/datos/">Datos</a></nav></div>
<p class="muted">Observatorio · Evidencia</p><h1>Evidencia documental</h1>
<p class="lead">Qué está documentado, qué es secundario y qué falta. Esta página no mide riesgo ni coordinación: ordena el estado documental de cada unidad.</p>
<div class="box"><b>Regla de lectura.</b> {e(data["unit_warning"])} Una fuente oficial acredita lo que dice el organismo; no demuestra por sí sola que una incidencia haya ocurrido ni su causa.</div>
<h2>1. Resumen por tema</h2>{summary}
<p class="muted">“Documento primario” no significa “hecho confirmado”: indica que existe un documento original localizado. En Infraestructuras se cuentan fuentes oficiales, no incidencias verificadas.</p>
<h2>2. Frontera Sur · fichas</h2><p>{e(fr["note"])}</p><div style="overflow-x:auto"><table><thead><tr><th>Ficha</th><th>Afirmación</th><th>Estado</th><th>Qué falta</th></tr></thead><tbody>{fr_rows}</tbody></table></div>
<h2>3. Protestas juveniles · episodios</h2><p>{e(yu["note"])}</p><div style="overflow-x:auto"><table><thead><tr><th>Episodio</th><th>Qué se publica</th><th>Verificación</th><th>Fuente primaria</th><th>Límite</th></tr></thead><tbody>{yu_rows}</tbody></table></div>
<h2>4. Elecciones generales · hitos</h2><p>{e(ca["note"])}</p><div style="overflow-x:auto"><table><thead><tr><th>Fecha</th><th>Hito</th><th>Documento</th></tr></thead><tbody>{ca_rows}</tbody></table></div><p class="muted">Un hito del BOE no es un acto de campaña. No consta ningún acto documentado.</p>
<h2>5. Infraestructuras · fuentes oficiales</h2><p>{e(inf["note"])}</p><div style="overflow-x:auto"><table><thead><tr><th>Fuente</th><th>Qué acredita</th></tr></thead><tbody>{inf_rows}</tbody></table></div>
<div class="box"><b>Qué no es esta página.</b> No es una verificación de hechos, no atribuye autoría ni intención y no usa clústeres, bandas o puntuaciones. Los vacíos se mantienen visibles.</div>
<footer class="foot"><div><b>Observatorio de lo publicado</b><p>Registro de afirmaciones, episodios y calendario oficial. No confirma hechos ni atribuye intenciones.</p><p>Actualizado: {e(data["generated_at"][:10])}.</p></div><div><b>Secciones</b><a href="/observatorio/">Inicio</a><a href="/observatorio/ceuta/situacion/">Frontera Sur</a><a href="/observatorio/juventud/situacion/">Protestas juveniles</a><a href="/observatorio/campana/situacion/">Elecciones generales</a><a href="/observatorio/infraestructuras/situacion/">Infraestructuras</a><a href="/observatorio/metodo/">Método</a></div><div><b>Contacto</b><a href="mailto:info-fimi@viajeinteligencia.com">info-fimi@viajeinteligencia.com</a><p>Prensa y correcciones: indica la URL y la fuente.</p><a href="/observatorio/privacidad/">Privacidad</a></div></footer>
</div></body></html>'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT_HTML)
    ap.add_argument("--json", type=Path, default=OUT_JSON)
    args = ap.parse_args()
    data = build()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page(data), encoding="utf-8")
    print(f"{args.out} · {args.json}")


if __name__ == "__main__":
    main()
