"""Métricas v2 — validación independiente POR CUENTA con NULO DE ATRIBUTO (Fase 1).

Dos correcciones sobre la Fase 0 (motivadas por los dos bloqueantes encontrados):

1. DILUCIÓN: la Fase 0 media la FRACCIÓN de TODOS los pares (~N^2) -> ~0 en
   clusters grandes. Aquí se mide POR CUENTA: grado de cada cuenta = nº de OTRAS
   cuentas con las que enlaza (tiempo/contenido/url). Un core coordinado da z
   alto aunque el cluster sea grande.

2. NULO INVÁLIDO: la Fase 0 permutaba la ETIQUETA DE AUTOR. Pero para un cluster
   de cuentas distintas (1 evento cada una) esa permutación NO cambia la partición
   -> métrica invariante -> std=0 -> todo satura. El nulo correcto para
   co-ocurrencia es permutar el ATRIBUTO de la dimensión (ts / url / texto) y
   dejar los autores fijos: ¿enlazan estas cuentas MÁS que si sus eventos
   tuvieran ts/url/texto repartidos al azar?

z(a) = (grado_obs(a) - media_nula(a)) / std_nula(a).  z alto = la cuenta coordina
más de lo esperado por azar.  None = saturada (sin varianza).
"""
import random
from collections import defaultdict

from validation.dimensions import _toks

DIMS = ["temporal_sync", "content_similarity", "network_density"]
_NULL_ATTR = {"temporal_sync": "ts", "content_similarity": "text", "network_density": "url"}


def _cross_author_pairs(authors):
    n = len(authors)
    return [(i, j) for i in range(n) for j in range(i + 1, n)
            if authors[i] and authors[j] and authors[i] != authors[j]]


def _linked(cross, values, dim, window=300, thr=0.5):
    """Subconjunto de pares cross-author enlazados por el ATRIBUTO dado."""
    out = []
    for i, j in cross:
        a, b = values[i], values[j]
        if dim == "temporal_sync":
            if a is not None and b is not None and abs(a - b) <= window:
                out.append((i, j))
        elif dim == "network_density":
            if a and b and a == b:
                out.append((i, j))
        else:  # content_similarity: values = frozenset de tokens
            if a and b and len(a & b) / len(a | b) >= thr:
                out.append((i, j))
    return out


def _degrees(authors, pairs):
    neigh = defaultdict(set)
    for i, j in pairs:
        ai, aj = authors[i], authors[j]
        neigh[ai].add(aj)
        neigh[aj].add(ai)
    return {a: len(s) for a, s in neigh.items()}


def _values(events, dim):
    if dim == "temporal_sync":
        return [e.get("ts") for e in events]
    if dim == "network_density":
        return [e.get("url") for e in events]
    return [frozenset(_toks(e.get("text"))) if (e.get("text") or "").strip() else None
            for e in events]


def author_pairs(events, dim, **kw):
    """Pares de AUTORES enlazados (observado), deduplicados."""
    authors = [e.get("author") for e in events]
    cross = _cross_author_pairs(authors)
    pairs = _linked(cross, _values(events, dim), dim, **kw)
    out = set()
    for i, j in pairs:
        a, b = authors[i], authors[j]
        out.add((a, b) if a <= b else (b, a))
    return out


def per_account_z(events, dim, B=100, seed=42, window=300, thr=0.5):
    """(grados_obs, z_por_cuenta, n_saturadas). Nulo = permutación del ATRIBUTO."""
    authors = [e.get("author") for e in events]
    universe = sorted({a for a in authors if a})
    cross = _cross_author_pairs(authors)
    values = _values(events, dim)
    obs = _degrees(authors, _linked(cross, values, dim, window, thr))

    rng = random.Random(seed)
    sums = {a: 0.0 for a in universe}
    sqs = {a: 0.0 for a in universe}
    for _ in range(B):
        sh = values[:]
        rng.shuffle(sh)
        d = _degrees(authors, _linked(cross, sh, dim, window, thr))
        for a in universe:
            v = d.get(a, 0)
            sums[a] += v
            sqs[a] += v * v

    z, sat = {}, 0
    for a in universe:
        m = sums[a] / B
        var = sqs[a] / B - m * m
        std = var ** 0.5 if var > 0 else 0.0
        o = obs.get(a, 0)
        if std <= 1e-9:
            if o > 0:
                z[a] = None
                sat += 1
            else:
                z[a] = 0.0
        else:
            z[a] = (o - m) / std
    return obs, z, sat


def largest_component(nodes, edges):
    """Tamaño de la mayor componente conexa del grafo (nodes, edges) — union-find."""
    parent = {n: n for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        if a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    comp = defaultdict(int)
    for n in nodes:
        comp[find(n)] += 1
    return max(comp.values()) if comp else 0
