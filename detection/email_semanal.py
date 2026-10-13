#!/usr/bin/env python3
"""detection/email_semanal.py — Resumen SEMANAL editorial del observatorio FIMI.

Pensado para retención: cada semana, 3 señales destacadas + 1 caso + 1 pista de
método, con enlace al informe visual del tema. Sin over-claim («amplificación
medida, no coordinación confirmada»).

Personalización: si el suscriptor eligió temas, el resumen se limita a ellos;
si no, muestra lo más alto del conjunto activo.

Envía con Resend a suscriptores confirmados con frecuencia semanal/ambos.
Flags: --dry (imprime HTML), --to <email>, --todos-email, --db, --temas a,b.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "radar.db"
BASE_URL = "https://fimi.viajeinteligencia.com"

BAND_ES = {
    "NORMAL": "Normal", "WATCH": "En observación", "ANOMALOUS": "Amplificación anómala",
    "HIGH": "Amplificación alta", "CRITICAL": "Amplificación muy alta",
}


def _band(score):
    s = float(score or 0)
    if s >= 80:
        return "CRITICAL"
    if s >= 60:
        return "HIGH"
    if s >= 40:
        return "ANOMALOUS"
    if s >= 20:
        return "WATCH"
    return "NORMAL"


def _load_temas_nombres():
    try:
        import yaml
        cfg = yaml.safe_load(open(ROOT / "config.yaml"))
        return {k: (v or {}).get("nombre", k) for k, v in (cfg.get("temas") or {}).items()}
    except Exception:
        return {}


_PISTAS = [
    ("Banda ≠ veredicto", "Una banda alta mide <b>amplificación</b> (varias cuentas repitiendo lo mismo), "
     "no coordinación confirmada ni autoría. El punto de partida es <b>revisar</b>, no concluir."),
    ("Eco de prensa", "Muchas señales altas son <b>eco de prensa</b>: un medio publica y decenas lo repiten. "
     "El sistema lo distingue de la coordinación entre cuentas anónimas."),
    ("El «no» también es resultado", "Cuando no hay señal, el radar lo dice. La ausencia de hallazgo es un "
     "resultado válido, no un fallo."),
    ("Ventana temporal", "La <b>sincronía de minutos</b> entre cuentas distintas sugiere algo más que coincidencia; "
     "el eco de semanas solo sugiere que el tema sigue vivo."),
    ("Permalink estable", "Cada campaña sostenida tiene un enlace <code>/c/…</code> que <b>no cambia</b> aunque el "
     "cluster se renumere cada ciclo: sirve para seguirla en el tiempo."),
]


def _n_cuentas(conn, cluster_id):
    try:
        return conn.execute(
            "SELECT COUNT(DISTINCT author) FROM cluster_events WHERE cluster_id=?",
            (cluster_id,)).fetchone()[0] or 0
    except Exception:
        return 0


def _titular(conn, cluster_id):
    try:
        r = conn.execute(
            "SELECT text FROM cluster_events WHERE cluster_id=? AND text<>'' "
            "ORDER BY LENGTH(text) ASC LIMIT 1", (cluster_id,)).fetchone()
        return (r["text"] if r else "")[:140]
    except Exception:
        return ""


def construir(db_path=None, temas=None):
    conn = sqlite3.connect(f"file:{db_path or DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        nombres = _load_temas_nombres()
        activos = [t for t, n in nombres.items()]
        filtro = [t for t in (temas or []) if t in nombres] or None
        where, args = "", []
        if filtro:
            where = " WHERE tema_id IN (%s)" % ",".join("?" * len(filtro))
            args = list(filtro)
        else:
            activos = [t for t in activos if t] or None
            if activos:
                where = " WHERE tema_id IN (%s)" % ",".join("?" * len(activos))
                args = list(activos)
        rows = conn.execute(
            "SELECT id, cluster_label, tema_id, overall_score FROM clusters"
            + where + " ORDER BY overall_score DESC LIMIT 12", args).fetchall()
        destacados = []
        for r in rows:
            if len(destacados) >= 3:
                break
            destacados.append({
                "tema": r["tema_id"],
                "tema_nombre": nombres.get(r["tema_id"], r["tema_id"]),
                "score": round(float(r["overall_score"] or 0)),
                "banda": _band(r["overall_score"]),
                "cuentas": _n_cuentas(conn, r["id"]),
                "titular": _titular(conn, r["id"]),
            })
        n_ev = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        n_cl = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
        n_high = conn.execute(
            "SELECT COUNT(*) FROM clusters WHERE overall_score>=60").fetchone()[0]
    finally:
        conn.close()
    return {"destacados": destacados, "n_ev": n_ev, "n_cl": n_cl, "n_high": n_high,
            "temas": filtro or []}


def _esc(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _bloque_destacado(d):
    tema_slug = _esc(d["tema"])
    visual = f"{BASE_URL}/informes/visual/{tema_slug}.html"
    tit = _esc(d["titular"])
    tit_html = f'<div style="color:#475569;font-size:.86rem;margin:2px 0 0">«{tit}…»</div>' if tit else ""
    return (
        '<div style="border:1px solid #e2e8f0;border-left:4px solid #c2410c;border-radius:8px;'
        'padding:10px 14px;margin:8px 0">'
        f'<div style="font-weight:700;color:#0f172a">{_esc(d["tema_nombre"])} '
        f'<span style="color:#c2410c">· {d["score"]}/100 {BAND_ES.get(d["banda"], d["banda"])}</span></div>'
        f'<div style="color:#64748b;font-size:.8rem;margin-top:2px">{d["cuentas"]} cuentas · '
        f'señal de amplificación medida (no coordinación confirmada)</div>'
        f'{tit_html}'
        f'<div style="margin-top:6px"><a href="{visual}" style="color:#c2410c;font-weight:600;'
        f'text-decoration:none">Ver informe visual →</a></div></div>')


def html_boletin(d, baja_url="#", pista_idx=0):
    import datetime
    pista = _PISTAS[pista_idx % len(_PISTAS)]
    if d["destacados"]:
        cuerpo = "".join(_bloque_destacado(x) for x in d["destacados"])
    else:
        cuerpo = ('<p style="color:#475569">Esta semana no hay señales destacadas en tus temas. '
                  'La ausencia de señal también es un resultado.</p>')
    return (
        '<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'max-width:620px;margin:0 auto;color:#1e293b;line-height:1.55">'
        f'<p style="color:#94a3b8;font-size:.78rem;margin:0 0 2px">{datetime.date.today().strftime("%d %b %Y")} · '
        'fimi.viajeinteligencia.com</p>'
        '<h2 style="margin:0 0 4px">📡 Resumen semanal · Observatorio de amplificación</h2>'
        '<p style="color:#64748b;margin:0 0 10px">La semana en señales de amplificación (ámbito FIMI): '
        '<b>cómo se mueve algo</b>, no si es verdad ni quién está detrás.</p>'
        '<h3 style="margin:14px 0 2px">🔎 Señales destacadas</h3>'
        + cuerpo
        + f'<h3 style="margin:16px 0 4px;border-top:1px solid #e2e8f0;padding-top:10px">🧭 Pista de método: {pista[0]}</h3>'
        f'<p style="color:#475569;font-size:.9rem;margin:2px 0">{pista[1]}</p>'
        '<h3 style="margin:16px 0 4px;border-top:1px solid #e2e8f0;padding-top:10px">Límites</h3>'
        '<p style="color:#475569;font-size:.9rem;margin:2px 0">Cobertura parcial (sin X, TikTok, Instagram, '
        'Facebook, YouTube, WhatsApp ni Telegram privado). Validación experimental. Una señal es un '
        '<b>punto de partida</b>, no una conclusión.</p>'
        f'<p style="margin:18px 0"><a href="{BASE_URL}" style="background:#c2410c;color:#fff;padding:10px 18px;'
        'border-radius:8px;text-decoration:none;font-weight:700">Abrir el observatorio</a> '
        f' <a href="{BASE_URL}/suscribirse.html" style="color:#c2410c;font-weight:700">Ajustar temas</a></p>'
        '<p style="font-size:.8rem;color:#94a3b8">Recibes esto por suscribirte en fimi.viajeinteligencia.com · '
        f'1 email/semana · <a href="{baja_url}">Darme de baja</a></p></div>'
    )


def _temas_de(raw):
    try:
        v = json.loads(raw or "[]")
        return [str(x) for x in v] if isinstance(v, list) else []
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--to", default=None)
    ap.add_argument("--todos-email", action="store_true")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--temas", default=None, help="lista separada por comas (para --dry)")
    args = ap.parse_args()

    temas_dry = [t.strip() for t in args.temas.split(",")] if args.temas else None
    d = construir(args.db, temas_dry)
    print(f"[semanal] corpus={d['n_ev']} clusters={d['n_cl']} high={d['n_high']} "
          f"destacados={len(d['destacados'])}", file=sys.stderr)

    if args.dry:
        print(html_boletin(d))
        return

    from detection.email_api import send_email
    from detection.schema_suscripciones import init as _init
    import sqlite3 as _s
    con = _s.connect(str(ROOT / "data" / "radar.db"))
    try:
        _init(con)
    except Exception as e:
        print(f"[semanal] schema init: {e}", file=sys.stderr)
    if args.to:
        destinos = [{"id": None, "destino": args.to, "temas": "[]"}]
    elif args.todos_email:
        destinos = [dict(r) for r in con.execute(
            "SELECT id,destino,temas FROM suscripciones WHERE canal='email' AND confirmado=1")]
    else:
        destinos = [dict(r) for r in con.execute(
            "SELECT id,destino,temas FROM suscripciones WHERE canal='email' AND confirmado=1"
            " AND frecuencia IN ('semanal','ambos')")]
    con.close()

    import datetime
    pista_idx = datetime.date.today().isocalendar()[1]
    enviados = 0
    for row in destinos:
        temas_sub = _temas_de(row.get("temas")) or None
        dsub = construir(args.db, temas_sub)
        baja = f"{BASE_URL}/api/baja?id={row['id']}" if row.get("id") else "#"
        html = html_boletin(dsub, baja, pista_idx)
        ok = send_email(row["destino"], "Observatorio · Resumen semanal", html)
        print(f"[semanal] {'ok' if ok else 'FAIL'} -> {row['destino']}")
        enviados += 1
    print(f"[semanal] enviados={enviados}", file=sys.stderr)


if __name__ == "__main__":
    main()
