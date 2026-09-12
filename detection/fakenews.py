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
from sklearn.preprocessing import normalize


def _thresholded_adjacency(X, thresh, block=1024):
    """Listas de adyacencia de los pares con cosine >= thresh, sin densificar n×n.

    X: matriz TF-IDF sparse ya ajustada. Se normalizan filas (norma L2, igual que
    cosine_similarity) y se multiplica por bloques: cada bloque da un CSR de
    (block×n) que se umbrala al instante, de modo que la memoria pico queda
    acotada al bloque (no a n²). Se conserva solo el triángulo superior (la
    similitud es simétrica) y se devuelve una lista de vecinos por nodo.
    """
    Xn = normalize(X)
    n = Xn.shape[0]
    adj = [[] for _ in range(n)]
    for i0 in range(0, n, block):
        i1 = min(i0 + block, n)
        S = (Xn[i0:i1] @ Xn.T).tocsr()
        S.data = np.where(S.data >= thresh, 1.0, 0.0)
        S.eliminate_zeros()
        for r in range(i1 - i0):
            gi = i0 + r
            cols = S.indices[S.indptr[r]:S.indptr[r + 1]]
            for c in cols:
                if c > gi:  # solo triángulo superior; espejo a la fila del colega
                    adj[gi].append(c)
                    adj[c].append(gi)
    return adj


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

    cand = [texts[i] for i in idx]
    X = TfidfVectorizer(ngram_range=(1, 2), min_df=1).fit_transform(cand)
    # Similitud UMBRALADA por bloques (memoria acotada, 12/sept): materializar la
    # matriz densa n×n de cosine_similarity (n≈23k en frontera_sur) costaba ~4.3 GB
    # y provocaba OOM en el server (3.4 GB RAM). Se calcula el producto por bloques
    # y se retienen SOLO los pares con sim >= near_thresh. Los clusters de
    # near-duplicates quedan como componentes conexas de ese grafo, que es
    # matemáticamente idéntico al enlace transitivo "similar a CUALQUIER miembro".
    adj = _thresholded_adjacency(X, near_thresh, block=1024)

    # clústeres de near-duplicates: una componente conexa = conjunto de textos que
    # se unen transitivamente por similitud >= umbral. members guarda POSICIONES en
    # el espacio de idx (0..len(idx)-1), como antes con las filas de sim.
    clusters = []
    seen = [False] * len(adj)
    min_cluster = config["thresholds"]["min_cluster_size"]
    for i in range(len(adj)):
        if seen[i]:
            continue
        stack = [i]
        seen[i] = True
        members = []
        while stack:
            v = stack.pop()
            members.append(v)
            for u in adj[v]:
                if not seen[u]:
                    seen[u] = True
                    stack.append(u)
        if len(members) >= min_cluster:
            clusters.append([idx[m] for m in sorted(members)])

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
        # muestra de eventos completos (texto entero + fuente + url) para poder
        # leer la narrativa real, no solo el titular truncado
        sample = []
        seen_txt = set()
        for r in rows[:6]:
            txt = str(r.get("text") or "")
            url = str(r.get("url") or "")
            if txt[:40] in seen_txt:
                continue
            seen_txt.add(txt[:40])
            sample.append({
                "texto": txt,
                "fuente": str(r.get("source") or ""),
                "url": url,
                "ts": int(r["ts"]),
            })
        results.append({
            "seed": rows[0]["text"][:80],
            "n_sources": distinct,
            "source_names": sorted(sources.keys()),
            "n_events": len(rows),
            "time_span_s": int(span),
            "window_hours": round(span / 3600, 1),
            "eventos": sample,
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
