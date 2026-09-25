#!/usr/bin/env python3
"""Harness de validación ARI del detector FIMI (gate de CI).

Genera el dataset sintético de 6 escenarios (A–F), ejecuta la capa de detección
REAL (features → anomalías → coordinación → clustering de componentes conexas)
SIN base de datos ni filtro de tema, y comprueba dos cosas:

  1. Separación de campañas: las cuentas de los grupos coordinados inyectados
     (B doméstica, C extranjera, F atribución desconocida) deben quedar en
     clusters distintos y bien separados -> **Adjusted Rand Index** alto frente
     al ground truth.
  2. Falsos positivos: las cuentas de los grupos orgánicos (A normal, D falsa
     alarma) NO deben caer en ningún cluster. (E, evento viral, puede clusterizar
     parcialmente: es el resultado correcto de "viral ≠ coordinación" y se
     reporta aparte, no cuenta como falso positivo.)

No usa la BD ni `run_fimi.main()` (que escribe SQLite y el dashboard); llama a
las mismas funciones del pipeline para que el gate sea rápido y determinista.

Uso:  python tests/test_synthetic_ari.py      (exit != 0 si falla el umbral)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd
from sklearn.metrics import adjusted_rand_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Grupos inyectados por tests/generate_synthetic.py
COORD_GROUPS = ("B", "C", "F")     # campañas coordinadas -> deben separarse
FP_GROUPS = ("A", "D")             # orgánico / falsa alarma -> 0 clusters
VIRAL_GROUP = "E"                  # viral: clusterización parcial aceptable

ARI_MIN = 0.9                      # separación mínima exigida a B/C/F
FP_RATE_MAX = 0.01                 # ≤1% de cuentas orgánicas (A/D) en cluster.
#                                    Un puñado de cuentas con texto muy corto puede
#                                    colisionar por azar (no es una campaña); el gate
#                                    detecta fallos gruesos, no ruido del fixture.


def _generate(out_dir) -> None:
    """Genera el dataset sintético en `out_dir` (NO escribe data/raw de producción)."""
    env = {**os.environ, "GEN_SYNTHETIC_OUT": str(out_dir)}
    subprocess.run(
        [sys.executable, str(ROOT / "tests" / "generate_synthetic.py")],
        check=True, capture_output=True, env=env,
    )


def _run_pipeline(events_csv):
    """Corre el detector real y devuelve la tabla por cuenta con cluster_label."""
    from detection.run_fimi import load_config
    from normalizer.ingest import load, normalize
    from features.features import build_features
    from features.bot_signals import bot_signal_score
    from detection.anomaly import detect_anomalies
    from detection.coordination import build_edges
    from clustering.clustering import cluster_by_components

    cfg = load_config()
    df = normalize(load(str(events_csv)))
    feat = build_features(df, cfg)
    for a in feat.index:
        feat.loc[a, "bot_signal"], _ = bot_signal_score(feat.loc[a].to_dict())
    scored, _ = detect_anomalies(feat, cfg)
    edges = build_edges(df, cfg)
    edges_df = (pd.DataFrame(edges) if edges
                else pd.DataFrame(columns=["source", "target", "weight", "evidence"]))
    # tema="synthetic" solo sirve de prefijo de label (no hay filtro por tema aquí)
    return cluster_by_components(scored, edges_df, cfg, tema="synthetic")


def evaluate(out_dir) -> dict:
    out_dir = Path(out_dir)
    _generate(out_dir)
    merged = _run_pipeline(out_dir / "events.csv")
    gt = pd.read_csv(out_dir / "ground_truth.csv")
    gt_map = dict(zip(gt["author"], gt["cluster"]))

    pred = {}
    for a in merged.index:
        lab = merged.at[a, "cluster_label"]
        pred[a] = None if (lab is None or (isinstance(lab, float) and pd.isna(lab))) else str(lab)

    # --- 1) ARI sobre los grupos coordinados ---
    coord = [a for a in gt_map if gt_map[a] in COORD_GROUPS]
    y_true = [gt_map[a] for a in coord]
    y_pred = [pred.get(a) or "noise" for a in coord]
    ari = float(adjusted_rand_score(y_true, y_pred)) if coord else 0.0

    # --- 2) falsos positivos sobre A/D ---
    fp = [a for a in gt_map if gt_map[a] in FP_GROUPS and pred.get(a)]
    n_fp_group = len([a for a in gt_map if gt_map[a] in FP_GROUPS])

    # --- recuerdo por grupo (informativo) ---
    per_group = {}
    for g in ("A", "B", "C", "D", "E", "F"):
        accs = [a for a in gt_map if gt_map[a] == g]
        in_cluster = [a for a in accs if pred.get(a)]
        labs = sorted({pred[a] for a in in_cluster})
        per_group[g] = {
            "cuentas": len(accs),
            "en_cluster": len(in_cluster),
            "clusters": labs,
        }

    return {
        "ari": round(ari, 4),
        "ari_min": ARI_MIN,
        "fp": len(fp),
        "fp_rate": round(len(fp) / max(n_fp_group, 1), 4),
        "fp_rate_max": FP_RATE_MAX,
        "fp_cuentas_organicas": n_fp_group,
        "n_clusters_detectados": int(merged["cluster_label"].nunique(dropna=True)),
        "por_grupo": per_group,
    }


def test_synthetic_ari(tmp_path):
    """Gate: el detector separa B/C/F (ARI) y no inventa clusters en A/D (FP)."""
    r = evaluate(tmp_path)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    assert r["ari"] >= ARI_MIN, (
        f"ARI {r['ari']} < {ARI_MIN}: el detector no separa bien las campañas B/C/F"
    )
    assert r["fp_rate"] <= FP_RATE_MAX, (
        f"tasa de falsos positivos {r['fp_rate']} > {FP_RATE_MAX} en grupos orgánicos (A/D)"
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        r = evaluate(d)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    ok = r["ari"] >= ARI_MIN and r["fp_rate"] <= FP_RATE_MAX
    print(f"\n[ari] ARI={r['ari']} (min {ARI_MIN}) · FP={r['fp']} "
          f"({r['fp_rate']} ≤ {FP_RATE_MAX}) · clusters={r['n_clusters_detectados']} "
          f"-> {'OK' if ok else 'FALLO'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
