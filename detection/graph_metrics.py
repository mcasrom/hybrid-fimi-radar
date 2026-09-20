#!/usr/bin/env python3
"""Metricas de grafo para el assessment (k-core).

El grafo de coordinacion (cuentas unidas por near-duplicate/same-url/timing) se
resume con el k-core: el mayor subgrafo en el que TODOS los nodos tienen grado
>= k. Un k-core alto indica un nucleo de cuentas mutuamente conectadas (senal de
coordinacion densa); un k bajo indica estructura en estrella o dispersa.

Es DESCRIPTIVO: no entra en el scoring (no cambia el overall). Se muestra como
contexto para el analista.
"""


def adjacency(edges):
    """Grafo no dirigido {nodo: set(vecinos)} a partir de aristas.

    Acepta aristas como dicts (claves 'source'/'target' — formato que devuelve
    `build_edges`) o como secuencias (u, v)."""
    adj = {}
    for e in edges or []:
        try:
            if isinstance(e, dict):
                u, v = e.get("source"), e.get("target")
            else:
                u, v = e[0], e[1]
        except Exception:
            continue
        if not u or not v or u == v:
            continue
        adj.setdefault(u, set()).add(v)
        adj.setdefault(v, set()).add(u)
    return adj


def kcore_subset(adj, nodes):
    """k-core maximo del subgrafo inducido por `nodes`.

    Devuelve (k_max, tamano_del_nucleo). Algoritmo de pelado: para k=1,2,... se
    eliminan los nodos con grado < k dentro del conjunto actual; el ultimo k con
    remanente no vacio es el k-core maximo.
    """
    cur = set(nodes or [])
    if not cur:
        return 0, 0
    best_k, best_size = 0, 0
    k = 0
    while cur:
        k += 1
        changed = True
        while changed:
            changed = False
            for n in list(cur):
                if len(adj.get(n, set()) & cur) < k:
                    cur.discard(n)
                    changed = True
        if cur:
            best_k, best_size = k, len(cur)
        else:
            break
    return best_k, best_size
