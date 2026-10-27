#!/usr/bin/env python3
"""Sonda de salud de fuentes (feed vivo) — distinto de 'eventos en 7 d'.

Uso:
    .venv/bin/python detection/probe_feeds.py [--days 30] [--json]

No modifica nada: descarga cada feed y comprueba HTTP, nº de items y fecha
del último. Escribe data/feed_health.json.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
from datetime import datetime, timezone, timedelta

import feedparser
import requests
import yaml

CFG = "/home/deploy/hybrid-fimi-radar/config.yaml"
OUT = "/home/deploy/hybrid-fimi-radar/data/feed_health.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
# UA de collectors/capture.py: melillahoy 403 a los dos anteriores pero lo sirve
# a este, así la sonda debe probarlo para no marcar como caído un feed vivo.
UA_CAPTURE = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ECR-capture/0.1"


def last_date(entries):
    for e in entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def probe(f, cutoff):
    name, url = f.get("nombre"), f.get("url")
    rec = {"nombre": name, "url": url, "tipo": f.get("tipo", "rss"), "http": None,
           "items": 0, "ultimo": None, "estado": "error"}
    if not url:
        return rec
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=12, allow_redirects=True)
        if r.status_code == 403:
            r = requests.get(url, headers={"User-Agent": "Feedly/1.0 (+http://www.feedly.com/fetcher.html)"}, timeout=12, allow_redirects=True)
        if r.status_code == 403:
            r = requests.get(url, headers={"User-Agent": UA_CAPTURE}, timeout=12, allow_redirects=True)
        rec["http"] = r.status_code
        d = feedparser.parse(r.content)
        if r.status_code == 403:
            d = feedparser.parse(url, agent=UA_CAPTURE)
            if d.entries:
                rec["http"] = 200
        if r.status_code in (301, 302, 303, 307, 308):
            d2 = feedparser.parse(url, agent=UA_CAPTURE)
            if d2.entries:
                d = d2
                rec["http"] = 200
        rec["items"] = len(d.entries)
        dt = last_date(d.entries)
        if dt:
            rec["ultimo"] = dt.strftime("%Y-%m-%d")
        if rec["http"] != 200:
            rec["estado"] = "http_error"
        elif rec["items"] == 0:
            rec["estado"] = "sin_items"
        elif dt and dt < cutoff:
            rec["estado"] = "parado"
        else:
            rec["estado"] = "ok"
    except Exception as e:
        rec["estado"] = "error"
        rec["error"] = str(e)[:120]
    return rec


def probe_tg(ch, cutoff):
    rec = {"nombre": f"telegram:{ch}", "url": f"https://t.me/s/{ch}", "tipo": "telegram",
           "http": None, "items": None, "ultimo": None, "estado": "error"}
    try:
        r = requests.get(rec["url"], headers={"User-Agent": UA}, timeout=12)
        rec["http"] = r.status_code
        dates = re.findall(r'datetime="([^"]+)"', r.text)
        if dates:
            rec["ultimo"] = dates[-1][:10]
            rec["estado"] = "ok" if dates[-1][:10] >= cutoff.strftime("%Y-%m-%d") else "parado"
        else:
            rec["estado"] = "sin_items"
    except Exception as e:
        rec["error"] = str(e)[:120]
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    cfg = yaml.safe_load(open(CFG, encoding="utf-8"))
    cutoff = datetime.now(timezone.utc) - timedelta(days=a.days)
    feeds = [f for f in cfg.get("feeds", []) if f.get("url")]
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        rows = list(ex.map(lambda f: probe(f, cutoff), feeds))
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        rows += list(ex.map(lambda ch: probe_tg(ch, cutoff), cfg.get("telegram_canales", [])))

    resumen = {"feeds": len(rows)}
    for k in ("ok", "parado", "sin_items", "http_error", "error"):
        resumen[k] = sum(1 for r in rows if r["estado"] == k)
    data = {"generado": datetime.now(timezone.utc).isoformat(), "dias": a.days,
            "resumen": resumen, "fuentes": rows}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if a.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print("resumen:", resumen)
        for r in rows:
            if r["estado"] != "ok":
                print(f"  {r['estado']:10s} {r['nombre']:28s} http={r['http']} items={r['items']} ultimo={r['ultimo']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
