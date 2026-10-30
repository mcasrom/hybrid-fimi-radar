#!/usr/bin/env python3
import json, html, re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
EP=ROOT/'data/caso_frontera_sur_hibridos/episodios_curados.json'
V1=ROOT/'docs/casos/ceuta-v1.json'
OUT=Path(__file__).with_name('index.html')
e=json.loads(EP.read_text(encoding='utf-8')); v1=json.loads(V1.read_text(encoding='utf-8'))
def esc(x): return html.escape(str(x or ''))
def urls(txt):
    return re.findall(r'https?://[^\s)]+', txt or '')

def tipo_grupo(t):
    t=(t or '').lower()
    if 'militar' in t: return 'Militar'
    if 'fronterizo' in t or 'migratorio' in t: return 'Migratorio'
    if 'político' in t or 'discursivo' in t: return 'Político'
    if 'defensa' in t: return 'Defensa'
    return 'Otros'

def timeline_svg(eps):
    w,h=940,230; pad=50; n=len(eps); step=(w-2*pad)/(n-1)
    colors={'Militar':'#b45309','Migratorio':'#0f766e','Político':'#7c3aed','Defensa':'#0369a1','Otros':'#64748b'}
    out=[f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Cronología de afirmaciones publicadas" style="width:100%;height:auto;display:block">']
    out.append(f'<line x1="{pad}" y1="105" x2="{w-pad}" y2="105" stroke="#cbd5e1" stroke-width="2"/>')
    for i,x in enumerate(eps):
        cx=pad+i*step; ty=80 if i%2==0 else 125
        c=colors.get(tipo_grupo(x.get('tipo')),'#64748b')
        out.append(f'<circle cx="{cx:.1f}" cy="105" r="8" fill="{c}" stroke="#fff" stroke-width="3"/>')
        out.append(f'<text x="{cx:.1f}" y="{ty}" text-anchor="middle" font-size="11" font-weight="700" fill="#334155">{html.escape(str(x.get("id",""))[-3:])}</text>')
        out.append(f'<text x="{cx:.1f}" y="{ty-15}" text-anchor="middle" font-size="10" fill="#64748b">{html.escape(str(x.get("periodo","")))}</text>')
    out.append('</svg>')
    return ''.join(out)
def source_items(ep):
    links=[]
    for s in ep.get('fuente',[]):
        u=re.search(r'(https?://[^\s)]+)',s)
        if u: links.append((u.group(1), re.sub(r'https?://[^\s)]+','',s).strip(' ()·')))
    return links
# Narrativas: agrupación editorial explícita sobre los seis episodios
groups=[
 ('Presión militar y naval',['CUR-2026-001','CUR-2026-002','CUR-2026-003'],'Titulares que sitúan movimiento naval, drones o capacidad militar cerca de Ceuta.'),
 ('Defensa aérea y rearme',['CUR-2026-006'],'Reportes sobre la negociación o compra de un sistema israelí de defensa aérea.'),
 ('Presión migratoria',['CUR-2026-004'],'Cobertura sobre flujos migratorios, empadronamientos y presión en la frontera.'),
 ('Controversia política',['CUR-2026-005'],'Declaraciones de actores políticos sobre la actuación del Gobierno.'),
]
byid={x['id']:x for x in e['episodios']}
cards=[]
tipos={}
for _x in e['episodios']:
    _g=tipo_grupo(_x.get('tipo')); tipos[_g]=tipos.get(_g,0)+1
timeline=timeline_svg(e['episodios'])
max_tipo=max(tipos.values()) if tipos else 1
tipo_bars=''.join(f'<div class="barrow"><span>{k}</span><div class="track"><div class="fill" style="width:{v/max_tipo*100:.0f}%"></div></div><b>{v}</b></div>' for k,v in sorted(tipos.items()))
for x in e['episodios']:
    links=source_items(x)
    src=''.join(f'<li><a href="{esc(u)}" target="_blank" rel="noopener">{esc(t or u)}</a></li>' for u,t in links) or '<li>No consta enlace.</li>'
    cards.append(f'''<article class="event" id="{esc(x['id'])}">
<div class="eventhead"><span class="id">{esc(x['id'])}</span><span class="type">{esc(x.get('tipo'))}</span><span class="period">{esc(x.get('periodo'))}</span></div>
<h3>{esc(x.get('titulo'))}</h3>
<p class="claim"><b>Qué se afirma.</b> {esc(x.get('afirmacion'))}</p>
<p><b>Actores citados.</b> {esc(x.get('actores') or 'No consta')}</p>
<p><b>Estado.</b> <span class="status">{esc(x.get('estado_verificacion'))}</span></p>
<p><b>Fuente primaria.</b> {esc(x.get('fuente_primaria') or 'No consta')}</p>
<details><summary>Fuentes y límites</summary><ul>{src}</ul><p><b>Explicación alternativa.</b> {esc(x.get('explicacion_alternativa') or 'No consta')}</p><p><b>Límites.</b> {esc(x.get('limites') or 'No consta')}</p></details>
</article>''')
# cronología por periodo declarado
cron=''.join(f'<li><b>{esc(x.get("periodo"))}</b> · <a href="#{esc(x.get("id"))}">{esc(x.get("titulo"))}</a> <span class="muted">({esc(x.get("id"))})</span></li>' for x in e['episodios'])
# actores
actors=[]
for x in e['episodios']:
    actors.append(f'<li><b>{esc(x.get("id"))}</b> — {esc(x.get("actores") or "No consta")}</li>')
# narrativas
narr=[]
for name,ids,desc in groups:
    titles=' · '.join(f'{i}: {esc(byid[i]["titulo"])}' for i in ids if i in byid)
    narr.append(f'<article class="narr"><h3>{esc(name)}</h3><p>{esc(desc)}</p><p class="muted">{titles}</p></article>')
# fuentes únicas
seen=set(); srcs=[]
for x in e['episodios']:
    for u,t in source_items(x):
        if u not in seen:
            seen.add(u); srcs.append((u,t))
src_html=''.join(f'<li><a href="{esc(u)}" target="_blank" rel="noopener">{esc(t or u)}</a></li>' for u,t in srcs)
cov=v1.get('cobertura_plataforma',{})
html_doc=f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Registro de lo publicado — Ceuta y Marruecos</title>
<meta name="description" content="Registro de lo que publican los medios sobre Ceuta y Marruecos: afirmaciones, fuentes, respuesta oficial y límites.">
<style>
:root{{--accent:#b45309;--ink:#1e293b;--muted:#64748b;--bg:#fffaf5;--line:#fde68a}}
*{{box-sizing:border-box}}body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:linear-gradient(180deg,#fff,var(--bg));color:var(--ink);line-height:1.6}}
.wrap{{max-width:980px;margin:0 auto;padding:28px 18px 60px}}a{{color:var(--accent)}}
header{{border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:22px}}h1{{font-size:1.75rem;line-height:1.2;margin:0 0 6px}}h2{{font-size:1.15rem;border-bottom:2px solid var(--line);padding-bottom:5px;margin:30px 0 10px}}h3{{margin:0 0 6px}}.lead{{font-size:1rem;color:#334155}}.muted{{color:var(--muted);font-size:.85rem}}.status{{background:#fffbeb;border:1px solid #fcd34d;padding:2px 7px;border-radius:6px;font-size:.86rem}}.event{{background:#fff;border:1px solid #e2e8f0;border-left:4px solid var(--accent);border-radius:10px;padding:14px 16px;margin:12px 0}}.eventhead{{display:flex;gap:10px;flex-wrap:wrap;font-size:.78rem;color:var(--muted);margin-bottom:8px}}.id{{font-weight:800;color:var(--accent)}}.type{{border:1px solid #e2e8f0;padding:1px 7px;border-radius:999px}}.claim{{background:#fff7ed;padding:8px 10px;border-radius:7px}}.narr{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:9px;padding:12px 14px;margin:10px 0}}.timeline{{overflow-x:auto;margin:10px 0 16px}}.timeline svg{{min-width:760px}}.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.barrow{{display:grid;grid-template-columns:150px 1fr 26px;gap:8px;align-items:center;font-size:.82rem;margin:6px 0}}.track{{height:12px;background:#e2e8f0;border-radius:6px;overflow:hidden}}.fill{{height:100%;background:#b45309}}.fill.alt{{background:#d97706}}@media(max-width:650px){{.grid2{{grid-template-columns:1fr}}.barrow{{grid-template-columns:1fr 1fr 22px}}}}table{{width:100%;border-collapse:collapse;font-size:.9rem}}th,td{{border-bottom:1px solid #e2e8f0;padding:7px;text-align:left}}details{{margin-top:8px}}li{{margin:4px 0}}.box{{background:#fff7ed;border-left:4px solid var(--accent);padding:10px 14px;border-radius:7px}}footer{{margin-top:34px;border-top:1px solid var(--line);padding-top:16px;color:var(--muted);font-size:.82rem}}@media(max-width:600px){{h1{{font-size:1.4rem}}.timeline{{overflow-x:auto}}.eventhead{{display:block}}.eventhead span{{margin-right:8px}}}}
</style></head><body><div class="wrap">
<header><p class="muted">Registro de lo publicado · Ceuta y Marruecos</p><h1>Ceuta y Marruecos: qué publican los medios</h1><p class="lead">Registro de afirmaciones publicadas por medios y de la respuesta oficial. No confirma que los hechos hayan ocurrido.</p><p class="muted">Actualización: 30-oct-2026 · Periodo de las fichas: 7-sep → 21-oct-2026</p></header>
<div class="box"><b>Qué es esto.</b> Un registro de lo que publican los medios sobre Ceuta y Marruecos. No es un observatorio de hechos ni una verificación de la realidad. Cada ficha indica qué se afirma, quién lo publica, qué respuesta oficial existe —o no— y qué no puede concluirse.</div>
<h2>1. Qué es este registro</h2><p>Se recogen seis afirmaciones publicadas: movimiento naval, drones, presión migratoria, declaraciones políticas y una posible compra de defensa aérea. La cobertura es periodística. No hay confirmación primaria localizada ni fuentes marroquíes suficientes para sostener una atribución.</p><p class="muted">No consta una operación de influencia confirmada. No se afirma que las afirmaciones sean falsas: se indica que no están verificadas.</p>
<h2>2. Vista rápida</h2><p class="muted">Cronología editorial de las seis afirmaciones publicadas. Los puntos ordenan los periodos declarados; no son una escala temporal exacta.</p><div class="timeline">{timeline}</div><div class="grid2"><div class="narr"><h3>Estado de las fichas</h3><div class="barrow"><span>Declaración documentada</span><div class="track"><div class="fill" style="width:17%"></div></div><b>1</b></div><div class="barrow"><span>Pendiente de contraste</span><div class="track"><div class="fill alt" style="width:83%"></div></div><b>5</b></div><p class="muted">Ninguna ficha tiene fuente primaria localizada.</p></div><div class="narr"><h3>Tipos de afirmación</h3>{tipo_bars}<p class="muted">Clasificación editorial a partir del tipo declarado en cada ficha.</p></div></div><h2>3. Afirmaciones publicadas</h2><p class="muted">Cada ficha separa la afirmación, los actores citados, el estado y la fuente primaria disponible. «Pendiente» no significa falso.</p>{''.join(cards)}
<h2>4. Cronología de publicaciones</h2><ul>{cron}</ul><p class="muted">Los periodos son los declarados en las fichas; no se convierten en fechas exactas si la fuente no las da.</p>
<h2>5. Actores y posiciones</h2><ul>{''.join(actors)}</ul><p class="muted">La mención de un actor no acredita que convocara, ordenara o participara en una acción.</p>
<h2>6. Versiones y temas</h2><p class="muted">Agrupación editorial de las afirmaciones de las fichas, no una conclusión sobre su veracidad.</p>{''.join(narr)}
<h2>7. Fuentes y cobertura</h2><ul>{src_html}</ul>
<p class="muted">Cobertura analizada en la auditoría V1 (30-jul→21-sep-2026): {esc(cov.get('bluesky'))} publicaciones de Bluesky, {esc(cov.get('prensa_rss'))} de prensa RSS, {esc(cov.get('otras_rss'))} de otras RSS y {esc(cov.get('telegram'))} de Telegram. No se presentan como confirmaciones independientes. Todas las fichas enlazan a medios; no se ha localizado una fuente institucional o primaria verificable para los episodios militares.</p>
<h2>8. Respuesta oficial y verificación</h2><table><tr><th>Comprobación V1</th><th>Resultado</th></tr><tr><td>Enlaces compartidos por ≥2 cuentas</td><td>{esc(v1.get('compartidas_2cuentas'))}</td></tr><tr><td>Porcentaje de enlaces de medios</td><td>{esc(v1.get('pct_medios'))} %</td></tr><tr><td>Casos con coordinación en validación ciega</td><td>{esc(v1.get('validacion_ciega',{}).get('con_coordinacion'))} de {esc(v1.get('validacion_ciega',{}).get('evaluables'))} evaluables ({esc(v1.get('validacion_ciega',{}).get('pct'))} %)</td></tr><tr><td>Ráfagas confirmadas</td><td>{esc(v1.get('rafagas',{}).get('confirmadas'))} de {esc(v1.get('rafagas',{}).get('total'))}</td></tr></table><p class="muted">{esc(v1.get('limites'))}</p>
<h2>9. Límites y preguntas abiertas</h2><ul><li>Falta una confirmación primaria de la fragata, del dron y del sistema de defensa aérea.</li><li>La versión oficial citada para el episodio naval lo califica de patrullaje ordinario; la discrepancia debe mantenerse visible.</li><li>La coincidencia temporal entre migración, movimiento naval y cobertura no demuestra coordinación ni intención.</li><li>Falta prensa marroquí y documentación institucional para contrastar la versión española.</li><li>No se ha demostrado una operación de influencia; tampoco se ha descartado con evidencia primaria.</li></ul>
<footer>Fuentes y estados revisados a 30-oct-2026. No se ha inventado ninguna fecha, lugar, organizador ni motivo. Los enlaces de medio que solo apuntan a la portada se muestran como tales. · <a href="/">Volver</a></footer>
</div></body></html>'''
html_doc = html_doc.replace('coordinación','pauta compartida').replace('Coordinación','Pauta compartida').replace('amplificación','difusión').replace('Amplificación','Difusión')
OUT.write_text(html_doc,encoding='utf-8')
print(OUT)
