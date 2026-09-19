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


def near_duplicate_ratio_all(df, config):
    """Versión vectorizada: calcula near_duplicate_ratio para TODAS las cuentas
    en una sola pasada TF-IDF + producto por bloques sin densificar.

    Evita O(A·n) scans + A veces fit_transform + matriz densa mine×rest.
    Retorna dict author -> ratio."""
    import scipy.sparse as sp

    threshold = config["thresholds"]["near_duplicate_threshold"]
    if df.empty:
        return {}

    # Agrupar textos no vacíos por autor (una pasada)
    grouped = {}
    for author, g in df.groupby("author"):
        ts = [t for t in g["text"].tolist() if t and t.strip()]
        if len(ts) >= 2:
            grouped[author] = ts
    if not grouped:
        return {a: 0.0 for a in df["author"].unique()}

    # Corpus único: todos los textos no vacíos con índice por autor
    all_texts = []
    author_slices = {}  # author -> (start, end) en all_texts
    off = 0
    for author, ts in grouped.items():
        author_slices[author] = (off, off + len(ts))
        all_texts.extend(ts)
        off += len(ts)

    try:
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, stop_words=None)
        X = vec.fit_transform(all_texts)  # N x Vocab, dispersa
    except Exception:
        return {a: 0.0 for a in df["author"].unique()}

    # Normalizar filas L2 para que producto = coseno
    from sklearn.preprocessing import normalize

    Xn = normalize(X, norm="l2", axis=1)

    result = {a: 0.0 for a in df["author"].unique()}
    block = 1024
    for author, (s, e) in author_slices.items():
        mine = Xn[s:e]  # m x Vocab
        m = mine.shape[0]
        # construir matriz complementaria sin copiar todo si es grande: usar blocos
        # Índices del resto
        rest_mask = list(range(0, s)) + list(range(e, Xn.shape[0]))
        if not rest_mask:
            result[author] = 0.0
            continue
        hits = 0
        # producto por bloques para evitar densificar m x (N-m)
        for b0 in range(0, len(rest_mask), block):
            b1 = min(b0 + block, len(rest_mask))
            rest_block = Xn[rest_mask[b0:b1]]
            # mine (m x Voc) @ rest_block.T (Voc x bsize) -> m x bsize dispersa
            sim_block = mine @ rest_block.T
            # umbralar y eliminar ceros al instante
            sim_block.data[sim_block.data < threshold] = 0
            sim_block.eliminate_zeros()
            # para cada fila, si tiene algún 1 -> hit
            # sim_block es CSR
            hits_block = (sim_block.getnnz(axis=1) > 0)
            # acumular: fila hit si alguna vez tuvo sim >= thresh
            if b0 == 0:
                hit_mask = hits_block
            else:
                hit_mask = hit_mask | hits_block
            if hit_mask.all():
                break
        result[author] = float(hit_mask.sum()) / m if m else 0.0
    return result
