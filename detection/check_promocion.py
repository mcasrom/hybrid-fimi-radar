#!/usr/bin/env python3
"""check_promocion.py — Ventana de validación de politica_nacional (piloto).

Se ejecuta en cada ciclo del cron (6h) DESPUÉS de run_fimi + dashboard.

Objetivo: decidir con datos si 'politica_nacional' está listo para pasar de
'estado: piloto' a 'estado: produccion' en config.yaml.

Criterios automáticos (idempotente, sin spam):
  1. 0 errores (Traceback) nuevos en la sección de politica_nacional de
     logs/fimi.log durante la ventana. (Los errores de otros temas no cuentan.)
  2. Ventana de observación >= VENTANA_H (72h) y >= MIN_CICLOS ciclos de
     snapshot completos (clusters del tema con created_at dentro de la ventana).

Al cumplirse, avisa por Telegram al dueño con el resumen y el paso a ejecutar
(cambiar 1 línea de config.yaml). Un error nuevo reinicia la ventana y avisa.
El aviso final se manda una sola vez.

Robustez:
  - Ciclos se cuentan vía BD (DISTINCT created_at de clusters del tema), NO del
    log: inmune a la rotación de logs (tail -100 a 5MB en el cron).
  - Errores: err_total se re-sincroniza si el log rota (err_total < err_base),
    para no reiniciar en falso por rotación.

Config por env (opcional):
  FIMI_PROMOCION_H=72            horas de observación
  FIMI_PROMOCION_MIN_CICLOS=8    ciclos de snapshot mínimos
  FIMI_PROMOCION_CHAT=47652516   chat_id de Telegram del dueño
"""
import json
import os
import sqlite3
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent

TEMA = "politica_nacional"
VENTANA_H = float(os.environ.get("FIMI_PROMOCION_H", 72))
MIN_CICLOS = int(os.environ.get("FIMI_PROMOCION_MIN_CICLOS", 8))
CHAT = int(os.environ.get("FIMI_PROMOCION_CHAT", "47652516"))
LOGFILE = ROOT / "logs" / "fimi.log"
STATE = ROOT / "data" / "promocion_politica_nacional.json"
DB = ROOT / "data" / "radar.db"


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


def _parsear_secciones():
    """Parsea logs/fimi.log → lista de secciones [tema, ts_epoch, traceback].

    El log no lleva día en la cabecera (HH:MM UTC) y se escribe en orden
    cronológico. Anclamos la ÚLTIMA sección (la más reciente): hoy si su hora
    <= ahora, ayer si es posterior (p.ej. son las 00:20 y el último run fue
    18:35). Caminando hacia atrás, cada vez que la HH:MM sube respecto a la
    siguiente (más reciente), pertenece a un día ANTERIOR.
    """
    ahora = time.time()
    ahora_min = int(time.strftime("%H")) * 60 + int(time.strftime("%M"))
    secciones = []  # [tema, hhmm, traceback]
    if not LOGFILE.exists():
        return secciones
    try:
        with open(LOGFILE, errors="ignore") as f:
            for raw in f:
                s = raw.strip()
                if s.startswith("=== run_fimi tema="):
                    try:
                        _tema = s.split("tema=")[1].split()[0].strip()
                        hh, mm = s.split(" ")[-2].split(":")[:2]
                        _hhmm = int(hh) * 60 + int(mm)
                    except Exception:
                        _tema, _hhmm = None, 0
                    secciones.append([_tema, _hhmm, False])
                elif secciones and s.startswith("Traceback"):
                    secciones[-1][2] = True
    except Exception:
        return []
    if not secciones:
        return secciones
    _ult_hhmm = secciones[-1][1]
    _dia_ult = int(ahora // 86400) * 86400
    if _ult_hhmm > ahora_min:
        _dia_ult -= 86400  # el último run fue ayer
    _dias = [0] * len(secciones)
    _dias[-1] = _dia_ult
    for _i in range(len(secciones) - 2, -1, -1):
        _dias[_i] = _dias[_i + 1]
        if secciones[_i][1] > secciones[_i + 1][1]:
            _dias[_i] -= 86400  # hora mayor que la siguiente => día anterior
    return [[_t, _dias[_i] + _hhmm * 60, _tr]
            for _i, (_t, _hhmm, _tr) in enumerate(secciones)]


def count_tracebacks_tema():
    """Nº de secciones de TEMA en logs/fimi.log que terminaron en Traceback.

    Cuenta toda la sección entre cabeceras '=== run_fimi tema=X'. Los errores
    de otros temas no cuentan para la promoción de este.
    """
    return sum(1 for _t, _ts, _tr in _parsear_secciones()
               if _t == TEMA and _tr)


def ciclos_snapshot(inicio):
    """Ciclos de snapshot completos y EXITOSOS del tema dentro de la ventana.

    Se cuentan las secciones '=== run_fimi tema=TEMA ... ===' del log que NO
    terminaron en Traceback y cuyo timestamp es >= inicio. NO se usa la tabla
    clusters: run_fimi hace DELETE + re-INSERT del snapshot del tema en cada
    ciclo, así que COUNT(DISTINCT created_at) de clusters siempre devuelve 1
    (solo queda el created_at del último run). Bug detectado 06/Sep (ciclos
    ok estancado en 1/8). El log rota a >5MB con tail -100 en el cron: si la
    rotación borra secciones viejas de la ventana se pierden ciclos, pero es
    la única fuente estable de "runs completos" y la ventana (72h ~12 runs)
    cabe de sobra en un log de 5MB.
    """
    return sum(1 for _t, _ts, _tr in _parsear_secciones()
               if _t == TEMA and not _tr and _ts >= inicio)


def clusters_resumen():
    try:
        c = sqlite3.connect(DB)
        rows = c.execute(
            "SELECT ROUND(overall_score), strftime('%m/%d', datetime(created_at,'unixepoch'))"
            " FROM clusters WHERE tema_id=? ORDER BY created_at DESC, overall_score DESC LIMIT 5",
            (TEMA,),
        ).fetchall()
        c.close()
        if not rows:
            return "sin clusters"
        return "; ".join(f"{sc} ({d})" for sc, d in rows)
    except Exception:
        return "sin clusters"


def send(token, text):
    if not token or ":" not in token:
        print("[promocion] sin token — mensaje no enviado:\n" + text)
        return False
    api = f"https://api.telegram.org/bot{token}"
    try:
        r = requests.post(
            f"{api}/sendMessage",
            data={"chat_id": str(CHAT), "text": text},
            timeout=20,
        )
        print(f"[promocion] telegram HTTP {r.status_code}")
        return r.ok
    except Exception as e:
        print(f"[promocion] telegram error: {e}")
        return False


def main():
    load_env(ROOT / ".env")
    token = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "")
    now = time.time()

    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text())
        except Exception:
            state = {}

    inicio = state.get("inicio")
    err_base = state.get("err_base", 0)
    ready = state.get("ready", False)
    notificado = state.get("notificado_ready", False)

    err_total = count_tracebacks_tema()

    def guardar():
        STATE.write_text(json.dumps(
            {"inicio": inicio, "err_base": err_base, "ready": ready,
             "notificado_ready": notificado}, indent=2))

    # 1) Log rotado -> re-sincronizar base (evita falso reinicio)
    if inicio is not None and err_total < err_base:
        err_base = err_total
        guardar()
        print("[promocion] log rotado — err_base re-sincronizado")

    # 2) Error NUEVO durante la ventana -> reiniciar ventana y avisar
    if inicio is not None and err_total > err_base:
        nuevos = err_total - err_base
        msg = (f"⚠️ Ventana de validación de {TEMA} REINICIADA ⚠️\n"
               f"detectados {nuevos} error(es) de pipeline desde "
               f"{time.strftime('%d/%m %H:%M', time.localtime(inicio))}.\n"
               f"Se reinicia el contador de 72h desde ahora.")
        send(token, msg)
        inicio = now
        err_base = err_total
        ready, notificado = False, False
        guardar()
        print(f"[promocion] ventana reiniciada ({nuevos} errores)")
        return

    # 3) Primera ejecución: comienza la ventana
    if inicio is None:
        inicio = now
        err_base = err_total
        guardar()
        print(f"[promocion] ventana iniciada — {VENTANA_H:.0f}h de observación para {TEMA}")
        return

    # 4) Ya validado y notificado -> solo log
    if ready and notificado:
        print("[promocion] ya validado; sin acción")
        return

    # 5) Ventana en curso
    elapsed_h = (now - inicio) / 3600.0
    ciclos = ciclos_snapshot(inicio)

    if elapsed_h >= VENTANA_H and ciclos >= MIN_CICLOS:
        ready = True
        msg = (f"✅ {TEMA} ha superado la ventana de validación ✅\n"
               f"· {ciclos} ciclos de snapshot completos sin errores\n"
               f"· {elapsed_h:.0f}h de observación\n"
               f"· 0 errores nuevos de pipeline\n"
               f"· Clusters actuales: {clusters_resumen()}\n\n"
               f"Para PROMOCIONAR a producción, edita config.yaml:\n"
               f"  temas.{TEMA}.estado: piloto -> produccion\n"
               f"(opcional: borra el campo disclaimer).\n"
               f"El siguiente cron desactiva el banner de calibración.")
        notificado = send(token, msg)
        guardar()
        print("[promocion] LISTO para promocionar")
        return

    print(f"[promocion] ventana en curso {elapsed_h:.0f}/{VENTANA_H:.0f}h · "
          f"{ciclos}/{MIN_CICLOS} ciclos ok · errores {err_total - err_base}")


if __name__ == "__main__":
    main()