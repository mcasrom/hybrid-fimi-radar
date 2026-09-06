#!/usr/bin/env python3
"""salud_tema.py — Score continuo de "salud" de cada tema monitorizado (0-100).

Hermano de check_cierre.py: en lugar de un veredicto binario "candidato a
cierre / no", produce una puntuación continua que el dashboard muestra junto
al dial de cada tema. Usa EXACTAMENTE los mismos criterios metodológicos
(volumen de hallazgos/día, narrativas sostenidas, antigüedad/calibración,
señal clara del último cluster), todos derivados de la BD, sin votos y sin
atribución de actor.

Interpretación de la escala (0-100):
  - 0-39   Salud baja: el tema muestra señal débil sostenida; candidato a
           revisión de cierre (coincide con los criterios de check_cierre).
  - 40-69  Salud media: funciona pero con reservas (en calibración piloto,
           volumen justo, o sin narrativas sostenidas recientes).
  - 70-100 Salud alta: volumen adecuado, narrativas sostenidas y/o señal clara.

El sistema NUNCA decide: este score es informativo y el cierre lo decide el
dueño (bitacora.py --nuevo-estado cerrado). Solo visibiliza lo que el
check_cierre ya juzgaba de forma binaria, de forma continua y comparable.

Uso:
  .venv/bin/python detection/salud_tema.py            # JSON por consola
  .venv/bin/python detection/salud_tema.py --html     # filas HTML de tabla
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
sys.path.insert(0, str(ROOT))

VENTANA_DIAS = int(os.environ.get("FIMI_CIERRE_VENTANA_DIAS", 21))
FINDINGS_POR_DIA = float(os.environ.get("FIMI_CIERRE_FINDINGS_POR_DIA", 2.0))
MIN_DIAS_OPERACION = int(os.environ.get("FIMI_CIERRE_MIN_DIAS", 14))
PILOTO_DIAS = int(os.environ.get("FIMI_CIERRE_PILOTO_DIAS", 90))
UMBRAL_SENAL = float(os.environ.get("FIMI_CIERRE_SENAL", 60))

# Pesos internos de la salud (normalizados a 100). Son del propio score, no
# del scoring de clusters — describen la VITALIDAD del tema.
W_VOLUMEN = 0.40      # hallazgos/día (hasta 2x el umbral por_dia, satura)
W_SOSTENIDAS = 0.20   # presencia de narrativas sostenidas (≥3d)
W_SENAL = 0.25        # score del último cluster (banda)
W_CALIBRACION = 0.15  # penaliza muy jóvenes (en calibración)


def cargar_config():
    try:
        return yaml.safe_load(open(ROOT / "config.yaml"))
    except Exception:
        return {}


def _inicio_ingesta(conn, tema):
    try:
        r = conn.execute("SELECT MIN(fecha) FROM findings WHERE tema_id=?", (tema,)).fetchone()
        return r[0] if r and r[0] else None
    except Exception:
        return None


def _volumen_ventana(conn, tema, inicio, ventana_inicio):
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM findings WHERE tema_id=? AND fecha>=?",
            (tema, int(ventana_inicio))).fetchone()[0] or 0
    except Exception:
        n = 0
    dias_op = max(MIN_DIAS_OPERACION, min(VENTANA_DIAS, (time.time() - inicio) / 86400.0)) if inicio else VENTANA_DIAS
    return n, n / dias_op


def _sostenidas_ventana(conn, tema, ventana_inicio, min_dias=3):
    try:
        rows = conn.execute(
            "SELECT DISTINCT date(fecha,'unixepoch') as d, substr(titulo,1,60) as t"
            " FROM findings WHERE tema_id=? AND fecha>=? AND tipo IN"
            " ('amplificacion_narrativa','cascada')",
            (tema, int(ventana_inicio))).fetchall()
    except Exception:
        rows = []
    dias_por_titulo = {}
    for d, t in rows:
        if not t:
            continue
        key = re.sub(r"[^a-z0-9áéíóúñü ]", "", t.lower())[:40]
        if key.strip():
            dias_por_titulo.setdefault(key, set()).add(d)
    return [(k, len(v)) for k, v in dias_por_titulo.items() if len(v) >= min_dias]


def _ultimo_cluster_score(conn, tema):
    try:
        r = conn.execute(
            "SELECT ROUND(overall_score) FROM clusters WHERE tema_id=?"
            " ORDER BY created_at DESC, overall_score DESC LIMIT 1", (tema,)).fetchone()
        return float(r[0]) if r and r[0] is not None else None
    except Exception:
        return None


def _banda(s):
    if s is None:
        return "—"
    if s >= 80:
        return "CRITICAL"
    if s >= 60:
        return "HIGH"
    if s >= 40:
        return "ANOMALOUS"
    return "WATCH"


def salud_por_tema(conn=None, cfg=None):
    import sqlite3
    cerrar = conn is None
    if conn is None:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
    cfg = cfg or cargar_config()
    temas_cfg = cfg.get("temas", {}) or {}
    ventana_inicio = time.time() - VENTANA_DIAS * 86400
    res = {}
    for tema in temas_cfg:
        tcfg = temas_cfg[tema] or {}
        estado = tcfg.get("estado", "produccion")
        inicio = _inicio_ingesta(conn, tema)
        # Subescores 0-100
        # 1) Volumen: lineal hasta 2x el umbral por_dia, satura en 100.
        #    _volumen_ventana ya normaliza temas jóvenes (divide por
        #    max(MIN_DIAS_OPERACION, edad)), así que no se gatea por edad.
        s_vol = 0.0
        por_dia = 0.0
        if inicio is not None:
            _, por_dia = _volumen_ventana(conn, tema, inicio, ventana_inicio)
            s_vol = min(100.0, 100.0 * por_dia / (2.0 * FINDINGS_POR_DIA))
        # 2) Narrativas sostenidas: 0 => 25, 1 => 70, 2+ => 100
        sost = _sostenidas_ventana(conn, tema, ventana_inicio)
        n_sost = len(sost)
        s_sost = 25.0 if n_sost == 0 else (70.0 if n_sost == 1 else 100.0)
        # 3) Señal clara (último cluster): banda sobre UMBRAL_SENAL
        ucs = _ultimo_cluster_score(conn, tema)
        if ucs is None:
            s_senal = 0.0
        else:
            s_senal = min(100.0, 100.0 * ucs / UMBRAL_SENAL)
        # 4) Calibración: muy joven no es "débil", solo está arrancando
        dias_op = (time.time() - inicio) / 86400.0 if inicio else 0
        if estado == "cerrado" or estado == "candidato_a_cierre":
            s_cal = 0.0
        elif dias_op < MIN_DIAS_OPERACION:
            s_cal = 100.0 * dias_op / MIN_DIAS_OPERACION  # aún en calibración
        else:
            s_cal = 100.0  # ya maduro, calibración no le penaliza
        score = (W_VOLUMEN * s_vol + W_SOSTENIDAS * s_sost +
                 W_SENAL * s_senal + W_CALIBRACION * s_cal)
        # Techos según estado y madurez: un tema muy joven o en calibración no
        # debe presentarse como "salud alta" sin trayectoria. PERO si ya hay
        # señal real y sostenida (narrativas ≥3d o cluster HIGH/CRITICAL con
        # volumen), la juventud no es motivo para ocultar que el tema está
        # vivo: ocultarlo aplanaría Frontera Sur (joven, 31/día, 37
        # sostenidas, CRITICAL) junto a temas jóvenes sin señal.
        _senal_real = (n_sost >= 1) or (ucs is not None and ucs >= 60 and (por_dia or 0) >= FINDINGS_POR_DIA)
        if estado == "cerrado":
            score = 0.0
        elif estado == "candidato_a_cierre":
            score = min(score, 39.0)
        elif (estado != "produccion" or dias_op < MIN_DIAS_OPERACION) and not _senal_real:
            # piloto o joven SIN señal real: no presumir "alta" sin trayectoria
            if score >= 70:
                score = min(score, 69.0)
        else:
            # producción madura o joven con señal real: sin cota artificial
            pass
        res[tema] = {
            "tema": tema,
            "estado": estado,
            "nombre": tcfg.get("nombre", tema),
            "score": round(score, 1),
            "nivel": "alta" if score >= 70 else ("media" if score >= 40 else "baja"),
            "volumen_por_dia": round(_volumen_ventana(conn, tema, inicio, ventana_inicio)[1], 1) if inicio else None,
            "sostenidas": n_sost,
            "ultimo_cluster": ucs,
            "banda": _banda(ucs),
            "dias_operacion": round(dias_op, 1) if inicio else 0,
        }
    if cerrar:
        conn.close()
    return res


def _html_rows(salud_map):
    """Filas <tr> para integrar en el dashboard (card Salud de los temas)."""
    order = sorted(salud_map.values(), key=lambda s: s["score"])
    rows = ""
    for s in order:
        if s["estado"] == "cerrado":
            color = "#64748b"
        elif s["nivel"] == "alta":
            color = "#16a34a"
        elif s["nivel"] == "media":
            color = "#d97706"
        else:
            color = "#dc2626"
        vol = f"{s['volumen_por_dia']:.1f}/día" if s["volumen_por_dia"] is not None else "—"
        senal = f"{s['ultimo_cluster']:.0f} {s['banda']}" if s["ultimo_cluster"] is not None else "—"
        rows += (f"<tr><td><b>{s['nombre']}</b> <code style='color:#94a3b8'>{s['tema']}</code></td>"
                 f"<td>{s['score']:.0f}/100</td>"
                 f"<td style='color:{color};font-weight:700'>{s['nivel']}</td>"
                 f"<td>{vol}</td><td>{s['sostenidas']}</td><td>{senal}</td>"
                 f"<td>{s['dias_operacion']:.0f}d</td></tr>")
    return rows


def main():
    load_env = getattr(__import__("detection.check_cierre", fromlist=["load_env"]), "load_env", None)
    if load_env is None:
        try:  # pragma: no cover
            from detection.check_cierre import load_env
        except Exception:
            load_env = None
    if load_env:
        load_env(ROOT / ".env")

    ap = argparse.ArgumentParser()
    ap.add_argument("--html", action="store_true", help="emitir filas <tr> HTML")
    args = ap.parse_args()
    salud = salud_por_tema()
    if args.html:
        print(_html_rows(salud))
    else:
        print(json.dumps({k: v for k, v in salud.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
