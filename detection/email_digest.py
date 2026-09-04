#!/usr/bin/env python3
"""email_digest.py — Resumen semanal por email (frecuencia 'semanal').

Destinado a ejecutarse por cron (una vez a la semana, p.ej. lunes 09:00):

  0 9 * * 1  /home/deploy/hybrid-fimi-radar/.venv/bin/python \
      /home/deploy/hybrid-fimi-radar/detection/email_digest.py >> logs/fimi.log 2>&1

Envía a cada suscriptor de email confirmado (confirmado=1) y con frecuencia
'semanal' un resumen del estado de los diales por tema + enlace de baja.
Reutiliza radar_trend (misma fuente de verdad que el dashboard y el bot).
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from schema_suscripciones import init as _init_schema  # noqa: E402
from radar_trend import _cargar_temas_activos, NOMBRE_TEMA, texto_dial  # noqa: E402
from email_api import send_email, load_env, short_id  # noqa: E402

BASE_URL = "https://fimi.viajeinteligencia.com"


def main(dry_run: bool = False):
    load_env(ROOT / ".env")
    conn = _init_schema()
    temas = _cargar_temas_activos()
    # estado por tema (importansia: importar radar_trend bike con su DB)
    from radar_trend import estado_por_tema
    estados = estado_por_tema(temas)

    subs = conn.execute(
        "SELECT * FROM suscripciones WHERE canal='email' AND confirmado=1"
        " AND frecuencia='semanal'").fetchall()
    enviados = 0
    for row in subs:
        try:
            mis_temas = json.loads(row["temas"]) or []
        except Exception:
            mis_temas = []
        if not mis_temas:
            continue
        lines = ["<ul>"]
        for t in mis_temas:
            st = estados.get(t, {})
            txt = texto_dial(t, st.get("estado", "estable"))
            lines.append(f"<li><b>{NOMBRE_TEMA.get(t, t)}</b>: {txt}</li>")
        lines.append("</ul>")
        sid = row["id"]
        baja = f"{BASE_URL}/api/baja?id={sid}"
        html = ('<div style="font-family:system-ui;max-width:600px;margin:0 auto">'
                '<h2>📡 Radar FIMI · Resumen semanal</h2>'
                '<p>Estado actual de tus temas:</p>'
                + "".join(lines) +
                f'<p><a href="{BASE_URL}" style="background:#c2410c;color:#fff;padding:9px 16px;'
                f'border-radius:6px;text-decoration:none;font-weight:700">Ver el radar</a></p>'
                f'<p><a href="{baja}">Darme de baja</a></p>'
                '<p style="font-size:.8rem;color:#888">Radar FIMI · fimi.viajeinteligencia.com</p></div>')
        if not dry_run:
            ok = send_email(row["destino"], "Radar FIMI · Resumen semanal", html)
            print(f"[digest] {'ok' if ok else 'FAIL'} -> {row['destino']}")
        else:
            print(f"[digest][dry] -> {row['destino']}")
        enviados += 1
    conn.close()
    print(f"[digest] {enviados} emails de {len(subs)} suscriptores")
    return enviados


if __name__ == "__main__":
    main(dry_run="--dry" in sys.argv)
