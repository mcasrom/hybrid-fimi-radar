#!/usr/bin/env python3
"""Persistencia de hallazgos positivos e informes diarios.

Los resultados del radar (narrativas amplificadas, clusters, cascadas) se
persisten en la tabla `findings` con fecha. Cada ciclo solo inserta hallazgos
NUEVOS (evita duplicados del mismo día). Al final del día se genera un
`daily_reports` con el resumen.

Así los "resultados positivos" NO se pierden cuando el tema deja de ser
noticia: quedan en el historial consultable.
"""
import json
import sqlite3
from datetime import datetime, timezone


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _epoch_day():
    return int(datetime.now(timezone.utc).timestamp())


def persist_findings(conn, narratives, clusters=None, cascades=None):
    """Persiste los hallazgos del ciclo, sin duplicar los del mismo día.

    Devuelve (insertados, total_acumulado).
    """
    hoy = _today()
    inserted = 0

    def ya_existe(titulo, tipo, fecha):
        row = conn.execute(
            "SELECT 1 FROM findings WHERE titulo=? AND tipo=? AND date(fecha, 'unixepoch')=?",
            (titulo[:200], tipo, fecha)).fetchone()
        return row is not None

    # narrativas amplificadas
    for n in narratives or []:
        titulo = n.get("seed", "")
        if not titulo or ya_existe(titulo, "amplificacion_narrativa", hoy):
            continue
        conn.execute(
            "INSERT INTO findings (fecha, tipo, titulo, detalle, n_sources, n_events,"
            " window_hours, fuentes, intensidad, url) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (_epoch_day(), "amplificacion_narrativa", titulo,
             f"{n['n_events']} eventos, {n['n_sources']} fuentes, ventana {n.get('window_hours',0)}h",
             n.get("n_sources", 0), n.get("n_events", 0), n.get("window_hours", 0),
             json.dumps(n.get("source_names", []), ensure_ascii=False),
             n.get("n_events", 0) * n.get("n_sources", 0) / max(n.get("window_hours", 1) + 1, 0.5),
             ""))
        inserted += 1

    # clusters (si los hay)
    for c in clusters or []:
        titulo = c.get("cluster", "")
        if not titulo or ya_existe(titulo, "cluster", hoy):
            continue
        conn.execute(
            "INSERT INTO findings (fecha, tipo, titulo, detalle, n_sources, n_events,"
            " window_hours, fuentes, intensidad, url) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (_epoch_day(), "cluster", titulo,
             f"score {c.get('overall_score',0):.0f}/100, {c.get('accounts',0)} cuentas",
             c.get("accounts", 0), c.get("events", 0), 0,
             json.dumps(c.get("evidence", {}), ensure_ascii=False),
             c.get("overall_score", 0), ""))
        inserted += 1

    # cascadas
    for c in cascades or []:
        titulo = c.get("seed_text", "")
        if not titulo or ya_existe(titulo, "cascada", hoy):
            continue
        conn.execute(
            "INSERT INTO findings (fecha, tipo, titulo, detalle, n_sources, n_events,"
            " window_hours, fuentes, intensidad, url) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (_epoch_day(), "cascada", titulo,
             f"{c.get('n_accounts',0)} cuentas, {c.get('n_events',0)} eventos",
             c.get("n_accounts", 0), c.get("n_events", 0), c.get("time_span_s", 0) / 3600,
             "[]", c.get("speed_accounts_hour", 0), ""))
        inserted += 1

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
    return inserted, total


def build_daily_report(conn, narratives, clusters):
    """Genera/actualiza el informe diario con los hallazgos del día."""
    hoy = _today()
    findings_hoy = conn.execute(
        "SELECT * FROM findings WHERE date(fecha, 'unixepoch')=?", (hoy,)).fetchall()

    lines = []
    lines.append(f"# Informe diario FIMI Radar — {hoy}")
    lines.append("")
    lines.append(f"- Hallazgos hoy: {len(findings_hoy)}")
    lines.append(f"- Narrativas amplificadas hoy: {len(narratives)}")
    lines.append(f"- Clusters hoy: {len(clusters)}")
    lines.append("")
    lines.append("## Hallazgos persistidos hoy")
    lines.append("")
    if findings_hoy:
        for f in findings_hoy:
            lines.append(f"- [{f[2]}] {f[3]} — {f[4]}")
    else:
        lines.append("Sin hallazgos nuevos hoy. (La ausencia de señal es un resultado válido.)")
    lines.append("")
    lines.append("_Generado automáticamente por el cron 6h._")

    resumen = "\n".join(lines)
    conn.execute(
        "INSERT OR REPLACE INTO daily_reports (fecha, resumen, n_findings, created_at)"
        " VALUES (?,?,?,?)",
        (hoy, resumen, len(findings_hoy), int(datetime.now(timezone.utc).timestamp())))
    conn.commit()
    return resumen


def persist_findings_from_run(conn, narratives, summary, cascades):
    """Wrapper: persiste narrativas + clusters (del summary) + cascadas."""
    clusters_list = []
    for label, s in (summary or {}).items():
        clusters_list.append({
            "cluster": label, "overall_score": s.get("overall_score", 0),
            "accounts": s.get("accounts", 0), "events": s.get("events", 0),
            "evidence": s.get("evidence", {}),
        })
    return persist_findings(conn, narratives, clusters_list, cascades)


def detectar_sostenidas(conn, min_dias=3):
    """Detecta narrativas sostenidas: el mismo título (o muy similar) ha sido
    hallazgo en >= min_dias días distintos. Señal de campaña sostenida, no de
    titular suelto.

    Devuelve lista de dicts: {titulo, dias, fechas, tipo}.
    """
    rows = conn.execute(
        "SELECT DISTINCT date(fecha,'unixepoch') as d, substr(titulo,1,60) as t, tipo"
        " FROM findings WHERE tipo IN ('amplificacion_narrativa','cascada')"
    ).fetchall()
    # agrupar por título normalizado (prefijo 40 chars sin puntuación)
    import re
    from collections import defaultdict
    dias_por_titulo = defaultdict(set)
    tipo_por_titulo = {}
    for d, t, tipo in rows:
        key = re.sub(r"[^a-z0-9áéíóúñü ]", "", t.lower())[:40]
        if key.strip():
            dias_por_titulo[key].add(d)
            tipo_por_titulo[key] = tipo
    sostenidas = []
    for key, dias in dias_por_titulo.items():
        if len(dias) >= min_dias:
            sostenidas.append({
                "titulo": key,
                "dias": len(dias),
                "fechas": sorted(dias),
                "tipo": tipo_por_titulo.get(key, ""),
            })
    sostenidas.sort(key=lambda x: -x["dias"])
    return sostenidas
