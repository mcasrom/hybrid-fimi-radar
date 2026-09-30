#!/usr/bin/env python3
"""Kappa de Cohen para la validación ciega con dos revisores.

Uso:
    .venv/bin/python detection/validacion_kappa.py \
        --a data/validacion/muestra_high_blind_20260929_postgate.csv \
        --b data/validacion/muestra_high_blind_20260929_revisor2.csv

Compara las columnas `label_coordinacion`, `label_inautenticidad`, `label_intencion`,
`label_dimension_extranjera` y `label_fimi` entre dos revisores INDEPENDIENTES y calcula:
  - acuerdo observado (po) y esperado por azar (pe)
  - kappa de Cohen (κ = (po-pe)/(1-pe))
  - matriz de confusión por dimensión
  - precisión de cada revisor en coordinación (excluyendo `dudoso`)

Interpretación orientativa de κ: <0.20 pobre · 0.21-0.40 débil · 0.41-0.60 moderada
· 0.61-0.80 fuerte · >0.80 casi perfecta.
"""
import argparse, csv, sys
from collections import Counter

DIMS = ["label_coordinacion", "label_inautenticidad", "label_intencion",
        "label_dimension_extranjera", "label_fimi"]
DUDS = {"dudoso", "dudosa", ""}


def load(path):
    with open(path, encoding="utf-8") as f:
        return {r["cluster_label"]: r for r in csv.DictReader(f)}


def kappa(pairs):
    """pairs: lista de (a,b). Devuelve (po, pe, kappa)."""
    n = len(pairs)
    if n == 0:
        return None
    po = sum(1 for a, b in pairs if a == b) / n
    ca = Counter(a for a, _ in pairs); cb = Counter(b for _, b in pairs)
    cats = set(ca) | set(cb)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in cats)
    k = (po - pe) / (1 - pe) if pe != 1 else 1.0
    return po, pe, k


def confusion(pairs, cats):
    m = {a: {b: 0 for b in cats} for a in cats}
    for a, b in pairs:
        m[a][b] += 1
    return m


def precision(rows, col):
    yes = sum(1 for r in rows.values() if r.get(col, "").strip().lower() == "si")
    no = sum(1 for r in rows.values() if r.get(col, "").strip().lower() == "no")
    dud = sum(1 for r in rows.values() if r.get(col, "").strip().lower() in ("dudoso", "dudosa"))
    tot = yes + no
    return yes, no, dud, (100 * yes / tot if tot else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="CSV revisor 1 (etiquetado)")
    ap.add_argument("--b", required=True, help="CSV revisor 2 (etiquetado)")
    args = ap.parse_args()
    A, B = load(args.a), load(args.b)
    comunes = sorted(set(A) & set(B))
    print(f"Revisor 1: {args.a}")
    print(f"Revisor 2: {args.b}")
    print(f"clusters comunes: {len(comunes)} (A={len(A)}, B={len(B)})\n")
    for dim in DIMS:
        pairs = []
        for cl in comunes:
            a = (A[cl].get(dim) or "").strip().lower()
            b = (B[cl].get(dim) or "").strip().lower()
            if a or b:                       # solo si alguno etiquetó
                pairs.append((a or "?", b or "?"))
        res = kappa(pairs)
        if not res:
            print(f"[{dim}] sin datos"); continue
        po, pe, k = res
        interpret = ("casi perfecta" if k > 0.8 else "fuerte" if k > 0.6 else
                     "moderada" if k > 0.4 else "débil" if k > 0.2 else "pobre")
        print(f"[{dim}] n={len(pairs)}  acuerdo={po*100:.0f}%  κ={k:.2f} ({interpret})")
        cats = sorted(set([a for a, _ in pairs] + [b for _, b in pairs]))
        m = confusion(pairs, cats)
        print("    matriz (filas=rev1, cols=rev2): " + " | ".join(cats))
        for a in cats:
            print(f"      {a:8} " + "  ".join(f"{m[a][b]:3}" for b in cats))
    print("\nPrecisión en coordinación (excl. dudoso):")
    for name, rows in (("rev1", A), ("rev2", B)):
        yes, no, dud, prec = precision(rows, "label_coordinacion")
        print(f"  {name}: {yes} sí / {no} no / {dud} dudoso · precisión {prec:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
