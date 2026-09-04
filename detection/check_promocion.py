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


def count_tracebacks_tema():
    """Nº de secciones de TEMA en logs/fimi.log que terminaron en Traceback.

    Cuenta toda la sección entre cabeceras '=== run_fimi tema=X'. Los errores
    de otros temas no cuentan para la promoción de este.
    """
    n = 0
    if not LOGFILE.exists():
        return 0
    seccion = None
    has_trace = False
    with open(LOGFILE, errors="ignore") as f:
        for raw in f:
            s = raw.strip()
            if s.startswith("=== run_fimi tema="):
                if seccion == TEMA and has_trace:
                    n += 1
                try:
                    seccion = s.split("tema=")[1].split()[0].strip()
                except Exception:
                    seccion = None
                has_trace = False
            elif seccion == TEMA and s.startswith("Traceback"):
                has_trace = True
    if seccion == TEMA and has_trace:
        n += 1
    return n


def ciclos_snapshot(inicio):
    """Ciclos de snapshot completos del tema dentro de la ventana: nº de
    created_at distintos (un run inserta todos sus clusters en el mismo segundo)."""
    try:
        c = sqlite3.connect(DB)
        n = c.execute(
            "SELECT COUNT(DISTINCT created_at) FROM clusters WHERE tema_id=? AND created_at>=?",
            (TEMA, int(inicio)),
        ).fetchone()[0]
        c.close()
        return n or 0
    except Exception:
        return 0


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