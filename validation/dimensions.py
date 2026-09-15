"""Dimensiones independientes (spike v2). Métrica POR UMBRAL (fracción de pares
cross-author que co-ocurren), no media → evita la dilución.

+ `intra_ratio`: de los pares que co-ocurren en tiempo, qué fracción es del
MISMO autor (eco intra-cuenta) → sirve para penalizar la falsa "coordinación".
"""
import itertools
import re

_WORD = re.compile(r"[0-9a-záéíóúñü]{3,}")
_CACHE = {}


def _toks(text):
    t = _CACHE.get(text)
    if t is None:
        t = set(_WORD.findall((text or "").lower()))
        _CACHE[text] = t
    return t


def temporal_sync(events, window=300):
    """Fracción de pares de autores DISTINTOS con |Δt| <= window seg."""
    ev = [e for e in events if e.get("ts") is not None]
    pairs = tight = 0
    for a, b in itertools.combinations(ev, 2):
        if a.get("author") == b.get("author"):
            continue
        pairs += 1
        if abs(a["ts"] - b["ts"]) <= window:
            tight += 1
    return (tight / pairs) if pairs else 0.0


def content_similarity(events, thr=0.5):
    """Fracción de pares de autores DISTINTOS con Jaccard de tokens >= thr."""
    ev = [e for e in events if (e.get("text") or "").strip()]
    pairs = hit = 0
    for a, b in itertools.combinations(ev, 2):
        if a.get("author") == b.get("author"):
            continue
        ta, tb = _toks(a["text"]), _toks(b["text"])
        if not ta or not tb:
            continue
        pairs += 1
        if len(ta & tb) / len(ta | tb) >= thr:
            hit += 1
    return (hit / pairs) if pairs else 0.0


def network_density(events):
    """Fracción de pares de autores DISTINTOS que comparten la MISMA url."""
    pairs = hit = 0
    for a, b in itertools.combinations(events, 2):
        if a.get("author") == b.get("author"):
            continue
        pairs += 1
        if a.get("url") and a["url"] == b.get("url"):
            hit += 1
    return (hit / pairs) if pairs else 0.0


def intra_ratio(events, window=300):
    """De los pares que co-ocurren en tiempo, fracción del MISMO autor (eco intra-cuenta)."""
    same = tot = 0
    for a, b in itertools.combinations(events, 2):
        if a.get("ts") is None or b.get("ts") is None:
            continue
        if abs(a["ts"] - b["ts"]) <= window:
            tot += 1
            if a.get("author") == b.get("author"):
                same += 1
    return (same / tot) if tot else 0.0


# dimension -> (metric_fn, null_kind). Nulo unificado: permutación de autor.
DIMS = {
    "temporal_sync": (temporal_sync, "author"),
    "content_similarity": (content_similarity, "author"),
    "network_density": (network_density, "author"),
}
