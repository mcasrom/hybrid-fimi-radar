#!/usr/bin/env python3
"""radar_trend.py — Estado real del dial de cada tema (fuente de verdad).

Extrae de gen_fimi_html.py la métrica de tendencia (HOY vs hace 48h) para
que el bot de Telegram y el cron de notificaciones informen con el MISMO
criterio que los diales de la vista resumen. Sin generar HTML.

Estados devueltos (match con ESTADO_DIAL del dashboard):
  - "recopilando": sin hallazgos hoy ni hace 48h ni alerts altos
  - "subiendo"   : clusters HIGH/CRITICAL hoy > hace48h, o hallazgos hoy > hace48h
  - "bajando"    : hallazgos hoy < hace48h
  - "estable"    : resto
"""
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"

TEMAS_DEFAULT = ["frontera_sur", "geopolitica_ue_marruecos", "politica_nacional"]

# etiquetas para el texto de las alertas (los nombres del catálogo real)
NOMBRE_TEMA = {
    "frontera_sur": "Frontera Sur",
    "geopolitica_ue_marruecos": "Geopolítica UE-Marruecos",
    "politica_nacional": "Política Nacional",
}
# temas en modo piloto (calibración)
PILOTO = {"politica_nacional"}


def _cargar_temas_activos() -> list:
    """Lee el catálogo real de config.yaml (fallback a los 3 conocidos)."""
    try:
        import yaml
        cfg = yaml.safe_load(open(ROOT / "config.yaml"))
        temas = list(cfg.get("temas", {}).keys())
        return temas or list(TEMAS_DEFAULT)
    except Exception:
        return list(TEMAS_DEFAULT)


def estado_por_tema(temas: list = None) -> dict:
    """Devuelve {tema: {estado, hoy, hace48, high_hoy, high_48}} con el MISMO
    criterio que los diales de la vista resumen."""
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    temas = temas or _cargar_temas_activos()
    hoy_d = datetime.now(timezone.utc).date()
    hace48 = hoy_d - timedelta(days=2)
    try:
        clusters = con.execute("SELECT * FROM clusters").fetchall()
    except Exception:
        clusters = []
    res = {}
    for t in temas:
        try:
            _hoy_n = con.execute(
                "SELECT COUNT(*) FROM findings WHERE tema_id=? AND date(fecha,'unixepoch')=?",
                (t, hoy_d.isoformat())).fetchone()[0]
            _h48_n = con.execute(
                "SELECT COUNT(*) FROM findings WHERE tema_id=? AND date(fecha,'unixepoch')=?",
                (t, hace48.isoformat())).fetchone()[0]
            _cl_tema = [c for c in clusters if c["tema_id"] == t]
            _high_hoy = sum(1 for c in _cl_tema if (c["overall_score"] or 0) >= 60)
            _high_48 = con.execute(
                "SELECT COUNT(*) FROM findings WHERE tema_id=? AND tipo='cluster'"
                " AND date(fecha,'unixepoch')=? AND intensidad>=60",
                (t, hace48.isoformat())).fetchone()[0]
            if _hoy_n == 0 and _h48_n == 0 and _high_hoy == 0 and _high_48 == 0:
                estado = "recopilando"
            elif _high_hoy > _high_48:
                estado = "subiendo"
            elif _hoy_n > _h48_n:
                estado = "subiendo"
            elif _hoy_n < _h48_n:
                estado = "bajando"
            else:
                estado = "estable"
            res[t] = {"estado": estado, "hoy": _hoy_n, "hace48": _h48_n,
                      "high_hoy": _high_hoy, "high_48": _high_48}
        except Exception:
            res[t] = {"estado": "estable", "hoy": 0, "hace48": 0,
                      "high_hoy": 0, "high_48": 0}
    con.close()
    return res


def texto_dial(tema: str, estado: str) -> str:
    """Texto legible del estado de un tema, con aviso de piloto."""
    txt = {"subiendo": "Subiendo", "bajando": "Bajando",
           "estable": "Estable", "recopilando": "En recopilación"}.get(estado, estado)
    if tema in PILOTO:
        txt += " (piloto, en calibración)"
    return txt


if __name__ == "__main__":
    for k, v in estado_por_tema().items():
        print(f"{k}: {texto_dial(k, v['estado'])} (hoy={v['hoy']}, hace48={v['hace48']}, high={v['high_hoy']})")
