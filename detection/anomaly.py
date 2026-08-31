"""Detección de anomalías con Isolation Forest (clásico, sin deep learning).

Salida: anomaly_score 0..1 por cuenta (más alto = más anómalo).
Solo usa características observables, sin conocer ninguna cuenta/hashtag/URL previa.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


def detect_anomalies(feat_df, config):
    """Devuelve (df con anomaly_score, umbral)."""
    if feat_df.shape[0] < 5:
        return feat_df.assign(anomaly_score=0.0), 1.0

    cols = [c for c in feat_df.columns if c not in ("author",)]
    X = feat_df[cols].values

    # escala robusta
    med = np.nanmedian(X, axis=0)
    iqr = np.nanpercentile(X, 75, axis=0) - np.nanpercentile(X, 25, axis=0)
    iqr = np.where(iqr == 0, 1.0, iqr)
    Xs = (X - med) / iqr
    Xs = np.nan_to_num(Xs, nan=0.0, posinf=10.0, neginf=-10.0)

    iso = IsolationForest(
        contamination=config["anomaly"]["contamination"],
        random_state=config["anomaly"]["random_state"],
        n_jobs=-1,
    )
    iso.fit(Xs)
    # anomaly_score normalizado 0..1 (mayor = más anómalo)
    score = -iso.score_samples(Xs)
    score = (score - score.min()) / (score.max() - score.min() + 1e-9)

    out = feat_df.copy()
    out["anomaly_score"] = score
    # umbral: percentil configurado
    p = config["thresholds"]["anomaly_percentile"]
    threshold = float(np.percentile(score, p * 100))
    return out, threshold
