#!/usr/bin/env python3
"""verifica.py — contraste con verificadores (posibles bulos), 5-oct-2026.

1. Ingiere Maldita + Newtral (RSS, con UA de navegador) en `verifica_items`
   (dedup por URL, poda >30d). NO entran al corpus ni al grafo (regla 5).
2. Cruza sus titulares (<=14d) con los clusters en banda HIGH/ANOMALOUS:
   solape >=2 tokens distintivos con >=1 de len>=8 (umbral calibrado 5-oct:
   deja 4 parejas tópicas y filtra el débil `reino`/`unido`).
3. Escribe `posible_bulos` (reemplazo por ciclo). El dashboard lo lee para la
   tarjeta `id='posibles-bulos'`.

Es CONTRASTE, no veredicto: no atribuye, no toca score/bandas. Solo lectura
del corpus + escritura en sus dos tablas propias.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DB = os.path.join(ROOT, "data", "radar.db")

FUENTES = [
    ("maldita", "https://maldita.es/feed"),
    ("newtral", "https://www.newtral.es/feed/"),
]
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126 Safari/537.36"}
VENTANA_DIAS = 14
RETENCION_DIAS = 30
SCORE_MIN = 40
TOP_TERMS = 25
MAX_TEXTOS = 40
STOP = set("de la el en y los las del se una por con para al como más pero sus este esta estos estas eso esa ese son fue han hay entre sobre hasta desde donde cuando quien qué cuál cuáles porque pues tan".split())


def toks(s: str) -> list:
    s = (s or "").lower()
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"[^a-z0-9áéíóúñü ]", " ", s)
    return [t for t in s.split() if len(t) > 4 and t not in STOP]


def solape(top: set, titulo: str) -> list:
    """Tokens compartidos entre los términos top del cluster y el titular."""
    return sorted(top & set(toks(titulo)))


def cumple(tokens: list) -> bool:
    return len(tokens) >= 2 and any(len(t) >= 8 for t in tokens)


def banda(sc: float) -> str:
    sc = sc or 0.0
    if sc >= 80:
        return "CRITICAL"
    if sc >= 60:
        return "HIGH"
    if sc >= 40:
        return "ANOMALOUS"
    if sc >= 20:
        return "WATCH"
    return "NORMAL"


def _tablas(con):
    con.execute("CREATE TABLE IF NOT EXISTS verifica_items(url TEXT PRIMARY KEY,"
                " source TEXT, titulo TEXT, published_ts INTEGER, fetched_ts INTEGER)")
    con.execute("CREATE TABLE IF NOT EXISTS posible_bulos(id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " cluster_label TEXT, tema_id TEXT, banda TEXT, verifica_fuente TEXT,"
                " verifica_titulo TEXT, verifica_url TEXT, solape TEXT, cycle_ts INTEGER)")


def actualizar() -> dict:
    import requests
    import feedparser
    con = sqlite3.connect(DB, timeout=60)
    try:
        _tablas(con)
        now = int(time.time())
        for name, url in FUENTES:
            try:
                r = requests.get(url, headers=UA, timeout=25)
                r.raise_for_status()
                feed = feedparser.parse(r.content)
            except Exception as e:
                print(f"verifica: {name} fallo ({e})", file=sys.stderr)
                continue
            for e in (feed.entries or [])[:60]:
                link = (getattr(e, "link", "") or "").strip()
                if not link:
                    continue
                try:
                    import calendar
                    pp = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
                    pub = int(calendar.timegm(pp)) if pp else now
                except Exception:
                    pub = now
                con.execute("INSERT OR IGNORE INTO verifica_items(url,source,titulo,published_ts,fetched_ts)"
                            " VALUES (?,?,?,?,?)",
                            (link, name, (getattr(e, "title", "") or "")[:300], pub, now))
        con.execute("DELETE FROM verifica_items WHERE fetched_ts<?", (now - RETENCION_DIAS * 86400,))
        con.commit()
    finally:
        con.close()
    return contrastar()


def contrastar() -> dict:
    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    try:
        _tablas(con)
        now = int(time.time())
        items = con.execute(
            "SELECT source, titulo, url FROM verifica_items WHERE fetched_ts>?",
            (now - VENTANA_DIAS * 86400,)).fetchall()
        out = []
        cls = con.execute(
            "SELECT tema_id, cluster_label, overall_score FROM clusters"
            " WHERE overall_score>=? ORDER BY overall_score DESC", (SCORE_MIN,)).fetchall()
        for c in cls:
            txts = ["%s %s" % (r[0] or "", r[1] or "") for r in con.execute(
                "SELECT ce.title, ce.text FROM cluster_events ce JOIN clusters cl"
                " ON cl.id=ce.cluster_id WHERE cl.cluster_label=? LIMIT ?",
                (c["cluster_label"], MAX_TEXTOS))]
            bag: Counter = Counter()
            for t in txts:
                bag.update(set(toks(t)))
            top = {w for w, _ in bag.most_common(TOP_TERMS)}
            if not top:
                continue
            for it in items:
                ov = solape(top, it["titulo"])
                if cumple(ov):
                    out.append((c["cluster_label"], c["tema_id"], banda(c["overall_score"]),
                                it["source"], it["titulo"], it["url"], ",".join(ov), now))
        con.execute("DELETE FROM posible_bulos")
        con.executemany(
            "INSERT INTO posible_bulos(cluster_label,tema_id,banda,verifica_fuente,"
            "verifica_titulo,verifica_url,solape,cycle_ts) VALUES (?,?,?,?,?,?,?,?)", out)
        con.commit()
        return {"items": len(items), "clusters": len(cls), "contrastes": len(out)}
    finally:
        con.close()


if __name__ == "__main__":
    r = actualizar()
    print("verifica OK:", r)
