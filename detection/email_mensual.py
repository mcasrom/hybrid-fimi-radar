#!/usr/bin/env python3
"""detection/email_mensual.py — Boletín mensual EDITORIAL (KPIs + mini-gráfico + caso/descarte).

Distinto de `email_digest.py` (digest de datos). Cuenta una historia, sin over-claim:
  1. KPIs del mes.
  2. Mini-gráfico: cómo se reparte lo que el observatorio ve (feed vs coordinación vs eco...).
  3. Caso del mes: reproducción coordinada entre cuentas (prefiriendo ventana corta).
  4. Descarte del mes: feed de una sola fuente (etiquetado benigno).
  5. Límites + CTA.

Envía con Resend a suscriptores confirmados; `--dry`/`--to`/`--todos-email`.
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

LABELS = {
    "single_source_feed": "Feed de una fuente", "single_piece_echo": "Eco de 1 pieza",
    "mainstream_echo": "Eco de prensa", "cross_account_synchrony": "Coordinación entre cuentas",
    "synchronized_without_operator": "Sincronía sin operador", "organic_viral": "Viralidad",
    "automated_non_malicious": "Automatización", "legitimate_mobilization": "Movilización",
    "graph_artifact": "Artefacto de grafo", "unresolved": "Sin concluir",
}
COLORES = {
    "single_source_feed": "#94a3b8", "mainstream_echo": "#94a3b8", "single_piece_echo": "#cbd5e1",
    "cross_account_synchrony": "#c2410c", "synchronized_without_operator": "#0ea5e9",
    "organic_viral": "#22c55e", "automated_non_malicious": "#a3a3a3",
    "legitimate_mobilization": "#22c55e", "graph_artifact": "#e2e8f0", "unresolved": "#f59e0b",
}


def _load_json(raw):
    try:
        return json.loads(raw or "[]")
    except Exception:
        return []


def _principal(items):
    return next((x["code"] for x in items if x.get("status") == "supported"), None) or \
        next((x["code"] for x in items if x.get("status") == "plausible"), "unresolved")


def _candidatos(conn, code, min_score=0.0):
    """Clusters cuya explicación principal soportada sea `code`, con su ventana y métricas."""
    out = []
    for r in conn.execute("SELECT id,cluster_label,tema_id,overall_score,alternative_explanations"
                          " FROM clusters"):
        if (r["overall_score"] or 0) < min_score:
            continue
        items = _load_json(r["alternative_explanations"])
        if not any(x.get("code") == code and x.get("status") == "supported" for x in items):
            continue
        ev = conn.execute("SELECT ts,author,title,url FROM cluster_events WHERE cluster_id=?",
                          (r["id"],)).fetchall()
        ts = [e["ts"] for e in ev if e["ts"]]
        tit = Counter((e["title"] or e["text"] or "").replace("\n", " ").replace("\r", " ").strip()[:90]
                      for e in ev if (e["title"] or e["text"]))
        doms = Counter(urlparse(e["url"] or "").netloc.replace("www.", "") for e in ev if e["url"])
        out.append({
            "label": r["cluster_label"], "tema": r["tema_id"], "score": round(r["overall_score"] or 0, 1),
            "cuentas": len({e["author"] for e in ev if e["author"]}), "eventos": len(ev),
            "ventana_h": round((max(ts) - min(ts)) / 3600, 1) if ts else 9999.0,
            "titular": (tit.most_common(1)[0][0] if tit else ""),
            "dominios": doms.most_common(3), "url": next((e["url"] for e in ev if e["url"]), ""),
        })
    return out


def _mejor(cands, prefer_tight=False):
    """El mejor candidato: si prefer_tight, ventana <= 24 h primero, luego más cuentas/score."""
    if not cands:
        return None
    if prefer_tight:
        cands.sort(key=lambda x: (x["ventana_h"] > 24, -x["cuentas"], -x["score"]))
    else:
        cands.sort(key=lambda x: -x["score"])
    return cands[0]


def construir(db_path=None):
    conn = sqlite3.connect(f"file:{db_path or DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        n_ev = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        n_cl = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
        n_high = conn.execute("SELECT COUNT(*) FROM clusters WHERE overall_score>=60").fetchone()[0]
        dist = Counter()
        for r in conn.execute("SELECT alternative_explanations FROM clusters"):
            dist[_principal(_load_json(r["alternative_explanations"]))] += 1
        caso = _mejor(_candidatos(conn, "cross_account_synchrony", min_score=55), prefer_tight=True)
        desc = _mejor(_candidatos(conn, "single_source_feed"), prefer_tight=False)
    finally:
        conn.close()
    return {"n_ev": n_ev, "n_cl": n_cl, "n_high": n_high, "dist": dist,
            "caso": caso, "descarte": desc}


def _esc(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _kpis(d):
    def kpi(v, t):
        return (f'<td style="padding:6px 10px;text-align:center"><div style="font-size:1.3rem;'
                f'font-weight:800;color:#c2410c">{v}</div><div style="font-size:.72rem;color:#64748b">{t}</div></td>')
    return ('<table style="width:100%;border-collapse:collapse;border:1px solid #e2e8f0;border-radius:8px;margin:8px 0"><tr>'
            + kpi(f'{d["n_ev"]:,}'.replace(",", "."), "eventos") + kpi(d["n_cl"], "clusters")
            + kpi(d["n_high"], "HIGH/CRITICAL") + kpi(d["dist"].get("cross_account_synchrony", 0), "coordinación entre cuentas")
            + '</tr></table>')


def _grafico(d):
    total = max(sum(d["dist"].values()), 1)
    orden = ["cross_account_synchrony", "single_source_feed", "single_piece_echo", "mainstream_echo",
             "synchronized_without_operator", "organic_viral", "automated_non_malicious",
             "legitimate_mobilization", "graph_artifact", "unresolved"]
    rows = ""
    for code in orden:
        n = d["dist"].get(code, 0)
        if not n:
            continue
        pct = round(n / total * 100)
        col = COLORES.get(code, "#94a3b8")
        rows += (f'<tr><td style="width:180px;font-size:.78rem;color:#334155;padding:2px 6px 2px 0">{LABELS[code]}</td>'
                 f'<td style="padding:2px 6px"><div style="background:#eef2f7;border-radius:4px;height:10px">'
                 f'<div style="width:{pct}%;height:10px;background:{col};border-radius:4px"></div></div></td>'
                 f'<td style="width:44px;text-align:right;font-size:.78rem;color:#475569">{n}</td></tr>')
    return ('<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 12px;margin:8px 0">'
            '<div style="font-size:.74rem;color:#64748b;font-weight:700;text-transform:uppercase;margin-bottom:4px">'
            'Qué ve el observatorio (todo el corpus)</div>'
            f'<table style="border-collapse:collapse;width:100%">{rows}</table>'
            '<div style="font-size:.7rem;color:#94a3b8;margin-top:4px">La barra naranja es la señal que merece revisión; '
            'las grises son difusión/eco (benignas).</div></div>')


def _bloque_caso(c):
    if not c:
        return "<p>(sin caso este mes)</p>"
    doms = ", ".join(f"{x[0]} ({x[1]})" for x in c.get("dominios", []))
    url = f'<a href="{_esc(c.get("url"))}" style="color:#c2410c">{_esc(c.get("url"))[:80]}</a>' if c.get("url") else ""
    return (f'<p style="margin:6px 0"><b>{_esc(c.get("label"))}</b> · tema <b>{_esc(c.get("tema"))}</b> · score {c.get("score")}/100</p>'
            f'<ul style="margin:6px 0;color:#334155;font-size:.92rem">'
            f'<li><b>{c.get("cuentas")} cuentas</b> distintas · {c.get("eventos")} eventos · ventana {c.get("ventana_h")} h</li>'
            f'<li>Titular repetido: «{_esc(c.get("titular"))}…»</li><li>Dominios: {_esc(doms)}</li><li>{url}</li></ul>')


def html_boletin(d, baja_url="#"):
    return (
        '<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'max-width:620px;margin:0 auto;color:#1e293b;line-height:1.55">'
        '<h2 style="margin:0 0 4px">📡 Observatorio · Boletín mensual</h2>'
        '<p style="color:#64748b;margin:0 0 10px">Señales de coordinación y amplificación (ámbito FIMI). '
        'Mide <b>cómo se mueve algo</b>, no si es verdad ni quién está detrás.</p>'
        + _kpis(d)
        + '<h3 style="margin:14px 0 2px">📊 El mes en datos</h3>' + _grafico(d)
        + '<h3 style="margin:16px 0 4px;border-top:1px solid #e2e8f0;padding-top:10px">🔎 Caso del mes: reproducción coordinada</h3>'
        + _bloque_caso(d["caso"])
        + '<p style="color:#475569;font-size:.9rem">Varias cuentas <b>distintas</b>, ninguna dominante, con el '
        '<b>mismo contenido</b> en poco tiempo. Es una <b>señal</b> que merece revisión; <b>no</b> prueba de campaña ni atribución.</p>'
        + '<h3 style="margin:16px 0 4px;border-top:1px solid #e2e8f0;padding-top:10px">🧹 Descarte del mes: feed de una sola fuente</h3>'
        + _bloque_caso(d["descarte"])
        + '<p style="color:#475569;font-size:.9rem">Una cuenta o dominio concentran casi todo: el sistema lo etiqueta como '
        '<b>benigno</b> (alguien comparte su propio sitio), no como coordinación.</p>'
        + '<h3 style="margin:16px 0 4px;border-top:1px solid #e2e8f0;padding-top:10px">Límites</h3>'
        '<p style="color:#475569;font-size:.9rem">Cobertura parcial (sin X, TikTok, Instagram, Facebook, YouTube, WhatsApp '
        'ni Telegram privado). Validación experimental. Una señal es un <b>punto de partida</b>, no una conclusión.</p>'
        f'<p style="margin:18px 0"><a href="{BASE_URL}" style="background:#c2410c;color:#fff;padding:10px 18px;'
        'border-radius:8px;text-decoration:none;font-weight:700">Abrir el observatorio</a> '
        f'<a href="{BASE_URL}/apoyo.html" style="margin-left:8px;color:#c2410c;font-weight:700">Apoyar el proyecto</a></p>'
        f'<p style="font-size:.8rem;color:#94a3b8">Recibes esto por suscribirte en fimi.viajeinteligencia.com · 1 email/mes · '
        f'<a href="{baja_url}">Darme de baja</a></p></div>'
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--to", default=None)
    ap.add_argument("--todos-email", action="store_true")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    d = construir(args.db)
    print(f"[mensual] corpus={d['n_ev']} clusters={d['n_cl']} high={d['n_high']} "
          f"dist={dict(d['dist'])}", file=sys.stderr)

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
        print(f"[mensual] schema init: {e}", file=sys.stderr)
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
