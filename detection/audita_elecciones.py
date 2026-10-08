#!/usr/bin/env python3
"""audita_elecciones.py — revisión mensual del registry electoral (solo lectura).

Regla (incidente Brasil 8-oct-2026): 3 días después de cada fecha hay que
verificar resultado y, si hay balotaje, añadir la fila. Este chequeo lista:
  - elecciones recién celebradas (-1..+5 d): revisar resultado/balotaje
  - filas en fase con cobertura ~0: keywords posiblemente muertas
  - filas activas con fecha >120 d: candidatas a cierre
Con --tg avisa por Telegram solo si hay avisos. Cron: día 1, 08:35 UTC.
"""
import argparse
import os
import sqlite3
import sys
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'detection'))
DB = os.path.join(BASE, 'data', 'radar.db')
YAML = os.path.join(BASE, 'data', 'elecciones.yaml')

import yaml  # noqa: E402
from gen_caso_electoral import proc_signal, tema_signal, UMBRAL_COBERTURA  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tg', action='store_true')
    a = ap.parse_args()
    hoy = date.today()
    rows = yaml.safe_load(open(YAML, encoding='utf-8')) or []
    con = sqlite3.connect(DB)
    avisos = []
    for r in rows:
        if r.get('estado') != 'activo':
            continue
        f = str(r.get('fecha'))[:10]
        try:
            dias = (date.fromisoformat(f) - hoy).days
        except ValueError:
            avisos.append('%s: fecha inválida %r' % (r.get('pais'), f))
            continue
        tag = '%s — %s (%s)' % (r.get('pais'), r.get('nombre'), f)
        if -1 <= dias <= 5:
            avisos.append('%s: celebrada hace %d d → verificar resultado y '
                          'si hay 2.ª vuelta (añadir fila)' % (tag, -dias))
        elif dias < -120:
            avisos.append('%s: pasada hace %d d y sigue activa → cerrar fila'
                          % (tag, -dias))
        if -3 <= dias <= 30:
            import time
            since = time.time() - 30 * 86400
            tk = str(r.get('tema') or '').strip()
            if tk:
                pev, _, _ = tema_signal(con, tk, since)
            else:
                pev, _, _ = proc_signal(con, r.get('keywords'), since)
            if pev < UMBRAL_COBERTURA:
                avisos.append('%s: en fase con %d menciones/30d → revisar '
                              'keywords' % (tag, pev))
    con.close()
    if not avisos:
        print('registry electoral ok (%d filas activas)' % sum(
            1 for r in rows if r.get('estado') == 'activo'))
        return 0
    txt = '🗳 registry electoral (%d avisos):\n' % len(avisos) + '\n'.join(
        '- ' + x for x in avisos)
    print(txt)
    if a.tg:
        import requests
        e = os.environ
        tok, chat = e.get('FIMI_TELEGRAM_BOT_TOKEN', ''), e.get(
            'FIMI_OWNER_CHAT', '')
        if not tok or not chat:
            print('[audita] sin token/chat', file=sys.stderr)
            return 2
        requests.post(
            'https://api.telegram.org/bot%s/sendMessage' % tok,
            data={'chat_id': chat, 'text': txt[:3900]}, timeout=30)
        print('[audita] avisado por Telegram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
