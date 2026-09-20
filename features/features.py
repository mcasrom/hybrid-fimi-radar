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


def _temporal_from_group(ev_series):
    """Versión optimizada que recibe ya la serie ts del grupo (sin filtrar df)."""
    ev = np.sort(ev_series.values)
    n = len(ev)
    if n == 0:
        return None
    span_days = max((ev[-1] - ev[0]) / 86400, 1e-6)
    span_hours = max((ev[-1] - ev[0]) / 3600, 1e-6)
    feats = {"n_events": n, "events_per_day": n / span_days, "events_per_hour": n / span_hours}
    if n >= 2:
        intervals = np.diff(ev)
        mean_int = intervals.mean()
        std_int = intervals.std()
        feats["mean_interval_s"] = mean_int
        feats["std_interval_s"] = std_int
        feats["cv_interval"] = std_int / mean_int if mean_int > 0 else 0.0
        feats["frac_short_int"] = np.mean(intervals < 60)
        feats["frac_long_int"] = np.mean(intervals > 86400)
    else:
        feats.update({"mean_interval_s": 0, "std_interval_s": 0, "cv_interval": 0, "frac_short_int": 0, "frac_long_int": 0})
    hours = ev / 3600
    bins = np.floor(hours / (1 / 6)).astype(int)
    cnt = Counter(bins.tolist())
    bursts = sum(1 for c in cnt.values() if c >= 5)
    feats["n_bursts"] = bursts
    feats["max_in_10min"] = max(cnt.values()) if cnt else 0
    bins_h = np.floor(hours).astype(int)
    cnt_h = Counter(bins_h.tolist())
    feats["max_concentration_1h"] = (max(cnt_h.values()) / n) if cnt_h else 0.0
    # uniformidad horaria: vectorizada sin Series por grupo
    # horas del día UTC: (ev // 3600) % 24  == hour
    hod = ((ev // 3600) % 24).astype(int)
    uniq = len(np.unique(hod))
    feats["distinct_hours"] = uniq
    feats["hour_uniformity"] = uniq / 24.0
    return feats


def temporal_features(df, author):
    """Características temporales de una cuenta (compat: filtra df)."""
    ev = df[df["author"] == author]["ts"]
    return _temporal_from_group(ev)


def _content_from_group(g, near_ratio, config):
    n = len(g)
    if n == 0:
        return None
    texts = g["text"].tolist()
    urls = g["url"].tolist()
    htags = g["hashtags"].tolist()
    actions = g["action"].tolist()
    feats = {
        "mean_text_len": float(np.mean([len(t) for t in texts])),
        "has_text": float(np.mean([len(t.strip()) > 0 for t in texts])),
        "has_url": float(np.mean([u.strip() != "" for u in urls])),
        "has_hashtag": float(np.mean([h.strip() != "" for h in htags])),
        "share_ratio": float(np.mean([a.lower() in ("share", "rt", "retweet", "repost") for a in actions])),
    }
    all_tags = []
    for h in htags:
        all_tags += [x.strip().lstrip("#").lower() for x in h.replace("#", " #").split() if x.strip().startswith("#")]
    feats["hashtag_diversity"] = len(set(all_tags)) / max(n, 1)
    doms = []
    for u in urls:
        d = content.extract_domain(u)
        if d:
            doms.append(d)
    feats["domain_diversity"] = len(set(doms)) / max(n, 1)
    feats["top_domain_share"] = (max(Counter(doms).values()) / n) if doms else 0.0
    feats["near_dup_ratio"] = float(near_ratio)
    return feats


def content_features(df, author, config):
    """Características de contenido de una cuenta (compat: filtra df)."""
    g = df[df["author"] == author]
    # fallback lento si no hay precomputo
    near = content.near_duplicate_ratio(df, author, config)
    return _content_from_group(g, near, config)


def build_features(df, config):
    """Matriz de características por cuenta → DataFrame indexado por author."""
    if df.empty:
        return pd.DataFrame()
    # Una sola pasada TF-IDF para near-duplicates (evita A veces fit)
    try:
        near_ratios = content.near_duplicate_ratio_all(df, config)
    except Exception as _e:
        import sys as _sys
        print("[warn] build_features near_dup_ratio_all fallo:", _e, file=_sys.stderr)
        near_ratios = {}
    features = {}
    # groupby evita O(A·n) scans de df[df["author"]==a]
    for author, g in df.groupby("author", sort=False):
        tf = _temporal_from_group(g["ts"])
        if tf is None:
            continue
        cf = _content_from_group(g, near_ratios.get(author, 0.0), config)
        if cf is None:
            continue
        row = {**tf, **cf}
        features[author] = row
    feat_df = pd.DataFrame.from_dict(features, orient="index")
    feat_df.index.name = "author"
    return feat_df.fillna(0.0)
