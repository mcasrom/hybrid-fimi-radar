#!/usr/bin/env python3
"""gen_datasets.py — datasets abiertos por tema (una fila por cluster).

Lee `clusters`/`cluster_events`/`cluster_lineage` (solo lectura) y escribe bajo
/var/www/fimi/datos/:
  <tema>/clusters.{csv,json}  — una fila por cluster, sin textos ni autores
  datapackage.json            — Frictionless: esquema, bytes/md5, licencia
  status.json                 — frescura por fichero (updated_at, filas, sha256)
  index.json                  — catálogo por tema

No toca captura, scoring, bandas ni la BD. Escritura atómica (.tmp + replace).
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DB = os.path.join(ROOT, "data", "radar.db")
OUT = "/var/www/fimi/datos"
LICENSE = "CC-BY-4.0"

COLS = ["lineage_id", "cluster_label", "banda", "overall_score",
        "coordination_score", "amplification_score", "anomaly_score",
        "infrastructure_score", "network_density", "confidence",
        "cuentas", "eventos", "ventana_horas", "first_seen_utc",
        "last_seen_utc", "n_ciclos", "narrative_subtype", "explicacion_principal"]


def banda(sc: float) -> str:
    sc = sc or 0.0
    if sc >= 80:
        return "CRITICAL"
    if sc >= 60:
        return "HIGH"
    if sc >= 40:
        return "ANOMALOUS"
    if sc >= 20:
        return "WATCH"
    return "NORMAL"


def num(x, nd=1):
    try:
        return round(float(x or 0), nd)
    except (TypeError, ValueError):
        return x if isinstance(x, str) else 0


def iso(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ""


def principal_of(raw: str) -> str:
    try:
        from detection import explicaciones
        items = json.loads(raw) if raw else []
        return explicaciones.resumen(items).get("principal", "")
    except Exception as e:
        print(f"  aviso: resumen explicaciones falló ({e})", file=sys.stderr)
        return ""


def main() -> int:
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    temas = [r[0] for r in con.execute("SELECT DISTINCT tema_id FROM clusters ORDER BY tema_id")]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    os.makedirs(OUT, exist_ok=True)
    catalog = []
    status_files = {}
    for tema in temas:
        try:
            rows = con.execute(
                "SELECT c.cluster_label, c.overall_score, c.coordination_score,"
                " c.amplification_score, c.anomaly_score, c.infrastructure_score,"
                " c.network_density, c.confidence, c.created_at,"
                " c.alternative_explanations, c.narrative_subtype,"
                " (SELECT COUNT(*) FROM cluster_events ce WHERE ce.cluster_id=c.id) AS nev,"
                " (SELECT COUNT(DISTINCT ce.author) FROM cluster_events ce WHERE ce.cluster_id=c.id) AS naut,"
                " (SELECT (MAX(ce.ts)-MIN(ce.ts))/3600.0 FROM cluster_events ce WHERE ce.cluster_id=c.id) AS vent,"
                " (SELECT l.lineage_id FROM cluster_lineage l WHERE l.tema_id=c.tema_id"
                "   AND l.cluster_label=c.cluster_label ORDER BY l.id DESC LIMIT 1) AS lin,"
                " (SELECT l.first_seen FROM cluster_lineage l WHERE l.tema_id=c.tema_id"
                "   AND l.cluster_label=c.cluster_label ORDER BY l.id DESC LIMIT 1) AS fs,"
                " (SELECT l.last_seen FROM cluster_lineage l WHERE l.tema_id=c.tema_id"
                "   AND l.cluster_label=c.cluster_label ORDER BY l.id DESC LIMIT 1) AS ls,"
                " (SELECT l.n_ciclos FROM cluster_lineage l WHERE l.tema_id=c.tema_id"
                "   AND l.cluster_label=c.cluster_label ORDER BY l.id DESC LIMIT 1) AS nc"
                " FROM clusters c WHERE c.tema_id=? ORDER BY c.overall_score DESC",
                (tema,)).fetchall()
        except Exception as e:
            print(f"tema {tema}: fallo lectura ({e}), se omite", file=sys.stderr)
            continue
        recs = []
        for r in rows:
            try:
                sub = json.loads(r["narrative_subtype"]) if r["narrative_subtype"] else {}
            except Exception as e:
                print(f"  aviso: subtype {r['cluster_label']} ({e})", file=sys.stderr)
                sub = {}
            recs.append({
                "lineage_id": r["lin"] or "", "cluster_label": r["cluster_label"],
                "banda": banda(r["overall_score"] or 0),
                "overall_score": num(r["overall_score"]),
                "coordination_score": num(r["coordination_score"]),
                "amplification_score": num(r["amplification_score"]),
                "anomaly_score": num(r["anomaly_score"]),
                "infrastructure_score": num(r["infrastructure_score"]),
                "network_density": num(r["network_density"]),
                "confidence": num(r["confidence"], 2),
                "cuentas": int(r["naut"] or 0), "eventos": int(r["nev"] or 0),
                "ventana_horas": round(float(r["vent"] or 0), 1),
                "first_seen_utc": iso(r["fs"]), "last_seen_utc": iso(r["ls"]),
                "n_ciclos": int(r["nc"] or 0),
                "narrative_subtype": sub.get("dominant", "") if isinstance(sub, dict) else "",
                "explicacion_principal": principal_of(r["alternative_explanations"]),
            })
        d = os.path.join(OUT, tema)
        os.makedirs(d, exist_ok=True)
        for name, data, ctype in (
                ("clusters.csv", None, "text/csv"),
                ("clusters.json", None, "application/json")):
            fp = os.path.join(d, name)
            tmp = fp + ".tmp"
            if name.endswith(".csv"):
                with open(tmp, "w", encoding="utf-8", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=COLS)
                    w.writeheader()
                    w.writerows(recs)
            else:
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump({"tema": tema, "updated_at": now, "clusters": recs,
                               "licencia": LICENSE}, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, fp)
            with open(fp, "rb") as fh:
                blob = fh.read()
            status_files[f"{tema}/{name}"] = {
                "filas": len(recs), "bytes": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest(), "updated_at": now,
                "tipo": ctype,
            }
        catalog.append({"tema": tema, "clusters": len(recs),
                        "eventos": sum(r["eventos"] for r in recs), "updated_at": now})
        print(f"tema {tema}: {len(recs)} clusters")
    pkg = {"name": "fimi-observatorio-amplificacion",
           "title": "Observatorio de amplificación — datasets por tema",
           "licenses": [{"name": LICENSE}], "updated_at": now,
           "metodo": "https://fimi.viajeinteligencia.com/metodo.html",
           "limites": "Bandas = amplificación medida, no coordinación confirmada ni atribución.",
           "resources": [{"path": k, **v} for k, v in sorted(status_files.items())]}
    for name, obj in (("datapackage.json", pkg),
                      ("status.json", {"updated_at": now, "files": status_files}),
                      ("index.json", {"updated_at": now, "temas": catalog})):
        fp = os.path.join(OUT, name)
        tmp = fp + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, fp)
    print(f"OK {OUT} ({len(catalog)} temas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
