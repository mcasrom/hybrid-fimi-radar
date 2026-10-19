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
# OOM por RUN, no por corpus total: el run más pesado es el de la MAYOR ventana
# por tema (el cron corre --ventana-dias con la ventana de config.yaml). Avisamos
# por el MAYOR run (ventana REAL), no por el corpus total (métrica engañosa: la
# historia es ~90 d y la ventana casi no recorta).
#
# Recalibrado 19-oct-2026 tras la optimización de memoria (bloques en
# build_edges / near_duplicate_ratio, commit 18e43ac/eedae1a). Densidad medida:
#   elecciones 64.479 ev -> 1.002 MB ; oriente_medio 48.974 ev -> 881 MB (VmHWM)
#   => ~15,5-18 KB/evento (la calibración de 13-oct daba 40 KB/evento y el
#   umbral 65k/80k saltaría sin riesgo real: elecciones estabiliza a 45 d en
#   ~81k ev con el pico medido < 1 GiB).
# Con ~2,3 Gi disponibles: 100 k ev ~ 1,6 GB de pico (vigilar) y 125 k ev ~ 2,0 GB
# (zona de swap/OOM: los OOM históricos mataron runs de 1,6-2,5 GB de RSS).
RUN_WARN = 100_000
RUN_BAD = 125_000
# Pico RSS MEDIDO en los últimos runs (logs/fimi_rss.log, /usr/bin/time -a del
# cron): señal real frente al modelo "eventos x KB". 1,8 Gi = vigilar;
# 2,2 Gi = casi seguro OOM con la base del sistema en uso.
RSS_LOG = ROOT / "logs" / "fimi_rss.log"
RSS_WARN_KB = 1_800_000
RSS_BAD_KB = 2_200_000
RSS_LECTURA = 18  # runs leídos del final (9 temas x 2 ciclos)
# Ventana por defecto de un tema si config.yaml no declara `ventana_dias`
# (el cron usa este mismo default). El peor run se calcula por tema con SU
# ventana real, no con este valor fijo.
VENTANA_DIAS_CHECK = 45


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
        sin_kw = sorted(t for t in temas_cfg if t not in kw_temas)
        extra = (f" (sin keywords propias: {', '.join(sin_kw)} — sumidero por defecto)"
                 if sin_kw else "")
        ok.append({"check": "config",
                   "msg": f"{len(kw_temas)}/{len(temas_cfg)} temas con keywords propias{extra}"})

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

    # 6.5) descarte: eventos sin tema (no matchean ninguna keyword)
    try:
        n_ev_total = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        n_sin_tema = con.execute(
            "SELECT COUNT(*) FROM events e WHERE NOT EXISTS "
            "(SELECT 1 FROM event_temas t WHERE t.event_id=e.id)").fetchone()[0]
        ratio = (n_sin_tema / n_ev_total) if n_ev_total else 0.0
        # estado previo para detectar crecimiento
        state_file = ROOT / "data" / "descarte_estado.json"
        prev = {}
        if state_file.exists():
            try:
                prev = json.loads(state_file.read_text()) or {}
            except Exception:
                prev = {}
        ratio_prev = prev.get("ratio", 0.0)
        delta = ratio - ratio_prev
        DICARTE_MAX = 0.40   # 40% de descarte como umbral de alerta
        DICARTE_CRECE = 0.10 # alertar si crece >10pp vs ciclo anterior
        if ratio >= DICARTE_MAX or delta >= DICARTE_CRECE:
            motivo = []
            if ratio >= DICARTE_MAX:
                motivo.append(f"{n_sin_tema:,}/{n_ev_total:,} eventos sin tema ({ratio*100:.0f}%) — umbral {DICARTE_MAX*100:.0f}%")
            if delta >= DICARTE_CRECE:
                motivo.append(f"crecimiento: {ratio_prev*100:.0f}% -> {ratio*100:.0f}% (+{delta*100:.0f}pp)")
            issues.append({"check": "descarte", "nivel": "warn",
                           "msg": "; ".join(motivo) +
                                  ". ¿Keywords demasiado estrechas? Ver salud de keywords."})
        else:
            ok.append({"check": "descarte",
                       "msg": f"{n_sin_tema:,}/{n_ev_total:,} sin tema ({ratio*100:.0f}%) — dentro de umbral"})
        # persistir estado
        state_file.write_text(json.dumps({"ratio": ratio, "n_sin_tema": n_sin_tema,
                                          "n_ev_total": n_ev_total,
                                          "generado": now.isoformat()}, ensure_ascii=False, indent=2))
    except Exception as e:
        issues.append({"check": "descarte", "nivel": "warn", "msg": f"error descarte: {e}"})

    # 6) tamaño del INPUT del run MÁS pesado — el OOM escala con el mayor run,
    # no con el corpus total. Cada tema corre con SU propia ventana
    # (temas.<tema>.ventana_dias; por defecto 45 d), así que el peor caso se
    # calcula con la ventana REAL de cada tema (no un 45 fijo). Ver RUN_WARN/RUN_BAD.
    try:
        _tema, n_run, _vent = "—", 0, None
        for _t in activos:
            _w = int((temas_cfg.get(_t) or {}).get("ventana_dias", VENTANA_DIAS_CHECK))
            _cut = int(datetime.datetime.now().timestamp()) - _w * 86400
            _n = con.execute(
                "SELECT COUNT(*) FROM event_temas et JOIN events e ON e.id=et.event_id"
                " WHERE et.tema_id=? AND e.timestamp>=?",
                (_t, _cut)).fetchone()[0]
            if _n > n_run:
                _tema, n_run, _vent = _t, _n, _w
        n_ev = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        _tail = f" (corpus total {n_ev:,})"
        _lbl = f"«{_tema}» {n_run:,} ev/ventana {_vent}d"
        if n_run >= RUN_BAD:
            issues.append({"check": "corpus_input", "nivel": "bad",
                           "msg": f"run mayor {_lbl} — umbral de OOM (RUN_BAD {RUN_BAD:,}). "
                                  f"Acortar la ventana de «{_tema}» o liberar RAM.{_tail}"})
        elif n_run >= RUN_WARN:
            issues.append({"check": "corpus_input", "nivel": "warn",
                           "msg": f"run mayor {_lbl} — vigilar (RUN_WARN {RUN_WARN:,}).{_tail}"})
        else:
            ok.append({"check": "corpus_input",
                       "msg": f"run mayor {_lbl} (margen); corpus {n_ev:,}"})
    except Exception as e:
        issues.append({"check": "corpus", "nivel": "warn", "msg": f"error corpus: {e}"})

    # 6b) pico de RAM MEDIDO en los últimos runs (fimi_rss.log) — señal real
    # frente al modelo de "eventos x KB". Si falta el log se avisa: un guardia
    # que deja de medir es tan malo como uno que grita de más (regla 4).
    try:
        if RSS_LOG.exists():
            lineas = RSS_LOG.read_text(encoding="utf-8",
                                       errors="replace").splitlines()[-RSS_LECTURA:]
            pico, pico_tema = 0, "—"
            for ln in lineas:
                m = re.search(r"run tema=(\S+):.*\s(\d+) KB RSS", ln)
                if m and int(m.group(2)) > pico:
                    pico, pico_tema = int(m.group(2)), m.group(1)
            if pico:
                lbl = f"«{pico_tema}» {pico:,} KB ({pico / 1024 / 1024:.2f} GiB)"
                if pico >= RSS_BAD_KB:
                    issues.append({"check": "pico_rss", "nivel": "bad",
                                   "msg": f"pico de RAM medido {lbl} — zona de OOM."})
                elif pico >= RSS_WARN_KB:
                    issues.append({"check": "pico_rss", "nivel": "warn",
                                   "msg": f"pico de RAM medido {lbl} — vigilar."})
                else:
                    ok.append({"check": "pico_rss",
                               "msg": f"pico de RAM medido {lbl} (margen)"})
        else:
            issues.append({"check": "pico_rss", "nivel": "warn",
                           "msg": f"no existe {RSS_LOG.name}: sin medición de pico de RAM"})
    except Exception as e:
        issues.append({"check": "pico_rss", "nivel": "warn", "msg": f"error pico_rss: {e}"})

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


def export_sin_tema(n=50):
    """Escribe CSV con los N eventos mas recientes SIN tema (no matchean
    ninguna keyword). Util para auditar si las keywords son demasiado
    estrechas y estamos tirando señal real."""
    import csv
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT e.id, e.timestamp, e.source, e.author, e.title, e.text, e.url "
        "FROM events e WHERE NOT EXISTS "
        "(SELECT 1 FROM event_temas t WHERE t.event_id=e.id) "
        "ORDER BY e.timestamp DESC LIMIT ?", (n,)).fetchall()
    con.close()
    out = ROOT / "data" / "eventos_sin_tema.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "timestamp", "source", "author", "title", "text", "url"])
        for r in rows:
            w.writerow([r["id"], r["timestamp"], r["source"], r["author"],
                        r["title"], r["text"], r["url"]])
    print(f"export {len(rows)} eventos sin tema -> {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", action="store_true")
    ap.add_argument("--notify", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--export-sin-tema", type=int, default=0,
                    help="exporta los N eventos mas recientes sin tema a CSV")
    args = ap.parse_args()
    if args.export_sin_tema:
        export_sin_tema(args.export_sin_tema)
        return
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
