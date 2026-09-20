#!/usr/bin/env python3
"""Persistencia de campanas entre ciclos (linaje de clusters).

Los `cluster_label` NO son estables entre ciclos (se regeneran cada 6 h). Para
poder SEGUIR una campana en el tiempo (y no solo ver instantaneas), este modulo
enlaza cada cluster con el del ciclo anterior de maximo solapamiento de miembros
(cuentas + URLs), por indice de Jaccard. Si el solapamiento supera
`lineage.jaccard_min` (config, def. 0.5), hereda el `lineage_id` y suma un ciclo;
si no, arranca una linea nueva.

Diseno: el ciclo anterior se lee ANTES de borrar los clusters (los miembros viven
en `cluster_events`), y se escribe `cluster_lineage` (una fila por cluster del
ciclo actual). No se guarda historico largo: solo el ultimo ciclo, que es el que
necesita el siguiente para comparar. No decide nada: es descriptivo.
"""
import time


def member_keys(author, url):
    """Claves de identidad de un miembro: cuenta y/o URL (normalizadas)."""
    keys = set()
    a = (author or "").strip().lower()
    u = (url or "").strip().lower()
    if a:
        keys.add("a:" + a)
    if u:
        keys.add("u:" + u)
    return keys


def read_prev(conn, tema):
    """Miembros y linaje del ciclo anterior (llamar ANTES de borrar clusters).

    Devuelve (prev_members, prev_lineage):
      prev_members: {cluster_label: set(keys)}
      prev_lineage: {cluster_label: (lineage_id, first_seen, n_ciclos)}
    """
    prev_members = {}
    rows = conn.execute(
        "SELECT c.cluster_label AS label, ce.author AS author, ce.url AS url "
        "FROM cluster_events ce JOIN clusters c ON c.id = ce.cluster_id "
        "WHERE c.tema_id = ?", (tema,)).fetchall()
    for r in rows:
        prev_members.setdefault(r["label"], set()).update(
            member_keys(r["author"], r["url"]))
    prev_lineage = {}
    for r in conn.execute(
        "SELECT cluster_label, lineage_id, first_seen, n_ciclos "
        "FROM cluster_lineage WHERE tema_id = ?", (tema,)):
        prev_lineage[r["cluster_label"]] = (r["lineage_id"], r["first_seen"], r["n_ciclos"])
    return prev_members, prev_lineage


def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / len(a | b)


def assign(prev_members, prev_lineage, new_members, jaccard_min=0.5, cycle_ts=None):
    """Asigna linaje a cada cluster nuevo.

    Devuelve {cluster_label: (lineage_id, first_seen, n_ciclos, jaccard)}.
    """
    cycle_ts = int(cycle_ts or time.time())
    out = {}
    for label, members in new_members.items():
        best_label, best_j = None, 0.0
        for plabel, pmembers in prev_members.items():
            j = jaccard(members, pmembers)
            if j > best_j:
                best_j, best_label = j, plabel
        if best_label is not None and best_j >= jaccard_min and best_label in prev_lineage:
            lid, fseen, ncyc = prev_lineage[best_label]
            out[label] = (lid, fseen, ncyc + 1, round(best_j, 3))
        else:
            out[label] = (f"{label}@{cycle_ts}", cycle_ts, 1, round(best_j, 3))
    return out


def write(conn, tema, rows, cycle_ts):
    """Reemplaza el linaje del tema por el del ciclo actual."""
    conn.execute("DELETE FROM cluster_lineage WHERE tema_id = ?", (tema,))
    for label, (lid, fseen, ncyc, j) in rows.items():
        conn.execute(
            "INSERT INTO cluster_lineage (tema_id, cluster_label, lineage_id, first_seen,"
            " last_seen, n_ciclos, jaccard, cycle_ts) VALUES (?,?,?,?,?,?,?,?)",
            (tema, label, lid, fseen, cycle_ts, ncyc, j, cycle_ts))
    conn.commit()


def load_map(conn):
    """Mapa {(tema_id, cluster_label): (first_seen, n_ciclos, jaccard)} para la UI."""
    out = {}
    for r in conn.execute(
            "SELECT tema_id, cluster_label, first_seen, n_ciclos, jaccard FROM cluster_lineage"):
        out[(r["tema_id"], r["cluster_label"])] = (r["first_seen"], r["n_ciclos"], r["jaccard"])
    return out
