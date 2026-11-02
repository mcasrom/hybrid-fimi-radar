#!/usr/bin/env python3
"""Genera los KPI de situación de un tema desde observatorio.db.

No interpreta: cuenta publicaciones, fuentes, idiomas y evidencia curada.
La unidad es la publicación, no el hecho. Los vacíos se publican como vacíos.
"""
import argparse
import json
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_DB = ROOT / "observatorio/data/observatorio.db"
DEFAULT_CURATED = HERE / "situacion_frontera_sur.json"
DEFAULT_OUT = HERE / "situacion_kpis.json"


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


def query_daily(con, topic, start, end):
    rows = con.execute(
        """SELECT substr(published,1,10) AS d, COUNT(*) AS n
           FROM items
           WHERE topic = ? AND published IS NOT NULL AND published >= ? AND published < ?
           GROUP BY d ORDER BY d""",
        (topic, start.isoformat(), (end + timedelta(days=1)).isoformat()),
    ).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def query_sources(con, topic, start, end):
    return con.execute(
        """SELECT COALESCE(NULLIF(TRIM(source), ''), 'sin fuente') AS s, COUNT(*) AS n
           FROM items
           WHERE topic = ? AND published IS NOT NULL AND published >= ? AND published < ?
           GROUP BY s ORDER BY n DESC, s""",
        (topic, start.isoformat(), (end + timedelta(days=1)).isoformat()),
    ).fetchall()


def query_languages(con, topic, start, end):
    return con.execute(
        """SELECT COALESCE(NULLIF(TRIM(source_lang), ''), 'sin idioma') AS l, COUNT(*) AS n
           FROM items
           WHERE topic = ? AND published IS NOT NULL AND published >= ? AND published < ?
           GROUP BY l ORDER BY n DESC, l""",
        (topic, start.isoformat(), (end + timedelta(days=1)).isoformat()),
    ).fetchall()


def query_classes(con, topic, start, end):
    return con.execute(
        """SELECT COALESCE(NULLIF(TRIM(source_class), ''), 'sin clase') AS c, COUNT(*) AS n
           FROM items
           WHERE topic = ? AND published IS NOT NULL AND published >= ? AND published < ?
           GROUP BY c ORDER BY n DESC, c""",
        (topic, start.isoformat(), (end + timedelta(days=1)).isoformat()),
    ).fetchall()


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
    try:
        counts = query_daily(con, args.topic, start - timedelta(days=6), end)
        sources = query_sources(con, args.topic, start, end)
        languages = query_languages(con, args.topic, start, end)
        classes = query_classes(con, args.topic, start, end)
    finally:
        con.close()

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

    src_total = sum(int(n) for _, n in sources)
    top = [{"source": s, "n": int(n), "share": pct(int(n), src_total)} for s, n in sources[:10]]
    top3 = sum(int(n) for _, n in sources[:3])
    lang = [{"lang": l, "n": int(n), "share": pct(int(n), total)} for l, n in languages]
    class_mix = [{"class": c, "n": int(n), "share": pct(int(n), total)} for c, n in classes]

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
            "distinct": len(sources),
            "total_publications": src_total,
            "top1_share": pct(int(sources[0][1]), src_total) if sources else None,
            "top3_share": pct(top3, src_total),
            "top": top,
        },
        "languages": {"distinct": len(languages), "top": lang},
        "source_classes": class_mix,
        "evidence": evidence(args.curated, args.curated_key),
        "notes": [
            "La unidad es la publicación capturada, no el hecho confirmado.",
            "El día de hoy es parcial; la variación usa los 7 días completos anteriores.",
            "Fuente es la etiqueta de captura; no mide independencia editorial.",
            "La evidencia solo se calcula donde hay fichas curadas.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{args.out} · {total} publicaciones · {len(sources)} fuentes · delta {delta}%")


if __name__ == "__main__":
    main()
