"""Utilidades de contenido: dominios, hashtags, near-duplicates con TF-IDF.

Sin LLM ni embeddings remotos. Solo TF-IDF clásico + coseno.
"""
import re
from collections import Counter
from urllib.parse import urlparse

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

_URL_RE = re.compile(r"https?://[^\s]+")
_TAG_RE = re.compile(r"#(\w+)")
_MENTION_RE = re.compile(r"@(\w+)")


def extract_urls(text):
    return _URL_RE.findall(text or "")


def extract_domain(url):
    try:
        host = urlparse(url).netloc.lower()
        return host.lstrip("www.")
    except Exception:
        return ""


def extract_hashtags(text):
    return [t.lower() for t in _TAG_RE.findall(text or "")]


def extract_mentions(text):
    return [m.lower() for m in _MENTION_RE.findall(text or "")]


def account_domains(df, author):
    """Dominios usados por una cuenta, a partir del campo url y del texto."""
    doms = Counter()
    ev = df[df["author"] == author]
    for u in ev["url"].tolist():
        d = extract_domain(u)
        if d:
            doms[d] += 1
    for t in ev["text"].tolist():
        for u in extract_urls(t):
            d = extract_domain(u)
            if d:
                doms[d] += 1
    return doms


def near_duplicate_ratio(df, author, config):
    """Fracción de textos de la cuenta que son near-duplicate (coseno >= umbral)
    de otro texto de cualquier cuenta distinta."""
    threshold = config["thresholds"]["near_duplicate_threshold"]
    ev = df[df["author"] == author]
    texts = ev["text"].tolist()
    if not texts:
        return 0.0
    # vectorizar solo textos no vacíos
    non_empty = [t for t in texts if t.strip()]
    if len(non_empty) < 2:
        return 0.0
    others = df[df["author"] != author]["text"].tolist()
    others = [t for t in others if t.strip()]
    if not others:
        return 0.0

    corpus = non_empty + others
    try:
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, stop_words=None)
        X = vec.fit_transform(corpus)
    except Exception:
        return 0.0
    mine = X[:len(non_empty)]
    rest = X[len(non_empty):]
    if mine.shape[0] == 0 or rest.shape[0] == 0:
        return 0.0
    sim = cosine_similarity(mine, rest)
    hits = (sim.max(axis=1) >= threshold).sum()
    return hits / len(non_empty)
