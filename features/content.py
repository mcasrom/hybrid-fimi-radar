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
    """Ratios near-dup de TODAS las cuentas en una pasada de TF-IDF SIN densificar.

    Para cada texto del corpus se calcula si tiene algún vecino con coseno >=
    umbral **de otra cuenta** (near-dup externo). El producto X·Xᵀ se hace por
    bloques y se umbrala al instante (patrón de `detection/fakenews._thresholded_
    adjacency`), de modo que la memoria pico queda acotada al bloque y NO se
    materializa la matriz densa m×(N-m).

    BUG corregido 15/09/2026 (profiling de memoria): la versión anterior hacía
    `sim.toarray()` sobre `X[mine] @ X[rest].T`; con una cuenta de miles de
    eventos eso era una matriz densa de ~2,5 GB y >5 min → era el pico real del
    paso [2/7] Features de run_fimi (3,18 GB), no coordinación/cascadas.
    """
    from collections import defaultdict
    threshold = config["thresholds"]["near_duplicate_threshold"]
    texts = df["text"].tolist()
    authors = df["author"].tolist()
    keep = [i for i, t in enumerate(texts) if (t or "").strip()]
    out = {a: 0.0 for a in set(authors)}
    if len(keep) < 2:
        return out
    auth_of = [authors[i] for i in keep]
    corpus = [texts[i] for i in keep]
    try:
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, stop_words=None)
        X = normalize(vec.fit_transform(corpus))
    except Exception:
        return out
    n = X.shape[0]
    pos_by_auth = defaultdict(list)
    for pos, a in enumerate(auth_of):
        pos_by_auth[a].append(pos)
    # por bloques de filas: vecinos >= umbral al instante (sin densificar)
    has_ext = np.zeros(n, dtype=bool)
    block = 1024
    for i0 in range(0, n, block):
        i1 = min(i0 + block, n)
        S = (X[i0:i1] @ X.T).tocsr()
        S.data = np.where(S.data >= threshold, 1.0, 0.0)
        S.eliminate_zeros()
        for r in range(i1 - i0):
            gi = i0 + r
            a_gi = auth_of[gi]
            cols = S.indices[S.indptr[r]:S.indptr[r + 1]]
            for c in cols:
                if c != gi and auth_of[c] != a_gi:
                    has_ext[gi] = True
                    break
    for a, poss in pos_by_auth.items():
        m = len(poss)
        if m >= 2:
            out[a] = float(has_ext[poss].sum()) / m
    return out
