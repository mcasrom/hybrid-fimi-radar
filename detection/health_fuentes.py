#!/usr/bin/env python3
"""health_fuentes.py — Salud + fiabilidad de las fuentes del Radar FIMI.

Responde a:
  1. ¿Son las fuentes correctas y están vivas? (actividad 7d/30d/90d)
  2. ¿Son fiables? (bias, reliability, transparency de MBFC/Ad Fontes)
  3. ¿Son independientes? (corroboration score: % de eventos corroborados por otra fuente)

Uso:
  .venv/bin/python detection/health_fuentes.py            # JSON por consola
  .venv/bin/python detection/health_fuentes.py --html     # snippet HTML card
"""
import argparse
import json
import sqlite3
import sys
import unicodedata
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "radar.db"
CONFIG = ROOT / "config.yaml"

HEALTH_ACTIVA_DIAS = 7
HEALTH_INACTIVA_DIAS = 30
CORROB_WINDOW_S = 7200  # +/-2h para corroboration


def _norm(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn").lower().strip()


def _cargar_config():
    feeds, telegram, subreddits = [], [], []
    editorial = {}
    try:
        import yaml
        cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
        feeds = cfg.get("feeds", []) or []
        telegram = cfg.get("telegram_canales", []) or []
        subreddits = cfg.get("subreddits", []) or []
        for f in feeds:
            nombre = f.get("nombre", "") if isinstance(f, dict) else str(f)
            editorial[nombre] = {
                "bias": f.get("bias", ""),
                "reliability": f.get("reliability", ""),
                "transparency": f.get("transparency", ""),
                "factcheck_url": f.get("factcheck_url", ""),
                "note": f.get("note", ""),
            }
    except Exception as e:
        print(f"[health] no se pudo leer config.yaml: {e}", file=sys.stderr)
    return feeds, telegram, subreddits, editorial


def _corroboration_scores(con):
    """Calcula corroboration score por fuente: % de eventos con al menos 1 evento
    de OTRO source dentro de +/-CORROB_WINDOW_S segundos."""
    try:
        now = datetime.datetime.now().timestamp()
        cut = int(now - 90 * 86400)
        rows = con.execute(
            "SELECT source, COUNT(*) total FROM events WHERE timestamp >= ? GROUP BY source",
            (cut,)).fetchall()
        stats = {r[0]: r[1] for r in rows}
        corrob = {}
        for src in stats:
            row = con.execute(
                "SELECT COUNT(DISTINCT e1.id) FROM events e1 "
                "JOIN events e2 ON e1.id != e2.id "
                "AND ABS(e1.timestamp - e2.timestamp) <= ? "
                "AND e1.source != e2.source "
                "WHERE e1.source = ? AND e1.timestamp >= ?",
                (CORROB_WINDOW_S, src, cut)).fetchone()
            n_corro = row[0] if row else 0
            total = stats.get(src, 1)
            corrob[src] = round(100.0 * n_corro / total, 1) if total else 0.0
        return corrob
    except Exception:
        return {}


def analizar():
    feeds, telegram, subreddits, editorial = _cargar_config()
    now = datetime.datetime.now().timestamp()
    cut90 = int(now - 90 * 86400)
    cut7 = int(now - HEALTH_ACTIVA_DIAS * 86400)
    cut30 = int(now - HEALTH_INACTIVA_DIAS * 86400)

    stats = {}
    corrob = {}
    if DB.exists():
        con = sqlite3.connect(DB)
        try:
            rows = con.execute(
                "SELECT source, COUNT(*) n90, "
                "  SUM(CASE WHEN timestamp>=? THEN 1 ELSE 0 END) n7, "
                "  MAX(timestamp) last_ts "
                "FROM events WHERE timestamp>=? GROUP BY source",
                (cut7, cut90)).fetchall()
            for src, n90, n7, last_ts in rows:
                stats[src] = {"n90": n90, "n7": n7 or 0, "last_ts": last_ts}
            corrob = _corroboration_scores(con)
        finally:
            con.close()

    def _estado(st):
        if st is None:
            return "inactiva"
        if st["n7"] and st["n7"] > 0:
            return "activa"
        if st and st["last_ts"] and st["last_ts"] >= cut30:
            return "baja"
        return "inactiva"

    fuentes = []

    def _add(nombre, tipo, clave_real):
        st = stats.get(clave_real)
        if st is None:
            for k, v in stats.items():
                if _norm(k) == _norm(clave_real):
                    st = v
                    break
        estado = _estado(st)
        ed = editorial.get(nombre, {})
        corrob_pct = corrob.get(clave_real, None)
        fuentes.append({
            "nombre": nombre,
            "tipo": tipo,
            "clave": clave_real,
            "n90": st["n90"] if st else 0,
            "n7": st["n7"] if st else 0,
            "last_ts": st["last_ts"] if st else None,
            "estado": estado,
            "bias": ed.get("bias", ""),
            "reliability": ed.get("reliability", ""),
            "transparency": ed.get("transparency", ""),
            "factcheck_url": ed.get("factcheck_url", ""),
            "note": ed.get("note", ""),
            "corroboration": corrob_pct,
        })

    for f in feeds:
        nombre = f.get("nombre", "?") if isinstance(f, dict) else str(f)
        _add(nombre, "rss", f"rss:{nombre}")
    for c in telegram:
        _add(f"telegram:{c}", "telegram", f"telegram:{c}")
    for s in subreddits:
        _add(f"reddit:{s}", "reddit", f"reddit:{s}")
    for plat in ("bluesky", "google-news"):
        _add(plat, "plataforma", plat)

    n = len(fuentes)
    activas = sum(1 for f in fuentes if f["estado"] == "activa")
    bajas = sum(1 for f in fuentes if f["estado"] == "baja")
    inactivas = sum(1 for f in fuentes if f["estado"] == "inactiva")
    high_reliability = sum(1 for f in fuentes if f["reliability"] == "high")
    mixed_low = sum(1 for f in fuentes if f["reliability"] in ("mixed", "low"))

    return {
        "generado": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "resumen": {
            "total": n, "activas": activas, "bajas": bajas, "inactivas": inactivas,
            "high_reliability": high_reliability, "mixed_low": mixed_low,
        },
        "alerta": ("Fuentes inactivas" if inactivas else None),
        "fuentes": sorted(fuentes, key=lambda x: (x["estado"] != "activa", -x["n90"])),
    }


BIAS_COLORS = {
    "least-biased": "#16a34a",
    "center": "#2563eb",
    "center-left": "#d97706",
    "center-right": "#d97706",
    "left": "#dc2626",
    "right": "#dc2626",
    "state": "#7c3aed",
}
BIAS_LABELS = {
    "least-biased": "neutral",
    "center": "centro",
    "center-left": "centro-izq",
    "center-right": "centro-der",
    "left": "izquierda",
    "right": "derecha",
    "state": "estatal",
}
REL_COLORS = {
    "high": "#16a34a",
    "mostly-factual": "#d97706",
    "mixed": "#dc2626",
    "low": "#dc2626",
}
REL_LABELS = {
    "high": "alta",
    "mostly-factual": "mayormente factual",
    "mixed": "mixta",
    "low": "baja",
}
ESTADO_COLORS = {"activa": "#16a34a", "baja": "#d97706", "inactiva": "#dc2626"}
ESTADO_TXT = {"activa": "activa", "baja": "actividad baja", "inactiva": "inactiva"}


def _corrob_color(pct):
    if pct is None:
        return "#64748b"
    if pct >= 95:
        return "#16a34a"
    if pct >= 80:
        return "#2563eb"
    if pct >= 60:
        return "#d97706"
    return "#dc2626"


def _html(d):
    R = d["resumen"]
    rows = []
    for f in d["fuentes"]:
        ec = ESTADO_COLORS.get(f["estado"], "#666")
        et = ESTADO_TXT.get(f["estado"], f["estado"])
        last = ""
        if f["last_ts"]:
            dias = int((datetime.datetime.now().timestamp() - f["last_ts"]) / 86400)
            last = f"hace {dias}d" if dias < 90 else f"hace >90d"
        else:
            last = "sin eventos"

        bc = BIAS_COLORS.get(f["bias"], "#64748b")
        bt = BIAS_LABELS.get(f["bias"], f["bias"] or "\u2014")
        rc = REL_COLORS.get(f["reliability"], "#64748b")
        rt = REL_LABELS.get(f["reliability"], f["reliability"] or "\u2014")

        corrob = f["corroboration"]
        cc = _corrob_color(corrob)
        ct = f"{corrob}%" if corrob is not None else "\u2014"

        fc = ""
        if f.get("factcheck_url"):
            fc = (
                ' <a href="' + f["factcheck_url"] + '" target="_blank" rel="noopener" '
                'style="color:#94a3b8;font-size:.7rem">MBFC\u2197</a>'
            )

        rows.append(
            "<tr>"
            '<td style="padding:3px 10px 3px 0;font-size:.8rem">' + f["nombre"] + fc + "</td>"
            '<td style="padding:3px 8px;font-size:.75rem;color:#64748b">' + f["tipo"] + "</td>"
            '<td style="padding:3px 8px;font-size:.75rem"><span style="color:' + bc + ';font-weight:700">' + bt + "</span></td>"
            '<td style="padding:3px 8px;font-size:.75rem"><span style="color:' + rc + '">' + rt + "</span></td>"
            '<td style="padding:3px 8px;text-align:right;font-size:.75rem">' + str(f["n7"]) + "/" + str(f["n90"]) + "</td>"
            '<td style="padding:3px 8px;text-align:right;font-size:.75rem;color:#94a3b8">' + last + "</td>"
            '<td style="padding:3px 8px;text-align:right;font-size:.75rem"><span style="color:' + cc + ';font-weight:700">' + ct + "</span></td>"
            '<td style="padding:3px 8px;font-size:.75rem;color:' + ec + ';font-weight:700">' + et + "</td>"
            "</tr>"
        )

    tabla = "".join(rows)

    aviso_inactive = ""
    if R["inactivas"]:
        aviso_inactive = (
            '<p style="font-size:.8rem;color:#dc2626;margin:6px 0">\u26a0\ufe0f '
            + str(R["inactivas"]) + " fuente(s) inactiva(s) (&gt;"
            + str(HEALTH_INACTIVA_DIAS) + 'd sin eventos). Revisa config.yaml.</p>'
        )

    aviso_mixed = ""
    if R["mixed_low"]:
        aviso_mixed = (
            '<p style="font-size:.8rem;color:#d97706;margin:4px 0">\u2139\ufe0f '
            + str(R["mixed_low"]) + " fuente(s) con fiabilidad <b>mixta o baja</b>"
            " \u2014 usar con cautela en analisis FIMI.</p>"
        )

    return (
        '<div class="card"><h3 id="salud-fuentes">Salud y fiabilidad de las fuentes</h3>'
        '<p class="caption">'
        '<b style="color:#16a34a">' + str(R["activas"]) + "</b> activas \xb7 "
        '<b style="color:#d97706">' + str(R["bajas"]) + "</b> actividad baja \xb7 "
        '<b style="color:#dc2626">' + str(R["inactivas"]) + "</b> inactivas \xb7 "
        "<b>" + str(R["total"]) + "</b> configuradas \xb7 "
        '<b style="color:#16a34a">' + str(R["high_reliability"]) + "</b> alta fiabilidad \xb7 "
        '<b style="color:#dc2626">' + str(R["mixed_low"]) + "</b> mixta/baja"
        "</p>" + aviso_inactive + aviso_mixed
        + '<details><summary style="cursor:pointer;font-size:.84rem;color:#c2410c">'
        + "Ver detalle por fuente</summary>"
        + '<div style="overflow-x:auto"><table style="border-collapse:collapse;margin-top:8px">'
        + '<tr>'
        + '<th align="left" style="font-size:.72rem;color:#94a3b8">fuente</th>'
        + '<th align="left" style="font-size:.72rem;color:#94a3b8">tipo</th>'
        + '<th align="left" style="font-size:.72rem;color:#94a3b8">sesgo</th>'
        + '<th align="left" style="font-size:.72rem;color:#94a3b8">fiabilidad</th>'
        + '<th align="right" style="font-size:.72rem;color:#94a3b8">7d/90d</th>'
        + '<th align="right" style="font-size:.72rem;color:#94a3b8">\xfaltima</th>'
        + '<th align="right" style="font-size:.72rem;color:#94a3b8">corroboration</th>'
        + '<th align="left" style="font-size:.72rem;color:#94a3b8">estado</th>'
        + "</tr>" + tabla + "</table></div></details></div>"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", action="store_true", help="emitir snippet HTML de la card")
    args = ap.parse_args()
    d = analizar()
    if args.html:
        print(_html(d))
    else:
        print(json.dumps(d, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
