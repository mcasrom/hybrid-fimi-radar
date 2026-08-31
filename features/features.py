"""Extracción de características de comportamiento por cuenta.

Temporal:
  - n eventos
  - eventos/día, eventos/hora
  - intervalo medio y desviación entre eventos
  - coeficiente de variación del intervalo (regularidad: robots=CV bajo, humanos=CV alto)
  - ráfagas (número de picos con >K eventos en ventana corta)
  - concentración temporal (máximo nº de eventos en 1h / total)
  - uniformidad horaria (cuántas horas distintas del día publica)

Contenido:
  - longitud media del texto
  - ratio de textos casi duplicados (near-duplicate con otros)
  - diversidad de hashtags (nº distintos / nº eventos)
  - diversidad de dominios
  - ratio share vs post (amplificación)
"""
import numpy as np
import pandas as pd
from collections import Counter

from . import content


def temporal_features(df, author):
    """Características temporales de una cuenta."""
    ev = df[df["author"] == author]["ts"].sort_values().values
    n = len(ev)
    if n == 0:
        return None

    span_days = max((ev[-1] - ev[0]) / 86400, 1e-6)
    span_hours = max((ev[-1] - ev[0]) / 3600, 1e-6)

    feats = {
        "n_events": n,
        "events_per_day": n / span_days,
        "events_per_hour": n / span_hours,
    }

    if n >= 2:
        intervals = np.diff(ev)
        mean_int = intervals.mean()
        std_int = intervals.std()
        feats["mean_interval_s"] = mean_int
        feats["std_interval_s"] = std_int
        feats["cv_interval"] = std_int / mean_int if mean_int > 0 else 0.0
        # regularidad: fracción de intervalos muy cortos (< 1 min) y muy largos (> 1 día)
        feats["frac_short_int"] = np.mean(intervals < 60)
        feats["frac_long_int"] = np.mean(intervals > 86400)
    else:
        feats.update({"mean_interval_s": 0, "std_interval_s": 0, "cv_interval": 0,
                      "frac_short_int": 0, "frac_long_int": 0})

    # ráfagas: ventanas de 10 min con >= burst_min_events
    from scipy.stats import iqr as _iqr
    hours = ev / 3600
    bins = np.floor(hours / (1 / 6)).astype(int)  # bins de 10 min
    cnt = Counter(bins.tolist())
    bursts = sum(1 for c in cnt.values() if c >= 5)
    feats["n_bursts"] = bursts
    feats["max_in_10min"] = max(cnt.values()) if cnt else 0

    # concentración temporal: máx nº de eventos en 1h / n
    bins_h = np.floor(hours).astype(int)
    cnt_h = Counter(bins_h.tolist())
    feats["max_concentration_1h"] = (max(cnt_h.values()) / n) if cnt_h else 0.0

    # uniformidad horaria: cuántas horas del día distintas
    hours_of_day = pd.Series(pd.to_datetime(ev, unit="s", utc=True)).dt.hour
    feats["distinct_hours"] = len(set(hours_of_day.tolist()))
    feats["hour_uniformity"] = len(set(hours_of_day.tolist())) / 24.0

    return feats


def content_features(df, author, config):
    """Características de contenido de una cuenta."""
    ev = df[df["author"] == author]
    n = len(ev)
    if n == 0:
        return None

    texts = ev["text"].tolist()
    urls = ev["url"].tolist()
    htags = ev["hashtags"].tolist()
    actions = ev["action"].tolist()

    feats = {
        "mean_text_len": float(np.mean([len(t) for t in texts])),
        "has_text": float(np.mean([len(t.strip()) > 0 for t in texts])),
        "has_url": float(np.mean([u.strip() != "" for u in urls])),
        "has_hashtag": float(np.mean([h.strip() != "" for h in htags])),
        "share_ratio": float(np.mean([a.lower() in ("share", "rt", "retweet", "repost") for a in actions])),
    }

    # diversidad de hashtags
    all_tags = []
    for h in htags:
        all_tags += [x.strip().lstrip("#").lower() for x in h.replace("#", " #").split() if x.strip().startswith("#")]
    feats["hashtag_diversity"] = len(set(all_tags)) / max(n, 1)

    # diversidad de dominios
    doms = []
    for u in urls:
        d = content.extract_domain(u)
        if d:
            doms.append(d)
    feats["domain_diversity"] = len(set(doms)) / max(n, 1)
    feats["top_domain_share"] = (max(Counter(doms).values()) / n) if doms else 0.0

    # ratio de near-duplicates de la cuenta frente a todo el dataset
    near = content.near_duplicate_ratio(df, author, config)
    feats["near_dup_ratio"] = near

    return feats


def build_features(df, config):
    """Matriz de características por cuenta → DataFrame indexado por author."""
    features = {}
    for author in df["author"].unique():
        tf = temporal_features(df, author)
        cf = content_features(df, author, config)
        if tf and cf:
            row = {**tf, **cf}
            features[author] = row
    feat_df = pd.DataFrame.from_dict(features, orient="index")
    feat_df.index.name = "author"
    return feat_df.fillna(0.0)
