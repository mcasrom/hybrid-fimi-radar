#!/usr/bin/env python3
"""interes_electoral.py — Interés ciudadano por las elecciones (engagement Bluesky).

Serie temporal por proceso electoral a partir del engagement PERSISTIDO en
`events` (bsky_likes/bsky_reposts/bsky_replies, ver collectors/capture.py).
Mide audiencia (likes/reposts/respuestas), NO coordinación ni atribución.

Uso:
  .venv/bin/python detection/interes_electoral.py [--dias 90] [--proceso Brasil] [--json]
"""
import argparse
import collections
import datetime
import json
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DB = str(ROOT / "data" / "radar.db")
from detection import elecciones as E  # noqa: E402


def _semana(ts):
    d = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
    return d.strftime("%Y-%W")


def interes(dias=90, solo=None, db=DB):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    ahora = int(con.execute("SELECT strftime('%s','now')").fetchone()[0])
    desde = ahora - dias * 86400

    procesos = []
    for f in E.cargar_registro():
        if solo and solo.lower() not in ((f.get("pais") or "") + " " + (f.get("nombre") or "")).lower():
            continue
        procesos.append({"pais": f.get("pais") or "?", "nombre": f.get("nombre") or "",
                         "fecha": f.get("fecha"), "kw": E._prep_vocab(f.get("keywords") or []),
                         "posts": 0, "likes": 0, "reposts": 0, "replies": 0,
                         "auth": set(), "likes_list": [], "semanas": collections.Counter()})

    tot = {"posts": 0, "likes": 0, "reposts": 0, "replies": 0}
    for r in con.execute(
            "SELECT timestamp, author, title, text, bsky_likes, bsky_reposts, bsky_replies"
            " FROM events WHERE source='bluesky' AND bsky_likes IS NOT NULL"
            " AND timestamp >= ?", (desde,)):
        txt = (r["title"] or "") + " " + (r["text"] or "")
        tn, toks = E._norm(txt), E._tokens_norm(txt)
        lk, rp, rl = r["bsky_likes"] or 0, r["bsky_reposts"] or 0, r["bsky_replies"] or 0
        tot["posts"] += 1
        tot["likes"] += lk
        tot["reposts"] += rp
        tot["replies"] += rl
        for p in procesos:
            if not E._match_vocab(tn, toks, p["kw"]):
                continue
            p["posts"] += 1
            p["likes"] += lk
            p["reposts"] += rp
            p["replies"] += rl
            p["auth"].add(r["author"])
            p["likes_list"].append(lk)
            p["semanas"][_semana(r["timestamp"])] += 1
    con.close()

    salida = []
    for p in procesos:
        if p["posts"] == 0:
            continue
        med = statistics.median(p["likes_list"]) if p["likes_list"] else 0
        salida.append({
            "pais": p["pais"], "nombre": p["nombre"], "fecha": p["fecha"],
            "posts": p["posts"], "likes": p["likes"], "reposts": p["reposts"],
            "replies": p["replies"], "likes_mediana": med,
            "likes_por_post": round(p["likes"] / p["posts"], 1) if p["posts"] else 0,
            "cuentas": len(p["auth"]), "semanas": dict(sorted(p["semanas"].items())),
        })
    salida.sort(key=lambda z: -z["likes"])
    return {"dias": dias, "total_bluesky": tot, "procesos": salida}


def _print(res):
    print(f"INTERES CIUDADANO (Bluesky, engagement) — ventana {res['dias']} d")
    t = res["total_bluesky"]
    print(f"Total posts con engagement en ventana: {t['posts']} | "
          f"likes {t['likes']} | reposts {t['reposts']} | respuestas {t['replies']}")
    print()
    print(f"{'proceso':34s} {'posts':>6s} {'likes':>9s} {'repos':>7s} {'resp':>6s} "
          f"{'med':>5s} {'like/post':>9s} {'ctas':>5s}")
    for p in res["procesos"]:
        nom = (p["pais"] + " " + p["nombre"])[:34]
        print(f"{nom:34s} {p['posts']:6d} {p['likes']:9d} {p['reposts']:7d} {p['replies']:6d} "
              f"{p['likes_mediana']:5.0f} {p['likes_por_post']:9.1f} {p['cuentas']:5d}")
    print("\nSerie semanal (posts con engagement por semana):")
    for p in res["procesos"]:
        sem = " ".join(f"{s}:{n}" for s, n in p["semanas"].items())
        print(f"  {(p['pais'] + ' ' + p['nombre'])[:30]:30s} {sem}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=90)
    ap.add_argument("--proceso", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = interes(a.dias, a.proceso)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        _print(r)
