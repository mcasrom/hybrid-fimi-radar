#!/usr/bin/env python3
"""kpi_alerta.py — KPI "Tiempo hasta la alerta" (time-to-alert).

Para cada cluster EN ALERTA (overall_score >= UMBRAL), mide el tiempo entre el
evento mas antiguo del cluster (MIN(cluster_events.ts)) y el ciclo que lo detecto
(clusters.created_at). Es la latencia de deteccion: cuanto tiempo llevaba la
actividad cuando el radar la marco.

Devuelve n, mediana, p90 y min/max en horas. Honesto: NO es "lead time vs el
mundo" (necesitaria ground truth externo que no tenemos).
"""
import sqlite3
import statistics
import os

DB = "/home/deploy/hybrid-fimi-radar/data/radar.db"
UMBRAL = 40.0  # ANOMALOUS+


def kpi(umbral=UMBRAL):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT c.created_at, MIN(e.ts) FROM clusters c "
        "JOIN cluster_events e ON e.cluster_id = c.id "
        "WHERE c.overall_score >= ? GROUP BY c.id", (umbral,)).fetchall()
    con.close()
    deltas = sorted((ca - mn) / 3600.0 for ca, mn in rows if ca and mn and ca > mn)
    if not deltas:
        return None
    n = len(deltas)
    return {
        "n": n,
        "mediana_h": round(statistics.median(deltas), 2),
        "p90_h": round(deltas[min(n - 1, int(n * 0.9))], 2),
        "min_h": round(deltas[0], 2),
        "max_h": round(deltas[-1], 2),
    }


if __name__ == "__main__":
    print(kpi())
