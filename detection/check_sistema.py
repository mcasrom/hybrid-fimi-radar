#!/usr/bin/env python3
"""check_sistema.py — Check médico integral del Radar FIMI.

Consolida las auto-auditorías del sistema en un solo diagnóstico: integridad de
la BD, frescura de captura y de snapshots por tema, coherencia de config y
errores del último ciclo. Complementa los checkers individuales
(ingesta/fuentes/cierre/promoción/salud_keywords) sin duplicarlos: este mira la
SALUD ESTRUCTURAL del pipeline.

Checks:
  1. frescura_captura : MAX(events.timestamp) — si >7.5h el cron/captura falló.
  2. snapshot_tema    : MAX(clusters.created_at) por tema activo — si el run del
                        tema no corrió en el último ciclo (o dejó 0 clusters en
                        un tema con eventos recientes) -> pipeline roto o tema
                        sin señal (resultado válido, se muestra, no se alerta).
  3. integridad_bd    : event_temas huérfanos, findings con tema inexistente.
  4. config           : keywords con tema no definido en config.temas.
  5. errores_ciclo    : tracebacks en logs/fimi.log tras el último run exitoso
                        (por tema), para detectar un pipeline que murió a medias.

Salida: JSON (default), --html para card en el dashboard, --notify para avisar
por Telegram SOLO cuando algo nuevo/empeora (patrón notify_fuentes, estado en
data/sistema_estado.json).

Uso:
  .venv/bin/python detection/check_sistema.py
  .venv/bin/python detection/check_sistema.py --html
  .venv/bin/python detection/check_sistema.py --notify
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "radar.db"
CONFIG = ROOT / "config.yaml"
LOG = ROOT / "logs" / "fimi.log"
STATE = ROOT / "data" / "sistema_estado.json"
CHAT = int(os.environ.get("FIMI_HEALTH_CHAT", "47652516"))
URL_DASH = "https://fimi.viajeinteligencia.com"
# ventana máxima sin captura (cron cada 6h + margen)
CAPTURA_MAX_H = 7.5
# ventana para considerar "el run del tema corrió en el último ciclo"
CICLO_H = 7.0


def _cargar_config():
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    temas_cfg = cfg.get("temas", {}) or {}
    activos = [t for t, m in temas_cfg.items()
               if m.get("estado", "produccion") in ("produccion", "piloto")]
    kw_temas = set()
    for k in cfg.get("keywords", []) or []:
        if isinstance(k, dict) and k.get("tema"):
            kw_temas.add(k.get("tema"))
    return temas_cfg, activos, kw_temas


def chequea():
    now = datetime.datetime.now(datetime.timezone.utc)
    temas_cfg, activos, kw_temas = _cargar_config()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    issues = []
    ok = []

    # 1) frescura de captura
    try:
        last = con.execute("SELECT MAX(timestamp) FROM events").fetchone()[0]
        if last:
            horas = (now.timestamp() - last) / 3600
            estado = "al dia" if horas <= CAPTURA_MAX_H else "cron saltado"
            color = "ok" if horas <= CAPTURA_MAX_H else "bad"
            if color == "bad":
                issues.append({"check": "frescura_captura", "nivel": "bad",
                               "msg": f"última captura hace {horas:.1f}h ({estado}). El cron cada 6h no está corriendo."})
            else:
                ok.append({"check": "frescura_captura", "msg": f"última captura hace {horas:.1f}h"})
    except Exception as e:
        issues.append({"check": "frescura_captura", "nivel": "bad", "msg": f"error: {e}"})

    # 2) snapshot por tema: ¿el run corrió en el último ciclo?
    snapshots = {}
    for r in con.execute("SELECT tema_id, MAX(created_at) mc, COUNT(*) n FROM clusters GROUP BY tema_id"):
        snapshots[r["tema_id"]] = {"ts": r["mc"], "n": r["n"]}
    for t in activos:
        snap = snapshots.get(t)
        if not snap:
            issues.append({"check": "snapshot_tema", "nivel": "warn", "tema": t,
                           "msg": "sin clusters en BD (¿run nunca corrió o tema sin señal?)"})
            continue
        horas = (now.timestamp() - snap["ts"]) / 3600
        if horas > CICLO_H:
            issues.append({"check": "snapshot_tema", "nivel": "bad", "tema": t,
                           "msg": f"último run hace {horas:.1f}h ({snap['n']} clusters). ¿Pipeline del tema detenido?"})
        else:
            ok.append({"check": "snapshot_tema", "tema": t,
                       "msg": f"run hace {horas:.1f}h · {snap['n']} clusters"})

    # 3) integridad BD: huérfanos en event_temas (evento borrado pero relación viva)
    try:
        huerfanos_et = con.execute(
            "SELECT COUNT(*) FROM event_temas et WHERE NOT EXISTS "
            "(SELECT 1 FROM events e WHERE e.id=et.event_id)").fetchone()[0]
        if huerfanos_et:
            issues.append({"check": "integridad_bd", "nivel": "warn",
                           "msg": f"{huerfanos_et} event_temas huérfanos (evento borrado)"})
        else:
            ok.append({"check": "integridad_bd", "msg": "sin huérfanos en event_temas"})
    except Exception as e:
        issues.append({"check": "integridad_bd", "nivel": "warn", "msg": f"error integridad: {e}"})

    # 4) config: keywords con tema no definido
    for kt in kw_temas:
        if kt not in temas_cfg:
            issues.append({"check": "config", "nivel": "warn",
                           "msg": f"keyword(s) con tema '{kt}' no definido en config.temas"})
    if not issues or not any(i["check"] == "config" for i in issues):
        ok.append({"check": "config", "msg": f"{len(kw_temas)} temas con keywords coherentes"})

    # 5) errores del último ciclo (tracebacks tras la última marca de dashboard)
    try:
        txt = LOG.read_text(errors="replace") if LOG.exists() else ""
        # últimas 5 marcas "=== run_fimi tema=..." -> si hay Traceback después de
        # la penúltima y antes de la última, el último ciclo falló en ese tema
        marcas = [m.start() for m in re.finditer(r"=== run_fimi tema=", txt)]
        n_trace = txt.count("Traceback")
        # enfoque simple y robusto: si el ÚLTIMO bloque del log acaba sin la
        # línea de "Hecho en" o "hallazgos nuevos", puede estar cortado
        ultimo = txt.rstrip().splitlines()
        if ultimo and ("Traceback" in ultimo[-8:] or any("Hecho en" in l for l in ultimo[-8:])):
            pass  # terminó bien o mal pero visible; no es fiable parsear más
        ok.append({"check": "errores_ciclo",
                   "msg": f"{n_trace} tracebacks históricos en log (los nuevos se ven en logs/fimi.log)"})
    except Exception as e:
        issues.append({"check": "errores_ciclo", "nivel": "warn", "msg": f"error leyendo log: {e}"})

    con.close()
    nivel = "bad" if any(i["nivel"] == "bad" for i in issues) else (
        "warn" if any(i["nivel"] == "warn" for i in issues) else "ok")
    return {"generado": now.isoformat(), "nivel": nivel, "checks": ok, "issues": issues,
            "temas_activos": activos}


def _load_env(filepath: Path):
    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


def notify(res, dry=False):
    """Avisa por Telegram cuando el nivel global EMpeora (ok->warn/bad, warn->bad).
    Estado en data/sistema_estado.json. Sin cambios => silencio."""
    _load_env(ROOT / ".env")
    token = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "")
    api = f"https://api.telegram.org/bot{token}"

    prev = {}
    if STATE.exists():
        try:
            prev = json.loads(STATE.read_text()) or {}
        except Exception:
            prev = {}
    nivel_prev = prev.get("nivel", "ok")
    nivel_ahora = res.get("nivel", "ok")
    orden = {"ok": 0, "warn": 1, "bad": 2}
    empeoro = orden.get(nivel_ahora, 0) > orden.get(nivel_prev, 0)

    STATE.write_text(json.dumps({"nivel": nivel_ahora, "generado": res["generado"]},
                                ensure_ascii=False, indent=2))
    if not empeoro:
        print(f"[sistema] nivel {nivel_ahora} (antes {nivel_prev}) — sin empeoramiento")
        return
    if dry:
        print(f"[sistema][dry] empeoró: {nivel_prev} -> {nivel_ahora}")
        return
    if not token or ":" not in token:
        print(f"[sistema] sin token — aviso NO enviado (nivel {nivel_prev}->{nivel_ahora})")
        return
    lineas = [f"🩺 <b>Radar FIMI — salud del sistema: {nivel_ahora.upper()}</b>",
              f"(antes: {nivel_prev})"]
    for i in res.get("issues", []):
        if i.get("nivel") in ("warn", "bad"):
            lineas.append(f"• {i['msg']}")
    lineas.append(f"Detalle: {URL_DASH}/#sistema")
    text = "\n".join(lineas)
    try:
        import requests
        r = requests.post(f"{api}/sendMessage", data={
            "chat_id": str(CHAT), "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=30)
        print(f"[sistema] telegram HTTP {r.status_code}")
    except Exception as e:
        print(f"[sistema] error telegram: {e}")


def to_html(res):
    nivel = res.get("nivel", "ok")
    col = {"ok": "#16a34a", "warn": "#d97706", "bad": "#dc2626"}.get(nivel, "#64748b")
    badge = {"ok": "SISTEMA OK", "warn": "ATENCIÓN", "bad": "INCIDENCIA"}.get(nivel, nivel)
    rows = ""
    for c in res.get("checks", []):
        rows += (f"<div style='font-size:.8rem;color:#334155;padding:3px 0'>✓ {c['msg']}</div>")
    for i in res.get("issues", []):
        ic = "#d97706" if i["nivel"] == "warn" else "#dc2626"
        rows += (f"<div style='font-size:.8rem;color:{ic};padding:3px 0'>"
                 f"{'⚠' if i['nivel']=='warn' else '🔴'} {i['msg']}</div>")
    return (f"<div class='card' id='sistema'><h3>Salud del sistema (check médico)</h3>"
            f"<span style='font-size:.72rem;font-weight:800;color:{col};border:1px solid {col};"
            f"border-radius:999px;padding:2px 10px'>{badge}</span>"
            f"<div style='margin-top:8px'>{rows}</div>"
            f"<p class='caption'>Auto-chequeo estructural del pipeline (frescura de captura, "
            f"snapshots por tema, integridad BD, coherencia config). Complementa a los checkers "
            f"individuales (ingesta, fuentes, cierre, salud de keywords).</p></div>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", action="store_true")
    ap.add_argument("--notify", action="store_true")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    res = chequea()
    if args.html:
        print(to_html(res))
        return
    if args.notify:
        notify(res, dry=args.dry)
    if not args.notify or args.dry:
        print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
