#!/usr/bin/env python3
import json, html
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).with_name('index.html')
esc=json.loads((Path(__file__).with_name('data')/'escanos_2026.json').read_text(encoding='utf-8'))
cen=json.loads((Path(__file__).with_name('data')/'censo_2026.json').read_text(encoding='utf-8'))
def e(x): return html.escape(str(x))
hitos=[
 ('6-oct-2026','Convocatoria electoral','Publicación del real decreto de disolución y convocatoria.','BOE · RD 806/2026',esc['meta']['url']),
 ('13-nov-2026','Inicio de la campaña electoral','Comienzo del periodo de actos y propaganda electoral.','Calendario de trabajo 29N','https://elecciones29n.pruebapublica.com/'),
 ('24–28-nov-2026','Periodo de reflexión / blackout','No se publicarán sondeos ni contenidos electorales en ese periodo.','Calendario de trabajo 29N','https://elecciones29n.pruebapublica.com/'),
 ('29-nov-2026','Jornada electoral','Elecciones generales.','Calendario de trabajo 29N','https://elecciones29n.pruebapublica.com/'),
]
rows=''.join(f'<tr><td>{e(d)}</td><td><b>{e(t)}</b></td><td>{e(x)}</td><td><a href="{e(u)}" target="_blank" rel="noopener">{e(s)}</a></td></tr>' for d,t,x,s,u in hitos)
html_doc=f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Campaña electoral 29N — observatorio de acontecimientos</title>
<meta name="description" content="Seguimiento documentado de la campaña electoral del 29N: calendario, actores, acontecimientos y fuentes. Sin pronósticos ni atribuciones.">
<style>
:root{{--a:#b45309;--i:#1e293b;--m:#64748b;--l:#fde68a}}*{{box-sizing:border-box}}body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:linear-gradient(180deg,#fff,#fffaf5);color:var(--i);line-height:1.6}}.wrap{{max-width:980px;margin:0 auto;padding:28px 18px 60px}}a{{color:var(--a)}}h1{{font-size:1.7rem;line-height:1.2;margin:0 0 6px}}h2{{font-size:1.15rem;border-bottom:2px solid var(--l);padding-bottom:5px;margin:28px 0 10px}}h3{{margin:0 0 5px}}.lead{{font-size:1rem;color:#334155}}.muted{{color:var(--m);font-size:.85rem}}.box{{background:#fff7ed;border-left:4px solid var(--a);padding:10px 14px;border-radius:7px}}table{{width:100%;border-collapse:collapse;font-size:.9rem}}th,td{{border-bottom:1px solid #e2e8f0;padding:8px;text-align:left;vertical-align:top}}li{{margin:5px 0}}footer{{margin-top:34px;border-top:1px solid var(--l);padding-top:16px;color:var(--m);font-size:.82rem}}@media(max-width:600px){{h1{{font-size:1.4rem}}}}
</style></head><body><div class="wrap">
<p class="muted">Observatorio · Campaña electoral</p><h1>España — campaña electoral 29N</h1>
<p class="lead">Seguimiento de acontecimientos y documentos de la campaña. No es un pronóstico ni una estimación de voto.</p>
<p class="muted">Actualización: 30-oct-2026 · Campaña no iniciada · Jornada: 29-nov-2026</p>
<div class="box"><b>Estado.</b> A 30-oct-2026 no hay campaña electoral en curso y no consta ningún acto de campaña documentado. Esta página muestra el calendario y las fuentes; los acontecimientos se incorporarán cuando existan y tengan fuente.</div>
<h2>1. Calendario</h2><table><thead><tr><th>Fecha</th><th>Hito</th><th>Qué significa</th><th>Fuente</th></tr></thead><tbody>{rows}</tbody></table>
<p class="muted">Las fechas de campaña y blackout son el calendario de trabajo de 29N; el enlace oficial de la JEC se incorporará cuando esté disponible. La convocatoria y los escaños se apoyan en el BOE.</p>
<h2>2. Acontecimientos documentados</h2><p><b>No consta.</b> La campaña no ha comenzado. No se inventan actos, sedes, intervinientes ni asistentes.</p>
<h2>3. Actores</h2><p><b>No consta en los datos locales</b> una lista oficial de candidaturas para el 29N. No se atribuyen actos ni posiciones sin fuente. Los partidos y candidaturas se incorporarán desde la documentación oficial.</p>
<h2>4. Qué se observará</h2><ul><li>Actos y convocatorias de campaña con fecha, lugar y fuente.</li><li>Declaraciones y documentos oficiales.</li><li>Debates y comparecencias.</li><li>Incidencias documentadas.</li><li>Evolución de la campaña y cobertura, separando hechos de opiniones.</li></ul>
<h2>5. Qué no se hará</h2><ul><li>No se publicarán pronósticos ni estimaciones propias de voto.</li><li>No se atribuirán actos a un partido por una mención.</li><li>No se convertirán publicaciones en acontecimientos.</li><li>No se usarán indicadores internos como si fueran acontecimientos.</li></ul>
<h2>6. Datos oficiales de contexto</h2><ul><li>Escaños: <b>{e(esc['total_escanos'])}</b> en <b>{e(len(esc['provincias']))}</b> provincias. Fuente: <a href="{e(esc['meta']['url'])}" target="_blank" rel="noopener">BOE · RD 806/2026</a>.</li><li>Censo: <b>{cen['total']:,}</b> electores. Fuente: <a href="{e(cen['ficheros']['provincias']['url'])}" target="_blank" rel="noopener">INE · Oficina del Censo Electoral</a>. El total incluye CER y CERA.</li></ul>
<h2>7. Datos electorales separados</h2><p>La media de sondeos, la participación histórica, el censo y los escaños por provincia están en el <a href="https://elecciones29n.pruebapublica.com/">Observatorio 29N</a>. No se mezclan con los acontecimientos de campaña.</p>
<h2>8. Fuentes</h2><ul><li><a href="{e(esc['meta']['url'])}" target="_blank" rel="noopener">BOE · Real Decreto 806/2026</a>.</li><li><a href="{e(cen['ficheros']['provincias']['url'])}" target="_blank" rel="noopener">INE · censo electoral 2026</a>.</li><li><a href="https://elecciones29n.pruebapublica.com/" target="_blank" rel="noopener">Observatorio 29N</a> (datos electorales, no campaña).</li></ul>
<footer>Datos fechados a 30-oct-2026. No se ha documentado ningún acto de campaña. · <a href="/">Volver</a></footer>
</div></body></html>'''
OUT.write_text(html_doc,encoding='utf-8')
print(OUT)
