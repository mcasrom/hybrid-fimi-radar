"""Modelo nulo — permutación de la ETIQUETA DE AUTOR con seed (determinista).

Respuesta a la pregunta correcta: "¿los autores concretos de este cluster
co-ocurren (en tiempo/contenido/URL) MÁS que si repartiéramos sus propios
eventos al azar entre autores?" Se mantienen ts/text/url intactos y solo se
barajan los autores → nulo limpio y único para las 3 dimensiones.

excess() devuelve (observado, media_nula, std_nula, z). z>0 = más que el azar.
"""
import random


def _shuffled(values, rng):
    v = list(values)
    rng.shuffle(v)
    return v


def excess(metric_fn, events, kind="author", B=200, seed=42):
    obs = metric_fn(events)
    rng = random.Random(seed)
    dist = []
    for _ in range(B):
        ev = [dict(e) for e in events]
        col = _shuffled([e.get(kind) for e in ev], rng)
        for e, v in zip(ev, col):
            e[kind] = v
        dist.append(metric_fn(ev))
    n = len(dist)
    mean = sum(dist) / n
    var = sum((x - mean) ** 2 for x in dist) / n
    std = var ** 0.5
    z = (obs - mean) / (std + 1e-9)
    return obs, mean, std, z
