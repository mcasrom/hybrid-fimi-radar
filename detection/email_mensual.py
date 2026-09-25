#!/usr/bin/env python3
"""detection/email_mensual.py — Boletín mensual EDITORIAL (no el digest de datos).

Distinto de `email_digest.py` (que envía el estado semanal de los diales): este boletín
cuenta una historia con evidencia y sin over-claim, para captar audiencia:

  1. Qué se movió este mes (cifras).
  2. Caso del mes: una **reproducción coordinada entre cuentas** (con evidencia real).
  3. Descarte del mes: un **feed de una sola fuente** que el sistema etiqueta como benigno.
  4. Límites (señal ≠ campaña) + CTA (dashboard y apoyo).

Envía con Resend a los suscriptores con frecuencia='mensual' (doble opt-in), reutilizando
`email_api.send_email`. Modo `--dry` para revisar sin enviar.

Uso:
    python detection/email_mensual.py --dry          # imprime el HTML (no envía)
    python detection/email_mensual.py                # envía a los 'mensual'
    python detection/email_mensual.py --to x@y.com   # envía solo a esa dirección
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "radar.db"
BASE_URL = "https://fimi.viajeinteligencia.com"


def _load_json(raw):
    try:
        return json.loads(raw or "[]")
    except Exception:
        return []


def _ejemplo(conn, code, n=1):
    """Mejor cluster (por score) cuya explicación principal soportada sea `code`."""
    cands = []
    for r in conn.execute("SELECT id,cluster_label,tema_id,overall_score,alternative_explanations"
                          " FROM clusters"):
        items = _load_json(r["alternative_explanations"])
        if any(x.get("code") == code and x.get("status") == "supported" for x in items):
            cands.append(r)
    cands.sort(key=lambda r: -(r["overall_score"] or 0))
    out = []
    for r in cands[:n]:
        ev = conn.execute("SELECT ts,author,title,url FROM cluster_events WHERE cluster_id=?",
                          (r["id"],)).fetchall()
        tit = Counter((e["title"] or e["text"] or "").replace("\n", " ").replace("\r", " ").strip()[:90]
                      for e in ev if (e["title"] or e["text"]))
        doms = Counter(urlparse(e["url"] or "").netloc.replace("www.", "") for e in ev if e["url"])
        ts = [e["ts"] for e in ev if e["ts"]]
        out.append({
            "label": r["cluster_label"], "tema": r["tema_id"],
            "score": round(r["overall_score"] or 0, 1),
            "cuentas": len({e["author"] for e in ev if e["author"]}),
            "eventos": len(ev),
            "ventana_h": round((max(ts) - min(ts)) / 3600, 1) if ts else 0,
            "titular": (tit.most_common(1)[0][0] if tit else ""),
            "dominios": doms.most_common(3),
            "url": next((e["url"] for e in ev if e["url"]), ""),
        })
    return out


def construir(db_path=None):
    conn = sqlite3.connect(f"file:{db_path or DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        n_ev = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        n_cl = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
        n_high = conn.execute("SELECT COUNT(*) FROM clusters WHERE overall_score>=60").fetchone()[0]
        cross = _ejemplo(conn, "cross_account_synchrony", 1)
        feed = _ejemplo(conn, "single_source_feed", 1)
    finally:
        conn.close()
    return {"n_ev": n_ev, "n_cl": n_cl, "n_high": n_high, "cross": cross, "feed": feed}


def _esc(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def html_boletin(d, baja_url="#"):
    c = (d["cross"] or [{}])[0]
    f = (d["feed"] or [{}])[0]
    def bloque_caso(c):
        if not c:
            return ""
        doms = ", ".join(f"{x[0]} ({x[1]})" for x in c.get("dominios", []))
        url = f'<a href="{_esc(c.get("url"))}" style="color:#c2410c">{_esc(c.get("url"))[:80]}</a>' if c.get("url") else ""
        return (f'<p style="margin:6px 0"><b>{_esc(c.get("label"))}</b> · tema <b>{_esc(c.get("tema"))}</b> '
                f'· score {c.get("score")}/100</p>'
                f'<ul style="margin:6px 0;color:#334155;font-size:.92rem">'
                f'<li><b>{c.get("cuentas")} cuentas</b> distintas · {c.get("eventos")} eventos · ventana {c.get("ventana_h")} h</li>'
                f'<li>Titular repetido: «{_esc(c.get("titular"))}…»</li>'
                f'<li>Dominios: {_esc(doms)}</li>'
                f'<li>{url}</li></ul>')
    return (
        '<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'max-width:620px;margin:0 auto;color:#1e293b;line-height:1.55">'
        '<h2 style="margin:0 0 4px">📡 Observatorio · Boletín mensual</h2>'
        '<p style="color:#64748b;margin:0 0 14px">Señales de coordinación y amplificación (ámbito FIMI). '
        'Mide <b>cómo se mueve algo</b>, no si es verdad ni quién está detrás.</p>'
        '<p><b>Qué se movió este mes:</b> ' + f'{d["n_ev"]:,} eventos y {d["n_cl"]} clusters; '
        f'{d["n_high"]} en banda alta (HIGH/CRITICAL).</p>'.replace(",", ".")
        + '<h3 style="margin:16px 0 4px;border-top:1px solid #e2e8f0;padding-top:10px">🔎 Caso del mes: reproducción coordinada</h3>'
        + bloque_caso(c) +
        '<p style="color:#475569;font-size:.9rem">Varias cuentas <b>distintas</b>, ninguna dominante, '
        'con el <b>mismo contenido</b> en poco tiempo. Es una <b>señal</b> que merece revisión; '
        '<b>no</b> prueba de campaña ni atribución de actor.</p>'
        '<h3 style="margin:16px 0 4px;border-top:1px solid #e2e8f0;padding-top:10px">🧹 Descarte del mes: feed de una sola fuente</h3>'
        + bloque_caso(f) +
        '<p style="color:#475569;font-size:.9rem">Una cuenta o dominio concentran casi todo: '
        'el sistema lo etiqueta como <b>benigno</b> (alguien comparte su propio sitio), no como coordinación.</p>'
        '<h3 style="margin:16px 0 4px;border-top:1px solid #e2e8f0;padding-top:10px">Límites</h3>'
        '<p style="color:#475569;font-size:.9rem">Cobertura parcial (sin X, TikTok, Instagram, Facebook, '
        'YouTube, WhatsApp ni Telegram privado). Validación experimental. Una señal es un '
        '<b>punto de partida</b>, no una conclusión.</p>'
        f'<p style="margin:18px 0"><a href="{BASE_URL}" style="background:#c2410c;color:#fff;padding:10px 18px;'
        'border-radius:8px;text-decoration:none;font-weight:700">Abrir el observatorio</a> '
        f'<a href="{BASE_URL}/apoyo.html" style="margin-left:8px;color:#c2410c;font-weight:700">Apoyar el proyecto</a></p>'
        f'<p style="font-size:.8rem;color:#94a3b8">Recibes esto por suscribirte en fimi.viajeinteligencia.com · '
        f'1 email/mes · <a href="{baja_url}">Darme de baja</a></p></div>'
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--to", default=None)
    ap.add_argument("--todos-email", action="store_true",
                    help="envía a TODOS los suscriptores email confirmados (prueba), ignorando frecuencia")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    d = construir(args.db)
    print(f"[mensual] corpus={d['n_ev']} clusters={d['n_cl']} high={d['n_high']} "
          f"cross={len(d['cross'])} feed={len(d['feed'])}", file=sys.stderr)

    if args.dry:
        print(html_boletin(d))
        return

    from detection.email_api import send_email
    from detection.schema_suscripciones import init as _init
    import sqlite3 as _s
    con = _s.connect(str(ROOT / "data" / "radar.db"))
    try:
        _init(con)
    except Exception:
        pass
    if args.to:
        destinos = [{"id": None, "destino": args.to}]
    elif args.todos_email:
        destinos = [dict(r) for r in con.execute(
            "SELECT id,destino FROM suscripciones WHERE canal='email' AND confirmado=1")]
    else:
        destinos = [dict(r) for r in con.execute(
            "SELECT id,destino FROM suscripciones WHERE canal='email' AND confirmado=1"
            " AND frecuencia='mensual'")]
    con.close()
    enviados = 0
    for row in destinos:
        baja = f"{BASE_URL}/api/baja?id={row['id']}" if row.get("id") else "#"
        ok = send_email(row["destino"], "Observatorio · Boletín mensual", html_boletin(d, baja))
        print(f"[mensual] {'ok' if ok else 'FAIL'} -> {row['destino']}")
        enviados += 1
    print(f"[mensual] enviados={enviados}", file=sys.stderr)


if __name__ == "__main__":
    main()
