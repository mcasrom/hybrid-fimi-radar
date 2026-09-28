#!/usr/bin/env python3
"""Panel de salud del observatorio (resumen multi-tema para el admin).

Calcula, por tema ACTIVO, un resumen de 14 dias (eventos, fuentes, dependencia
de la fuente dominante, clusters por banda, sincronias entre cuentas, clusters
solo-feed y posibles narrativas) y una lista de `avisos` a vigilar.

Solo LEE la base de datos y el estado de `salud_keywords` (`keywords_estado.json`).
No toca captura, scoring ni bandas.

Salidas:
  --json  RUTA   escribe el JSON (por defecto data/salud_temas.json)
  --md    RUTA   escribe el resumen en markdown (por defecto data/salud_temas.md)
  --tg           envia un mini-resumen por Telegram
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB_DEFECTO = ROOT / "data" / "radar.db"
ESTADO_KEYWORDS = ROOT / "data" / "keywords_estado.json"
DIAS_DEFECTO = 14

UMBRAL_DEPENDENCIA = 85      # % de eventos de una sola fuente
UMBRAL_SOLO_FEED = 80        # % de clusters explicados como feed de una fuente
MIN_EVENTOS_AVISO = 200      # no avisar de temas con muy poco volumen


def _temas_activos() -> list[str]:
    """Temas con estado != cerrado, leidos de config.yaml (misma fuente que el resto)."""
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
        temas = cfg.get("temas", {}) or {}
        activos = []
        for slug, v in temas.items():
            estado = (v or {}).get("estado", "activo")
            if str(estado).lower() not in ("cerrado", "cerrada", "cerrados"):
                activos.append(slug)
        if activos:
            return sorted(activos)
    except Exception as e:  # noqa: BLE001
        print(f"[salud_panel] no pude leer config.yaml: {e}", file=sys.stderr)
    # fallback: los 8 temas vivos conocidos
    return ["frontera_sur", "oriente_medio", "elecciones", "inteligencia_artificial",
            "eeuu_politica", "sahel", "energia", "defensa_espana"]


def _dependencia(fuentes: dict[str, int]) -> tuple[int, str]:
    if not fuentes:
        return 0, "—"
    top = max(fuentes.items(), key=lambda kv: kv[1])
    total = sum(fuentes.values()) or 1
    return round(top[1] * 100 / total), top[0]


def calcular(dias: int = DIAS_DEFECTO, db: Path = DB_DEFECTO) -> dict:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    mx = con.execute("SELECT MAX(timestamp) FROM events WHERE timestamp<=strftime('%s','now')").fetchone()[0]
    cut = mx - dias * 86400

    eventos: dict[str, int] = defaultdict(int)
    fuentes: dict[str, dict[str, int]] = defaultdict(dict)
    for r in con.execute(
        "SELECT et.tema_id t, e.source s, COUNT(*) n FROM events e"
        " JOIN event_temas et ON et.event_id=e.id WHERE e.timestamp>=?"
        " GROUP BY et.tema_id, e.source", (cut,),
    ):
        eventos[r["t"]] += r["n"]
        fuentes[r["t"]][r["s"]] = r["n"]

    cl: dict[str, dict] = defaultdict(lambda: {
        "clusters": 0, "high": 0, "anom": 0, "max": 0.0,
        "sync": 0, "sost": 0, "feed": 0, "pot_narrativas": 0,
    })
    for r in con.execute("SELECT tema_id t, overall_score s, narrative_subtype ns FROM clusters"):
        d = cl[r["t"]]
        d["clusters"] += 1
        sc = r["s"] or 0
        if sc >= 60:
            d["high"] += 1
        elif sc >= 40:
            d["anom"] += 1
        d["max"] = max(d["max"], sc)
        if r["ns"] and "potential_narrative" in str(r["ns"]):
            d["pot_narrativas"] += 1
    for r in con.execute(
        "SELECT c.tema_id t, json_extract(j.value,'$.code') code FROM clusters c,"
        " json_each(c.alternative_explanations) j"
        " WHERE json_extract(j.value,'$.status')='supported'"
    ):
        d = cl[r["t"]]
        if r["code"] == "cross_account_synchrony":
            d["sync"] += 1
        elif r["code"] == "sustained_amplification":
            d["sost"] += 1
        elif r["code"] == "single_source_feed":
            d["feed"] += 1

    temas = []
    for t in _temas_activos():
        f = fuentes.get(t, {})
        dep, top = _dependencia(f)
        d = cl.get(t, {})
        temas.append({
            "tema": t,
            "eventos": eventos.get(t, 0),
            "fuentes": len(f),
            "dependencia_pct": dep,
            "fuente_top": top,
            "clusters": d.get("clusters", 0),
            "high": d.get("high", 0),
            "anom": d.get("anom", 0),
            "max": round(d.get("max", 0), 1),
            "sync": d.get("sync", 0),
            "sost": d.get("sost", 0),
            "feed": d.get("feed", 0),
            "pot_narrativas": d.get("pot_narrativas", 0),
        })

    avisos = _avisos(temas, cl)
    return {
        "generado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dias": dias,
        "corpus": {
            "eventos": con.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "clusters": con.execute("SELECT COUNT(*) FROM clusters").fetchone()[0],
        },
        "temas": temas,
        "avisos": avisos,
    }


def _avisos(temas: list[dict], cl: dict) -> list[dict]:
    avisos: list[dict] = []
    estado_kw = {}
    try:
        estado_kw = json.loads(ESTADO_KEYWORDS.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[salud_panel] sin keywords_estado.json: {e}", file=sys.stderr)

    for t in temas:
        nombre = t["tema"]
        # tema ciego (keywords que capturan pero nada se etiqueta)
        s = estado_kw.get(nombre, {})
        if s.get("alerta") or (s.get("sin_etiquetar") or 0) > 50:
            avisos.append({"tipo": "tema_ciego", "tema": nombre, "nivel": "alto",
                           "detalle": f"{s.get('sin_etiquetar', '?')} eventos sin etiquetar"})
        if t["eventos"] >= MIN_EVENTOS_AVISO:
            # dependencia extrema de una sola fuente
            if t["dependencia_pct"] >= UMBRAL_DEPENDENCIA:
                avisos.append({"tipo": "dependencia", "tema": nombre, "nivel": "medio",
                               "detalle": f"{t['dependencia_pct']}% de {t['fuente_top']}"})
            # senal baja: casi todo feed y sin sincronias
            d = cl.get(nombre, {})
            if d.get("clusters") and t["sync"] == 0:
                pct_feed = round(d.get("feed", 0) * 100 / d["clusters"])
                if pct_feed >= UMBRAL_SOLO_FEED:
                    avisos.append({"tipo": "senal_baja", "tema": nombre, "nivel": "medio",
                                   "detalle": f"{pct_feed}% de clusters son feed de una fuente"})
            if t["sync"] == 0 and t["pot_narrativas"] == 0:
                avisos.append({"tipo": "sin_senal", "tema": nombre, "nivel": "bajo",
                               "detalle": "0 sincronias y 0 posibles narrativas"})
    orden = {"alto": 0, "medio": 1, "bajo": 2}
    avisos.sort(key=lambda a: (orden.get(a["nivel"], 9), a["tema"]))
    return avisos


def _cabecera(r: dict) -> str:
    return (f"Salud de temas · {r['dias']} d · {r['generado']} · "
            f"corpus {r['corpus']['eventos']:,} ev / {r['corpus']['clusters']:,} clusters").replace(",", ".")


def a_markdown(r: dict) -> str:
    L = [f"# {_cabecera(r)}", "",
         "| Tema | ev | fuentes | dep% | HIGH | ANOM | max | sync | feed | potN |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for t in r["temas"]:
        L.append(f"| {t['tema']} | {t['eventos']} | {t['fuentes']} | {t['dependencia_pct']} |"
                 f" {t['high']} | {t['anom']} | {t['max']} | {t['sync']} | {t['feed']} | {t['pot_narrativas']} |")
    L += ["", "## Avisos a vigilar"]
    if not r["avisos"]:
        L.append("- (ninguno)")
    for a in r["avisos"]:
        L.append(f"- [{a['nivel']}] **{a['tema']}** · {a['tipo']}: {a['detalle']}")
    return "\n".join(L) + "\n"


def _load_env(filepath: Path) -> None:
    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except Exception as e:  # noqa: BLE001
        print(f"[salud_panel] no pude leer {filepath}: {e}", file=sys.stderr)


def _telegram(texto: str) -> bool:
    from urllib.request import Request, urlopen
    _load_env(ROOT / ".env")
    token = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("FIMI_OWNER_CHAT") or os.environ.get("FIMI_TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print("[salud_panel] sin FIMI_TELEGRAM_BOT_TOKEN/CHAT_ID", file=sys.stderr)
        return False
    data = json.dumps({"chat_id": chat, "text": texto, "parse_mode": "Markdown"}).encode()
    req = Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=20) as resp:
            return resp.status == 200
    except Exception as e:  # noqa: BLE001
        print(f"[salud_panel] Telegram fallo: {e}", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Panel de salud multi-tema (admin).")
    ap.add_argument("--dias", type=int, default=DIAS_DEFECTO)
    ap.add_argument("--db", default=str(DB_DEFECTO))
    ap.add_argument("--json", dest="json_out", default=str(ROOT / "data" / "salud_temas.json"))
    ap.add_argument("--md", dest="md_out", default=str(ROOT / "data" / "salud_temas.md"))
    ap.add_argument("--tg", action="store_true", help="enviar mini-resumen por Telegram")
    ap.add_argument("--stdout", action="store_true", help="imprimir el markdown")
    args = ap.parse_args()

    r = calcular(args.dias, Path(args.db))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    md = a_markdown(r)
    if args.md_out:
        Path(args.md_out).write_text(md, encoding="utf-8")
    if args.stdout:
        print(md)
    if args.tg:
        cab = _cabecera(r)
        cuerpo = "\n".join(f"• *{a['tema']}*: {a['detalle']}" for a in r["avisos"][:12]) or "• sin avisos"
        _telegram(f"`{cab}`\n\n*Salud de temas*\n{cuerpo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
