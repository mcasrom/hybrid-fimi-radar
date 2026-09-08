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
from sklearn.preprocessing import normalize

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


def near_duplicate_ratio_all(df, config):
    """Ratios near-dup de TODAS las cuentas en una sola pasada de TF-IDF.

    Equivalente a llamar near_duplicate_ratio() por cuenta, pero el corpus de
    cada cuenta es siempre "todos los textos no vacíos del dataset" (non_empty
    de la cuenta + others). Vectorizando una única vez sobre ese corpus el
    resultado es numéricamente idéntico y se evita re-fitear el vectorizador
    N veces (1768 cuentas ≈ el 87% del tiempo de run_fimi en frontera_sur).
    """
    from collections import defaultdict
    threshold = config["thresholds"]["near_duplicate_threshold"]
    texts = df["text"].tolist()
    authors = df["author"].tolist()
    keep = [i for i, t in enumerate(texts) if (t or "").strip()]
    out = {a: 0.0 for a in set(authors)}
    if len(keep) < 2:
        return out
    pos_by_auth = defaultdict(list)
    corpus = []
    for i, idx in enumerate(keep):
        pos_by_auth[authors[idx]].append(i)
        corpus.append(texts[idx])
    try:
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, stop_words=None)
        X = normalize(vec.fit_transform(corpus))
    except Exception:
        return out
    N = X.shape[0]
    for a, mine in pos_by_auth.items():
        if len(mine) < 2:
            continue
        mset = set(mine)
        rest = np.array([i for i in range(N) if i not in mset], dtype=int)
        if rest.size == 0:
            continue
        sim = X[mine] @ X[rest].T
        sim = sim.toarray() if hasattr(sim, "toarray") else np.atleast_2d(sim)
        hits = (sim.max(axis=1) >= threshold).sum()
        out[a] = hits / len(mine)
    return out
