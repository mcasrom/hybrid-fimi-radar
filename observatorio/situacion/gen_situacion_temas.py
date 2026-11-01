#!/usr/bin/env python3
"""Fichas de situación de Protestas juveniles, Elecciones e Infraestructuras."""
import argparse
import html
import json
import re
import yaml
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_PROTESTAS = ROOT / "data/protestas.yaml"
DEFAULT_CALENDARIO = HERE.parent / "calendario/calendario_oficial.json"
DEFAULT_FEEDS = HERE.parent / "feeds.json"
DEFAULT_SIT = HERE / "situacion_temas.json"
DEFAULT_OUT = HERE.parent


def e(value):
    return html.escape(str(value or ""))


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def domain(url):
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def role_badge(role, label):
    cls = {"primaria": "rp", "oficial": "ro", "agencia": "ra", "medio": "rm",
           "extranjera": "rx", "organizacion": "rg", "referencia": "rr"}.get(role, "rm")
    return f'<span class="chip {cls}">{e(label)}</span>'


def page(title, desc, path, body, accent="#0f766e"):
    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)} — Observatorio de lo publicado</title>
<meta name="description" content="{e(desc)}"><link rel="canonical" href="https://fimi.viajeinteligencia.com{path}">
<meta property="og:type" content="article"><meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="https://fimi.viajeinteligencia.com{path}"><meta property="og:image" content="https://fimi.viajeinteligencia.com/observatorio/og.png">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="https://fimi.viajeinteligencia.com/observatorio/og.png">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Article","headline":"{e(title)}","isPartOf":{{"@type":"WebSite","name":"Observatorio de lo publicado"}}}}</script>
<style>
:root{{--a:{accent};--i:#1e293b;--m:#64748b;--l:#e2e8f0}}
*{{box-sizing:border-box}}body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:linear-gradient(180deg,#fff,#f8fafc);color:var(--i);line-height:1.6}}a{{color:var(--a)}}.wrap{{max-width:1000px;margin:0 auto;padding:28px 18px 60px}}.sitehead{{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;border-bottom:1px solid #e2e8f0;padding-bottom:12px;margin-bottom:18px}}.brand{{font-weight:800;text-decoration:none;font-size:1.05rem}}.sitehead nav{{display:flex;gap:6px;flex-wrap:wrap;font-size:.82rem}}.sitehead nav a{{text-decoration:none;padding:4px 7px;border-radius:6px}}.sitehead nav a:hover{{background:#f8fafc}}h1{{font-size:1.8rem;line-height:1.2;margin:0 0 6px}}h2{{font-size:1.15rem;border-bottom:2px solid var(--l);padding-bottom:5px;margin:28px 0 10px}}h3{{margin:0 0 5px}}.lead{{font-size:1rem;color:#334155;max-width:72ch}}.muted{{color:var(--m);font-size:.84rem}}.hero{{border-left:5px solid var(--a);padding-left:16px;margin:8px 0 18px}}.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}}.kpi{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:12px;text-align:center}}.kpi b{{display:block;font-size:1.5rem;color:var(--a);line-height:1.1}}.kpi span{{font-size:.76rem;color:var(--m)}}.box{{background:#f8fafc;border-left:4px solid var(--a);padding:10px 14px;border-radius:7px;margin:12px 0}}.box.warn{{background:#fff7ed;border-left-color:#b45309}}table{{width:100%;border-collapse:collapse;font-size:.88rem}}th,td{{border-bottom:1px solid #e2e8f0;padding:8px;text-align:left;vertical-align:top}}th{{background:#f8fafc;font-size:.78rem;text-transform:uppercase;color:#475569}}ul{{padding-left:20px}}li{{margin:5px 0}}.event{{background:#fff;border:1px solid #e2e8f0;border-left:4px solid var(--a);border-radius:9px;padding:13px 15px;margin:10px 0}}.eventhead{{display:flex;gap:8px;flex-wrap:wrap;font-size:.78rem;color:var(--m);margin-bottom:6px}}.id{{font-weight:800;color:var(--a)}}.chip{{display:inline-block;font-size:.75rem;padding:2px 7px;border-radius:999px;border:1px solid #e2e8f0;background:#fff}}.ro{{background:#e0f2fe;border-color:#7dd3fc}}.rm{{background:#f8fafc}}.rx{{background:#fef3c7;border-color:#fcd34d}}.rg{{background:#f3e8ff;border-color:#d8b4fe}}.rr{{background:#f1f5f9}}.foot{{display:grid;grid-template-columns:1.4fr 1fr 1.2fr;gap:20px;margin-top:40px;border-top:2px solid var(--l);padding-top:22px;color:#334155;font-size:.86rem}}.foot b{{display:block;color:var(--i);margin-bottom:6px}}.foot a{{display:block;text-decoration:none;margin:4px 0}}.foot p{{margin:0 0 8px;color:var(--m)}}@media(max-width:720px){{.kpis,.foot{{grid-template-columns:1fr}}h1{{font-size:1.45rem}}table{{font-size:.82rem}}}}
</style></head><body><div class="wrap">
<div class="sitehead"><a class="brand" href="/observatorio/">Observatorio de lo publicado</a><nav><a href="/observatorio/">Inicio</a><a href="/observatorio/ceuta/">Frontera Sur</a><a href="/observatorio/juventud/">Protestas juveniles</a><a href="/observatorio/campana/">Elecciones generales</a><a href="/observatorio/infraestructuras/">Infraestructuras</a></nav></div>
{body}
<footer class="foot"><div><b>Observatorio de lo publicado</b><p>Ficha de situación construida sobre datos existentes. No confirma hechos ni atribuye intenciones.</p></div><div><b>Secciones</b><a href="/observatorio/">Inicio</a><a href="/observatorio/metodo/">Método</a><a href="/observatorio/fuentes/">Fuentes</a><a href="/observatorio/datos/">Datos</a></div><div><b>Contacto</b><a href="mailto:info-fimi@viajeinteligencia.com">info-fimi@viajeinteligencia.com</a><a href="/observatorio/privacidad/">Privacidad</a></div></footer>
</div></body></html>'''


def source_table(sit, domains_counts):
    rows = "".join(
        f'<tr><td>{e(d)}</td><td>{role_badge(sit["source_roles"][d]["role"], sit["source_roles"][d]["label"])}</td><td>{n}</td></tr>'
        for d, n in sorted(domains_counts.items())
    )
    return f'<table><thead><tr><th>Dominio</th><th>Papel</th><th>Enlaces</th></tr></thead><tbody>{rows}</tbody></table>'


def youth(topic, protestas_path):
    eps = yaml.safe_load(Path(protestas_path).read_text(encoding="utf-8")) or []
    eps.sort(key=lambda x: str(x.get("fecha")))
    domains = {}
    sources_count = set()
    for ep in eps:
        for url in ep.get("fuentes") or []:
            sources_count.add(url)
            d = domain(url)
            domains[d] = domains.get(d, 0) + 1
    unknown = set(domains) - set(topic["source_roles"])
    if unknown:
        raise SystemExit(f"Fuentes sin clasificar en juventud: {sorted(unknown)}")
    cards = []
    for ep in eps:
        links = "".join(f'<li><a href="{e(u)}" target="_blank" rel="noopener">{e(domain(u))}</a></li>' for u in ep.get("fuentes") or [])
        demands = "".join(f"<li>{e(x)}</li>" for x in ep.get("demandas") or []) or '<li class="muted">No consta.</li>'
        cards.append(f'''<article class="event"><div class="eventhead"><span class="id">{e(ep.get("id"))}</span><span>{e(ep.get("fecha"))} · {e(ep.get("ciudad"))} · {e(ep.get("pais"))}</span><span>{e(ep.get("tipo_detonante"))}</span></div>
<h3>{e(ep.get("nombre"))}</h3><p><b>Qué se publica.</b> {e(ep.get("llamada"))}</p><p><b>Detonante.</b> {e(ep.get("detonante"))}</p><p><b>Convocantes citados.</b> {e(ep.get("convocantes") or "No consta")}</p><p><b>Estado.</b> {e(ep.get("estado"))}</p><p><b>Fuente primaria.</b> {e(ep.get("fuente_primaria") or "No localizada")}</p><details><summary>Demandas y fuentes</summary><ul>{demands}</ul><ul>{links}</ul></details></article>''')
    source_count = len(sources_count)
    body = f'''<div class="hero"><p class="muted">Ficha de situación · {e(topic["fuente"])}</p><h1>{e(topic["titulo"])}</h1><p class="lead">{e(topic["subtitulo"])}. Qué se publica, qué se sabe y qué falta.</p><p class="muted">Actualizada: {e(topic["actualizado"]) if "actualizado" in topic else "2026-11-01"} · Sin relaciones documentadas entre episodios.</p></div>
<div class="kpis"><div class="kpi"><b>{len(eps)}</b><span>episodios</span></div><div class="kpi"><b>{source_count}</b><span>enlaces únicos</span></div><div class="kpi"><b>0</b><span>fuentes primarias</span></div><div class="kpi"><b>0</b><span>relaciones documentadas</span></div></div>
<div class="box"><b>Qué es.</b> Una ficha de situación de los episodios ya curados. No añade hechos, no atribuye autoría y no convierte la coincidencia internacional en coordinación.</div>
<h2>1. Qué se publica</h2>{''.join(f'<p>{e(x)}</p>' for x in topic["resumen"])}
<h2>2. Episodios</h2>{''.join(cards)}
<h2>3. Relaciones</h2><div class="box warn"><b>No hay relaciones documentadas.</b> {e(topic["relation_note"])}</div>
<h2>4. Contradicciones y cifras</h2><ul>{''.join(f'<li>{e(x)}</li>' for x in topic["contradicciones"])}</ul>
<h2>5. Preguntas abiertas</h2><ul>{''.join(f'<li>{e(x)}</li>' for x in topic["preguntas"])}</ul>
<h2>6. Qué no se puede concluir</h2><ul>{''.join(f'<li>{e(x)}</li>' for x in topic["limites"])}</ul>
<h2>7. Fuentes y papel documental</h2>{source_table(topic, domains)}<p class="muted">{source_count} enlaces únicos en {len(domains)} dominios · 0 fuentes primarias · la clasificación describe el tipo de pieza, no su independencia editorial.</p>
<p><a href="/observatorio/juventud/"><b>← Volver al registro de Protestas juveniles</b></a> · <a href="/observatorio/situacion/ceuta/situacion/">Ficha de Frontera Sur</a></p>'''
    return page(topic["titulo"], topic["subtitulo"] + ". Sin relaciones documentadas.", "/observatorio/juventud/situacion/", body, "#0f766e")


def campana(topic, calendario_path):
    cal = load(calendario_path)
    rows = "".join(f'<tr><td>{e(x["fecha"])}</td><td><b>{e(x["hito"])}</b></td><td>{e(x.get("evidencia"))}</td><td><a href="{e(x["fuente"])}" target="_blank" rel="noopener">BOE</a></td></tr>' for x in cal["hitos"])
    domains = {"boe.es": 5}
    source_table_html = "".join(f'<tr><td>{e(d)}</td><td>{role_badge(topic["source_roles"][d]["role"], topic["source_roles"][d]["label"])}</td><td>{n}</td></tr>' for d, n in domains.items())
    body = f'''<div class="hero"><p class="muted">Ficha de situación · calendario oficial</p><h1>{e(topic["titulo"])}</h1><p class="lead">{e(topic["subtitulo"])}. Qué está fijado y qué falta.</p><p class="muted">Actualizada: 2026-11-01 · Jornada: 29-nov-2026 · Fuente: BOE.</p></div>
<div class="kpis"><div class="kpi"><b>{len(cal["hitos"])}</b><span>hitos oficiales</span></div><div class="kpi"><b>1</b><span>documento BOE</span></div><div class="kpi"><b>0</b><span>actos registrados</span></div><div class="kpi"><b>0</b><span>relaciones documentadas</span></div></div>
<div class="box"><b>Qué es.</b> El calendario oficial y los límites del registro. No es un pronóstico, no contiene estimaciones de voto y no convierte actos previstos en actos celebrados.</div>
<h2>1. Qué está fijado</h2>{''.join(f'<p>{e(x)}</p>' for x in topic["resumen"])}
<h2>2. Calendario oficial</h2><table><thead><tr><th>Fecha</th><th>Hito</th><th>Qué acredita</th><th>Fuente</th></tr></thead><tbody>{rows}</tbody></table><p class="muted">Fuente única: <a href="{e(cal["source"]["url"])}" target="_blank" rel="noopener">{e(cal["source"]["documento"])}</a>. Las fechas no se extrapolan.</p>
<h2>3. Actos y campaña</h2><div class="box warn"><b>No consta ningún acto de campaña documentado</b> en este registro a 1-nov-2026. No se inventan sedes, intervinientes ni asistencias.</div>
<h2>4. Relaciones</h2><div class="box warn"><b>No hay relaciones documentadas.</b> {e(topic["relation_note"])}</div>
<h2>5. Preguntas abiertas</h2><ul>{''.join(f'<li>{e(x)}</li>' for x in topic["preguntas"])}</ul>
<h2>6. Qué no se puede concluir</h2><ul>{''.join(f'<li>{e(x)}</li>' for x in topic["limites"])}</ul>
<h2>7. Fuentes y papel documental</h2><table><thead><tr><th>Dominio</th><th>Papel</th><th>Enlaces</th></tr></thead><tbody>{source_table_html}</tbody></table><p class="muted">BOE es fuente primaria del calendario; no confirma actos de campaña ni posiciones políticas.</p>
<p><a href="/observatorio/campana/"><b>← Volver al calendario electoral</b></a> · <a href="/observatorio/ceuta/situacion/">Ficha de Frontera Sur</a></p>'''
    return page(topic["titulo"], topic["subtitulo"] + ". Sin pronósticos.", "/observatorio/campana/situacion/", body, "#b45309")


def infraestructuras(topic, feeds_path):
    try:
        nfeeds = len(load(feeds_path))
    except Exception:
        nfeeds = 95
    sources = "".join(f'<tr><td><a href="{e(x["url"])}" target="_blank" rel="noopener">{e(x["name"])}</a></td><td>{role_badge(x["role"], "Fuente oficial")}</td></tr>' for x in topic["official_sources"])
    domains = {domain(x["url"]): 1 for x in topic["official_sources"]}
    body = f'''<div class="hero"><p class="muted">Ficha de situación · cobertura automática</p><h1>{e(topic["titulo"])}</h1><p class="lead">{e(topic["subtitulo"])}. Qué cubre el registro y qué no puede afirmar.</p><p class="muted">Actualizada: 2026-11-01 · Captura cada 30 minutos · {nfeeds} feeds.</p></div>
<div class="kpis"><div class="kpi"><b>{nfeeds}</b><span>feeds</span></div><div class="kpi"><b>{len(topic["official_sources"])}</b><span>fuentes oficiales</span></div><div class="kpi"><b>0</b><span>datos manuales</span></div><div class="kpi"><b>0</b><span>relaciones documentadas</span></div></div>
<div class="box"><b>Qué es.</b> Una ficha de cobertura: explica qué registra la captura automática y qué fuentes institucionales existen. No confirma incidencias, causas ni responsabilidades.</div>
<h2>1. Qué cubre</h2>{''.join(f'<p>{e(x)}</p>' for x in topic["resumen"])}
<h2>2. Fuentes primarias institucionales</h2><table><thead><tr><th>Fuente</th><th>Papel</th></tr></thead><tbody>{sources}</tbody></table><p class="muted">Una fuente oficial acredita su propia documentación; no es independiente sobre sus fallos.</p>
<h2>3. Relaciones</h2><div class="box warn"><b>No hay relaciones documentadas.</b> {e(topic["relation_note"])}</div>
<h2>4. Preguntas abiertas</h2><ul>{''.join(f'<li>{e(x)}</li>' for x in topic["preguntas"])}</ul>
<h2>5. Qué no se puede concluir</h2><ul>{''.join(f'<li>{e(x)}</li>' for x in topic["limites"])}</ul>
<h2>6. Papel documental</h2>{source_table(topic, domains)}<p class="muted">{len(topic["official_sources"])} fuentes oficiales enlazadas · {nfeeds} feeds de captura · 0 datos manuales · la captura no es una verificación.</p>
<p><a href="/observatorio/infraestructuras/"><b>← Volver al registro de Infraestructuras</b></a> · <a href="/observatorio/ceuta/situacion/">Ficha de Frontera Sur</a></p>'''
    return page(topic["titulo"], topic["subtitulo"] + ". Sin causas verificadas.", "/observatorio/infraestructuras/situacion/", body, "#b45309")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--situacion", type=Path, default=DEFAULT_SIT)
    ap.add_argument("--protestas", type=Path, default=DEFAULT_PROTESTAS)
    ap.add_argument("--calendario", type=Path, default=DEFAULT_CALENDARIO)
    ap.add_argument("--feeds", type=Path, default=DEFAULT_FEEDS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    data = load(args.situacion)
    out = args.out
    generated = []
    builders = {
        "juventud": (youth, args.protestas),
        "campana": (campana, args.calendario),
        "infraestructuras": (infraestructuras, args.feeds),
    }
    for key, (builder, source_path) in builders.items():
        topic = dict(data["topics"][key])
        topic["actualizado"] = data["actualizado"]
        html_doc = builder(topic, source_path)
        path = out / key / "situacion/index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html_doc, encoding="utf-8")
        generated.append(str(path))
    print(" | ".join(generated))


if __name__ == "__main__":
    main()
