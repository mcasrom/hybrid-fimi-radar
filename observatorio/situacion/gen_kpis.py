#!/usr/bin/env python3
"""Genera los KPI de situación de un tema desde observatorio.db.

No interpreta: cuenta publicaciones, dominios, idiomas y evidencia curada.
La unidad es la publicación, no el hecho. Los vacíos se publican como vacíos.
"""
import argparse
import html
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_DB = ROOT / "observatorio/data/observatorio.db"
DEFAULT_CURATED = HERE / "situacion_frontera_sur.json"
DEFAULT_OUT = HERE / "situacion_kpis.json"
AGGREGATOR = "news.google.com"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def window(start, end):
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "days": (end - start).days + 1,
    }


def norm_title(value):
    value = html.unescape(str(value or "")).casefold()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def domain(url):
    host = (urlsplit(url or "").hostname or "").lower().removeprefix("www.")
    return host or "sin dominio"


def query_rows(con, topic, start, end):
    return con.execute(
        """SELECT title, url, source, published, source_lang, source_class
           FROM items
           WHERE topic = ? AND published IS NOT NULL AND published >= ? AND published < ?
           ORDER BY published""",
        (topic, start.isoformat(), (end + timedelta(days=1)).isoformat()),
    ).fetchall()


def dedup_rows(rows):
    """Deduplica solo la misma pieza de la misma fuente el mismo día.

    No colapsa dos medios distintos que publican el mismo titular: eso es
    distribución entre fuentes, no un enlace duplicado.
    """
    seen = set()
    kept = []
    duplicates = 0
    invalid = 0
    for r in rows:
        title = norm_title(r["title"])
        day = (r["published"] or "")[:10]
        source = (r["source"] or "").strip()
        if not title:
            invalid += 1
            continue
        key = (day, title, source)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        kept.append(r)
    return kept, duplicates, invalid


def evidence(curated_path, curated_key=None):
    if not curated_path or not Path(curated_path).exists():
        return None
    cur = load(curated_path)
    if "topics" in cur:
        return (cur["topics"].get(curated_key or "") or {}).get("evidence")
    statuses = Counter(cur.get("episode_status", {}).values())
    roles = Counter(x.get("role") for x in cur.get("source_roles", {}).values())
    return {
        "unit": "fichas",
        "total": len(cur.get("episode_status", {})),
        "primary_sources": roles.get("primaria", 0),
        "reported_pending": statuses.get("reportado_sin_primaria", 0)
        + statuses.get("reportado_cifras_prensa", 0),
        "declared_public": statuses.get("declaracion_publica", 0),
        "documented_relations": len(cur.get("relations", [])),
        "open_questions": len(cur.get("open_questions", [])),
        "status_counts": dict(statuses),
        "note": "Solo se evalúa la evidencia de las fichas curadas; no se deduce del volumen.",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--topic", default="frontera_sur")
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    ap.add_argument("--curated", type=Path, default=DEFAULT_CURATED)
    ap.add_argument("--curated-key", default=None)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    if not args.db.exists():
        raise SystemExit(f"No existe la base: {args.db}")
    today = args.today or datetime.now(timezone.utc).date()
    end = today
    start = end - timedelta(days=args.days - 1)

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = query_rows(con, args.topic, start - timedelta(days=6), end)
    finally:
        con.close()

    kept, duplicate_count, invalid_count = dedup_rows(rows)
    counts = Counter((r["published"] or "")[:10] for r in kept)
    period_rows = [r for r in kept if start.isoformat() <= (r["published"] or "")[:10] <= end.isoformat()]
    daily = []
    for i in range(args.days):
        d = start + timedelta(days=i)
        n = counts.get(d.isoformat(), 0)
        ma = sum(counts.get((d - timedelta(days=j)).isoformat(), 0) for j in range(7)) / 7.0
        daily.append({"date": d.isoformat(), "n": n, "ma7": round(ma, 1)})

    total = sum(x["n"] for x in daily)
    complete_end = end - timedelta(days=1)
    last_start = complete_end - timedelta(days=6)
    prev_end = last_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)
    last7 = sum(counts.get((last_start + timedelta(days=i)).isoformat(), 0) for i in range(7))
    prev7 = sum(counts.get((prev_start + timedelta(days=i)).isoformat(), 0) for i in range(7))
    delta = round(100.0 * (last7 - prev7) / prev7, 1) if prev7 else None
    days_with_data = sum(1 for x in daily if x["n"])
    nonempty = [x["date"] for x in daily if x["n"]]

    raw_period = [r for r in rows if start.isoformat() <= (r["published"] or "")[:10] <= end.isoformat()]
    raw_total = len(raw_period)
    period_valid = [r for r in raw_period if norm_title(r["title"])]
    period_empty = len(raw_period) - len(period_valid)
    period_dups = len(period_valid) - len(period_rows)
    direct_rows = [r for r in period_rows if domain(r["url"]) != AGGREGATOR]
    agg = len(period_rows) - len(direct_rows)
    domains = Counter(domain(r["url"]) for r in direct_rows)
    src_total = len(direct_rows)
    top = [
        {"source": d, "domain": d, "n": n, "share": pct(n, src_total)}
        for d, n in domains.most_common(10)
    ]
    top3 = sum(n for _, n in domains.most_common(3))
    langs = Counter((r["source_lang"] or "sin idioma").strip() for r in period_rows)
    classes = Counter((r["source_class"] or "sin clase").strip() for r in period_rows)

    data = {
        "version": "2026-11-02",
        "topic": args.topic,
        "unit": "publicaciones",
        "period": window(start, end),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "activity": {
            "total": total,
            "days_with_data": days_with_data,
            "coverage": {
                "first": nonempty[0] if nonempty else None,
                "last": nonempty[-1] if nonempty else None,
            },
            "today_n": daily[-1]["n"],
            "partial_day": True,
            "last7_complete": {"from": last_start.isoformat(), "to": complete_end.isoformat(), "n": last7},
            "previous7_complete": {"from": prev_start.isoformat(), "to": prev_end.isoformat(), "n": prev7},
            "delta_pct": delta,
            "delta_abs": last7 - prev7,
            "daily": daily,
        },
        "sources": {
            "distinct": len(domains),
            "total_publications": src_total,
            "top1_share": pct(domains.most_common(1)[0][1], src_total) if domains else None,
            "top3_share": pct(top3, src_total),
            "top": top,
        },
        "languages": {
            "distinct": len(langs),
            "top": [{"lang": l, "n": n, "share": pct(n, total)} for l, n in langs.most_common()],
        },
        "source_classes": [
            {"class": c, "n": n, "share": pct(n, total)}
            for c, n in classes.most_common()
        ],
        "quality": {
            "raw_publications": raw_total,
            "valid_titles": len(period_valid),
            "dedup_publications": total,
            "duplicates_removed": period_dups,
            "empty_titles": period_empty,
            "aggregator_publications": agg,
            "aggregator_share": pct(agg, total),
            "direct_publications": src_total,
            "direct_domains": len(domains),
            "dedup_rule": "misma fecha + mismo título normalizado + misma fuente; no se colapsan medios distintos",
        },
        "evidence": evidence(args.curated, args.curated_key),
        "notes": [
            "La unidad es la publicación deduplicada, no el hecho confirmado.",
            "El día de hoy es parcial; la variación usa los 7 días completos anteriores.",
            "Google News se separa como agregador: no se usa para la concentración de dominios.",
            "Una misma noticia en medios distintos no se colapsa: es distribución entre fuentes.",
            "La evidencia solo se calcula donde hay fichas curadas.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{args.out} · {total} dedup · {raw_total} raw · {len(domains)} dominios directos · delta {delta}%")


if __name__ == "__main__":
    main()
