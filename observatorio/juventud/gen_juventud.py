#!/usr/bin/env python3
import html, yaml, re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; OUT=Path(__file__).with_name('index.html')
eps=yaml.safe_load((ROOT/'data/protestas.yaml').read_text(encoding='utf-8')) or []
def e(x): return html.escape(str(x or ''))
def clean(x): return e(x).replace('cluster','grupo').replace('Clúster','Grupo').replace('amplificación','difusión').replace('coordinación','pauta compartida')
def links(ep):
    out=[]
    for u in ep.get('fuentes') or []:
        out.append(f'<li><a href="{e(u)}" target="_blank" rel="noopener">{e(u)}</a></li>')
    return ''.join(out) or '<li>No consta enlace.</li>'
rows=[]; timeline=[]; sources=set()
for x in eps:
    city=e(x.get('ciudad')); country=e(x.get('pais')); date=e(x.get('fecha')); title=e(x.get('nombre'))
    demands=''.join(f'<li>{clean(d)}</li>' for d in (x.get('demandas') or [])) or '<li>No consta.</li>'
    for u in x.get('fuentes') or []: sources.add(u)
    rows.append(f'''<article class="event" id="{e(x.get('id'))}">
<div class="eventhead"><span class="id">{e(x.get('id'))}</span><span class="type">{e(x.get('tipo_detonante'))}</span><span class="period">{date} · {city} · {country}</span></div>
<h3>{title}</h3>
<p class="claim"><b>Qué se publica.</b> {clean(x.get('llamada'))}</p>
<p><b>Detonante citado.</b> {clean(x.get('detonante'))}</p>
<p><b>Convocantes citados.</b> {clean(x.get('convocantes') or 'No consta')}</p>
<p><b>Estado.</b> {clean(x.get('estado'))}</p>
<p><b>Fuente primaria.</b> {clean(x.get('fuente_primaria') or 'No consta')}</p>
<details><summary>Demandas citadas y fuentes</summary><ul>{demands}</ul><ul>{links(x)}</ul><p class="muted">Verificación: {clean((x.get('verificacion') or {}).get('nota'))}</p></details>
</article>''')
    timeline.append(f'<li><a href="#{e(x.get("id"))}"><b>{date}</b> · {city} · {title}</a></li>')
source_html=''.join(f'<li><a href="{e(u)}" target="_blank" rel="noopener">{e(u)}</a></li>' for u in sorted(sources))
doc=f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Protestas juveniles — registro de lo publicado</title><meta name="description" content="Registro de episodios publicados sobre protestas juveniles: fechas, ciudades, convocantes citados, demandas, estado y fuentes.">
<style>:root{{--a:#0f766e;--i:#1e293b;--m:#64748b;--l:#99f6e4}}*{{box-sizing:border-box}}body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:linear-gradient(180deg,#fff,#f0fdfa);color:var(--i);line-height:1.6}}.wrap{{max-width:980px;margin:0 auto;padding:28px 18px 60px}}a{{color:var(--a)}}h1{{font-size:1.7rem;line-height:1.2;margin:0 0 6px}}h2{{font-size:1.15rem;border-bottom:2px solid var(--l);padding-bottom:5px;margin:28px 0 10px}}h3{{margin:0 0 5px}}.lead{{font-size:1rem;color:#334155}}.muted{{color:var(--m);font-size:.85rem}}.box{{background:#f0fdfa;border-left:4px solid var(--a);padding:10px 14px;border-radius:7px}}.event{{background:#fff;border:1px solid #e2e8f0;border-left:4px solid var(--a);border-radius:10px;padding:14px 16px;margin:12px 0}}.eventhead{{display:flex;gap:10px;flex-wrap:wrap;font-size:.78rem;color:var(--m);margin-bottom:8px}}.id{{font-weight:800;color:var(--a)}}.type{{border:1px solid #e2e8f0;padding:1px 7px;border-radius:999px}}.claim{{background:#f0fdfa;padding:8px 10px;border-radius:7px}}details{{margin-top:8px}}li{{margin:4px 0}}footer{{margin-top:34px;border-top:1px solid var(--l);padding-top:16px;color:var(--m);font-size:.82rem}}@media(max-width:600px){{h1{{font-size:1.4rem}}.eventhead{{display:block}}.eventhead span{{margin-right:8px}}}}</style></head><body><div class="wrap">
<p class="muted">Registro de lo publicado · Protestas juveniles</p><h1>Protestas juveniles: qué publican los medios</h1>
<p class="lead">Seis episodios publicados sobre movilizaciones juveniles. El registro muestra fechas, ciudades, convocantes citados, demandas y fuentes. No confirma autoría, dirección ni intención.</p>
<p class="muted">Actualización: 30-oct-2026 · 6 episodios</p>
<div class="box"><b>Qué es esto.</b> Un registro de afirmaciones y episodios publicados, no un observatorio de hechos confirmados. Todos los episodios tienen fuentes secundarias; <b>ninguno tiene fuente primaria localizada</b>.</div>
<h2>1. Cronología de publicaciones</h2><ul>{''.join(timeline)}</ul>
<h2>2. Episodios publicados</h2>{''.join(rows)}
<h2>3. Qué no puede concluirse</h2><ul><li>No se puede afirmar quién organizó las movilizaciones ni quién dirigió los disturbios.</li><li>No se puede confirmar el número de participantes ni de detenidos con fuente primaria.</li><li>No se puede atribuir una operación de influencia a un actor.</li><li>Una publicación o una mención no equivale a una convocatoria.</li></ul>
<h2>4. Fuentes</h2><p class="muted">Enlaces de prensa, agencias y referencias secundarias utilizadas en las fichas. No son confirmaciones independientes.</p><ul>{source_html}</ul>
<footer>Datos fechados a 30-oct-2026. No se ha inventado ningún convocante, motivo, fecha o lugar. · <a href="/">Volver</a></footer>
</div></body></html>'''
doc=doc.replace('cluster','grupo').replace('Clúster','Grupo').replace('amplificación','difusión').replace('coordinación','pauta compartida')
OUT.write_text(doc,encoding='utf-8'); print(OUT)
