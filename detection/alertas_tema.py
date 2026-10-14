#!/usr/bin/env python3
"""alertas_tema.py — Aviso event-driven de banda alta en los temas del suscriptor.

Para cada suscriptor de email CONFIRMADO, detecta clusters que cruzan a banda
HIGH/CRITICAL en SUS temas y aún no se le avisaron. **Dedup por `lineage_id`**
(estable entre ciclos; NO por `cluster_label`, que se renumera cada 6 h).
Cooldown diario (máx 1 aviso/día/suscriptor). **Silencio** si no hay señal.

Primera ejecución = **siembra** (marca lo actual como visto, no envía) para no
escupir el histórico. Estado en `data/alertas_estado.json`.

Envío por Resend (`send_email`). Flags: --dry / --to <email> / --todos-email.
Cron sugerido: diario 08:05 UTC (tras el ciclo de 06:30).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "radar.db"
ESTADO = ROOT / "data" / "alertas_estado.json"
BASE_URL = "https://fimi.viajeinteligencia.com"
BAND_ES = {"HIGH": "Amplificación alta", "CRITICAL": "Amplificación muy alta"}
UMBRAL = 60  # banda alta


def _temas_nombres():
    try:
        import yaml
        cfg = yaml.safe_load(open(ROOT / "config.yaml"))
        return {k: (v or {}).get("nombre", k) for k, v in (cfg.get("temas") or {}).items()}
    except Exception:
        return {}


def _estado():
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except Exception:
        return None  # None -> primera vez (sembrar)


def _guardar(d):
    try:
        ESTADO.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[alertas] no se pudo escribir estado: {e}", file=sys.stderr)


def _banda(s):
    return "CRITICAL" if (s or 0) >= 80 else "HIGH" if (s or 0) >= UMBRAL else "WATCH"


def _titular(conn, cluster_label):
    try:
        r = conn.execute("SELECT text FROM cluster_events ce JOIN clusters c ON c.id=ce.cluster_id "
                         "WHERE c.cluster_label=? AND ce.text<>'' AND ce.text LIKE '% %' "
                         "ORDER BY LENGTH(ce.text) ASC LIMIT 1", (cluster_label,)).fetchone()
        return (r[0] if r else "")[:160]
    except Exception:
        return ""


def scan(conn):
    """Devuelve {tema: [alta clusters actuales]} con lineage_id."""
    nombres = _temas_nombres()
    out = {}
    rows = conn.execute(
        "SELECT c.tema_id, c.cluster_label, c.overall_score, cl.lineage_id "
        "FROM clusters c LEFT JOIN cluster_lineage cl ON cl.cluster_label = c.cluster_label "
        "WHERE c.overall_score >= ?", (UMBRAL,)).fetchall()
    for r in rows:
        lid = r["lineage_id"] or r["cluster_label"]
        out.setdefault(r["tema_id"], []).append({
            "lid": lid, "label": r["cluster_label"],
            "score": round(float(r["overall_score"] or 0)),
            "banda": _banda(r["overall_score"]),
            "tema": r["tema_id"], "tema_nombre": nombres.get(r["tema_id"], r["tema_id"]),
            "titular": _titular(conn, r["cluster_label"]),
        })
    return out


def _esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _bloque(c):
    url = f"{BASE_URL}/informes/visual/{c['tema']}.html"
    t = _esc(c["titular"])
    tit = f'<div style="color:#475569;font-size:.86rem;margin:2px 0 0">«{t}…»</div>' if t else ""
    return ('<div style="border:1px solid #e2e8f0;border-left:4px solid #c2410c;border-radius:8px;'
            'padding:10px 14px;margin:8px 0">'
            f'<div style="font-weight:700;color:#0f172a">{_esc(c["tema_nombre"])} '
            f'<span style="color:#c2410c">· {c["score"]}/100 {BAND_ES.get(c["banda"], c["banda"])}</span></div>'
            f'{tit}'
            f'<div style="margin-top:6px"><a href="{url}" style="color:#c2410c;font-weight:600;'
            f'text-decoration:none">Ver informe visual →</a></div></div>')


def html_alerta(nuevos, baja_url="#"):
    bloques = "".join(_bloque(c) for c in nuevos)
    return (
        '<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'max-width:620px;margin:0 auto;color:#1e293b;line-height:1.55">'
        f'<p style="color:#94a3b8;font-size:.78rem;margin:0 0 2px">{datetime.now(timezone.utc):%d %b %Y} · '
        'fimi.viajeinteligencia.com</p>'
        '<h2 style="margin:0 0 4px">🔔 Señal en tus temas</h2>'
        '<p style="color:#64748b;margin:0 0 10px">Hay <b>señal de amplificación en banda alta</b> '
        '(≥60/100) en los temas que sigues. <b>Una banda alta es amplificación medida, no '
        'coordinación confirmada</b> ni atribución de actor.</p>'
        + bloques +
        '<p style="color:#475569;font-size:.9rem;margin:12px 0">Puedes revisar el detalle y los '
        f'límites en cada informe. <a href="{BASE_URL}" style="color:#c2410c;font-weight:700">Abrir el observatorio</a></p>'
        '<p style="color:#475569;font-size:.85rem">¿Demasiados avisos? Ajusta tus temas o la '
        f'frecuencia en <a href="{BASE_URL}/suscribirse.html" style="color:#c2410c">tu suscripción</a>.</p>'
        '<p style="font-size:.8rem;color:#94a3b8">Solo te aviso cuando hay señal en tus temas · '
        f'<a href="{baja_url}">Darme de baja</a></p></div>')


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
    a = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    alta = scan(conn)
    conn.close()

    st = _estado()
    if st is None:
        # primera vez: sembrar (marcar lo actual como visto, sin enviar)
        seed = {t: [c["lid"] for c in cs] for t, cs in alta.items()}
        seed["_last"] = datetime.now(timezone.utc).date().isoformat()
        if a.dry:
            print(f"[alertas] SIEMBRA (dry): {sum(len(v) for k, v in seed.items() if k != '_last')} clusters marcados")
            return
        _guardar(seed)
        print(f"[alertas] siembra: {sum(len(v) for k, v in seed.items() if k != '_last')} clusters marcados (no se envía)")
        return

    # nuevos por tema (lineage_id no vistos)
    nuevos_por_tema, marcados = {}, {}
    for t, cs in alta.items():
        vistos = set(st.get(t, []))
        nuevos = [c for c in cs if c["lid"] not in vistos]
        if nuevos:
            nuevos_por_tema[t] = nuevos
        marcados[t] = sorted(vistos | {c["lid"] for c in cs})

    total_nuevos = sum(len(v) for v in nuevos_por_tema.values())
    print(f"[alertas] nuevos en banda alta: {total_nuevos} ({ {t: len(v) for t, v in nuevos_por_tema.items()} })",
          file=sys.stderr)

    if a.dry:
        for t, cs in nuevos_por_tema.items():
            for c in cs:
                print(f"  {t}: {c['score']}/100 {c['banda']} · {c['titular'][:70]}")
        return

    from detection.email_api import send_email
    from detection.schema_suscripciones import init as _init
    con = sqlite3.connect(str(ROOT / "data" / "radar.db"))
    try:
        _init(con)
    except Exception as e:
        print(f"[alertas] schema init: {e}", file=sys.stderr)
    if a.to:
        destinos = [{"id": None, "destino": a.to, "temas": json.dumps(list(nuevos_por_tema.keys())),
                     "frecuencia": "ambos"}]
    elif a.todos_email:
        destinos = [dict(r) for r in con.execute(
            "SELECT id,destino,temas,frecuencia FROM suscripciones WHERE canal='email' AND confirmado=1")]
    else:
        destinos = [dict(r) for r in con.execute(
            "SELECT id,destino,temas,frecuencia FROM suscripciones WHERE canal='email' AND confirmado=1")]

    hoy = datetime.now(timezone.utc).date().isoformat()
    enviados = 0
    for row in destinos:
        temas_sub = set(_temas_de(row.get("temas")))
        # avisos de los temas del suscriptor que tienen novedad
        suyos = [c for t, cs in nuevos_por_tema.items() if t in temas_sub for c in cs]
        if not suyos:
            continue
        # cooldown diario
        _k = "_sent_" + str(row.get("id") or row["destino"])
        if st.get(_k) == hoy:
            continue
        baja = f"{BASE_URL}/api/baja?id={row['id']}" if row.get("id") else "#"
        ok = send_email(row["destino"], f"🔔 Señal en tus temas ({len(suyos)})",
                        html_alerta(suyos, baja))
        print(f"[alertas] {'ok' if ok else 'FAIL'} -> {row['destino']} ({len(suyos)})")
        if ok:
            st[_k] = hoy
            enviados += 1
    con.close()

    # persistir estado (vistos + marcas)
    for t, ids in marcados.items():
        st[t] = ids
    st["_last"] = hoy
    _guardar(st)
    print(f"[alertas] enviados={enviados}", file=sys.stderr)


if __name__ == "__main__":
    main()
