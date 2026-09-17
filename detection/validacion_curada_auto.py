#!/usr/bin/env python3
"""Validación curada periódica (automática, mínima intervención del admin).

Ciclo:
  1. Mira la última muestra (data/validacion/muestra_*.csv).
     - Si no existe, o está COMPLETA (todas las filas etiquetadas), o tiene más
       de --dias, genera una nueva con tests/export_validacion.py.
     - Si está pendiente de etiquetar, recuerda (Telegram) que está lista.
  2. Recalcula la precisión por banda de TODAS las muestras etiquetadas y
     actualiza el historial (data/validacion/historial.csv) — serie temporal.

El etiquetado se hace desde el bot de Telegram con /validar (2 toques por
cluster, solo el admin). Este script no etiqueta: solo prepara y mide.

Uso:
  .venv/bin/python detection/validacion_curada_auto.py [--dias 30] [--per-band 8] [--notify] [--json]
"""
import argparse
import csv
import datetime
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAL_DIR = ROOT / "data" / "validacion"
HIST = VAL_DIR / "historial.csv"
ESTADO = VAL_DIR / "curada_estado.json"
ORDEN = ["CRITICAL", "HIGH", "ANOMALOUS", "WATCH"]


def _info(msg):
    print(f"[curada] {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M:%S} {msg}")


def _env(name):
    try:
        for line in open(ROOT / ".env"):
            line = line.strip()
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return os.environ.get(name, "")


def _telegram(msg):
    token, chat = _env("FIMI_TELEGRAM_BOT_TOKEN"), _env("FIMI_OWNER_CHAT")
    if not token or not chat:
        _info("Telegram no configurado; no se avisa")
        return False
    try:
        import requests
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": msg[:4000]}, timeout=30)
        return r.status_code == 200
    except Exception as e:
        _info(f"Telegram fallo: {e}")
        return False


def _muestras():
    return sorted(VAL_DIR.glob("muestra_*.csv")) if VAL_DIR.exists() else []


def _leer(path):
    try:
        return list(csv.DictReader(open(path, encoding="utf-8")))
    except Exception:
        return []


def _completa(rows):
    return bool(rows) and all((r.get("label") or "").strip() for r in rows)


def _metricas(rows):
    by = defaultdict(lambda: defaultdict(int))
    for r in rows:
        lab = (r.get("label") or "").strip().lower()
        if lab:
            by[r.get("banda")][lab] += 1
    out = {}
    for b in ORDEN:
        d = by.get(b)
        if not d:
            continue
        co, no, du = d["coordinado"], d["no_coordinado"], d["dudoso"]
        out[b] = {"n": co + no + du, "coord": co, "no": no, "dud": du,
                  "precision": round(100 * co / (co + no), 1) if (co + no) else None}
    return out


def _actualizar_historial():
    """Añade al historial las muestras etiquetadas que falten (dedupe por nombre)."""
    hechas = set()
    if HIST.exists():
        for r in _leer(HIST):
            hechas.add(r.get("muestra"))
    nuevas = 0
    with open(HIST, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not hechas:
            w.writerow(["muestra", "banda", "n", "coord", "no", "dud", "precision"])
        for p in _muestras():
            if p.name in hechas:
                continue
            rows = _leer(p)
            if not _completa(rows):
                continue
            for b, m in _metricas(rows).items():
                w.writerow([p.name, b, m["n"], m["coord"], m["no"], m["dud"], m["precision"]])
            nuevas += 1
    return nuevas


def _generar(per_band):
    cmd = [sys.executable, "tests/export_validacion.py", "--per-band", str(per_band)]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout or r.stderr)[-300:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=30)
    ap.add_argument("--per-band", type=int, default=8)
    ap.add_argument("--notify", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    VAL_DIR.mkdir(parents=True, exist_ok=True)

    muestras = _muestras()
    ultima = muestras[-1] if muestras else None
    rows = _leer(ultima) if ultima else []
    edad = (time.time() - ultima.stat().st_mtime) / 86400 if ultima else None

    accion = "nada"
    if ultima is None:
        accion = "generar"
    elif _completa(rows):
        accion = "generar"
    elif edad is not None and edad > args.dias:
        accion = "generar"

    generada = None
    if accion == "generar":
        ok, msg = _generar(args.per_band)
        generada = msg if ok else None
        _info(f"muestra {'generada' if ok else 'FALLO'}: {msg.strip().splitlines()[-1] if msg else ''}")
    else:
        pend = sum(1 for r in rows if not (r.get("label") or "").strip())
        _info(f"muestra al día: {ultima.name} ({pend} pendientes, {edad:.1f}d)")

    nuevas = _actualizar_historial()
    if nuevas:
        _info(f"historial actualizado: +{nuevas} muestra(s) etiquetada(s)")

    # aviso Telegram solo si hay algo accionable y cambió el estado
    _ult = _muestras()[-1] if _muestras() else None
    pend = sum(1 for r in _leer(_ult) if not (r.get("label") or "").strip()) if _ult else 0
    estado_prev = {}
    if ESTADO.exists():
        try:
            estado_prev = json.loads(ESTADO.read_text())
        except Exception:
            estado_prev = {}
    estado = {"ultima": ultima.name if ultima else None,
              "generada": generada.splitlines()[0] if generada else None}
    cambio = estado != estado_prev
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=2))

    if args.notify and cambio and accion == "generar":
        _telegram("🔬 Validación curada: nueva muestra lista.\n"
                  "Etiquétala en el bot con /validar (2 toques por cluster).")
        _info("aviso Telegram enviado")
    elif args.notify and cambio and pend:
        _telegram(f"🔬 Validación curada: quedan {pend} clusters por etiquetar (/validar).")
        _info("recordatorio Telegram enviado")

    if args.json:
        print(json.dumps({"accion": accion, "historial_nuevas": nuevas}, ensure_ascii=False))
    _info("OK")


if __name__ == "__main__":
    main()
