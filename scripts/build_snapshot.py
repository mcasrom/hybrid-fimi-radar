#!/usr/bin/env python3
"""build_snapshot.py — empaqueta un snapshot CONGELADO y citable del dataset público.

Genera data/snapshots/fimi-dataset-<YYYYMMDD>/ con:
  - datasets por tema (clusters.csv/json, ya anonimizados) + datapackage/index/status/bulos
  - validacion-ciega.csv (conjunto ciego, textos REDACTADOS y URLs -> solo dominio)
  - README.md, CITATION.cff, LICENSE (nota de licencia)
y un .zip del conjunto. No publica nada (la subida a Zenodo la hace el dueño).
"""
import csv
import glob
import io
import os
import re
import shutil
import subprocess
import sys
from datetime import date

ROOT = "/home/deploy/hybrid-fimi-radar"
DATOS = "/var/www/fimi/datos"
HOY = date.today().strftime("%Y%m%d")
OUT = os.path.join(ROOT, "data", "snapshots", "fimi-dataset-" + HOY)
PY = os.path.join(ROOT, ".venv", "bin", "python")


def redact_blind(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys()) if rows else []
    for r in rows:
        doms = set()
        for u in re.split(r"[;\s]+", r.get("urls_evidencia", "") or ""):
            m = re.match(r"https?://([^/]+)", u.strip())
            if m:
                doms.add(m.group(1).lower())
        r["urls_evidencia"] = "; ".join(sorted(doms))
        r["textos_evidencia"] = "[redactado por privacidad]"
    with open(dst, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def main():
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)
    # 1) datasets publicos por tema
    for f in ("datapackage.json", "index.json", "status.json", "bulos.json"):
        p = os.path.join(DATOS, f)
        if os.path.exists(p):
            shutil.copy(p, os.path.join(OUT, f))
    shutil.copytree(os.path.join(DATOS), os.path.join(OUT, "por-tema"),
                    ignore=shutil.ignore_patterns("*.xml", "*.png", "index.json",
                                                  "status.json", "datapackage.json",
                                                  "bulos.json"))
    # 2) conjunto ciego redactado
    blind_tmp = os.path.join(OUT, "_blind_raw.csv")
    subprocess.run([PY, os.path.join(ROOT, "detection", "auditoria_high.py"),
                    "--formato", "blind", "--muestra", "40", "--seed", "7",
                    "--out", blind_tmp], check=True, stdout=subprocess.DEVNULL)
    n = redact_blind(blind_tmp, os.path.join(OUT, "validacion-ciega.csv"))
    os.remove(blind_tmp)
    # 3) CITATION + README
    cit = os.path.join(ROOT, "CITATION.cff")
    if os.path.exists(cit):
        shutil.copy(cit, os.path.join(OUT, "CITATION.cff"))
    with io.open(os.path.join(OUT, "README.md"), "w", encoding="utf-8") as f:
        f.write(
            "# Observatorio de amplificación (ámbito FIMI) — snapshot %s\n\n"
            "Dataset congelado del observatorio. **Datos: CC-BY-4.0.** Código: **AGPL-3.0**.\n\n"
            "## Contenido\n"
            "- `por-tema/<tema>/clusters.{csv,json}`: clusters por tema (label, banda, score,\n"
            "  componentes, k-core…). **Sin textos ni autores** (anonimizado).\n"
            "- `datapackage.json`: metadatos Frictionless (bytes + sha256 por recurso).\n"
            "- `validacion-ciega.csv`: conjunto ciego de validación (%d filas) con los textos\n"
            "  REDACTADOS y `urls_evidencia` reducidas a dominio; columnas `label_*` vacías\n"
            "  para anotación humana (ver `docs/RUBRICA-VALIDACION.md`).\n"
            "- `bulos.json`, `index.json`, `status.json`: contrastes con verificadores y estado.\n\n"
            "## Límites (leer antes de usar)\n"
            "- Una **banda alta es amplificación medida, NO coordinación confirmada** ni atribución.\n"
            "  Validación ciega: 8,3 %% de coordinación en banda alta, 0 casos FIMI.\n"
            "- Sin X/TikTok/Meta/WhatsApp. Dependencia de Bluesky + Google News.\n"
            "- Los `cluster_label` NO son estables entre ciclos; usar `lineage_id` cuando aplique.\n\n"
            "## Cómo citar\n"
            "Observatorio de amplificación (ámbito FIMI), M. Castillo, %s. "
            "DOI: (pendiente de asignar en Zenodo).\n" % (HOY, n, HOY))
    # 4) zip
    zipbase = os.path.join(ROOT, "data", "snapshots", "fimi-dataset-" + HOY)
    shutil.make_archive(zipbase, "zip", OUT)
    zp = zipbase + ".zip"
    # copia descargable
    pub = os.path.join(DATOS, "fimi-dataset-" + HOY + ".zip")
    shutil.copy(zp, pub)
    print("snapshot:", OUT)
    print("zip:", zp, os.path.getsize(zp), "bytes")
    print("descargable:", pub)
    print("filas validacion-ciega:", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
