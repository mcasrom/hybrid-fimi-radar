#!/usr/bin/env python3
"""Validación automática del radar (sin intervención del admin, sin API keys).

Qué hace, en orden:
  1. Refresca el dataset externo EUvsDisinfo (Zenodo, sin clave) si está viejo.
  2. Corre la validación externa (tests/validacion_externa.py) en dos variantes:
     global y --lang spanish.
  3. Escribe un informe JSON en data/validacion/auto_<fecha>.json (+ auto_ultimo.json).
  4. Avisa por Telegram SOLO si cambia el resultado (patrón on_change), para no
     generar ruido. Cero intervención en el caso normal.

Es un job de MONITORIZACIÓN de la validación: comprueba que el cruce sigue
ejecutándose y detecta si alguna fuente/dominio documentado aparece en las
señales del radar (tripwire). No sustituye a la validación curada (C).

Uso:
  .venv/bin/python detection/validacion_auto.py [--refresh-days 30] [--notify] [--json]
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
DATASET = ROOT / "data" / "euvsdisinfo_base.csv"
OUTDIR = ROOT / "data" / "validacion"
ESTADO = OUTDIR / "auto_estado.json"


def _info(msg):
    print(f"[validacion] {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M:%S} {msg}")


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


def _refresh_dataset(dias):
    if DATASET.exists():
        edad = (time.time() - DATASET.stat().st_mtime) / 86400
        if edad < dias:
            return False, round(edad, 1)
    _info(f"dataset viejo/ausente; refrescando desde Zenodo…")
    import urllib.request
    api = "https://zenodo.org/api/records/10514307"
    hdr = {"User-Agent": "Mozilla/5.0 (radar-fimi)", "Accept": "application/json"}
    with urllib.request.urlopen(urllib.request.Request(api, headers=hdr), timeout=60) as r:
        rec = json.load(r)
    link = rec["files"][0]["links"]["self"]
    data = urllib.request.urlopen(urllib.request.Request(link, headers=hdr), timeout=180).read()
    DATASET.parent.mkdir(parents=True, exist_ok=True)
    DATASET.write_bytes(data)
    return True, 0.0


def _correr(lang=None):
    cmd = [sys.executable, "tests/validacion_externa.py", "--json", "--db", str(DB)]
    if lang:
        cmd += ["--lang", lang]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout)[-500:])
    return json.loads(out.stdout)


def _resumen(r):
    p = r["precision"]
    n = p.get("señales_cluster_score>=60.0")
    if n is None:
        n = p.get("señales_cluster_score>=60")
    return {
        "precision": p["precision"],
        "recall": r["recall"]["recall"],
        "n_senales": n,
        "n_senales_doc": p.get("señales_con_dominio_documentado"),
        "dominios_doc_amplificados": len(p["dominios_documentados_amplificados"]),
        "fuentes_doc_con_senal": r["recall"]["fuentes_documentadas_con_señal"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-days", type=int, default=30)
    ap.add_argument("--notify", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    OUTDIR.mkdir(parents=True, exist_ok=True)

    refrescado, edad = _refresh_dataset(args.refresh_days)
    _info(f"dataset: {'refrescado' if refrescado else f'al día ({edad}d)'}")

    res = {}
    for key, lang in (("global", None), ("spanish", "spanish")):
        r = _correr(lang)
        res[key] = _resumen(r)
        _info(f"{key}: precision={res[key]['precision']:.1%} recall={res[key]['recall']:.1%} "
              f"señales={res[key]['n_senales']}")

    report = {
        "fecha": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "dataset_refrescado": refrescado,
        "dataset_edad_dias": edad,
        "resultados": res,
    }
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M")
    (OUTDIR / f"auto_{stamp}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (OUTDIR / "auto_ultimo.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))

    # on_change: avisa solo si cambia el resultado respecto a la última vez
    prev = {}
    if ESTADO.exists():
        try:
            prev = json.loads(ESTADO.read_text()).get("resultados", {})
        except Exception:
            prev = {}
    cambió = prev != res
    ESTADO.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    if cambió:
        msg = ("🔬 Validación externa (EUvsDisinfo)\n"
               f"global: precision {res['global']['precision']:.0%} · recall {res['global']['recall']:.0%} "
               f"({res['global']['n_senales']} señales)\n"
               f"spanish: precision {res['spanish']['precision']:.0%} · "
               f"recall {res['spanish']['recall']:.0%}")
        _info("cambio detectado" + ("; avisando por Telegram" if args.notify else " (sin --notify)"))
        if args.notify:
            _telegram(msg)
    else:
        _info("sin cambios respecto al último informe")
    _info("OK")


if __name__ == "__main__":
    main()
