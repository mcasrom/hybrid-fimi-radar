#!/usr/bin/env python3
"""informe_tema.py — informe semanal de señales de un tema (solo lectura).

Lee data/radar.db y genera, por tema y semana ISO:
  data/informes/<tema>/<SEMANA>.json   (dataset)
  /var/www/fimi/informes/<tema>/<SEMANA>.html  (informe)
  /var/www/fimi/informes/<tema>/index.html     (último + histórico)

Las 5 preguntas mapean a instrumentos ya existentes (regla 12: nada nuevo).
Honestidad (revisión 8-oct):
  - "Nuevo" = linaje que NO estaba en el informe anterior, no first_seen
    reciente (un tema joven tiene todos los first_seen recientes).
  - Los scores clavados en 39,0/59,0 son topes de banda aplicados, no
    señales independientes: se cuentan aparte como "topados".
  - Sin informe anterior no hay comparativa: se dice, no se inventa.

Uso:
    .venv/bin/python detection/informe_tema.py --tema espana_elecciones
"""
import argparse
import glob
import html
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, 'data', 'radar.db')
BANDAS = [(0, 'NORMAL'), (20, 'WATCH'), (40, 'ANOMALOUS'), (60, 'HIGH'),
          (80, 'CRITICAL')]
BAND_ES = {'NORMAL': 'Normal', 'WATCH': 'En observación',
           'ANOMALOUS': 'Amplificación anómala', 'HIGH': 'Amplificación alta',
           'CRITICAL': 'Amplificación muy alta'}
STOP = set('''de la el en y que los del se las una por con para al como más pero sus este esta estos estas eso esa ese ser son fue han hay entre sobre todo también tras ante bajo cuyo cuya cuyos cuyas cual cuales donde cuando porque pues sino aunque según cada dos tres día días vez veces año años hoy ayer anteayer aquí ahí allí entonces pues tan tanto mucha mucho muchas muchos poca poco este esta eso esa aquel aquella aquello ello ello lo le les me te se nos os mi mis tu tus su sus nuestro nuestra nuestros nuestras este esta estos estas estas hay está están estoy estamos eres es son sea sean sido siendo tener tiene tienen hacer hace hacen decir dice dicen poder puede pueden haber hay van ver vez gran grandes nuevo nueva nuevos nuevas primer primera primeros primeras mismo misma mismos mismas otro otra otros otras tanto tanta tantos tantas todo toda todos todas cada cual quien quienes cuyo cuya cuyos cuyas donde como cuando cuanto cuanta cuantos cuantas porque pues sino mas si no ni o u e y'''.split())

CURADO_PATH = os.path.join(BASE, 'data', 'narrativas.json')
LIMITES = [
    'Una banda alta es amplificación medida, nunca coordinación confirmada '
    '(8,3 % en la validación ciega del 29/Sep/2026).',
    'No se atribuye actor ni intención: el resultado por defecto es UNKNOWN.',
    'Los verificadores aportan contraste, no veredicto.',
]


def band(score):
    out = 'NORMAL'
    for lo, name in BANDAS:
        if (score or 0) >= lo:
            out = name
    return out


def pct(a, b):
    return round(100.0 * a / max(b, 1), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tema', default='espana_elecciones')
    ap.add_argument('--db', default=DB)
    ap.add_argument('--datos', default=os.path.join(BASE, 'data', 'informes'))
    ap.add_argument('--web', default='/var/www/fimi/informes')
    a = ap.parse_args()
    if not os.path.exists(a.db):
        print('sin BD: %s' % a.db)
        return 1
    now = datetime.now(timezone.utc)
    semana = '%d-W%02d' % now.isocalendar()[:2]
    con = sqlite3.connect(a.db)
    con.row_factory = sqlite3.Row

    ev = con.execute(
        'SELECT COUNT(*) n, COUNT(DISTINCT e.author) a '
        'FROM events e JOIN event_temas et ON et.event_id=e.id '
        'WHERE et.tema_id=?', (a.tema,)).fetchone()
    cls = con.execute(
        'SELECT c.id, c.cluster_label, c.overall_score, c.anomaly_score, '
        'c.narrative_subtype, c.alternative_explanations, '
        '(SELECT COUNT(*) FROM cluster_events ce WHERE ce.cluster_id=c.id) nev, '
        '(SELECT COUNT(DISTINCT author) FROM cluster_events ce '
        ' WHERE ce.cluster_id=c.id) nau, '
        '(SELECT MIN(ts) FROM cluster_events ce WHERE ce.cluster_id=c.id) t0, '
        '(SELECT MAX(ts) FROM cluster_events ce WHERE ce.cluster_id=c.id) t1 '
        'FROM clusters c WHERE c.tema_id=? ORDER BY c.overall_score DESC',
        (a.tema,)).fetchall()

    def dominios(cid, n=3):
        c = Counter()
        try:
            rows = con.execute(
                'SELECT url FROM cluster_events WHERE cluster_id=? '
                'AND url IS NOT NULL AND url<>""', (cid,)).fetchall()
        except Exception:
            return []
        for r in rows:
            try:
                dom = urlparse(r[0]).netloc.lower()
            except Exception:
                continue
            if dom.startswith('www.'):
                dom = dom[4:]
            if dom:
                c[dom] += 1
        return ['%s (%d)' % x for x in c.most_common(n)]

    def contenido(cid):
        """Capa semántica determinista (sin LLM): título más repetido,
        top textos y términos. Reproducible y citable."""
        try:
            tit = con.execute(
                'SELECT title, COUNT(*) n FROM cluster_events '
                'WHERE cluster_id=? AND title IS NOT NULL AND title<>"" '
                'GROUP BY title ORDER BY n DESC LIMIT 3',
                (cid,)).fetchall()
            txt = con.execute(
                'SELECT text FROM cluster_events WHERE cluster_id=? '
                'AND text IS NOT NULL AND text<>"" LIMIT 400',
                (cid,)).fetchall()
        except Exception:
            return {'titulos': [], 'terminos': [], 'resumen': ''}
        toks = Counter()
        for r in txt:
            for w in re.sub(r'[^a-záéíóúñü ]', ' ',
                            (r[0] or '').lower()).split():
                if len(w) >= 4 and w not in STOP:
                    toks[w] += 1
        titulos = [(r[0][:160], r[1]) for r in tit]
        resumen = titulos[0][0] if titulos else ''
        return {'titulos': titulos,
                'terminos': [w for w, _ in toks.most_common(8)],
                'resumen': resumen}

    def fmt_ts(ts):
        if not ts:
            return '—'
        return datetime.fromtimestamp(ts, timezone.utc).strftime('%d/%m')

    def subtype(c):
        try:
            st = json.loads(c['narrative_subtype'] or '{}')
        except ValueError:
            return '?'
        if isinstance(st, dict):
            return st.get('dominant', st.get('dominant_subtype', '?'))
        return str(st)

    def supported(c):
        try:
            expl = json.loads(c['alternative_explanations'] or '{}')
        except ValueError:
            return []
        if isinstance(expl, dict):
            items = expl.items()
        elif isinstance(expl, list):
            items = [((e.get('code') or e.get('id') or e)
                      if isinstance(e, dict) else e, e)
                     for e in expl]
        else:
            return []
        return [k for k, v in items
                if (isinstance(v, dict) and v.get('status') == 'supported')]

    info = []
    try:
        with open(CURADO_PATH, encoding='utf-8') as f:
            curado = (json.load(f).get(a.tema, {}))
    except (OSError, ValueError):
        curado = {}
    for c in cls:
        sc = round(c['overall_score'] or 0, 1)
        cont = contenido(c['id'])
        nar = curado.get(c['cluster_label'])
        if not nar:
            nar = ' · '.join(cont['terminos'][:3]) or 'sin etiquetar'
        info.append({'label': c['cluster_label'], 'score': sc,
                     'banda': band(c['overall_score']),
                     'eventos': c['nev'], 'autores': c['nau'],
                     'ventana': '%s–%s' % (fmt_ts(c['t0']), fmt_ts(c['t1'])),
                     'subtipo': subtype(c), 'exp': supported(c)[:3],
                     'anomalia': round(c['anomaly_score'] or 0, 1),
                     'dominios': dominios(c['id']) if sc >= 55 else [],
                     'narrativa': nar,
                     'narrativa_curada': bool(curado.get(c['cluster_label'])),
                     'resumen': cont['resumen'],
                     'atribucion': 'UNKNOWN',
                     'hipotesis': supported(c)[:3],
                     'titulos_top': cont['titulos'],
                     'terminos': cont['terminos'][:8]})
    rep = {name: 0 for _, name in BANDAS}
    for t in info:
        rep[t['banda']] += 1
    topados = [t for t in info if t['score'] in (39.0, 59.0)]
    high = [t for t in info if t['banda'] in ('HIGH', 'CRITICAL')]
    watch_alto = [t for t in info if t['banda'] == 'ANOMALOUS'
                  and t['score'] >= 55.0]

    narr = Counter(t['subtipo'] for t in info)
    exps = Counter(e for t in info for e in t['exp'])

    lin = {r['lineage_id']: dict(r) for r in con.execute(
        'SELECT lineage_id, MIN(first_seen) fs, MAX(n_ciclos) nc, '
        'MIN(first_band_ts) fb, MAX(cycle_ts) lc FROM cluster_lineage '
        'WHERE tema_id=? GROUP BY lineage_id', (a.tema,)).fetchall()}
    linajes = sorted(lin)

    bulos = [dict(r) for r in con.execute(
        'SELECT cluster_label, banda, verifica_fuente, verifica_titulo, '
        'verifica_url, solape FROM posible_bulos WHERE tema_id=? '
        'ORDER BY cycle_ts DESC LIMIT 30', (a.tema,)).fetchall()]
    nbulos = con.execute(
        'SELECT COUNT(*) FROM posible_bulos WHERE tema_id=?',
        (a.tema,)).fetchone()[0]
    cl_by_label = {t['label']: t for t in info}

    def norm(s):
        return re.sub(r'[^a-záéíóúñü ]', ' ', (s or '').lower())

    cruce = []
    for b in bulos:
        t = cl_by_label.get(b['cluster_label'])
        toks = [x.strip().lower() for x in (b.get('solape') or '').split(',')
                if x.strip()]
        rep_txt = norm(t['resumen']) if t else ''
        rel = ('MATCH' if t and len(toks) >= 2
               and sum(1 for x in toks if x and x in rep_txt) >= 2
               else 'THEMATIC')
        cruce.append({'fuente': b['verifica_fuente'],
                      'titular': (b['verifica_titulo'] or '')[:110],
                      'url': b['verifica_url'],
                      'cluster': b['cluster_label'],
                      'relacion': rel,
                      'score': t['score'] if t else None,
                      'banda': t['banda'] if t else b['banda'],
                      'autores': t['autores'] if t else None,
                      'narrativa': t['narrativa'] if t else ''})

    # Comparativa con el informe anterior (si existe)
    ddir = os.path.join(a.datos, a.tema)
    os.makedirs(ddir, exist_ok=True)
    prevs = sorted(f for f in glob.glob(os.path.join(ddir, '*.json')))
    prevs = [f for f in prevs if not f.endswith(semana + '.json')]
    delta, prev_rep = None, None
    if prevs:
        with open(prevs[-1]) as f:
            prev_rep = json.load(f)
        d = {'eventos': ev['n'] - prev_rep['kpis']['eventos'],
             'autores': ev['a'] - prev_rep['kpis']['autores'],
             'clusters': len(cls) - prev_rep['kpis']['clusters'],
             'high': rep.get('HIGH', 0) + rep.get('CRITICAL', 0)
             - prev_rep['kpis']['bandas'].get('HIGH', 0)
             - prev_rep['kpis']['bandas'].get('CRITICAL', 0)}
        prev_lin = set(prev_rep.get('linajes_lista', []))
        d['linajes_nuevos'] = sorted(set(linajes) - prev_lin)
        d['linajes_caidos'] = sorted(prev_lin - set(linajes))
        delta = d
    nuevos_n = len(delta['linajes_nuevos']) if delta else None

    # Conclusión automática (descriptiva, sin veredicto)
    n_high = rep.get('HIGH', 0) + rep.get('CRITICAL', 0)
    concl = (
        'Esta semana: %s eventos de %s autores en %s clusters '
        '(%s en banda alta%s). ' % (
            ev['n'], ev['a'], len(cls), n_high,
            '; %s topados en techos de banda' % len(topados) if topados
            else ''))
    if delta:
        concl += 'Frente a la anterior: %s%sev, %s%s autores, %s en banda alta; %s linajes nuevos, %s caídos. ' % (
            '+' if delta['eventos'] >= 0 else '', delta['eventos'],
            '+' if delta['autores'] >= 0 else '', delta['autores'],
            '%+d' % delta['high'], len(delta['linajes_nuevos']),
            len(delta['linajes_caidos']))
    else:
        concl += 'Primera edición: sin comparativa todavía (la línea base empieza aquí). '
    dom = next(((k, v) for k, v in narr.most_common() if k not in ('?', '')), None)
    if dom:
        concl += 'Rol dominante: %s (%s clusters). ' % dom
    elif exps:
        concl += 'Explicación más frecuente: %s (%s clusters). ' % exps.most_common(1)[0]
    concl += 'Qué vigilar: %s clusters en anómala alta pre-HIGH (55–59,9)%s.' % (
        len(watch_alto),
        '; %s contrastes con verificadores esta semana' % nbulos if nbulos else '')

    informe = {
        'tema': a.tema, 'semana': semana,
        'generado_utc': now.strftime('%Y-%m-%d %H:%M'),
        'kpis': {'eventos': ev['n'], 'autores': ev['a'],
                 'clusters': len(cls), 'bandas': rep,
                 'linajes': len(linajes), 'topados_techo': len(topados)},
        'delta_vs_anterior': delta,
        'linajes_lista': linajes,
        'que_ocurre': {'clusters_detalle': info,
                       'narrativas_dominantes': narr.most_common(5),
                       'explicaciones_top': exps.most_common(5)},
        'que_cambia': {'linajes_nuevos_vs_anterior': nuevos_n,
                       'detalle_nuevos': (delta['linajes_nuevos'][:15]
                                          if delta else [])},
        'que_persiste': {'nota': 'linajes con ≥3 ciclos (ver JSON)'},
        'que_se_sabe': {'contrastes_bulos': nbulos, 'cruce': cruce[:15]},
        'high_explicados': [
            {'label': t['label'], 'score': t['score'],
             'autores': t['autores'], 'subtipo': t['subtipo'],
             'explicaciones': t['exp']} for t in high],
        'vigilar_proxima': [t['label'] for t in watch_alto[:10]],
        'conclusion': concl,
        'que_no_se_sabe': LIMITES,
    }
    with open(os.path.join(ddir, semana + '.json'), 'w') as f:
        json.dump(informe, f, ensure_ascii=False, indent=1)
    wdir = os.path.join(a.web, a.tema)
    os.makedirs(wdir, exist_ok=True)
    with open(os.path.join(wdir, semana + '.json'), 'w') as f:
        json.dump(informe, f, ensure_ascii=False, indent=1)

    def guia(t):
        g = []
        if t['autores'] <= 5 and t['eventos'] >= 50:
            g.append('volumen concentrado en pocos autores: vigilar si se '
                     'diversifica o aparece sincronización entre independientes')
        if t['dominios']:
            g.append('repetición en %s: vigilar si diversifica fuentes' %
                     t['dominios'][0].split(' (')[0])
        if t['banda'] in ('HIGH', 'CRITICAL'):
            g.append('banda alta sostenida: vigilar cambios de volumen y banda')
        if not g:
            g.append('vigilar evolución de volumen, autores y banda')
        return g

    def ficha(t):
        # Ficha: QUÉ (narrativa+contenido), CÓMO (conducta), QUÉ SIGNIFICA.
        bulos_t = [c for c in cruce
                   if c['cluster'] == t['label']][:3]
        lb = ''.join(
            '<li>%s — <a href="%s">%s</a> [%s]</li>' % (
                html.escape(b['fuente'] or ''), html.escape(b['url'] or ''),
                html.escape(b['titular'][:80]), b['relacion']) for b in bulos_t)
        num = t['label'].split('_cluster_')[-1]
        return (
            '<div style="border:1px solid #e2e8f0;border-radius:10px;'
            'padding:10px 12px;margin:8px 0">'
            '<h3 style="margin:0 0 6px">%s — %s</h3>'
            '<p style="color:#64748b;margin:0 0 6px"><b>%s</b> · %s · '
            '%s autores · %s eventos · %s</p>'
            '<p><b>Qué circula:</b> %s</p>'
            '<p><b>Qué detecta el radar:</b> %s autores repiten contenido '
            '(%s) con anomalía %s; rol conductual %s.</p>'
            '<p><b>Qué no permite concluir:</b> coordinación ni atribución '
            '(hipótesis compatibles: %s; atribución UNKNOWN).</p>'
            '<p style="color:#64748b">Dominios: %s · '
            '<a href="/api/v1/cluster/%s">API</a>%s</p></div>' % (
                html.escape(num), html.escape(t['narrativa']),
                BAND_ES[t['banda']], t['score'], t['autores'], t['eventos'],
                t['ventana'], html.escape(t['resumen'][:220] or '—'),
                t['autores'],
                html.escape(', '.join(t['dominios'][:3]) or 'sin dominios'),
                t['anomalia'], html.escape(str(t['subtipo'])),
                html.escape(', '.join(t['exp'])
                            or 'sin explicación concluyente'),
                html.escape(', '.join(t['dominios'][:3]) or '—'),
                html.escape(t['label']),
                ('<br>Contrastes: <ul>%s</ul>' % lb) if lb else ''))

    fichas_high = ''.join(ficha(t) for t in high)
    fichas_pre = ''.join(ficha(t) for t in watch_alto)
    filas_anom = ''.join(
        '<tr><td><code>%s</code> — %s</td>'
        '<td style="text-align:right">%s</td>'
        '<td style="text-align:right">%s</td>'
        '<td>%s</td></tr>' % (
            html.escape(t['label'].split('_cluster_')[-1]),
            html.escape(t['narrativa'][:70]),
            t['score'], t['autores'],
            html.escape(', '.join(t['exp'][:2]) or '—'))
        for t in info if t['banda'] == 'ANOMALOUS' and t['score'] < 55)
    prio = high + watch_alto
    curadas = {t['label'] for t in info if t['narrativa_curada']}
    agg = {}
    for t in prio:
        agg.setdefault(t['narrativa'], {'clusters': [], 'ev': 0,
                                         'cur': False})
        agg[t['narrativa']]['clusters'].append(
            t['label'].split('_cluster_')[-1])
        agg[t['narrativa']]['ev'] += t['eventos']
        agg[t['narrativa']]['cur'] = agg[t['narrativa']]['cur'] or (
            t['label'] in curadas)
    filas_narr = ''.join(
        '<tr><td>%s%s</td><td>%s</td><td style="text-align:right">%s</td>'
        '<td style="text-align:right">%s</td></tr>' % (
            html.escape(nar[:80]),
            '' if v['cur'] else ' <span style="color:#64748b">(auto)</span>',
            html.escape(', '.join(v['clusters'])),
            len(v['clusters']), v['ev'])
        for nar, v in sorted(agg.items(), key=lambda x: -x[1]['ev'])[:12])
    filas_watch = ''.join(
        '<li><b>%s — %s</b> (%s autores / %s eventos): %s.</li>' % (
            html.escape(t['label'].split('_cluster_')[-1]),
            html.escape(t['narrativa'][:70]), t['autores'], t['eventos'],
            html.escape('; '.join(guia(t))))
        for t in watch_alto[:10])
    filas_cruce = ''.join(
        '<tr><td>%s</td><td><a href="%s">%s</a></td>'
        '<td>%s</td><td style="text-align:right">%s</td></tr>' % (
            html.escape(c['fuente'] or ''), html.escape(c['url'] or ''),
            html.escape(c['titular']), c['relacion'],
            c['score'] if c['score'] is not None
            else '—') for c in cruce[:10])
    n_watch = rep.get('WATCH', 0) + rep.get('NORMAL', 0)
    body = (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Informe semanal %s · %s · Observatorio de amplificación</title>'
        '<meta property="og:image" content="https://fimi.viajeinteligencia.com'
        '/informes/%s/og-%s.png">'
        '</head><body style="font-family:system-ui,sans-serif;max-width:760px;'
        'margin:0 auto;padding:16px;color:#0f172a">'
        '<p><a href="/casos/electoral/">← panorama electoral</a></p>'
        '<h1>Informe semanal: %s <span style="color:#64748b">%s</span></h1>'
        '<p><a href="./%s.png"><img src="./%s.png" alt="Resumen visual del '
        'informe semanal %s: cifras, mapa de clusters y narrativas" '
        'loading="lazy" style="width:100%%;max-width:680px;display:block;'
        'margin:10px auto;border:1px solid #e2e8f0;border-radius:10px"></a>'
        '<a href="./%s.png" download>Descargar imagen</a></p>'
        '<p style="color:#64748b">%s · %s eventos · %s autores · %s clusters · '
        '%s en banda alta · <a href="./%s.json">JSON</a></p>'
        '<h2>Conclusión</h2><p>%s</p>'
        '<h2>Qué ocurre</h2><p>%s</p>'
        '<h2>Narrativas de la semana</h2><p>Agregado de los clusters '
        'prioritarios. <span style="color:#64748b">(auto)</span> = etiqueta '
        'automática por términos, sin curar; el resto, curadas a mano.</p>'
        '<table border="1" cellpadding="4" cellspacing="0">'
        '<tr><th>Narrativa</th><th>Clusters (id)</th><th>N.º</th><th>Ev.</th></tr>%s</table>'
        '<h2>Banda alta — ficha completa</h2>%s'
        '<h2>Anómala alta (55–59,9) — ficha completa</h2>%s'
        '<h2>Anómala &lt;55 — resumen</h2>'
        '<table border="1" cellpadding="4" cellspacing="0">'
        '<tr><th>Clúster — narrativa</th><th>Score</th><th>Aut.</th>'
        '<th>Explicación</th></tr>%s</table>'
        '<p style="color:#64748b">%s clusters clavados en techos de banda '
        '(39,0/59,0): topes aplicados, no señales independientes. '
        'WATCH+NORMAL (%s): solo estadística agregada, detalle en el JSON.</p>'
        '<h2>Cruce con verificadores</h2><p>%s contrastes (contraste, no '
        'veredicto): MATCH = el titular verificado circula en el clúster; '
        'THEMATIC = coincidencia temática.</p>'
        '<table border="1" cellpadding="4" cellspacing="0">'
        '<tr><th>Fuente</th><th>Titular</th><th>Relación</th><th>Score</th></tr>%s</table>'
        '<h2>Qué vigilar la próxima semana</h2><ul>%s</ul>'
        '<h2>Qué no se sabe</h2><ul>%s</ul>'
        '</body></html>' % (
            html.escape(a.tema), semana, a.tema, semana,
            html.escape(a.tema), semana, semana, semana, semana, semana,
            informe['generado_utc'], informe['kpis']['eventos'],
            informe['kpis']['autores'], informe['kpis']['clusters'], n_high,
            semana, html.escape(concl),
            ', '.join('%s: %s' % (BAND_ES[k], v)
                       for k, v in sorted(rep.items()) if v),
            filas_narr,
            fichas_high or '<p>Ninguno esta semana.</p>',
            fichas_pre or '<p>Ninguno esta semana.</p>', filas_anom,
            len(topados), n_watch, nbulos, filas_cruce, filas_watch,
            ''.join('<li>%s</li>' % html.escape(x) for x in LIMITES)))
    with open(os.path.join(wdir, semana + '.html'), 'w') as f:
        f.write(body)
    hist = sorted(f for f in os.listdir(ddir) if f.endswith('.json'))
    idx = (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<title>Informes semanales · %s</title></head>'
        '<body style="font-family:system-ui,sans-serif;max-width:760px;'
        'margin:0 auto;padding:16px">'
        '<h1>Informes semanales: %s</h1><ul>%s</ul></body></html>' % (
            html.escape(a.tema), html.escape(a.tema),
            ''.join('<li><a href="./%s.html">%s</a> (<a href="./%s.json">JSON</a>)</li>'
                    % (h[:-5], h[:-5], h[:-5]) for h in sorted(hist, reverse=True))))
    with open(os.path.join(wdir, 'index.html'), 'w') as f:
        f.write(idx)
    print('informe %s %s: %s ev, %s cl, %s HIGH, %s bulos, deltas=%s -> %s'
          % (a.tema, semana, informe['kpis']['eventos'],
             informe['kpis']['clusters'], n_high, nbulos,
             'si' if delta else 'primera edicion', wdir))
    return 0


if __name__ == '__main__':
    sys.exit(main())
