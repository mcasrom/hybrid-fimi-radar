"""Cascadas de amplificación y deriva de micro-narrativa.

Objetivo: detectar propagación artificial de contenido (fake news / fakes).
Sin LLM. Señales:

  CASCADA: un mismo texto/base muy similar difundido por MANY cuentas en una
  ventana corta. Cuanto más rápido se propaga a más cuentas, más fuerte la señal.

  DERIVA DE NARRATIVA: una base textual que muta ligeramente a lo largo del
  tiempo (narrativa que se va adaptando) difundida por muchas cuentas.

  AMPLIFICACIÓN ARTIFICIAL: cluster de cuentas que comparten casi idéntico
  contenido pero casi nunca publican contenido propio original.

Salida honesta: "posible amplificación artificial de contenido", nunca
"campaña de desinformación de <país/partido>".
"""
from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def detect_cascades(df, config):
    """Detecta grupos de eventos con texto casi idéntico difundidos en ventana corta.

    Devuelve lista de dicts: {seed_text, n_accounts, n_events, time_span_s,
                               speed_accounts_hour, n_cluster}
    """
    near_thresh = config["thresholds"]["near_duplicate_threshold"]
    tight = config["thresholds"]["tight_timing_seconds"]

    texts = df["text"].tolist()
    min_len = config["features"].get("min_text_len", 10)
    idx = [i for i, t in enumerate(texts) if t.strip() and len(t.split()) >= min_len // 4]
    if len(idx) < 3:
        return []

    X = TfidfVectorizer(ngram_range=(1, 2), min_df=1).fit_transform([texts[i] for i in idx])
    sim = cosine_similarity(X)
    # clústeres de near-duplicates: un candidato se une si es similar a CUALQUIER
    # miembro ya asignado (enlace único transitivo).
    # members guarda POSICIONES en el espacio de idx (0..len(idx)-1), que son
    # las filas/columnas de sim.
    clusters = []
    assigned = set()
    n = len(idx)
    for i in range(n):
        if i in assigned:
            continue
        members = [i]
        assigned.add(i)
        for j in range(i + 1, n):
            if j in assigned:
                continue
            if any(sim[j][m_pos] >= near_thresh for m_pos in members):
                members.append(j)
                assigned.add(j)
        if len(members) >= config["thresholds"]["min_cluster_size"]:
            clusters.append([idx[m] for m in members])

    results = []
    for mem in clusters:
        sub = df.iloc[mem]
        accounts = sub["author"].nunique()
        n_events = len(sub)
        tspan = sub["ts"].max() - sub["ts"].min()
        # velocidad solo si hay ventana temporal real (evita división por cero)
        speed = (accounts / max(tspan / 3600, 1e-6)) if tspan > 0 else 0.0
        seed = sub["text"].iloc[0]
        # UNA CASCADA DE AMPLIFICACIÓN EXIGE VARIAS CUENTAS DISTINTAS:
        # una sola cuenta repitiendo su propio texto no es una cascada.
        min_acc = max(3, config["thresholds"]["min_cluster_size"])
        results.append({
            "seed_text": seed[:80],
            "n_accounts": accounts,
            "n_events": n_events,
            "time_span_s": int(tspan),
            "speed_accounts_hour": round(float(speed), 1),
            "anomalous": accounts >= min_acc and tspan <= 3600 * 24,
        })
    # solo devolver las que son cascadas reales (varias cuentas, ventana corta)
    return [r for r in results if r["anomalous"]]


def amplification_signal(edges_df, n_accounts_total):
    """Señal global de amplificación: densidad de cuentas conectadas por
    near_duplicate + share_ratio alto."""
    if edges_df.empty:
        return 0.0
    near_edges = edges_df[edges_df["evidence"].str.contains("near_duplicate", na=False)]
    if near_edges.empty:
        return 0.0
    connected = set(near_edges["source"]) | set(near_edges["target"])
    return min(1.0, len(connected) / max(n_accounts_total, 1) * 5)


def detect_narrative_amplification(df, config):
    """Detección de AMPLIFICACIÓN DE NARRATIVA (hecho observable, no atribución).

    Agrupa titulares casi idénticos compartidos por FUENTES/MEDIOS DISTINTOS
    en una ventana de tiempo. Distingue "una noticia se propaga" (amplificación)
    de "coordinación entre cuentas" (requiere historia acumulada).

    Devuelve lista de dicts: {seed, n_sources, n_events, time_span_s, sources}.
    NUNCA atribuye actor: solo dice qué narrativa se está amplificando y desde
    qué fuentes.
    """
    from collections import defaultdict
    near_thresh = config["thresholds"]["near_duplicate_threshold"]
    min_sources = max(3, config["thresholds"].get("min_amp_sources", 3))

    if df.empty or len(df) < min_sources:
        return []

    # normalizar texto: minúsculas, sin puntuación, sin espacios duplicados
    def norm(t):
        import re
        s = str(t).lower()
        s = re.sub(r"[^a-z0-9áéíóúñü ]", "", s)
        return re.sub(r"\s+", " ", s).strip()[:60]

    df = df.copy()
    df["_norm"] = df["text"].fillna("").astype(str).apply(norm)
    df = df[df["_norm"].str.len() >= 20]  # ignorar textos demasiado cortos
    if df.empty:
        return []

    # agrupar por texto normalizado
    groups = defaultdict(list)
    for _, r in df.iterrows():
        groups[r["_norm"]].append(r)

    results = []
    for norm_t, rows in groups.items():
        if len(rows) < min_sources:
            continue
        # fuentes DISTINTAS (no duplicados del mismo medio)
        sources = {}
        for r in rows:
            src = str(r["source"])
            # normalizar familia de fuente (El País RSS == El País)
            fam = _family(src)
            sources.setdefault(fam, []).append(r)
        distinct = len(sources)
        if distinct < min_sources:
            continue
        ts = [r["ts"] for r in rows]
        span = max(ts) - min(ts) if ts else 0
        results.append({
            "seed": rows[0]["text"][:80],
            "n_sources": distinct,
            "source_names": sorted(sources.keys()),
            "n_events": len(rows),
            "time_span_s": int(span),
            "window_hours": round(span / 3600, 1),
        })

    results.sort(key=lambda x: -x["n_sources"])
    return results


def _family(src):
    """Agrupa fuentes del mismo medio (El País RSS vs El País RSS 2, etc.)."""
    s = str(src).lower()
    if "elpais" in s or "el país" in s:
        return "El País"
    if "google" in s:
        return "Google News"
    if "bbc" in s:
        return "BBC"
    if "aljazeera" in s:
        return "Al Jazeera"
    if "elmundo" in s:
        return "El Mundo"
    if "faro" in s:
        return "El Faro Ceuta"
    if "melilla hoy" in s:
        return "Melilla Hoy"
    if "ceutatv" in s or "ceuta tv" in s:
        return "Ceuta TV"
    if "yabiladi" in s:
        return "Yabiladi"
    if "algerie360" in s:
        return "Algerie360"
    if "hespress" in s:
        return "Hespress"
    if "tsa" in s:
        return "TSA"
    if "ami mauritanie" in s:
        return "AMI"
    if "maldita" in s:
        return "Maldita"
    if "reddit" in s:
        return "Reddit"
    if "bsky" in s or "bluesky" in s:
        return "Bluesky"
    if "masto" in s:
        return "Mastodon"
    return s[:14]
