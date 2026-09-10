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
        # proyecto del semillero unico (fimi/blog/etc). Fallback fimi para filas legacy sin columna.
        try:
            proyecto = (row["proyecto"] or "fimi").strip().lower()
        except Exception:
            proyecto = "fimi"
        if proyecto == "blog":
            try:
                import xml.etree.ElementTree as ET
                rss = Path("/home/deploy/analisis-pruebapublica/dist/client/rss.xml")
                items = []
                if rss.exists():
                    root = ET.parse(str(rss)).getroot()
                    for it in root.findall(".//item")[:5]:
                        t = (it.findtext("title") or "").strip()[:90]
                        l = (it.findtext("link") or "https://analisis.pruebapublica.com/").strip()
                        d = (it.findtext("description") or "").strip()[:140]
                        # tarjeta compacta con título + descripción
                        items.append('<li style="margin:8px 0"><a href="' + l + '" style="color:#c2410c;text-decoration:none;font-weight:700">' + t + '</a><br><span style="color:#475569;font-size:.82rem">' + d + '</span></li>')
                body_blog = '<ul style="padding-left:18px">' + "".join(items) + '</ul>' if items else "<p>Visita el blog para los ultimos analisis.</p>"
            except Exception as e:
                print(f"[digest][blog] parse error: {e}")
                body_blog = "<p>Visita el blog para los ultimos analisis.</p>"
            sid = row["id"]
            baja = BASE_URL + "/api/baja?id=" + sid
            html = ('<div style="font-family:system-ui;max-width:600px;margin:0 auto">'
                    '<h2>Noticias Analisis &middot; Resumen semanal</h2>'
                    '<p>Ultimos articulos del blog:</p>'
                    + body_blog +
                    '<p><a href="https://analisis.pruebapublica.com" style="background:#c2410c;color:#fff;padding:9px 16px;'
                    'border-radius:6px;text-decoration:none;font-weight:700">Leer el blog</a></p>'
                    '<p><a href="' + baja + '">Darme de baja</a></p>'
                    '<p style="font-size:.8rem;color:#888">Analisis &middot; analisis.pruebapublica.com</p></div>')
            if not dry_run:
                ok = send_email(row["destino"], "Analisis - Resumen semanal", html)
                print("[digest][blog] ok" if ok else "[digest][blog] FAIL" + " -> " + row["destino"])
            else:
                print("[digest][blog][dry] -> " + row["destino"])
            enviados += 1
            continue
        try:
            mis_temas = json.loads(row["temas"]) or []
        except Exception:
            mis_temas = []
        if not mis_temas:
            continue
        lines = ['<ul style="padding-left:18px">']
        # salud por tema para B (una sola consulta)
        try:
            salud_map = {r["tema"]: r for r in salud_por_tema()}
        except Exception:
            salud_map = {}
        for t in mis_temas:
            st = estados.get(t, {})
            txt = texto_dial(t, st.get("estado", "estable"))
            hoy = st.get("hoy", 0)
            high_hoy = st.get("high_hoy", 0)
            high_48 = st.get("high_48", 0)
            # top cluster
            top_txt = ""
            banda_txt = ""
            try:
                cur = conn.execute("SELECT id, cluster_label, overall_score FROM clusters WHERE tema_id=? ORDER BY overall_score DESC LIMIT 1", (t,))
                crow = cur.fetchone()
                if crow:
                    lab = crow["cluster_label"] or t
                    sc = int(crow["overall_score"] or 0)
                    # n_cuentas = distinct authors en cluster_events (cluster_events.cluster_id = clusters.id)
                    try:
                        cid = crow["id"]
                        nc = conn.execute("SELECT COUNT(DISTINCT author) FROM cluster_events WHERE cluster_id=?", (cid,)).fetchone()[0] or 0
                    except: nc = 0
                    banda = "CRITICAL" if sc>=80 else "HIGH" if sc>=60 else "ANOMALOUS" if sc>=40 else "WATCH" if sc>=20 else "NORMAL"
                    tit = ""
                    try:
                        er = conn.execute("SELECT title, url FROM cluster_events WHERE cluster_id=? ORDER BY ts DESC LIMIT 1", (cid,)).fetchone()
                        if er and er["title"]:
                            tit = (er["title"] or "").strip()[:90]
                            url = (er["url"] or "").strip()
                            url = (er["url"] or "").strip()
                            if tit.startswith("http"):
                                tit = tit.split(" ",1)[-1][:90] if " " in tit else tit[:90]
                    except: pass
                    url_link = f' · <a href="{url}" style="color:#c2410c">"{tit}"</a>' if tit and url else (f' · "{tit}"' if tit else "")
                    top_txt = f"<br><span style=\"color:#475569;font-size:.82rem\">Top: {lab} {sc}/100 {banda} · {nc} cuentas{url_link}</span>"
                    banda_txt = f" · {banda}"
            except Exception as e:
                print(f"[digest] top err {t}: {e}")
                top_txt = ""
            # banda p25-p75 y salud
            extra = ""
            try:
                # p25/p75 de findings intensidad últimos 30d
                rows = conn.execute("SELECT intensidad FROM findings WHERE tema_id=? AND tipo='cluster' AND fecha > strftime('%s','now','-30 days') ORDER BY intensidad", (t,)).fetchall()
                vals = [r[0] for r in rows if r[0] is not None]
                if len(vals) >= 3:
                    vals.sort()
                    p25 = vals[int(len(vals)*0.25)]
                    p75 = vals[int(len(vals)*0.75)]
                    extra += f" · banda normal {int(p25)}-{int(p75)}"
            except: pass
            try:
                sm = salud_map.get(t)
                if sm:
                    extra += f" · salud {int(sm.get('score',0))}/100 {sm.get('nivel','')}"
            except: pass
            # narrativas sostenidas
            try:
                narr = conn.execute("SELECT COUNT(*) FROM findings WHERE tema_id=? AND tipo='narrativa' AND intensidad>=60", (t,)).fetchone()[0]
                if narr:
                    extra += f" · {narr} narrativas HIGH"
            except: pass
            link = f"{BASE_URL}/#{t}"
            lines.append(f"<li style=\"margin:12px 0\"><b>{NOMBRE_TEMA.get(t, t)}</b>: {txt}{banda_txt} · <b>{hoy}/100</b> · {high_hoy} HIGH hoy vs {high_48} hace 48h<span style=\"color:#64748b;font-size:.82rem\">{extra}</span>{top_txt}<br><a href=\"{link}\" style=\"color:#c2410c;font-size:.82rem\">Ver detalle en el radar →</a></li>")
        lines.append("</ul>")
        sid = row["id"]
        baja = f"{BASE_URL}/api/baja?id={sid}"
        html = ('<div style="font-family:system-ui;max-width:600px;margin:0 auto">'
                '<h2>📡 Radar FIMI · Resumen semanal</h2>'
                '<p>Estado actual de tus temas (score, HIGH y top cluster):</p>'
                + "".join(lines) +
                f'<p><a href="{BASE_URL}" style="background:#c2410c;color:#fff;padding:9px 16px;'
                f'border-radius:6px;text-decoration:none;font-weight:700">Abrir el radar</a></p>'
                f'<p style="font-size:.82rem;color:#64748b">Recibes esto porque te suscribiste en fimi.viajeinteligencia.com · 1 email/semana · <a href="{baja}">Darme de baja</a></p>'
                '<p style="font-size:.8rem;color:#888">Radar FIMI · fimi.viajeinteligencia.com · semilla única</p></div>')
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
