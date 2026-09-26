#!/usr/bin/env python3
"""kpi_alerta.py — KPIs de alerta (latencia interna + antigüedad hacia delante).

Tres medidas honestas y distintas, que NO son "lead time frente al mundo"
(eso exigiría verdad de referencia externa que no tenemos):

1. `antiguedad` (hacia delante): para cada linaje ACTUALMENTE en banda
   ANOMALOUS+, cuánto tiempo ha pasado desde que cruzó el umbral por primera
   vez (`cluster_lineage.first_band_ts`, instrumentado desde 26-Sep-2026).
   Para linajes anteriores a la instrumentación, `first_band_ts` se inicializa
   a `first_seen` (aproximación = cota superior; documentado).
2. `latencia` (interna): tiempo entre el evento más antiguo de un cluster en
   alerta y el ciclo que lo detectó (`created_at - MIN(ts)`). Mide que el
   cluster ARRASTRA contenido que llevaba días circulando, NO que el radar
   tardara en verlo.
3. `recencia`: porcentaje de eventos del cluster alerta que son de los últimos
   7 días. Si es bajo, el cluster es sobre todo memoria, no actividad viva.

La causa de la latencia alta está documentada: `load_sqlite` alimenta el
pipeline con TODO el corpus del tema, sin ventana temporal, así que la
pertenencia a un cluster incluye el histórico de sus cuentas.
"""
import os
import sqlite3
import statistics
import time

DB = "/home/deploy/hybrid-fimi-radar/data/radar.db"
UMBRAL = 40.0  # ANOMALOUS+
VENTANA_REC_D = 7


def _pctl(vals, q):
    vals = sorted(vals)
    n = len(vals)
    if not n:
        return None
    return vals[min(n - 1, int(n * q))]


def _med(vals):
    return round(statistics.median(vals), 2) if vals else None


def kpi(umbral=UMBRAL, db=DB):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    now = int(time.time())

    # 1) Latencia interna (legacy): created_at - MIN(ts) por cluster en alerta.
    _r = con.execute(
        "SELECT c.created_at AS ca, MIN(e.ts) AS mn FROM clusters c "
        "JOIN cluster_events e ON e.cluster_id = c.id "
        "WHERE c.overall_score >= ? GROUP BY c.id", (umbral,)).fetchall()
    lat = [(r["ca"] - r["mn"]) / 3600.0 for r in _r if r["ca"] and r["mn"] and r["ca"] > r["mn"]]

    # 2) Antigüedad de la alerta (hacia delante) + rampa (1ª observación → alerta).
    _a = con.execute(
        "SELECT cl.first_seen AS fs, cl.first_band_ts AS fb FROM cluster_lineage cl "
        "JOIN clusters c ON c.tema_id = cl.tema_id AND c.cluster_label = cl.cluster_label "
        "WHERE c.overall_score >= ? AND cl.first_band_ts IS NOT NULL", (umbral,)).fetchall()
    ages = [(now - r["fb"]) / 3600.0 for r in _a if r["fb"] and now >= r["fb"]]
    ramp = [(r["fb"] - r["fs"]) / 3600.0 for r in _a
            if r["fb"] and r["fs"] and r["fb"] >= r["fs"]]

    # 3) Recencia: fracción de eventos de los últimos 7 días por cluster alerta.
    _rec = con.execute(
        "SELECT c.id, COUNT(e.ts) AS n, "
        "SUM(CASE WHEN e.ts >= ? THEN 1 ELSE 0 END) AS n7 "
        "FROM clusters c JOIN cluster_events e ON e.cluster_id = c.id "
        "WHERE c.overall_score >= ? GROUP BY c.id", (now - VENTANA_REC_D * 86400, umbral)).fetchall()
    fracs = [100.0 * r["n7"] / r["n"] for r in _rec if r["n"]]
    con.close()

    if not lat and not ages:
        return None

    out = {
        "n": len(lat),  # compat: nº clusters en alerta
        "mediana_h": _med(lat),
        "p90_h": round(_pctl(lat, 0.9), 2) if lat else None,
        "min_h": round(min(lat), 2) if lat else None,
        "max_h": round(max(lat), 2) if lat else None,
        "antiguedad": {
            "n": len(ages),
            "mediana_h": _med(ages),
            "p90_h": round(_pctl(ages, 0.9), 2) if ages else None,
        },
        "rampa": {
            "n": len(ramp),
            "mediana_h": _med(ramp),
        },
        "recencia": {
            "n": len(fracs),
            "mediana_pct": round(statistics.median(fracs), 1) if fracs else None,
        },
    }
    return out


if __name__ == "__main__":
    print(kpi())
