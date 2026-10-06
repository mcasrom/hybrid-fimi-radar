"""match_cache.py — caché persistente de matches keyword↔evento entre ciclos.

`salud_keywords.analizar(14)` re-matcheaba ~50k eventos × ~150 keywords en cada
ciclo (~2:45, 150 MB). Los textos de los eventos son inmutables, así que el
resultado por (event_id, cfg) es estable: se persiste en la tabla `match_cache`
y cada ciclo solo se calculan los eventos nuevos.

Invalidación: hash sha1 de (keywords por tema + filtros + contextos). Si la
config cambia, se recalcula todo y se podan las filas de cfgs viejas.
Poda: filas de eventos fuera de la ventana actual (la ventana desliza).
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter


def hash_cfg(por_tema, filtros, contextos) -> str:
    """Huella determinista de la config de matching."""
    def norm_palabras(pals):
        return sorted({(p or "").strip().lower() for p in (pals or []) if (p or "").strip()})

    blob = {
        "temas": {t: norm_palabras(p) for t, p in sorted((por_tema or {}).items())},
        "filtros": {t: norm_palabras(f) for t, f in sorted((filtros or {}).items())},
        "contextos": {t: norm_palabras(c) for t, c in sorted((contextos or {}).items())},
    }
    return hashlib.sha1(json.dumps(blob, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def ensure(con) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS match_cache("
                "event_id INTEGER PRIMARY KEY, cfg TEXT NOT NULL, "
                "temas TEXT NOT NULL, kws TEXT NOT NULL)")


def cargar(con, cfg, event_ids):
    """Devuelve ({eid: set(temas)}, Counter(palabra)) para los eventos cacheados."""
    hit_temas, hit_kw = {}, Counter()
    ids = list(dict.fromkeys(event_ids))
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        ph = ",".join("?" * len(chunk))
        for eid, temas_j, kws_j in con.execute(
                "SELECT event_id, temas, kws FROM match_cache"
                " WHERE cfg=? AND event_id IN (%s)" % ph,
                [cfg] + chunk):
            try:
                ts = set(json.loads(temas_j or "[]"))
                ks = set(json.loads(kws_j or "[]"))
            except (ValueError, TypeError):
                continue
            hit_temas[eid] = ts
            hit_kw.update(ks)
    return hit_temas, hit_kw


def guardar(con, cfg, hits) -> int:
    """hits: {eid: (set_temas, set_palabras)}. Devuelve nº de filas escritas."""
    rows = [(eid, cfg, json.dumps(sorted(ts), ensure_ascii=False),
             json.dumps(sorted(ks), ensure_ascii=False))
            for eid, (ts, ks) in hits.items()]
    if not rows:
        return 0
    con.executemany(
        "INSERT OR REPLACE INTO match_cache(event_id,cfg,temas,kws) VALUES (?,?,?,?)", rows)
    con.commit()
    return len(rows)


def podar(con, cfg, valid_ids) -> int:
    """Borra filas de otras cfgs y de eventos fuera de la ventana. Devuelve nº borrado."""
    n = 0
    cur = con.execute("DELETE FROM match_cache WHERE cfg!=?", (cfg,))
    n += cur.rowcount or 0
    valid = list(dict.fromkeys(valid_ids))
    if valid:
        con.execute("CREATE TEMP TABLE IF NOT EXISTS _mc_keep(eid INTEGER PRIMARY KEY)")
        con.execute("DELETE FROM _mc_keep")
        for i in range(0, len(valid), 500):
            con.executemany("INSERT OR IGNORE INTO _mc_keep(eid) VALUES (?)",
                            [(e,) for e in valid[i:i + 500]])
        cur = con.execute("DELETE FROM match_cache WHERE cfg=? AND event_id NOT IN"
                          " (SELECT eid FROM _mc_keep)", (cfg,))
        n += cur.rowcount or 0
        con.execute("DROP TABLE _mc_keep")
    else:
        cur = con.execute("DELETE FROM match_cache WHERE cfg=?", (cfg,))
        n += cur.rowcount or 0
    con.commit()
    return n
