#!/usr/bin/env python3
"""informe_tema.py — parte semanal de señales de un tema (MVP, solo lectura).

Lee data/radar.db y genera, por tema y semana ISO:
  data/informes/<tema>/<SEMANA>.json   (dataset)
  /var/www/fimi/informes/<tema>/<SEMANA>.html  (parte)
  /var/www/fimi/informes/<tema>/index.html     (último + histórico)

Las 5 preguntas mapean a instrumentos ya existentes (regla 12: nada nuevo):
  qué ocurre   = reparto de bandas + top clusters por score
  qué cambia   = linajes nuevos (first_seen 7d) y rampas (first_band_ts 7d)
  qué persiste = linajes con n_ciclos>=3 + sustained_amplification
  qué se sabe  = contrastes posible_bulos + explicaciones dominantes
  qué no se sabe = límites honestos fijos (banda=amplificación, UNKNOWN, etc.)

Uso:
    .venv/bin/python detection/informe_tema.py --tema espana_elecciones
"""
import argparse
import html
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, 'data', 'radar.db')
BANDAS = [(0, 'NORMAL'), (20, 'WATCH'), (40, 'ANOMALOUS'), (60, 'HIGH'),
          (80, 'CRITICAL')]
BAND_ES = {'NORMAL': 'Normal', 'WATCH': 'En observación',
           'ANOMALOUS': 'Amplificación anómala', 'HIGH': 'Amplificación alta',
           'CRITICAL': 'Amplificación muy alta'}
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
    week_ago = now.timestamp() - 7 * 86400
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
    rep = {name: 0 for _, name in BANDAS}
    top = []
    for c in cls:
        b = band(c['overall_score'])
        rep[b] = rep.get(b, 0) + 1
        if len(top) < 10:
            try:
                expl = json.loads(c['alternative_explanations'] or '{}')
            except ValueError:
                expl = {}
            if isinstance(expl, dict):
                items = expl.items()
            elif isinstance(expl, list):
                items = [(e.get('id', e) if isinstance(e, dict) else e, e)
                         for e in expl]
            else:
                items = []
            dom = [k for k, v in items
                   if (isinstance(v, dict) and v.get('estado') == 'supported')
                   or (isinstance(v, str) and v == 'supported')]
            top.append({'label': c['cluster_label'],
                        'score': round(c['overall_score'] or 0, 1),
                        'banda': b, 'eventos': c['nev'], 'autores': c['nau'],
                        't0': c['t0'], 't1': c['t1'],
                        'explicaciones_supported': dom[:3]})
    lin = con.execute(
        'SELECT lineage_id, MAX(first_seen) fs, MAX(n_ciclos) nc, '
        'MAX(first_band_ts) fb FROM cluster_lineage '
        'WHERE tema_id=? GROUP BY lineage_id', (a.tema,)).fetchall()
    nuevos = sorted([r['lineage_id'] for r in lin
                     if (r['fs'] or 0) >= week_ago])
    rampas = sorted([r['lineage_id'] for r in lin
                     if (r['fb'] or 0) >= week_ago])
    persist = sorted([r['lineage_id'] for r in lin if (r['nc'] or 0) >= 3])
    bulos = [dict(r) for r in con.execute(
        'SELECT cluster_label, banda, verifica_fuente, verifica_titulo, '
        'verifica_url FROM posible_bulos WHERE tema_id=? '
        'ORDER BY cycle_ts DESC LIMIT 20', (a.tema,)).fetchall()]
    nbulos = con.execute(
        'SELECT COUNT(*) FROM posible_bulos WHERE tema_id=?',
        (a.tema,)).fetchone()[0]
    con.close()

    informe = {
        'tema': a.tema, 'semana': semana,
        'generado_utc': now.strftime('%Y-%m-%d %H:%M'),
        'kpis': {'eventos': ev['n'], 'autores': ev['a'],
                 'clusters': len(cls), 'bandas': rep,
                 'linajes': len(lin)},
        'que_ocurre': {'top_clusters': top},
        'que_cambia': {'linajes_nuevos_7d': len(nuevos),
                       'rampas_7d': len(rampas),
                       'detalle_nuevos': nuevos[:15]},
        'que_persiste': {'linajes_3ciclos': len(persist),
                         'detalle': persist[:15]},
        'que_se_sabe': {'contrastes_bulos': nbulos, 'bulos': bulos},
        'que_no_se_sabe': LIMITES,
    }
    ddir = os.path.join(a.datos, a.tema)
    os.makedirs(ddir, exist_ok=True)
    with open(os.path.join(ddir, semana + '.json'), 'w') as f:
        json.dump(informe, f, ensure_ascii=False, indent=1)
    wdir = os.path.join(a.web, a.tema)
    os.makedirs(wdir, exist_ok=True)
    with open(os.path.join(wdir, semana + '.json'), 'w') as f:
        json.dump(informe, f, ensure_ascii=False, indent=1)
    filas_top = ''.join(
        '<tr><td><code>%s</code></td><td>%s</td>'
        '<td style="text-align:right">%s</td>'
        '<td style="text-align:right">%s</td>'
        '<td style="text-align:right">%s</td></tr>' % (
            html.escape(t['label']), BAND_ES[t['banda']], t['score'],
            t['eventos'], t['autores']) for t in top)
    filas_b = ''.join(
        '<tr><td>%s</td><td style="text-align:right">%s</td></tr>' % (
            html.escape(b.get('verifica_fuente', '')), html.escape(
                (b.get('verifica_titulo') or '')[:90]))
        for b in bulos[:10])
    body = (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Parte semanal %s · %s · Observatorio de amplificación</title>'
        '</head><body style="font-family:system-ui,sans-serif;max-width:760px;'
        'margin:0 auto;padding:16px;color:#0f172a">'
        '<p><a href="/casos/electoral/">← panorama electoral</a></p>'
        '<h1>Parte semanal: %s <span style="color:#64748b">%s</span></h1>'
        '<p style="color:#64748b">%s · %s eventos · %s autores · %s clusters · '
        '%s linajes. <a href="./%s.json">JSON</a></p>'
        '<h2>Qué ocurre</h2><p>%s</p>'
        '<table border="1" cellpadding="4" cellspacing="0">'
        '<tr><th>Clúster</th><th>Banda</th><th>Score</th><th>Ev.</th>'
        '<th>Aut.</th></tr>%s</table>'
        '<h2>Qué cambia (7 d)</h2><p>%s linajes nuevos · %s rampas '
        '(cruzan a banda de aviso).</p>'
        '<h2>Qué persiste</h2><p>%s linajes con ≥3 ciclos.</p>'
        '<h2>Qué se sabe (contrastes)</h2><p>%s contrastes con verificadores '
        '(contraste, no veredicto).</p>'
        '<table border="1" cellpadding="4" cellspacing="0">'
        '<tr><th>Fuente</th><th>Titular</th></tr>%s</table>'
        '<h2>Qué no se sabe</h2><ul>%s</ul>'
        '</body></html>' % (
            html.escape(a.tema), semana, html.escape(a.tema), semana,
            informe['generado_utc'], informe['kpis']['eventos'],
            informe['kpis']['autores'], informe['kpis']['clusters'],
            informe['kpis']['linajes'], semana,
            ', '.join('%s: %s' % (BAND_ES[k], v)
                       for k, v in sorted(rep.items()) if v),
            filas_top, len(nuevos), len(rampas), len(persist),
            nbulos, filas_b,
            ''.join('<li>%s</li>' % html.escape(x) for x in LIMITES)))
    with open(os.path.join(wdir, semana + '.html'), 'w') as f:
        f.write(body)
    hist = sorted(f for f in os.listdir(ddir) if f.endswith('.json'))
    idx = (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<title>Partes semanales · %s</title></head>'
        '<body style="font-family:system-ui,sans-serif;max-width:760px;'
        'margin:0 auto;padding:16px">'
        '<h1>Partes semanales: %s</h1><ul>%s</ul></body></html>' % (
            html.escape(a.tema), html.escape(a.tema),
            ''.join('<li><a href="./%s.html">%s</a> (<a href="./%s.json">JSON</a>)</li>'
                    % (h[:-5], h[:-5], h[:-5]) for h in sorted(hist, reverse=True))))
    with open(os.path.join(wdir, 'index.html'), 'w') as f:
        f.write(idx)
    print('parte %s %s: %s ev, %s cl, %s bulos -> %s'
          % (a.tema, semana, informe['kpis']['eventos'],
             informe['kpis']['clusters'], nbulos, wdir))
    return 0


if __name__ == '__main__':
    sys.exit(main())
