#!/usr/bin/env python3
"""check_cierre.py — Detecta temas 'candidatos a cierre' (solo avisa, NO decide).

Hermano de check_promocion.py: supervisa en cada ciclo del cron (6h) si algún
tema activado (produccion | piloto) muestra señal débil de forma sostenida.
Si cumple criterios, avisa al administrador por Telegram y registra una 'sugerencia'
en la bitácora (origen='sistema'). NO cambia estado ni toca config.yaml.

Criterios (por defecto: ventana 21 días, configurables por tema — ver Config):
  1. Volumen bajo: promedio de hallazgos/día < FINDINGS_POR_DIA en la ventana.
     Solo se evalúa a partir de MIN_DIAS_OPERACION días de operación real
     (evita marcar un tema recién activado). Volumen desde BD (findings con
     tema_id), inmune a rotación de logs.
  2. Sin narrativas sostenidas: 0 títulos persistidos en >= 3 días distintos
     dentro de la ventana (mismo criterio que detectar_sostenidas).
  3. Piloto estancado (extra si el tema es 'piloto'): > PILOTO_DIAS desde el
     inicio sin haber superado la ventana de promoción (data/promocion_<tema>.json
     con ready=true) y sin señal clara (último cluster >= UMBRAL_SENAL).
  4. Calendario (opcional por tema, `cierre_calendario_dias`): si hay una
     elección del registro (`data/elecciones.yaml`) dentro de ±N días, NO se
     sugiere cerrar — el tema puede estar dormido entre procesos, no muerto.

Robustez (patrón check_promocion):
  - Estado de máquina por tema en data/cierre_<tema>.json (gitignored):
    avisa UNA vez por episodio de candidatura; si el tema se recupera, se
    rearma para un futuro episodio.
  - Al registrar el cierre manualmente (bitacora.py --nuevo-estado cerrado),
    el check deja de considerarlo activo (config.yaml estado).

Config por tema (opcional, en config.yaml → temas.<tema>.ventanas):
  promocion_h / promocion_ciclos            (los lee check_promocion.py)
  cierre_ventana_dias     ventana de observación (días)
  cierre_findings_por_dia umbral de volumen (hallazgos/día)
  cierre_min_dias         días mínimos de operación antes de evaluar
  cierre_piloto_dias      piloto estancado (días sin promocionar)
  cierre_senal            último cluster >= este score = hay señal
  cierre_calendario_dias  si >0, no cerrar con una elección a ±N días

Los mismos nombres siguen disponibles por env (FIMI_CIERRE_*) como default.
"""
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
sys.path.insert(0, str(ROOT))

from detection.schema_bitacora import init as binit  # noqa: E402

VENTANA_DIAS = int(os.environ.get("FIMI_CIERRE_VENTANA_DIAS", 21))
FINDINGS_POR_DIA = float(os.environ.get("FIMI_CIERRE_FINDINGS_POR_DIA", 2.0))
MIN_DIAS_OPERACION = int(os.environ.get("FIMI_CIERRE_MIN_DIAS", 14))
PILOTO_DIAS = int(os.environ.get("FIMI_CIERRE_PILOTO_DIAS", 90))
UMBRAL_SENAL = float(os.environ.get("FIMI_CIERRE_SENAL", 60))
CHAT = int(os.environ.get("FIMI_CIERRE_CHAT", "47652516"))
LOGFILE = ROOT / "logs" / "fimi.log"


def load_env(filepath: Path):
    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


def cargar_config():
    import yaml
    try:
        return yaml.safe_load(open(ROOT / "config.yaml"))
    except Exception:
        return {}


# --- Parámetros de ventana por tema (config) con defaults globales (env) ------
_VENT_DEF = {
    "cierre_ventana_dias": VENTANA_DIAS,
    "cierre_findings_por_dia": FINDINGS_POR_DIA,
    "cierre_min_dias": MIN_DIAS_OPERACION,
    "cierre_piloto_dias": PILOTO_DIAS,
    "cierre_senal": UMBRAL_SENAL,
    "cierre_calendario_dias": 0,
}


def ventanas_tema(cfg, tema):
    """Parámetros de cierre del tema (config → env defaults)."""
    v = dict(_VENT_DEF)
    conf = (((cfg or {}).get("temas") or {}).get(tema) or {}).get("ventanas") or {}
    for k in list(v):
        if k in conf and conf[k] is not None:
            v[k] = conf[k]
    return v


def eleccion_cercana(dias):
    """True si hay una elección registrada dentro de ±`dias` (fase de calendario)."""
    import datetime
    import yaml
    p = ROOT / "data" / "elecciones.yaml"
    if not p.exists():
        return False
    try:
        data = yaml.safe_load(open(p)) or []
    except Exception:
        return False
    if isinstance(data, dict):
        data = data.get("elecciones") or []
    hoy = datetime.datetime.now(datetime.timezone.utc).date()
    for e in data:
        if not isinstance(e, dict) or e.get("estado") == "cerrado":
            continue
        f = e.get("fecha")
        if not f:
            continue
        try:
            d = datetime.datetime.strptime(str(f)[:10], "%Y-%m-%d").date()
        except Exception:
            continue
        if abs((d - hoy).days) <= dias:
            return True
    return False


def inicio_ingesta(conn, tema):
    """Primer hallazgo persistido del tema (findings)."""
    try:
        r = conn.execute(
            "SELECT MIN(fecha) FROM findings WHERE tema_id=?", (tema,)).fetchone()
        return r[0] if r and r[0] else None
    except Exception:
        return None


def volumen_ventana(conn, tema, inicio, ventana_dias, min_dias):
    """Hallazgos del tema dentro de la ventana y días efectivos de operación."""
    ventana_inicio = time.time() - ventana_dias * 86400
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM findings WHERE tema_id=? AND fecha>=?",
            (tema, int(ventana_inicio))).fetchone()[0] or 0
    except Exception:
        n = 0
    # días efectivos: máx(min_dias, MIN(ventana, edad del tema))
    dias_op = max(min_dias, min(ventana_dias, (time.time() - inicio) / 86400.0)) if inicio else ventana_dias
    return n, n / dias_op


def sostenidas_ventana(conn, tema, ventana_dias, min_dias=3):
    """Títulos persistidos en >= min_dias días distintos dentro de la ventana
    (mismo normalizado que detectar_sostenidas)."""
    import re
    ventana_inicio = time.time() - ventana_dias * 86400
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


def ultimo_cluster_score(conn, tema):
    try:
        r = conn.execute(
            "SELECT ROUND(overall_score) FROM clusters WHERE tema_id=?"
            " ORDER BY created_at DESC, overall_score DESC LIMIT 1", (tema,)).fetchone()
        return float(r[0]) if r and r[0] is not None else None
    except Exception:
        return None


def promocion_ready(tema):
    """True si el tema ya superó su ventana de promoción (data/promocion_<tema>.json).

    BUG corregido 15/09/2026: antes leía SIEMPRE el JSON de politica_nacional,
    de modo que con ready=true anulaba los motivos de cierre de TODOS los pilotos.
    """
    p = ROOT / "data" / f"promocion_{tema}.json"
    try:
        s = json.loads(p.read_text())
        return bool(s.get("ready", False))
    except Exception:
        return False


def send(token, text):
    if not token or ":" not in token:
        print("[cierre] sin token — mensaje no enviado:\n" + text)
        return False
    api = f"https://api.telegram.org/bot{token}"
    try:
        r = requests.post(f"{api}/sendMessage",
                          data={"chat_id": str(CHAT), "text": text}, timeout=20)
        print(f"[cierre] telegram HTTP {r.status_code}")
        return r.ok
    except Exception as e:
        print(f"[cierre] telegram error: {e}")
        return False


def evaluar_tema(conn, cfg, temas_cfg):
    """Devuelve lista de dicts de candidatos con motivos metodológicos."""
    evaluados = []
    for tema in temas_cfg:
        est = (temas_cfg.get(tema, {}) or {}).get("estado", "produccion")
        if est not in ("produccion", "piloto"):
            continue  # candidato_a_cierre/cerrado no se reevalúan
        v = ventanas_tema(cfg, tema)
        ventana = int(v["cierre_ventana_dias"])
        min_dias = int(v["cierre_min_dias"])
        fpd = float(v["cierre_findings_por_dia"])
        piloto_dias = int(v["cierre_piloto_dias"])
        senal = float(v["cierre_senal"])
        cal_dias = int(v["cierre_calendario_dias"])
        # (B) fase de calendario electoral: no sugerir cierre si hay elección cerca
        if cal_dias > 0 and eleccion_cercana(cal_dias):
            print(f"[cierre] {tema}: en fase de calendario (elección a ±{cal_dias}d) — no se evalúa")
            continue
        inicio = inicio_ingesta(conn, tema)
        if inicio is None or (time.time() - inicio) / 86400.0 < min_dias:
            continue  # demasiado joven para "débil sostenido"
        total, por_dia = volumen_ventana(conn, tema, inicio, ventana, min_dias)
        sost = sostenidas_ventana(conn, tema, ventana)
        motivos = []
        if por_dia < fpd:
            motivos.append(
                f"volumen bajo sostenido ({por_dia:.1f} hallazgos/día,"
                f" umbral {fpd:.1f} en {ventana}d, total {total})")
        if not sost:
            motivos.append(f"0 narrativas sostenidas (≥3d) en los últimos {ventana}d")
        if est == "piloto":
            if promocion_ready(tema):
                motivos = []  # ya validado para promoción; no es candidato
            elif (time.time() - inicio) / 86400.0 > piloto_dias:
                motivos.append(
                    f"piloto con >{piloto_dias}d sin superar la ventana de promoción")
            score = ultimo_cluster_score(conn, tema)
            if score is not None and score >= senal:
                motivos = []  # hay señal clara real; no es candidato
        if motivos:
            evaluados.append({
                "tema": tema, "estado": est, "inicio": inicio,
                "por_dia": por_dia, "sostenidas": len(sost), "motivos": motivos,
            })
    return evaluados


def main():
    load_env(ROOT / ".env")
    token = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "")
    conn = binit()
    cfg = cargar_config()
    temas_cfg = cfg.get("temas", {}) or {}

    candidatos = evaluar_tema(conn, cfg, temas_cfg)
    for cand in candidatos:
        tema = cand["tema"]
        state_file = ROOT / "data" / f"cierre_{tema}.json"
        state = {}
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text())
            except Exception:
                state = {}
        if state.get("candidato") and state.get("notificado"):
            print(f"[cierre] {tema} ya notificado; sin acción")
            continue
        motivos = " · ".join(cand["motivos"])
        f_inicio = time.strftime("%d/%m/%Y", time.gmtime(cand["inicio"]))
        texto = (f"🗂 Candidato a cierre: {tema}\n"
                 f"· Volumen: {cand['por_dia']:.1f} hallazgos/día\n"
                 f"· Narrativas sostenidas (≥3d): {cand['sostenidas']}\n"
                 f"· Estado: {cand['estado']} · ingesta desde {f_inicio}\n"
                 f"Motivo: {motivos}\n\n"
                 f"El sistema NO modifica nada. Si decides cerrarlo:\n"
                 f"  detection/bitacora.py --tema {tema} --nuevo-estado cerrado"
                 f" --nota \"motivo\"\n"
                 f"y edita config.yaml si procede.")
        ok = send(token, texto)
        estado_nuevo = "candidato_a_cierre"
        try:
            # registrar sugerencia en la bitácora (origen=sistema), idempotente
            clave = hashlib.sha1(motivos.encode("utf-8")).hexdigest()[:20]
            conn.execute(
                "INSERT OR IGNORE INTO bitacora"
                " (tema, tipo, fecha, estado_anterior, estado_nuevo, motivo, origen, clave)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (tema, "sugerencia", int(time.time()), cand["estado"], estado_nuevo,
                 motivos, "sistema", clave))
            conn.commit()
        except Exception as e:
            print(f"[cierre] no se pudo registrar sugerencia: {e}")
        state_file.write_text(json.dumps(
            {"candidato": True, "notificado": ok,
             "desde": int(time.time()), "motivos": cand["motivos"]}, indent=2))
        print(f"[cierre] {tema} candidato (notificado={ok}) — {motivos}")

    # rearmar estado de temas que dejaron de ser candidatos
    for tema in temas_cfg:
        st_f = ROOT / "data" / f"cierre_{tema}.json"
        if not st_f.exists():
            continue
        est_actual = (temas_cfg.get(tema, {}) or {}).get("estado", "produccion")
        sigue = any(c["tema"] == tema for c in candidatos)
        if est_actual in ("cerrado", "candidato_a_cierre"):
            st_f.unlink(missing_ok=True)
        elif not sigue:
            st_f.unlink(missing_ok=True)
            print(f"[cierre] {tema} recuperado/rearmado (deja de ser candidato)")

    if not candidatos:
        print("[cierre] 0 candidatos a cierre en este ciclo")


if __name__ == "__main__":
    main()
