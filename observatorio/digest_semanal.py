#!/usr/bin/env python3
"""Digestión semanal del Observatorio de lo publicado.

Compara las publicaciones de los últimos 7 días completos con los 7 anteriores.
Mide cobertura publicada, no movilización. No publica en redes: envía al dueño.
Si no hay cambios relevantes, calla.
"""
import argparse
import html
import json
import os
import re
import sqlite3
import sys
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("OBS_DB", "/home/deploy/observatorio/data/observatorio.db"))
OUT = ROOT / "data/digest_semanal.md"
JSON_OUT = ROOT / "data/digest_semanal.json"
ENV = Path(os.environ.get("FIMI_ENV", "/home/deploy/hybrid-fimi-radar/.env"))
BASE = "https://fimi.viajeinteligencia.com"
TOPICS = [
    ("frontera_sur", "Frontera Sur", "/observatorio/ceuta/"),
    ("protestas_juveniles", "Protestas juveniles", "/observatorio/juventud/"),
    ("elecciones_generales", "Elecciones generales", "/observatorio/campana/"),
    ("infraestructuras_espana", "Infraestructuras", "/observatorio/infraestructuras/"),
]


def load_env(path):
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except OSError:
        pass


def norm_title(value):
    value = html.unescape(str(value or "")).casefold()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def load_counts(start, end):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT topic,title,url,source,published FROM items "
            "WHERE published IS NOT NULL AND published >= ? AND published < ?",
            (start.isoformat(), (end + timedelta(days=1)).isoformat()),
        ).fetchall()
    finally:
        con.close()
    seen = set()
    counts = Counter()
    google = Counter()
    for r in rows:
        title = norm_title(r["title"])
        day = (r["published"] or "")[:10]
        if not title:
            continue
        key = (day, title, (r["source"] or "").strip())
        if key in seen:
            continue
        seen.add(key)
        counts[(r["topic"], day)] += 1
        if "news.google.com" in (r["url"] or ""):
            google[(r["topic"], day)] += 1
    return counts, google


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--tg", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    args = ap.parse_args()
    load_env(ENV)
    today = args.today or datetime.now(timezone.utc).date()
    end = today - timedelta(days=1)
    last_start = end - timedelta(days=6)
    prev_end = last_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)
    counts, google = load_counts(prev_start, end)
    topics = []
    for key, label, path in TOPICS:
        last = sum(counts[(key, (last_start + timedelta(days=i)).isoformat())] for i in range(7))
        prev = sum(counts[(key, (prev_start + timedelta(days=i)).isoformat())] for i in range(7))
        daily = [(last_start + timedelta(days=i)).isoformat() for i in range(7)]
        peak_day, peak_n = max(((d, counts[(key, d)]) for d in daily), key=lambda x: x[1], default=(None, 0))
        delta = round(100 * (last - prev) / prev, 1) if prev else None
        topics.append({
            "topic": key, "label": label, "url": BASE + path,
            "last7": last, "prev7": prev, "delta_pct": delta,
            "peak_day": peak_day, "peak_n": peak_n,
            "google_share": round(100 * sum(google[(key, d)] for d in daily) / last, 1) if last else None,
        })
    all_jump = sum(1 for t in topics if (t["delta_pct"] or 0) >= 100)
    changed = [t for t in topics if abs(t["delta_pct"] or 0) >= 20]
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "period": f"{last_start} → {end}",
        "previous": f"{prev_start} → {prev_end}",
        "topics": topics,
        "changed": [t["topic"] for t in changed],
        "all_jump_warning": all_jump >= 3,
        "unit": "publicaciones deduplicadas",
        "note": "Mide cobertura publicada, no movilización ni intensidad del conflicto.",
    }
    lines = [
        f"# Lo que cambió · {last_start} → {end}",
        "",
        "Publicaciones deduplicadas. No es movilización, no es coordinación y no es un pronóstico.",
        "",
        "| Tema | 7 días | 7 anteriores | Δ | Pico | Google News |",
        "|---|---:|---:|---:|---|---:|",
    ]
    for t in topics:
        d = "s/d" if t["delta_pct"] is None else f'{t["delta_pct"]:+.1f} %'
        g = "s/d" if t["google_share"] is None else f'{t["google_share"]:.1f} %'
        lines.append(f'| [{t["label"]}]({t["url"]}) | {t["last7"]} | {t["prev7"]} | {d} | {t["peak_day"] or "—"} ({t["peak_n"]}) | {g} |')
    if all_jump >= 3:
        lines += ["", "**Aviso:** los cuatro temas suben a la vez. No se interpreta como movilización. Puede ser un ciclo informativo, una cobertura excepcional o un cambio de captura; hay que revisar fuentes antes de concluir."]
    if not changed:
        lines += ["", "Sin cambios relevantes: no se envía aviso."]
    lines += ["", "Qué no dice: no mide personas movilizadas, no confirma hechos y no atribuye coordinación."]
    text = "\n".join(lines)
    data["markdown"] = text
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text + "\n", encoding="utf-8")
    JSON_OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(text)
    if not changed and not args.force:
        print("[digest] sin cambios relevantes; no se envía")
        return 0
    if args.dry or not args.tg:
        print("[digest] dry/sin --tg; no se envía")
        return 0
    token = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "")
    owner = os.environ.get("FIMI_OWNER_CHAT", "47652516")
    if not token or ":" not in token:
        print("[digest] sin token; no se envía", file=sys.stderr)
        return 0
    body = "📊 <b>Lo que cambió · semana</b>\n\n" + "\n".join(
        f'<b>{html.escape(t["label"])}</b>: {t["last7"]} vs {t["prev7"]} publicaciones.'
        for t in topics
    )
    body += "\n\nNo es movilización ni coordinación. Detalle en el informe."
    if all_jump >= 3:
        body += "\n⚠️ Los cuatro temas suben a la vez: revisar captura/fuentes antes de interpretar."
    dataq = urllib.parse.urlencode({"chat_id": owner, "text": body, "parse_mode": "HTML"}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=dataq
        ), timeout=20).read()
        print("[digest] enviado al dueño")
    except Exception as exc:
        print(f"[digest] telegram: {type(exc).__name__}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
