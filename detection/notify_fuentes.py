#!/usr/bin/env python3
"""notify_fuentes.py — Alerta proactiva de salud de fuentes por Telegram.

Se lanza tras cada ciclo del cron (6h). Calcula la salud de las fuentes
(detection/health_fuentes.analizar) y avisa al administrador SOLO cuando una fuente
EMPEORA (activa -> baja/inactiva, o baja -> inactiva). Sin cambios => silencio.

Motivo: una fuente que se cae en silencio (feed roto, 403, deja de publicar)
debe notificarse cuanto antes, pero sin spam — el estado se guarda entre
ciclos (data/fuentes_estado.json) para no repetir el mismo aviso.

Avisos a mejoras (recuperación) NO se envían: no son urgentes y el dashboard
ya muestra el estado actual. El fichero de estado se actualiza siempre.

Distinción clave (18-oct): «salud de fuentes» mide EVENTOS (match de keywords),
NO si el feed vive. Un feed que respira (sonda detection/probe_feeds.py →
data/feed_health.json, estado 'ok') pero no genera eventos NO es un riesgo de
fuente, es falta de coincidencias: se registra pero NO se manda como «en riesgo».
"""
import json
import os
import sys
import time
from pathlib import Path

import requests  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from health_fuentes import analizar  # noqa: E402

URL_DASH = "https://fimi.viajeinteligencia.com"
STATE = ROOT / "data" / "fuentes_estado.json"
PROBE = ROOT / "data" / "feed_health.json"
CHAT = int(os.environ.get("FIMI_HEALTH_CHAT", "47652516"))
PEOR = {"activa": 0, "baja": 1, "inactiva": 2}


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


def _estado_txt(estado):
    return {"activa": "activa", "baja": "actividad baja", "inactiva": "inactiva"}.get(estado, estado)


def _feeds_vivos():
    """nombre -> estado de la sonda de feeds (data/feed_health.json). {} si no hay."""
    try:
        d = json.loads(PROBE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {f["nombre"]: f.get("estado")
            for f in d.get("fuentes", []) if f.get("nombre")}


def _probe_txt(probe):
    """Traduce el estado de la sonda a texto corto ('' si es ok/None)."""
    return {"http_error": "feed inaccesible", "sin_items": "feed sin items",
            "error": "feed con error", "parado": "feed parado"}.get(probe, "")


def main(dry_run: bool = False):
    load_env(ROOT / ".env")
    token = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "")
    api = f"https://api.telegram.org/bot{token}"

    data = analizar()
    fuentes = data.get("fuentes", [])
    resumen = data.get("resumen", {})
    estado_actual = {f["clave"]: f["estado"] for f in fuentes}
    vivos = _feeds_vivos()  # nombre -> estado de la sonda (feed vivo, no eventos)

    prev = {}
    if STATE.exists():
        try:
            prev = json.loads(STATE.read_text()) or {}
        except Exception:
            prev = {}

    primera_vez = not prev
    avisos = []
    for clave, estado in estado_actual.items():
        anterior = prev.get(clave)
        # actualizar siempre el estado del ciclo
        prev[clave] = estado
        if primera_vez:
            continue  # sembrar estado sin avisar (evita spam inicial)
        if anterior is None or anterior == estado:
            continue  # sin cambio
        if PEOR.get(estado, 2) <= PEOR.get(anterior, 0):
            continue  # mejora o igual: no avisar
        f = next((x for x in fuentes if x["clave"] == clave), {})
        tipo = f.get("tipo", "")
        nombre = f.get("nombre", clave)
        dias = 0
        if f.get("last_ts"):
            dias = int((time.time() - f["last_ts"]) / 86400)
        avisos.append((clave, anterior, estado, nombre, tipo, dias, vivos.get(nombre)))

    STATE.write_text(json.dumps(prev, ensure_ascii=False, indent=2))

    if not avisos:
        print(f"[fuentes] sin cambios ({resumen.get('activas')} activas, "
              f"{resumen.get('bajas')} bajas, {resumen.get('inactivas')} inactivas)")
        return

    # Un feed que respira (sonda OK) pero no genera eventos NO es un riesgo de
    # fuente: es falta de coincidencias. Se registra, pero no se manda como tal.
    riesgo = [a for a in avisos if a[6] != "ok"]
    benigno = [a for a in avisos if a[6] == "ok"]
    if benigno:
        print(f"[fuentes] {len(benigno)} sin coincidencias (feed vivo): "
              + ", ".join(a[3] for a in benigno))

    if not riesgo:
        if dry_run:
            print("[fuentes][dry] solo feeds vivos sin coincidencias — no se envía")
        return

    if not token or ":" not in token:
        print(f"[fuentes] sin token — {len(riesgo)} aviso(s) NO enviado(s)")
        for a in riesgo:
            print("   ", a)
        return

    lineas = ["🔌 <b>Radar FIMI — fuentes en riesgo</b>"]
    for clave, anterior, estado, nombre, tipo, dias, probe in riesgo:
        emoji = "🔴" if estado == "inactiva" else "🟠"
        ant = _estado_txt(anterior)
        act = _estado_txt(estado)
        dias_txt = f" ({dias} días sin eventos)" if dias else ""
        pv = _probe_txt(probe)
        pv_txt = f" · {pv}" if pv else ""
        lineas.append(f"{emoji} <b>{nombre}</b> ({tipo})\n"
                      f"   {ant} → <b>{act}</b>{dias_txt}{pv_txt}")
    if benigno:
        lineas.append("\n🟢 Feed vivo · sin coincidencias (no es riesgo): "
                      + ", ".join(a[3] for a in benigno))
    lineas.append(f"\nEstado: {resumen.get('activas')} activas · "
                  f"{resumen.get('bajas')} baja(s) · {resumen.get('inactivas')} inactiva(s)")
    lineas.append(f"Detalle: {URL_DASH}/#fuentes")

    text = "\n".join(lineas)
    if dry_run:
        print("[fuentes][dry]\n" + text)
        return
    try:
        r = requests.post(f"{api}/sendMessage", data={
            "chat_id": str(CHAT), "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=30)
        print(f"[fuentes] telegram HTTP {r.status_code} — {len(riesgo)} aviso(s)")
    except Exception as e:
        print(f"[fuentes] error telegram: {e}")


if __name__ == "__main__":
    main(dry_run="--dry" in sys.argv)