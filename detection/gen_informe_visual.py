#!/usr/bin/env python3
"""gen_informe_visual.py — tarjeta visual semanal del informe (A).

Lee data/informes/<tema>/<ultima>.json y genera en web:
  <SEMANA>.png  (resumen 1200px: titular, KPIs, mapa burbujas, narrativas)
  og-<SEMANA>.png (1200x630 para compartir)
Determinista, matplotlib+PIL, sin red. Corre con /usr/bin/python3.
Uso: /usr/bin/python3 detection/gen_informe_visual.py --tema espana_elecciones
"""
import argparse
import glob
import json
import math
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLASE = [  # (explicaciones que la disparan, etiqueta, color)
    (('cross_account_synchrony', 'synchronized_without_operator'),
     'Pocas cuentas', '#e8933c'),
    (('mainstream_echo', 'single_piece_echo'), 'Eco de prensa', '#2e9e97'),
    (('single_source_feed', 'syndicated_wire', 'automated_non_malicious'),
     'Agregador o utilidad', '#8a94a6'),
    (('organic_viral', 'legitimate_mobilization'), 'Repetición individual',
     '#c9a227'),
    (('unresolved',), 'Fuente a revisar', '#7c6bc4'),
]
GRIS = ('Otra / sin clasificar', '#b6bdc9')


def clase_de(exp):
    for exps, lab, col in CLASE:
        if any(e in exps for e in exp):
            return lab, col
    return GRIS


TITULO = {'espana_elecciones': 'Elecciones generales 29-N',
          'frontera_sur': 'Frontera Sur'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tema', default='espana_elecciones')
    a = ap.parse_args()
    fs = sorted(glob.glob(os.path.join(
        BASE, 'data', 'informes', a.tema, '*.json')))
    if not fs:
        print('sin informes de %s' % a.tema)
        return 1
    with open(fs[-1], encoding='utf-8') as f:
        d = json.load(f)
    sem = d['semana']
    det = d['que_ocurre']['clusters_detalle']
    k = d['kpis']
    wdir = '/var/www/fimi/informes/%s' % a.tema
    os.makedirs(wdir, exist_ok=True)

    prio = [t for t in det if t['score'] >= 55]
    mapa = sorted(prio, key=lambda t: -t['eventos'])[:25]

    fig = plt.figure(figsize=(12, 9), dpi=100)
    fig.patch.set_facecolor('#f1f5f9')
    # Cabecera (texto marino sobre claro: siempre legible)
    ax0 = fig.add_axes([0, 0.93, 1, 0.07])
    ax0.axis('off')
    ax0.text(0.02, 0.62, '%s · informe semanal' % TITULO.get(
        a.tema, a.tema), color='#0f2a43', fontsize=20, weight='bold',
        va='center')
    ax0.text(0.02, 0.25, 'Radar FIMI · tema %s · %s · %s' % (
        a.tema, sem, d['generado_utc']), color='#64748b', fontsize=10,
        va='center')
    # KPIs
    kpis = [('%s' % k['eventos'], 'eventos'), ('%s' % k['autores'], 'autores'),
            ('%s' % k['clusters'], 'clusters'),
            ('%s' % (k['bandas'].get('HIGH', 0)
                     + k['bandas'].get('CRITICAL', 0)), 'banda alta'),
            ('%s' % k.get('topados_techo', 0), 'topados 39/59')]
    for i, (v, lab) in enumerate(kpis):
        ax = fig.add_axes([0.02 + i * 0.192, 0.80, 0.175, 0.105])
        ax.axis('off')
        ax.add_patch(Rectangle((0, 0), 1, 1, facecolor='white', edgecolor='#e2e8f0',
                               transform=ax.transAxes, figure=fig))
        ax.text(0.5, 0.62, v, fontsize=22, weight='bold', ha='center',
                va='center')
        ax.text(0.5, 0.28, lab, fontsize=9, color='#64748b', ha='center',
                va='center')
    # Mapa burbujas: autores (log) vs anomalía, tamaño = eventos
    axm = fig.add_axes([0.06, 0.13, 0.55, 0.60])
    axm.set_facecolor('white')
    for t in mapa:
        exp = t.get('hipotesis', [])
        lab, col = clase_de(exp) if exp else ('Sin clasificar', '#b6bdc9')
        axm.scatter(max(t['autores'], 1), t['anomalia'],
                    s=max(30, math.sqrt(t['eventos']) * 14),
                    c=col, alpha=0.75, edgecolors='white', linewidths=0.6)
        axm.text(max(t['autores'], 1), t['anomalia'] + 1.5,
                 t['label'].split('_cluster_')[-1], fontsize=7, color='#334155')
    axm.set_xscale('log')
    axm.set_xlabel('Autores en el cluster (log)', fontsize=9)
    axm.set_ylabel('Anomalía (0–100)', fontsize=9)
    axm.set_title('Quién repite y cuánto se desvía', fontsize=12, weight='bold',
                  loc='left')
    axm.grid(True, alpha=0.25)
    usadas = []
    for t in mapa:
        exp = t.get('hipotesis', [])
        lc = clase_de(exp) if exp else ('Sin clasificar', '#b6bdc9')
        if lc not in usadas:
            usadas.append(lc)
    for lab, col in usadas:
        axm.scatter([], [], c=col, s=60, label=lab, edgecolors='white')
    axm.legend(frameon=True, fontsize=7, loc='lower right')
    # Narrativas: barras por eventos
    agg = {}
    for t in prio:
        agg.setdefault(t['narrativa'], [0, 0, []])
        agg[t['narrativa']][0] += t['eventos']
        agg[t['narrativa']][1] += 1
        agg[t['narrativa']][2].append(t['label'].split('_cluster_')[-1])
    items = sorted(agg.items(), key=lambda x: -x[1][0])[:8]
    axn = fig.add_axes([0.65, 0.13, 0.33, 0.60])
    axn.axis('off')
    axn.set_title('Narrativas (clusters prioritarios)', fontsize=12,
                  weight='bold', loc='left')
    y = 0.94
    mx = max((v[0] for _, v in items), default=1)
    for nar, (ev, ncl, labs) in items:
        axn.text(0.01, y, (nar[:34] + ('…' if len(nar) > 34 else '')),
                 fontsize=8, va='center', color='#0f172a')
        axn.add_patch(Rectangle((0.01, y - 0.045), 0.62 * ev / mx, 0.035,
                                facecolor='#2e9e97', alpha=0.85,
                                transform=axn.transAxes, figure=fig))
        axn.text(0.66, y - 0.027, '%d ev · %d cl' % (ev, ncl), fontsize=7,
                 va='center', color='#475569')
        y -= 0.105
    # Pie honesto
    axf = fig.add_axes([0.02, 0.01, 0.96, 0.06])
    axf.axis('off')
    axf.text(0.0, 0.7, 'Banda alta = amplificación, no coordinación confirmada. '
             'Atribución UNKNOWN. Contraste, no veredicto.',
             fontsize=9, color='#475569', va='center')
    axf.text(0.0, 0.25, 'fimi.viajeinteligencia.com/informes/%s/ · %s' % (
        a.tema, sem), fontsize=9, color='#0ea5e9', va='center')
    out = os.path.join(wdir, '%s.png' % sem)
    fig.savefig(out, bbox_inches='tight', facecolor=fig.get_facecolor())
    print('visual %s' % out, os.path.getsize(out), 'B')

    # OG 1200x630
    fig2 = plt.figure(figsize=(12, 6.3), dpi=100)
    fig2.patch.set_facecolor('#0f2a43')
    ax = fig2.add_axes([0, 0, 1, 1])
    ax.axis('off')
    ax.text(0.04, 0.72, 'Informe semanal · %s' % TITULO.get(
        a.tema, a.tema),
            color='white', fontsize=30, weight='bold', va='center')
    ax.text(0.04, 0.52, '%s eventos · %s autores · %s clusters · %s en banda alta' % (
        k['eventos'], k['autores'], k['clusters'],
        k['bandas'].get('HIGH', 0) + k['bandas'].get('CRITICAL', 0)),
        color='#cbd5e1', fontsize=17, va='center')
    ax.text(0.04, 0.32, '%s · fimi.viajeinteligencia.com' % sem, color='#7dd3fc',
            fontsize=15, va='center')
    ax.text(0.04, 0.14, 'Amplificación, no coordinación confirmada · UNKNOWN',
            color='#94a3b8', fontsize=12, va='center')
    out2 = os.path.join(wdir, 'og-%s.png' % sem)
    fig2.savefig(out2, bbox_inches='tight', facecolor=fig2.get_facecolor())
    print('og %s' % out2, os.path.getsize(out2), 'B')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
