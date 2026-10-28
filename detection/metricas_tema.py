#!/usr/bin/env python3
"""metricas_tema.py — definiciones CANONICAS por tema (fuente unica de verdad).

Las usan el dashboard, el informe visual y el informe semanal para que las tres
superficies digan exactamente lo mismo. Solo lectura; no calcula scoring.

Vocabulario:
  eventos_tema        = eventos etiquetados al tema (event_temas).
  autores_tema        = autores distintos del tema (corpus).
  cuentas_en_clusters = cuentas implicadas en clusters (DISTINTAS, no suma).
  clusters_tema       = nº de clusters del tema.
  banda_alta          = clusters con overall_score >= 60.
  inicio_ingesta      = primer hallazgo persistido (MIN(fecha) findings);
                        misma fuente que salud_tema._inicio_ingesta.
  dias_operando       = (ahora - inicio_ingesta)/86400.
"""
import sqlite3
import time
from datetime import datetime, timezone

UMBRAL_ALTA = 60


def eventos_tema(con, tema):
    r = con.execute(
        "SELECT COUNT(*) FROM events e JOIN event_temas et ON et.event_id=e.id"
        " WHERE et.tema_id=?", (tema,)).fetchone()
    return r[0] if r else 0


def autores_tema(con, tema):
    r = con.execute(
        "SELECT COUNT(DISTINCT e.author) FROM events e JOIN event_temas et ON et.event_id=e.id"
        " WHERE et.tema_id=?", (tema,)).fetchone()
    return r[0] if r else 0


def fuentes_tema(con, tema):
    r = con.execute(
        "SELECT COUNT(DISTINCT e.source) FROM events e JOIN event_temas et ON et.event_id=e.id"
        " WHERE et.tema_id=?", (tema,)).fetchone()
    return r[0] if r else 0


def cuentas_en_clusters(con, tema):
    r = con.execute(
        "SELECT COUNT(DISTINCT ce.author) FROM cluster_events ce"
        " JOIN clusters c ON c.id=ce.cluster_id WHERE c.tema_id=?", (tema,)).fetchone()
    return r[0] if r else 0


def clusters_tema(con, tema):
    r = con.execute("SELECT COUNT(*) FROM clusters WHERE tema_id=?", (tema,)).fetchone()
    return r[0] if r else 0


def banda_alta(con, tema):
    r = con.execute("SELECT COUNT(*) FROM clusters WHERE tema_id=? AND overall_score>=?",
                    (tema, UMBRAL_ALTA)).fetchone()
    return r[0] if r else 0


def clusters_exclusivos(con, tema):
    """Clusters del tema cuya firma de cuentas (set de autores) NO coincide con la
    de ningún cluster de OTRO tema. Es el número que muestra el dashboard (señal
    ya contada una vez); `clusters_tema` es el bruto por tema_id."""
    from collections import defaultdict
    tema_de = {}
    for r in con.execute("SELECT id, tema_id FROM clusters"):
        tema_de[r[0]] = r[1]
    acc = defaultdict(set)
    for r in con.execute("SELECT cluster_id, author FROM cluster_events"):
        if r[1]:
            acc[r[0]].add(r[1])
    by = defaultdict(list)
    sig = {}
    for cid, s in acc.items():
        sig[cid] = frozenset(s)
        by[sig[cid]].append(cid)
    n = 0
    for cid, s in sig.items():
        if tema_de.get(cid) != tema:
            continue
        if not any(tema_de.get(o) != tema for o in by[s]):
            n += 1
    return n


def inicio_ingesta(con, tema):
    try:
        r = con.execute("SELECT MIN(fecha) FROM findings WHERE tema_id=?", (tema,)).fetchone()
    except sqlite3.Error:
        return None
    return r[0] if r and r[0] else None


def dias_operando(con, tema, ahora=None):
    """Devuelve (días de calendario, inicio_epoch) o (0.0, None).

    Se usan fechas UTC, no bloques de 24 h: 26/10 -> 28/10 son 2 días.
    """
    ini = inicio_ingesta(con, tema)
    if not ini:
        return 0.0, None
    t = time.time() if ahora is None else ahora
    hoy = datetime.fromtimestamp(t, tz=timezone.utc).date()
    inicio_d = datetime.fromtimestamp(ini, tz=timezone.utc).date()
    return float((hoy - inicio_d).days), ini
