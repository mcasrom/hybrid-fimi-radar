#!/usr/bin/env python3
"""revisar_relevancia.py — cola de revisión humana de contaminación temática.

Solo lectura (no toca scoring, bandas ni BD). Para un tema, calcula la
relevancia temática de cada cluster (fracción de eventos cuyo título+texto
contiene términos del tema) y vuelca un CSV con los candidatos a revisar
(relevancia baja/parcial primero), con su evidencia, más un CSV de eventos.

El CSV de clústeres lleva columnas `decision` y `nota` VACÍAS: las rellena
la persona que revisa (legitimo | revisar_agrupamiento | ruido). El CSV
firmado es el expediente auditable.

Uso:
  .venv/bin/python detection/revisar_relevancia.py --tema frontera_sur [--out DIR]
  .venv/bin/python detection/revisar_relevancia.py --todos [--out DIR]
"""
import argparse
import csv
import json
import os
import re
import sqlite3
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "data", "radar.db")
CFG = os.path.join(BASE, "config.yaml")
BANDAS = [(80, "CRITICAL"), (60, "HIGH"), (40, "ANOMALOUS"), (20, "WATCH"), (0, "NORMAL")]
ACTIVOS = ["frontera_sur", "oriente_medio", "elecciones", "inteligencia_artificial",
           "eeuu_politica", "sahel", "energia", "defensa_espana", "espana_elecciones"]
# Dominios/plataformas que no cuentan como "dominio" (acortadores/redes propias).
DOM_EXCL = {"youtu.be", "youtube.com", "bit.ly", "t.co", "x.com", "twitter.com",
            "bsky.app", "facebook.com", "instagram.com", "t.me", "reddit.com",
            "news.google.com", "pruebapublica.com", "viajeinteligencia.com"}


def band(score):
    for lo, name in BANDAS:
        if (score or 0) >= lo:
            return name
    return "NORMAL"


def norm(s):
    return re.sub(r"[^a-záéíóúñü ]", " ", (s or "").lower())


def load_redactar():
    try:
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location(
            "informe_tema", os.path.join(BASE, "detection", "informe_tema.py"))
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.redactar
    except Exception:
        return lambda t: (t or "", False)


def kw_terms(tema):
    try:
        import yaml
        cfg = yaml.safe_load(open(CFG, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = set()
    for k in (cfg.get("keywords") or []):
        kt = k.get("tema")
        if kt == tema or (tema == "frontera_sur" and kt is None):
            w = norm(k.get("palabra", "")).strip()
            if len(w) >= 4:
                out.add(w)
    return sorted(out)


def cluster_hosts(con, cid):
    seen = {}
    for (u,) in con.execute(
            "SELECT url FROM cluster_events WHERE cluster_id=?"
            " AND TRIM(COALESCE(url,''))<>''", (cid,)):
        m = re.sub(r"^https?://", "", (u or "")).split("/")[0].lower()
        if m and m not in DOM_EXCL:
            seen[m] = seen.get(m, 0) + 1
    return seen


def supported_codes(con, cid):
    row = con.execute("SELECT alternative_explanations FROM clusters WHERE id=?",
                      (cid,)).fetchone()
    try:
        items = json.loads((row[0] if row else "") or "[]")
    except ValueError:
        items = []
    if isinstance(items, dict):
        items = list(items.values())
    out = []
    for e in items:
        if isinstance(e, dict) and e.get("status") == "supported":
            out.append(e.get("code") or e.get("id") or "?")
    return out


def revisar(con, tema, redactar):
    terms = kw_terms(tema)
    rx = (re.compile("|".join(r"\b%s\b" % re.escape(w) for w in terms))
          if terms else None)
    rows = con.execute(
        "SELECT c.id, c.cluster_label, c.overall_score, c.anomaly_score,"
        " (SELECT MIN(ts) FROM cluster_events ce WHERE ce.cluster_id=c.id) t0,"
        " (SELECT MAX(ts) FROM cluster_events ce WHERE ce.cluster_id=c.id) t1,"
        " (SELECT lineage_id FROM cluster_lineage cl WHERE"
        "  cl.cluster_label=c.cluster_label ORDER BY cycle_ts DESC LIMIT 1) lin"
        " FROM clusters c WHERE c.tema_id=?", (tema,)).fetchall()
    filas, eventos = [], []
    for r in rows:
        cid = r[0]
        evs = con.execute(
            "SELECT source, title, text, url, ts FROM cluster_events"
            " WHERE cluster_id=?", (cid,)).fetchall()
        nev = len(evs)
        hit = sum(1 for e in evs
                  if rx and rx.search(norm("%s %s" % (e[1], e[2]))))
        frac = round(hit / max(nev, 1), 2)
        rel = "alta" if frac >= 0.5 else "parcial" if frac >= 0.2 else "baja"
        hosts = cluster_hosts(con, cid)
        dom_top = ", ".join("%s(%d)" % (d, n) for d, n in
                            sorted(hosts.items(), key=lambda x: -x[1])[:4]) or "—"
        nau = con.execute(
            "SELECT COUNT(DISTINCT author) FROM cluster_events WHERE cluster_id=?",
            (cid,)).fetchone()[0]
        titulos = []
        for e in sorted(evs, key=lambda x: -(x[4] or 0)):
            t, _ = redactar((e[1] or "")[:120])
            if t:
                titulos.append(t)
            if len(titulos) >= 4:
                break
        filas.append({
            "tema": tema, "cluster_id": r[1], "linaje": r[6] or "",
            "relevancia": rel, "relevancia_frac": frac,
            "banda": band(r[2]), "score": round(r[2] or 0, 1),
            "anomalia": round(r[3] or 0, 1),
            "n_eventos": nev, "n_autores": nau,
            "dominios_top": dom_top,
            "explicaciones_supported": ";".join(supported_codes(con, cid)) or "—",
            "titulos_muestra": " | ".join(titulos),
            "ventana": "%s-%s" % (
                datetime.fromtimestamp(r[4], timezone.utc).strftime("%d/%m") if r[4] else "—",
                datetime.fromtimestamp(r[5], timezone.utc).strftime("%d/%m") if r[5] else "—"),
            "decision": "", "nota": "",
        })
        for e in evs:
            t, _ = redactar((e[1] or "")[:160])
            eventos.append({
                "tema": tema, "cluster_id": r[1], "source": e[0] or "",
                "url": e[3] or "", "titulo": t,
                "fecha": (datetime.fromtimestamp(e[4], timezone.utc)
                          .strftime("%Y-%m-%d %H:%M") if e[4] else ""),
            })
    # orden: baja primero, luego parcial, luego alta; dentro, por anomalía desc
    orden = {"baja": 0, "parcial": 1, "alta": 2}
    filas.sort(key=lambda x: (orden.get(x["relevancia"], 3), -x["anomalia"]))
    return filas, eventos


def escribir(out_dir, tema, filas, eventos):
    os.makedirs(out_dir, exist_ok=True)
    fecha = datetime.now(timezone.utc).strftime("%Y%m%d")
    f1 = os.path.join(out_dir, "revision-%s-%s.csv" % (tema, fecha))
    cols = ["tema", "cluster_id", "linaje", "relevancia", "relevancia_frac",
            "banda", "score", "anomalia", "n_eventos", "n_autores",
            "dominios_top", "explicaciones_supported", "titulos_muestra",
            "ventana", "decision", "nota"]
    with open(f1, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in filas:
            w.writerow(r)
    f2 = os.path.join(out_dir, "revision-%s-%s-eventos.csv" % (tema, fecha))
    if eventos:
        with open(f2, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(eventos[0].keys()))
            w.writeheader()
            for e in eventos:
                w.writerow(e)
    return f1, f2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema")
    ap.add_argument("--todos", action="store_true")
    ap.add_argument("--out", default=os.path.join(BASE, "data", "revision"))
    a = ap.parse_args()
    temas = ACTIVOS if a.todos else ([a.tema] if a.tema else [])
    if not temas:
        print("indica --tema <slug> o --todos")
        return 2
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    redactar = load_redactar()
    for tema in temas:
        filas, eventos = revisar(con, tema, redactar)
        f1, f2 = escribir(a.out, tema, filas, eventos)
        bajas = sum(1 for x in filas if x["relevancia"] == "baja")
        parciales = sum(1 for x in filas if x["relevancia"] == "parcial")
        print("%s: %d clusters · %d baja · %d parcial · firmar %s"
              % (tema, len(filas), bajas, parciales, f1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
