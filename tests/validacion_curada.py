#!/usr/bin/env python3
"""Validación curada (ground truth propio) del motor de coordinación.

Lee la muestra etiquetada a mano (tests/export_validacion.py) y calcula la
PRECISIÓN POR BANDA: de los clusters que el radar coloca en cada banda, qué
fracción corresponde a coordinación real según el analista.

    precision(banda) = coordinado / (coordinado + no_coordinado)   [excluye 'dudoso']

No hay recall formal: exigiría conocer TODAS las coordinaciones reales del corpus
(etiquetar el flujo crudo completo), inviable. Aquí se mide si las señales
emitidas están justificadas — que es la pregunta honesta para un radar de
detección (su salida son clusters, no un universo etiquetado).

Uso:
  .venv/bin/python tests/validacion_curada.py [muestra.csv] [--json]
  (sin argumento: usa el muestra_*.csv más reciente en data/validacion/)
"""
import argparse
import csv
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = {"coordinado", "no_coordinado", "dudoso"}
ORDEN = ["CRITICAL", "HIGH", "ANOMALOUS", "WATCH"]


def _pct(a, b):
    return round(100.0 * a / b, 1) if b else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("muestra", nargs="?", help="CSV etiquetado")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    path = args.muestra or (sorted(glob.glob(str(ROOT / "data" / "validacion" / "muestra_*.csv")))[-1]
                            if glob.glob(str(ROOT / "data" / "validacion" / "muestra_*.csv")) else None)
    if not path:
        sys.exit("E: no encuentro muestra; ejecuta tests/export_validacion.py")

    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    if not rows:
        sys.exit("E: muestra vacía")

    by_band = defaultdict(lambda: defaultdict(int))
    sin_etiquetar = 0
    for r in rows:
        lab = (r.get("label") or "").strip().lower()
        if lab not in LABELS:
            sin_etiquetar += 1
            continue
        by_band[r.get("banda", "?")][lab] += 1

    res = {"muestra": path, "n_total": len(rows), "sin_etiquetar": sin_etiquetar, "bandas": {}}
    for b in ORDEN:
        d = by_band.get(b)
        if not d:
            continue
        co, no, du = d["coordinado"], d["no_coordinado"], d["dudoso"]
        res["bandas"][b] = {
            "n": co + no + du, "coordinado": co, "no_coordinado": no, "dudoso": du,
            "precision": _pct(co, co + no),
        }

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    print(f"Muestra: {path}")
    print(f"Clusters: {len(rows)}  ·  sin etiquetar: {sin_etiquetar}")
    if sin_etiquetar:
        print("  (rellena la columna 'label' con: coordinado | no_coordinado | dudoso)")
    print()
    print(f"{'BANDA':10s} {'n':>3s} {'coord':>5s} {'no':>4s} {'dud':>4s} {'precisión':>10s}")
    for b in ORDEN:
        v = res["bandas"].get(b)
        if not v:
            continue
        p = f"{v['precision']}%" if v["precision"] is not None else "—"
        print(f"{b:10s} {v['n']:3d} {v['coordinado']:5d} {v['no_coordinado']:4d} {v['dudoso']:4d} {p:>10s}")
    tot_c = sum(v["coordinado"] for v in res["bandas"].values())
    tot_n = sum(v["coordinado"] + v["no_coordinado"] for v in res["bandas"].values())
    print()
    print(f"Precisión global (excl. dudoso): {_pct(tot_c, tot_n)}%  ({tot_c}/{tot_n})")


if __name__ == "__main__":
    main()
