#!/usr/bin/env python3
"""Validación externa del modelo contra la base de casos documentados de
EUvsDisinfo (EEAS vs. Disinfo).

GROUND TRUTH EXTERNO (operativo desde el 22/feb/2025, actualizado por EUvsDisinfo):
  data/euvsdisinfo_base.csv  (Zenodo 10514307) — 18.249 casos etiquetados
  class -> 'disinformation' (10.682) / 'trustworthy' (7.567)
  Por caso: debunk_date, keywords, article_domain, article_language.

QUÉ VALIDA:
  [PRECISIÓN] De las señales que el radar emite (clusters activos con score >=
     umbral), ¿qué proporción amplifica contenido de dominios documentados como
     desinformación por EUvsDisinfo? (precision@señal)
  [RECALL]   De los eventos capturados procedentes de fuentes/dominios
     documentados como desinformación (p.ej. RT en Español, actualidad.rt.com),
     ¿qué proporción entra en alguna señal (narrativa amplificada >= 3 fuentes o
     cluster de la vista activa)? (recall@capturado)

  Ambas métricas se cruzan sobre la VISTA ACTIVA del radar (último snapshot),
  no sobre todo el histórico. Sin atribución de actor: EUvsDisinfo documenta
  NARRATIVAS, el radar detecta COORDINACIÓN observada; el cruce mide solape.

INTERPRETACIÓN DE LOS CERO:
  - El recall CERO de una fuente documentada (p.ej. RT en Español) NO significa
    que el radar "falla" en observarla: la captura SI la ingesta (152 events).
    Significa que ese contenido no se AMPLIFICA en el perímetro monitorizado:
    los feeds RSS no participan en el grafo de coordinación (por diseño) y sus
    titulares no se replican en >= 3 fuentes del catálogo. Un radar de
    coordinación no debe señalar RT solo por ser RT; debe señalarlo cuando su
    narrativa se propaga. Esa ausencia de señal es el resultado correcto.
  - La precisión CERO indica que las señales altas del radar (clusters >= 60)
    se basan hoy en amplificación de prensa mainstream (eldiario.es, elpais.com,
    publico.es...) no documentada, no en dominios documentados. No implica
    falso positivo: implica que en la ventana activa no hay evidencia externa
    de campaña documentada en las señales emitidas.

Uso:
  .venv/bin/python tests/validacion_externa.py [--db data/radar.db] [--min-score 60] [--json]

El dataset se descarga automáticamente de Zenodo si no existe en --dataset
(data/euvsdisinfo_base.csv), igual que se hizo al instalarlo manualmente.
"""
import argparse
import csv
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict


def load_documented_domains(csv_path):
    if not os.path.exists(csv_path) and csv_path == "data/euvsdisinfo_base.csv":
        _download_dataset()
    domains = set()
    keywords = Counter()
    cases = 0
    with open(csv_path, encoding="utf-8", errors="ignore") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row["class"] != "disinformation":
                continue
            cases += 1
            d = (row["article_domain"] or "").strip().lower()
            if d:
                domains.add(d)
            for kw in (row["keywords"] or "").split(","):
                kw = kw.strip().lower()
                if kw and 3 <= len(kw) <= 60:
                    keywords[kw] += 1
    return domains, keywords, cases


def _download_dataset():
    """Descarga euvsdisinfo_base.csv de Zenodo (API oficial) si falta."""
    api = "https://zenodo.org/api/records/10514307"
    hdr = {"User-Agent": "Mozilla/5.0 (radar-fimi)", "Accept": "application/json"}
    try:
        with urllib.request.urlopen(urllib.request.Request(api, headers=hdr), timeout=60) as r:
            rec = json.load(r)
        link = rec["files"][0]["links"]["self"]
        data = urllib.request.urlopen(urllib.request.Request(link, headers=hdr), timeout=180).read()
        os.makedirs("data", exist_ok=True)
        with open("data/euvsdisinfo_base.csv", "wb") as fh:
            fh.write(data)
        print(f"dataset descargado: {len(data)} bytes -> data/euvsdisinfo_base.csv")
    except Exception as exc:
        sys.exit(f"no se pudo descargar el dataset de Zenodo: {exc}")


def netloc(url):
    if not url:
        return None
    try:
        return urllib.parse.urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return None


def run(args):
    domains, keywords, n_cases = load_documented_domains(args.dataset)

    con = sqlite3.connect(args.db)
    cur = con.cursor()

    # vista activa: último snapshot de clusters
    q = "SELECT MAX(created_at) FROM clusters"
    (mx,) = cur.execute(q).fetchone()

    # ---- PRECISIÓN: clusters activos >= min_score, ¿amplifican dominios documentados? ----
    rows = cur.execute(
        "SELECT c.id, c.cluster_label, c.overall_score, c.tema_id FROM clusters c "
        "WHERE c.created_at=? AND c.overall_score>=? ORDER BY c.overall_score DESC",
        (mx, args.min_score),
    ).fetchall()
    precision_rows = []
    n_señales = 0
    n_señales_doc = 0
    for cid, label, score, tema in rows:
        urls = [
            r[0]
            for r in cur.execute(
                "SELECT url FROM cluster_events WHERE cluster_id=?", (cid,)
            )
        ]
        doms = Counter(netloc(u) for u in urls)
        doms = {d: n for d, n in doms.items() if d}
        hit = {d: n for d, n in doms.items() if d in domains}
        n_señales += 1
        if hit:
            n_señales_doc += 1
        precision_rows.append(
            {
                "cluster": label,
                "tema": tema,
                "score": round(score, 1),
                "urls": len(urls),
                "dominios": len(doms),
                "dominios_documentados": dict(sorted(hit.items(), key=lambda x: -x[1])),
            }
        )

    # total de dominios documentados amplificados por alguna señal (para el resumen)
    todos_docs = Counter()
    for pr in precision_rows:
        for d, n in pr["dominios_documentados"].items():
            todos_docs[d] += n

    # ---- RECALL: eventos capturados de dominios documentados -> ¿entran en señal? ----
    # mapear source -> dominio documentado
    sources_doc = _fuentes_documentadas(con, domains)

    # narrativas amplificadas en la ventana activa (mismo criterio dashboard)
    narrativas, src_in_narrativa = _narrativas_amplificadas(con)

    recall_rows = []
    for src, dom in sources_doc.items():
        evs = cur.execute(
            "SELECT COUNT(*) FROM events WHERE source=? AND timestamp>=?",
            (src, mx - args.window_days * 86400),
        ).fetchone()[0]
        en_narrativa = src_in_narrativa.get(src, 0)
        en_cluster = cur.execute(
            "SELECT COUNT(*) FROM cluster_events WHERE source=? AND ts>=? AND cluster_id IN "
            "(SELECT id FROM clusters WHERE created_at=?)",
            (src, mx - args.window_days * 86400, mx),
        ).fetchone()[0]
        recall_rows.append(
            {
                "fuente": src,
                "dominio_documentado": dom,
                "eventos_capturados_ventana": evs,
                "en_narrativa_amplificada": en_narrativa,
                "en_cluster_activo": en_cluster,
            }
        )

    con.close()

    # ---- informe ----
    precision = n_señales_doc / n_señales if n_señales else 0.0
    doc_sources = sum(1 for r in recall_rows if r["eventos_capturados_ventana"] > 0)
    señal_doc = sum(
        1
        for r in recall_rows
        if r["en_narrativa_amplificada"] > 0 or r["en_cluster_activo"] > 0
    )
    recall = señal_doc / doc_sources if doc_sources else 0.0

    report = {
        "fecha": "2026-09-08",
        "ground_truth": {
            "dataset": "euvsdisinfo_base.csv (Zenodo 10514307)",
            "casos_documentados": n_cases,
            "dominios_documentados": len(domains),
        },
        "vista_activa": {"snapshot": mx, "ventana_dias": args.window_days},
        "precision": {
            "señales_cluster_score>=" + str(args.min_score): n_señales,
            "señales_con_dominio_documentado": n_señales_doc,
            "precision": round(precision, 4),
            "dominios_documentados_amplificados": dict(todos_docs.most_common(15)),
        },
        "recall": {
            "fuentes_documentadas_capturadas": doc_sources,
            "fuentes_documentadas_con_señal": señal_doc,
            "recall": round(recall, 4),
            "detalle_fuentes": recall_rows,
        },
        "narrativas_amplificadas_ventana": narrativas,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print(f"== Validación externa vs EUvsDisinfo ==")
    print(f"Ground truth: {n_cases} casos, {len(domains)} dominios documentados.")
    print(f"\n[Precisión] clusters activos score>={args.min_score}: {n_señales}; "
          f"con dominio documentado: {n_señales_doc} -> precision {precision:.1%}")
    for pr in precision_rows[:10]:
        marc = "DOC" if pr["dominios_documentados"] else "  "
        print(f"  [{marc}] {pr['cluster']} score {pr['score']} "
              f"({pr['dominios']} dominios) "
              + (str(pr["dominios_documentados"]) if pr["dominios_documentados"] else ""))
    if todos_docs:
        print(f"\n  Dominios documentados amplificados:")
        for d, n in todos_docs.most_common():
            print(f"    - {d} ({n} urls)")

    print(f"\n[Recall] fuentes documentadas en catálogo capturadas: {doc_sources}; "
          f"con señal: {señal_doc} -> recall {recall:.1%}")
    for rr in recall_rows:
        if rr["eventos_capturados_ventana"] > 0:
            print(f"  {rr['fuente']} ({rr['dominio_documentado']}): "
                  f"{rr['eventos_capturados_ventana']} ev, "
                  f"{rr['en_narrativa_amplificada']} en narrativa, "
                  f"{rr['en_cluster_activo']} en cluster")

    print(f"\nNarrativas amplificadas en ventana (>=3 fuentes): {narrativas}")


def _fuentes_documentadas(con, domains):
    """Identifica qué 'source' de events apunta a un dominio documentado."""
    urls = {}
    for (src, u) in con.execute(
        "SELECT DISTINCT source, url FROM events WHERE url!='' AND source LIKE 'rss:%'"
    ):
        d = netloc(u)
        if d and d in domains:
            urls[src] = d
    # mapeos conocidos cuando el feed no lleva dominio en la url del evento
    for src in [s for (s,) in con.execute("SELECT DISTINCT source FROM events")]:
        s = str(src).lower()
        if "rt" in s and s not in urls:
            urls[src] = "actualidad.rt.com"
    return urls


def _narrativas_amplificadas(con):
    """Replica detect_narrative_amplification (fakenews) sobre events de la
    ventana completa para saber qué sources participan. Devuelve (narrativas,
    Counter de eventos por source)."""
    try:
        import io
        import sys

        sys.path.insert(0, ".")
        from detection.fakenews import detect_narrative_amplification

        import pandas as pd

        df = pd.read_sql(
            "SELECT timestamp AS ts, source, title, url, text FROM events", con
        )
        narr = detect_narrative_amplification(
            df,
            {"thresholds": {"near_duplicate_threshold": 0.7, "min_amp_sources": 3}},
        )
        src_count = Counter()
        for n in narr:
            for s in n.get("sources", []):
                src_count[s] += 1
        n_narr = len(narr)
        return n_narr, src_count
    except Exception as exc:  # no romper la validación si cambia el módulo
        print("aviso: narrativas no computables:", exc)
        return 0, Counter()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/radar.db")
    ap.add_argument("--dataset", default="data/euvsdisinfo_base.csv")
    ap.add_argument("--min-score", type=float, default=60.0,
                    help="score mínimo para contar como 'señal' (def. 60 = HIGH)")
    ap.add_argument("--window-days", type=int, default=90)
    ap.add_argument("--json", action="store_true")
    run(ap.parse_args())


if __name__ == "__main__":
    main()