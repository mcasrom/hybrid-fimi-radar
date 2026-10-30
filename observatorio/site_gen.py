import json,yaml,re,html,shutil
from pathlib import Path
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parent.parent
OUT=Path(__file__).resolve().parent
def e(x): return html.escape(str(x or ''))
ce=json.loads((ROOT/'data/caso_frontera_sur_hibridos/episodios_curados.json').read_text())['episodios']
yu=yaml.safe_load((ROOT/'data/protestas.yaml').read_text())
cal=json.loads((OUT/'calendario/calendario_oficial.json').read_text())
def links(x,key):
 out=[]
 for s in x.get(key,[]) or []:
  m=re.search(r'(https?://[^\s)]+)',s)
  if m: out.append(m.group(1))
 return out
urls=sorted(set(sum([links(x,'fuente') for x in ce],[])+sum([links(x,'fuentes') for x in yu],[])+[h['fuente'] for h in cal['hitos']]))
def domain(u):
 from urllib.parse import urlparse
 return urlparse(u).netloc.replace('www.','') or u
now=datetime.now(timezone.utc).strftime('%d-%b-%Y %H:%M UTC')
summary={
 'actualizado':now,
 'ceuta':{'fichas':len(ce),'fuentes':len(set(sum([links(x,'fuente') for x in ce],[])))},
 'juventud':{'episodios':len(yu),'fuentes':len(set(sum([links(x,'fuentes') for x in yu],[])))},
 'campana':{'hitos':len(cal['hitos']),'documento':cal['source']['documento']},
 'fuentes_unicas':len(urls),
 'criterio':'Registro de lo publicado; no confirma hechos.',
}
(OUT/'data').mkdir(exist_ok=True); (OUT/'data'/'resumen.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
shutil.copy((OUT/'calendario/calendario_oficial.json'),OUT/'data'/'calendario_oficial.json')
css='''<style>:root{--a:#b45309;--i:#1e293b;--m:#64748b;--l:#fde68a}*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:linear-gradient(180deg,#fff,#fffaf5);color:var(--i);line-height:1.6}.wrap{max-width:900px;margin:0 auto;padding:32px 20px 64px}a{color:var(--a)}h1{font-size:1.9rem;margin:0 0 6px}h2{font-size:1.15rem;border-bottom:2px solid var(--l);padding-bottom:5px;margin:28px 0 8px}h3{margin:0 0 4px}.muted{color:var(--m);font-size:.85rem}.lead{font-size:1.02rem;color:#334155;max-width:68ch}.nav{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0 24px;font-size:.9rem}.nav a{padding:6px 10px;border:1px solid #e2e8f0;border-radius:999px;text-decoration:none;background:#fff}.card{background:#fff;border:1px solid #e2e8f0;border-left:5px solid var(--a);border-radius:12px;padding:16px 18px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.stat{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:14px;text-align:center}.stat b{display:block;font-size:1.8rem;color:var(--a)}.stat span{font-size:.8rem;color:var(--m)}.box{background:#fff7ed;border-left:4px solid var(--a);padding:10px 14px;border-radius:7px}li{margin:5px 0}table{width:100%;border-collapse:collapse;font-size:.88rem}th,td{border-bottom:1px solid #e2e8f0;padding:7px;text-align:left;vertical-align:top}footer{margin-top:34px;border-top:1px solid var(--l);padding-top:16px;color:var(--m);font-size:.82rem}@media(max-width:650px){.grid{grid-template-columns:1fr}h1{font-size:1.45rem}}'''
def page(title,body):
 return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title><meta name="description" content="Registro de lo publicado: datos, método, fuentes y límites.">{css}</head><body><div class="wrap"><p class="muted">Observatorio de lo publicado · <a href="/observatorio/">inicio</a></p><nav class="nav"><a href="/observatorio/">Inicio</a><a href="/observatorio/ceuta/">Ceuta</a><a href="/observatorio/juventud/">Juventud</a><a href="/observatorio/campana/">Campaña</a><a href="/observatorio/metodo/">Método</a><a href="/observatorio/fuentes/">Fuentes</a><a href="/observatorio/datos/">Datos</a><a href="/observatorio/sobre/">Sobre</a></nav>{body}<footer>Actualizado: {now}. Registro de lo publicado; no confirma hechos. · <a href="/privacidad.html">Privacidad</a></footer></div></body></html>'''
# Home
body=f'''<h1>Observatorio de lo publicado</h1><p class="lead">Registro de afirmaciones publicadas, episodios y calendario oficial. No confirma que los hechos hayan ocurrido; indica qué se publica, quién lo publica y qué falta.</p><p class="muted">Última actualización: <b>{now}</b></p><div class="grid"><div class="stat"><b>{len(ce)}</b><span>fichas de Ceuta</span></div><div class="stat"><b>{len(yu)}</b><span>episodios juveniles</span></div><div class="stat"><b>{len(cal['hitos'])}</b><span>hitos oficiales</span></div></div><a class="card" href="/observatorio/ceuta/"><h2>Ceuta y Marruecos</h2><p>{len(ce)} afirmaciones publicadas; {summary['ceuta']['fuentes']} fuentes únicas. Estado, actores y límites.</p></a><a class="card" href="/observatorio/juventud/"><h2>Protestas juveniles</h2><p>{len(yu)} episodios publicados; {summary['juventud']['fuentes']} fuentes únicas. Fechas, ciudades, convocantes citados y demandas.</p></a><a class="card" href="/observatorio/campana/"><h2>Campaña electoral 29N</h2><p>{len(cal['hitos'])} hitos oficiales del BOE; campaña no iniciada.</p></a><div class="box"><b>Qué no es.</b> No es un observatorio de hechos confirmados, no atribuye operaciones y no usa clústeres, bandas ni puntuaciones internas.</div>'''
(OUT/'home').mkdir(exist_ok=True); (OUT/'home'/'index.html').write_text(page('Observatorio de lo publicado',body))
# Method
body='''<h1>Método</h1><p class="lead">Este registro documenta lo que se publica y lo que puede comprobarse. No convierte una publicación en un hecho.</p><h2>Qué se registra</h2><ul><li><b>Afirmaciones publicadas:</b> título, medio, fecha y enlace.</li><li><b>Episodios:</b> fecha, ciudad, convocantes citados, demandas y estado.</li><li><b>Calendario:</b> fechas oficiales del BOE.</li></ul><h2>Cómo se obtiene</h2><p>La selección es manual a partir de fuentes públicas. El calendario se extrae automáticamente del real decreto del BOE y se valida. No hay captura automática de acontecimientos ni confirmación automática.</p><h2>Estados</h2><ul><li><b>Secundaria:</b> solo prensa o referencia secundaria.</li><li><b>Documentada:</b> existe un documento oficial o declaración directa.</li><li><b>Pendiente:</b> falta fuente primaria o contraste.</li><li><b>No consta:</b> no hay información suficiente.</li></ul><h2>Qué no se hace</h2><ul><li>No se atribuye autoría ni intención.</li><li>No se confirma un acto por su fecha prevista.</li><li>No se usan clústeres, bandas, scores ni métricas internas.</li></ul>'''
(OUT/'metodo').mkdir(exist_ok=True); (OUT/'metodo'/'index.html').write_text(page('Método',body))
# Sources
rows=''.join(f'<tr><td><a href="{e(u)}" target="_blank" rel="noopener">{e(domain(u))}</a></td><td class="muted">{e(u)}</td></tr>' for u in urls)
body=f'''<h1>Fuentes</h1><p class="lead">{len(urls)} enlaces únicos usados en las fichas y el calendario. Una fuente repetida no equivale a confirmación independiente.</p><table><thead><tr><th>Dominio</th><th>URL</th></tr></thead><tbody>{rows}</tbody></table>'''
(OUT/'fuentes').mkdir(exist_ok=True); (OUT/'fuentes'/'index.html').write_text(page('Fuentes',body))
# Data
body=f'''<h1>Datos</h1><p class="lead">Resumen descargable de lo publicado hasta {now}.</p><div class="grid"><div class="stat"><b>{summary['fuentes_unicas']}</b><span>fuentes únicas</span></div><div class="stat"><b>{len(ce)+len(yu)}</b><span>fichas y episodios</span></div><div class="stat"><b>{len(cal['hitos'])}</b><span>hitos oficiales</span></div></div><ul><li><a href="/observatorio/data/resumen.json">resumen.json</a> — contadores y criterio.</li><li><a href="/observatorio/data/calendario_oficial.json">calendario_oficial.json</a> — fechas y fuente BOE.</li></ul><p class="muted">No se publican datos personales ni identificadores de cuentas.</p>'''
(OUT/'datos').mkdir(exist_ok=True); (OUT/'datos'/'index.html').write_text(page('Datos',body))
# About
body=f'''<h1>Sobre este registro</h1><p class="lead">Un registro independiente de lo que publican medios y organismos sobre asuntos de interés público.</p><p>Lo mantiene Miguel Castillo. No es un observatorio de hechos confirmados ni una herramienta de atribución. No usa clústeres, bandas ni puntuaciones internas.</p><p>Contacto: <a href="mailto:info-fimi@viajeinteligencia.com">info-fimi@viajeinteligencia.com</a>.</p>'''
(OUT/'sobre').mkdir(exist_ok=True); (OUT/'sobre'/'index.html').write_text(page('Sobre',body))
print('site pages generated',len(urls))
