#!/usr/bin/env python3
"""health_fuentes.py — Salud de las fuentes del Radar FIMI.

Responde a la pregunta "¿son las fuentes correctas y están vivas?": para cada
fuente CONFIGURADA (feeds RSS, canales Telegram, subreddits) y cada plataforma
agregada (bluesky, google-news) calcula cuántos eventos aporta en la ventana y
cuándo fue su última aparición, y la clasifica:

  activa   : >=1 evento en los ultimos HEALTH_ACTIVA_DIAS (7)
  baja     : ultimo evento entre 8 y HEALTH_INACTIVA_DIAS (30)
  inactiva : ultimo evento hace >30 dias o nunca ha producido
  (alerta) : el resumen expone cuantas fuentes estan inactivas / sin datos

Los feeds configurados que llevan >30d sin producir o que nunca aparecen en la
DB son los candidatos a "fuente muerta / mal configurada" que conviene revisar
en config.yaml (docs/FUENTES.md explica como anadir/quitar).

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


def _norm(s: str) -> str:
    """Normaliza para emparejar nombres con/sin acentos (rss:El País España vs config)."""
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn").lower().strip()


def _cargar_config():
    feeds, telegram, subreddits = [], [], []
    try:
        import yaml
        cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
        feeds = cfg.get("feeds", []) or []
        telegram = cfg.get("telegram_canales", []) or []
        subreddits = cfg.get("subreddits", []) or []
    except Exception as e:
        print(f"[health] no se pudo leer config.yaml: {e}", file=sys.stderr)
    return feeds, telegram, subreddits


def analizar() -> dict:
    """Devuelve dict con resumen y detalle por fuente configurada/real."""
    feeds, telegram, subreddits = _cargar_config()
    now = datetime.datetime.now().timestamp()
    cut90 = int(now - 90 * 86400)
    cut7 = int(now - HEALTH_ACTIVA_DIAS * 86400)
    cut30 = int(now - HEALTH_INACTIVA_DIAS * 86400)

    # fuentes reales en DB: source -> (n90, n7, last_ts)
    stats = {}
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
            # emparejar normalizado por si hay diferencias de acentos
            for k, v in stats.items():
                if _norm(k) == _norm(clave_real):
                    st = v
                    break
        estado = _estado(st)
        fuentes.append({
            "nombre": nombre,
            "tipo": tipo,
            "clave": clave_real,
            "n90": st["n90"] if st else 0,
            "n7": st["n7"] if st else 0,
            "last_ts": st["last_ts"] if st else None,
            "estado": estado,
        })

    for f in feeds:
        nombre = f.get("nombre", "?") if isinstance(f, dict) else str(f)
        _add(nombre, "rss", f"rss:{nombre}")
    for c in telegram:
        _add(f"telegram:{c}", "telegram", f"telegram:{c}")
    for s in subreddits:
        _add(f"reddit:{s}", "reddit", f"reddit:{s}")
    # plataformas agregadas por keywords
    for plat in ("bluesky", "google-news"):
        _add(plat, "plataforma", plat)

    # resumen
    n = len(fuentes)
    activas = sum(1 for f in fuentes if f["estado"] == "activa")
    bajas = sum(1 for f in fuentes if f["estado"] == "baja")
    inactivas = sum(1 for f in fuentes if f["estado"] == "inactiva")
    muertas = [f for f in fuentes if f["estado"] == "inactiva"]

    return {
        "generado": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "resumen": {"total": n, "activas": activas, "bajas": bajas, "inactivas": inactivas},
        "alerta": ("Fuentes inactivas" if inactivas else None),
        "fuentes": sorted(fuentes, key=lambda x: (x["estado"] != "activa", -x["n90"])),
    }


def _html(d: dict) -> str:
    R = d["resumen"]
    estado_color = {"activa": "#16a34a", "baja": "#d97706", "inactiva": "#dc2626"}
    estado_txt = {"activa": "activa", "baja": "actividad baja", "inactiva": "inactiva"}
    rows = []
    for f in d["fuentes"]:
        col = estado_color.get(f["estado"], "#666")
        txt = estado_txt.get(f["estado"], f["estado"])
        last = ""
        if f["last_ts"]:
            dias = int((datetime.datetime.now().timestamp() - f["last_ts"]) / 86400)
            last = f"hace {dias}d" if dias < 90 else f"hace >90d"
        else:
            last = "sin eventos"
        rows.append(
            f"<tr><td style='padding:3px 10px 3px 0;font-size:.8rem'><code>{f['clave']}</code></td>"
            f"<td style='padding:3px 10px;font-size:.8rem;color:#64748b'>{f['tipo']}</td>"
            f"<td style='padding:3px 10px;text-align:right;font-size:.8rem'>{f['n7']}/{f['n90']}</td>"
            f"<td style='padding:3px 10px;text-align:right;font-size:.8rem;color:#94a3b8'>{last}</td>"
            f"<td style='padding:3px 10px;font-size:.8rem;color:{col};font-weight:700'>{txt}</td></tr>")
    tabla = "".join(rows)
    aviso = ""
    if R["inactivas"]:
        aviso = (f"<p style='font-size:.8rem;color:#dc2626;margin:6px 0'>⚠️ {R['inactivas']} fuente(s) "
                 f"inactiva(s) (&gt;{HEALTH_INACTIVA_DIAS}d sin eventos o sin datos). Revisa config.yaml "
                 f"(docs/FUENTES.md).</p>")
    return (
        f"<div class='card'><h3 id='salud-fuentes'>Salud de las fuentes</h3>"
        f"<p class='caption'>Eventos por fuente (7d/90d) y estado. "
        f"<b>{R['activas']}</b> activas · <b>{R['bajas']}</b> actividad baja · "
        f"<b style='color:{'#dc2626' if R['inactivas'] else '#16a34a'}'>{R['inactivas']}</b> inactivas "
        f"de {R['total']} configuradas.</p>{aviso}"
        f"<details><summary style='cursor:pointer;font-size:.84rem;color:#c2410c'>Ver detalle por fuente</summary>"
        f"<div style='overflow-x:auto'><table style='border-collapse:collapse;margin-top:8px'>"
        f"<tr><th align='left' style='font-size:.75rem;color:#94a3b8'>fuente</th>"
        f"<th align='left' style='font-size:.75rem;color:#94a3b8'>tipo</th>"
        f"<th align='right' style='font-size:.75rem;color:#94a3b8'>7d/90d</th>"
        f"<th align='right' style='font-size:.75rem;color:#94a3b8'>última</th>"
        f"<th align='left' style='font-size:.75rem;color:#94a3b8'>estado</th></tr>{tabla}</table></div></details></div>")


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
