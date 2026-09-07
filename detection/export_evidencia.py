#!/usr/bin/env python3
"""export_evidencia.py — Exporta la evidencia (cluster_events) de un cluster.

Reutiliza `exportar_cluster` de email_api (misma lógica que el endpoint
web /api/export), pero desde CLI para el dueño: permite auditar o compartir
los textos/fuentes/URLs de un cluster de la vista activa sin pasar por web.

Uso:
  .venv/bin/python detection/export_evidencia.py --list
  .venv/bin/python detection/export_evidencia.py --cluster frontera_sur_cluster_000 [--fmt csv|json] [--out ruta]
"""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
sys.path.insert(0, str(Path(__file__).resolve().parent))


def listar():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT cluster_label, tema_id, overall_score FROM clusters"
        " ORDER BY tema_id, cluster_label").fetchall()
    con.close()
    print("Clusters de la vista activa:")
    for r in rows:
        print(f"  {r['cluster_label']:42s} | {r['tema_id']:24s} | {r['overall_score']:6.1f}")


def main():
    ap = argparse.ArgumentParser(description="Exporta evidencia de un cluster FIMI")
    ap.add_argument("--list", action="store_true", help="lista los clusters disponibles")
    ap.add_argument("--cluster", help="cluster_label a exportar")
    ap.add_argument("--fmt", default="csv", choices=["csv", "json"], help="formato")
    ap.add_argument("--out", help="ruta de salida (sin ella, imprime y guarda en data/export)")
    args = ap.parse_args()

    if args.list:
        listar()
        return

    if not args.cluster:
        ap.error("usa --list o --cluster <label>")

    from email_api import exportar_cluster
    try:
        ctype, body, fname = exportar_cluster(args.cluster, args.fmt)
    except KeyError as e:
        print(f"[export] ERROR: {e}")
        sys.exit(1)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_bytes(body)
        print(f"[export] guardado en {args.out} ({len(body)} bytes)")
    else:
        outdir = ROOT / "data" / "export"
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / fname
        out.write_bytes(body)
        print(f"[export] guardado en {out} ({len(body)} bytes)")
        if args.fmt == "csv" and len(body) < 2000:
            print(body.decode("utf-8"))


if __name__ == "__main__":
    main()
