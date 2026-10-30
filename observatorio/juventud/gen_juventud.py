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

# datos estándar para la cabecera y los gráficos
from datetime import date as _date
uniq=sorted({u for x in eps for u in (x.get('fuentes') or [])})
status={}
for x in eps:
    st=((x.get('verificacion') or {}).get('estado') or 'sin estado').strip()
    status[st]=status.get(st,0)+1
types={}
for x in eps:
    t=x.get('tipo_detonante') or 'otros'; types[t]=types.get(t,0)+1
ordered=sorted(eps,key=lambda x:str(x.get('fecha')))
from collections import Counter
bydate={}
for x in ordered: bydate.setdefault(str(x['fecha']),[]).append(x)
dates=sorted(bydate)
def _d(x): return _date.fromisoformat(str(x))
vt=[]
for dt in dates:
    xs=bydate[dt]; n=len(xs); label=f'{n} episodio' if n==1 else f'{n} episodios'
    cities=', '.join(sorted({str(x.get('ciudad','')) for x in xs}))
    links=' · '.join(f'<a href="#{e(x.get("id"))}">{e(x.get("nombre"))}</a>' for x in xs)
    vt.append(f'<div class="vitem"><time>{e(dt)}</time><div><b>{label}</b><p>{e(cities)}</p><p class="muted">{links}</p></div></div>')
timeline_html='<div class="vtimeline">'+''.join(vt)+'</div>'
maxs=max(status.values()) if status else 1
status_bars=''.join(f'<div class="barrow"><span>{e(k)}</span><div class="track"><div class="fill" style="width:{v/maxs*100:.0f}%"></div></div><b>{v}</b></div>' for k,v in status.items())
maxt=max(types.values()) if types else 1
type_bars=''.join(f'<div class="barrow"><span>{e(k)}</span><div class="track"><div class="fill alt" style="width:{v/maxt*100:.0f}%"></div></div><b>{v}</b></div>' for k,v in sorted(types.items()))
doc=f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Protestas juveniles — registro de lo publicado</title><meta name="description" content="Registro de episodios publicados sobre protestas juveniles: fechas, ciudades, convocantes citados, demandas, estado y fuentes."><link rel="canonical" href="https://fimi.viajeinteligencia.com/observatorio/juventud/">
<style>:root{{--a:#0f766e;--i:#1e293b;--m:#64748b;--l:#99f6e4}}*{{box-sizing:border-box}}body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:linear-gradient(180deg,#fff,#f0fdfa);color:var(--i);line-height:1.6}}.wrap{{max-width:980px;margin:0 auto;padding:28px 18px 60px}}.sitehead{{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;border-bottom:1px solid #e2e8f0;padding-bottom:12px;margin-bottom:18px}}.brand{{font-weight:800;text-decoration:none;font-size:1.05rem}}.sitehead nav{{display:flex;gap:6px;flex-wrap:wrap;font-size:.82rem}}.sitehead nav a{{text-decoration:none;padding:4px 7px;border-radius:6px}}.sitehead nav a:hover{{background:#fff7ed}}.share{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0 16px;font-size:.85rem}}.share b{{font-size:.82rem;color:#64748b}}.share a,.share button{{font:inherit;font-size:.8rem;padding:4px 9px;border:1px solid #e2e8f0;border-radius:999px;background:#fff;color:#b45309;text-decoration:none;cursor:pointer}}@media(max-width:700px){{.sitehead{{align-items:flex-start}}.sitehead nav{{font-size:.78rem}}}}a{{color:var(--a)}}h1{{font-size:1.7rem;line-height:1.2;margin:0 0 6px}}h2{{font-size:1.15rem;border-bottom:2px solid var(--l);padding-bottom:5px;margin:28px 0 10px}}h3{{margin:0 0 5px}}.lead{{font-size:1rem;color:#334155}}.muted{{color:var(--m);font-size:.85rem}}.kpis{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:16px 0 20px}}.kpi{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:12px 10px;text-align:center}}.kpi b{{display:block;font-size:1.55rem;color:var(--a);line-height:1.1}}.kpi span{{font-size:.76rem;color:var(--m);display:block;margin-top:3px}}.chart{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;margin:10px 0}}.vtimeline{{position:relative;margin:8px 0 4px;padding-left:26px}}.vtimeline:before{{content:"";position:absolute;left:8px;top:6px;bottom:6px;width:2px;background:#99f6e4}}.vitem{{position:relative;padding:8px 0 12px}}.vitem:before{{content:"";position:absolute;left:-23px;top:14px;width:12px;height:12px;border-radius:50%;background:var(--a);border:2px solid #fff;box-shadow:0 0 0 1px #99f6e4}}.vitem time{{font-weight:800;color:var(--a);font-size:.88rem}}.vitem p{{margin:2px 0 0;font-size:.88rem}}.vitem a{{color:var(--a)}}.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.barrow{{display:grid;grid-template-columns:130px 1fr 24px;gap:8px;align-items:center;font-size:.82rem;margin:7px 0}}.track{{height:12px;background:#e2e8f0;border-radius:6px;overflow:hidden}}.fill{{height:100%;background:#0f766e}}.fill.alt{{background:#14b8a6}}@media(max-width:700px){{.kpis{{grid-template-columns:repeat(2,1fr)}}.grid2{{grid-template-columns:1fr}}}}.box{{background:#f0fdfa;border-left:4px solid var(--a);padding:10px 14px;border-radius:7px}}.event{{background:#fff;border:1px solid #e2e8f0;border-left:4px solid var(--a);border-radius:10px;padding:14px 16px;margin:12px 0}}.eventhead{{display:flex;gap:10px;flex-wrap:wrap;font-size:.78rem;color:var(--m);margin-bottom:8px}}.id{{font-weight:800;color:var(--a)}}.type{{border:1px solid #e2e8f0;padding:1px 7px;border-radius:999px}}.claim{{background:#f0fdfa;padding:8px 10px;border-radius:7px}}details{{margin-top:8px}}li{{margin:4px 0}}.foot{{display:grid;grid-template-columns:1.4fr 1fr 1.2fr;gap:20px;margin-top:40px;border-top:2px solid var(--l);padding-top:22px;color:#334155;font-size:.86rem}}.foot b{{display:block;color:var(--i);margin-bottom:6px}}.foot a{{display:block;text-decoration:none;margin:4px 0;color:var(--a)}}.foot p{{margin:0 0 8px;color:var(--m)}}@media(max-width:750px){{.foot{{grid-template-columns:1fr}}}}.livebox{{background:#fff;border:1px solid #e2e8f0;border-left:4px solid var(--a);border-radius:10px;padding:14px 16px;margin:16px 0}}.live-head{{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:baseline}}.live-head h2{{margin:0;border:0;padding:0;font-size:1.05rem}}.live-meta{{font-size:.78rem;color:var(--m)}}.live-list{{margin:8px 0 0;padding-left:18px}}.live-list li{{margin:6px 0}}.live-note{{font-size:.8rem;color:var(--m);margin:6px 0 0}}footer{{margin-top:34px;border-top:1px solid var(--l);padding-top:16px;color:var(--m);font-size:.82rem}}@media(max-width:600px){{h1{{font-size:1.4rem}}.eventhead{{display:block}}.eventhead span{{margin-right:8px}}}}</style></head><body><div class="wrap"><div class="sitehead"><a class="brand" href="/observatorio/">Observatorio de lo publicado</a><nav><a href="/observatorio/">Inicio</a><a href="/observatorio/ceuta/">Frontera Sur</a><a href="/observatorio/juventud/">Protestas juveniles</a><a href="/observatorio/campana/">Elecciones generales</a><a href="/observatorio/infraestructuras/">Infraestructuras</a><a href="/observatorio/metodo/">Método</a><a href="/observatorio/fuentes/">Fuentes</a><a href="/observatorio/datos/">Datos</a><a href="/observatorio/ayuda/">Ayuda</a><a href="/observatorio/suscribirse/">Avisos</a><a href="/observatorio/sobre/">Sobre</a></nav></div>
<p class="muted">Registro de lo publicado · Protestas juveniles</p><h1>Protestas juveniles: qué publican los medios</h1>
<p class="lead">Seis episodios publicados sobre movilizaciones juveniles. El registro muestra fechas, ciudades, convocantes citados, demandas y fuentes. No confirma autoría, dirección ni intención.</p>
<p class="muted">Actualización: 30-oct-2026 · 6 episodios</p>
<div class="kpis"><div class="kpi"><b>6</b><span>episodios</span></div><div class="kpi"><b>10</b><span>fuentes únicas</span></div><div class="kpi"><b>0</b><span>fuentes primarias</span></div><div class="kpi"><b>5</b><span>secundarias</span></div><div class="kpi"><b>1</b><span>agencia</span></div></div>
<section class="livebox" data-live-topic="protestas_juveniles"><h2>Publicaciones capturadas</h2><p class="muted">Cargando captura automática…</p></section>
<div class="share"><b>Compartir</b><a href="https://twitter.com/intent/tweet?url=https%3A//fimi.viajeinteligencia.com/observatorio/juventud/&text=Protestas%20juveniles%3A%20qu%C3%A9%20publican%20los%20medios" target="_blank" rel="noopener">X</a><a href="https://mastodon.social/share?text=Protestas%20juveniles%3A%20qu%C3%A9%20publican%20los%20medios%20https%3A//fimi.viajeinteligencia.com/observatorio/juventud/" target="_blank" rel="noopener">Mastodon</a><a href="https://bsky.app/intent/compose?text=Protestas%20juveniles%3A%20qu%C3%A9%20publican%20los%20medios%20https%3A//fimi.viajeinteligencia.com/observatorio/juventud/" target="_blank" rel="noopener">Bluesky</a><a href="https://wa.me/?text=Protestas%20juveniles%3A%20qu%C3%A9%20publican%20los%20medios%20https%3A//fimi.viajeinteligencia.com/observatorio/juventud/" target="_blank" rel="noopener">WhatsApp</a><button type="button" onclick="navigator.clipboard.writeText(location.href);this.textContent='Copiado'">Copiar enlace</button></div>
<div class="box"><b>Qué es esto.</b> Un registro de afirmaciones y episodios publicados, no un observatorio de hechos confirmados. Todos los episodios tienen fuentes secundarias; <b>ninguno tiene fuente primaria localizada</b>.</div>
<h2>1. Vista rápida</h2><div class="chart">{timeline_html}</div><div class="grid2"><div class="chart"><h3>Estado de las fuentes</h3>{status_bars}<p class="muted">Ninguna ficha tiene fuente primaria localizada.</p></div><div class="chart"><h3>Tipos de detonante</h3>{type_bars}</div></div>
<h2>2. Episodios publicados</h2>{''.join(rows)}
<h2>3. Qué no puede concluirse</h2><ul><li>No se puede afirmar quién organizó las movilizaciones ni quién dirigió los disturbios.</li><li>No se puede confirmar el número de participantes ni de detenidos con fuente primaria.</li><li>No se puede atribuir una operación de influencia a un actor.</li><li>Una publicación o una mención no equivale a una convocatoria.</li></ul>
<h2>4. Fuentes</h2><p class="muted">Enlaces de prensa, agencias y referencias secundarias utilizadas en las fichas. No son confirmaciones independientes.</p><ul>{source_html}</ul>
<footer class="foot"><div><b>Observatorio de lo publicado</b><p>Registro de afirmaciones, episodios y calendario oficial. No confirma hechos ni atribuye intenciones.</p><p>Actualizado: 30-oct-2026.</p></div><div><b>Secciones</b><a href="/observatorio/">Inicio</a><a href="/observatorio/ceuta/">Frontera Sur</a><a href="/observatorio/juventud/">Protestas juveniles</a><a href="/observatorio/campana/">Elecciones generales</a><a href="/observatorio/infraestructuras/">Infraestructuras</a><a href="/observatorio/metodo/">Método</a><a href="/observatorio/fuentes/">Fuentes</a><a href="/observatorio/datos/">Datos</a><a href="/observatorio/ayuda/">Ayuda</a></div><div><b>Contacto</b><a href="mailto:info-fimi@viajeinteligencia.com">info-fimi@viajeinteligencia.com</a><p>Prensa y correcciones: indica la URL y la fuente.</p><a href="/observatorio/privacidad/">Privacidad</a><a href="/observatorio/admin/" rel="nofollow">Admin</a><p>Software v0.1.0 · DOI anterior: <a href="https://doi.org/10.5281/zenodo.23282710">10.5281/zenodo.23282710</a></p></div></footer>
</div><script src="/observatorio/live.js" defer></script></body></html>'''
doc=doc.replace('cluster','grupo').replace('Clúster','Grupo').replace('amplificación','difusión').replace('coordinación','pauta compartida')
OUT.write_text(doc,encoding='utf-8'); print(OUT)
