"""Grafo de coordinación entre cuentas — señales FUERTES primero.

Para no conectar el mundo entero (problema detectado en el test), las aristas
solo se crean cuando hay señal de coordinación REAL:

  SEÑAL FUERTE (crea arista directamente):
    - misma URL exacta compartida       (+same_url, peso alto)
    - texto casi idéntico (near-dup)    (+near_duplicate_text, peso alto)
    - ráfaga sincronizada               (+tight_timing, peso alto)

  SEÑAL DÉBIL (solo refuerza si YA hay otra señal):
    - mismo dominio compartido          (+same_domain)
    - mismo hashtag específico          (+same_hashtag)
    - mismo patrón de acción            (+same_action_pattern)

Así, dos cuentas que comparten un hashtag común (#elecciones) NO se conectan
si no tienen otra evidencia de coordinación.
"""
import itertools
from collections import defaultdict

import networkx as nx
import numpy as np


def build_edges(df, config):
    """Construye aristas entre cuentas con evidencia de coordinación.

    Solo se crean aristas entre cuentas de REDES SOCIALES (bluesky, telegram,
    reddit, mastodon). Los RSS de medios NO participan en el grafo de
    coordinación: son fuentes legítimas que cubren los mismos temas por
    periodismo, no por coordinación.
    """
    w = config["weights"]
    tight_seconds = config["thresholds"]["tight_timing_seconds"]
    near_thresh = config["thresholds"]["near_duplicate_threshold"]

    from features.content import extract_domain, extract_hashtags
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    # ---- filtro: solo redes sociales para grafo de coordinación ----
    SOCIAL_PREFIXES = ("bsky:", "tg:", "reddit:", "masto:")
    def is_social(author):
        return any(author.startswith(p) for p in SOCIAL_PREFIXES)

    # eventos agrupados por cuenta (solo redes sociales)
    acc_events = defaultdict(list)
    for _, row in df.iterrows():
        if is_social(row["author"]):
            acc_events[row["author"]].append(row)

    strong_links = defaultdict(float)      # (a,b) -> suma peso fuerte
    weak_links = defaultdict(set)          # (a,b) -> set de señales débiles
    strong_ev = defaultdict(set)

    # ---- 1) misma URL exacta (señal fuerte) ----
    url_accs = defaultdict(set)
    for author, rows in acc_events.items():
        for r in rows:
            u = (r["url"] or "").strip()
            if u:
                url_accs[u].add(author)
    for u, accs in url_accs.items():
        accs = list(accs)
        if len(accs) >= 2:
            for a, b in itertools.combinations(sorted(accs)[:15], 2):
                strong_links[(a, b)] += w["same_url"]
                strong_ev[(a, b)].add("same_url")

    # ---- 2) near-duplicate de texto (señal fuerte) ----
    acc_text = {}
    for a, rows in acc_events.items():
        ts = [r["text"] for r in rows if (r["text"] or "").strip()]
        if len(ts) >= 1:
            acc_text[a] = ts
    if acc_text:
        all_t = [t for ts in acc_text.values() for t in ts]
        try:
            vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
            X = vec.fit_transform(all_t)
            off = 0
            acc_vec = {}
            for a, ts in acc_text.items():
                Xa = X[off:off + len(ts)]
                acc_vec[a] = np.asarray(Xa.mean(axis=0)).ravel()
                off += len(ts)
            alist = list(acc_vec.keys())
            if len(alist) >= 2:
                import scipy.sparse as sp
                M = sp.csr_matrix(np.vstack([acc_vec[a] for a in alist]))
                sim = cosine_similarity(M)
                for i, a in enumerate(alist):
                    for j in range(i + 1, len(alist)):
                        if sim[i, j] >= near_thresh:
                            strong_links[(a, alist[j])] += w["near_duplicate_text"]
                            strong_ev[(a, alist[j])].add("near_duplicate_text")
        except Exception:
            pass

    # ---- 3) ráfaga sincronizada (señal fuerte) ----
    # Conecta cuentas que tienen ráfagas DENSAS reales: varios eventos propios
    # con intervalo < burst_int_s (los grupos de coordinación publican en ráfagas
    # de 2-8s; las cuentas normales tienen intervalos de horas).
    # Solo conectar si AMBAS cuentas tienen ráfagas densas.
    burst_int = config["thresholds"].get("burst_interval_s", 10)
    burst_min = config["thresholds"].get("burst_min_events", 5)

    def bursty(author):
        ts = sorted(r["ts"] for r in acc_events[author])
        if len(ts) < burst_min:
            return False
        intervals = [ts[i+1] - ts[i] for i in range(len(ts)-1)]
        short = sum(1 for d in intervals if d <= burst_int)
        return short >= burst_min

    # ---- 3) ráfaga sincronizada (señal fuerte) ----
    # Conecta cuentas con ráfagas densas reales (varios eventos propios con
    # intervalo < burst_int_s). Los grupos de coordinación publican en ráfagas
    # de pocos segundos; las cuentas normales tienen intervalos de horas.
    def bursty(author):
        ts = sorted(r["ts"] for r in acc_events[author])
        if len(ts) < burst_min:
            return False
        intervals = [ts[i+1] - ts[i] for i in range(len(ts)-1)]
        short = sum(1 for d in intervals if d <= burst_int)
        return short >= burst_min

    bursty_accs = {a for a in acc_events if bursty(a)}
    # conectar bursty SOLO si además comparten contenido (dominio o texto similar):
    # así las campañas de texto distinto (B vs F) no se mezclan por casualidad.
    dom_accs_t = defaultdict(set)
    for author in bursty_accs:
        for r in acc_events[author]:
            u = (r["url"] or "").strip()
            if u:
                d = extract_domain(u)
                if d:
                    dom_accs_t[d].add(author)
    linked_by_dom = set()
    for d, accs in dom_accs_t.items():
        accs = list(accs)
        for a, b in itertools.combinations(sorted(accs), 2):
            linked_by_dom.add((a, b))
    for a in bursty_accs:
        for b in bursty_accs:
            if a >= b:
                continue
            # mismo dominio compartido: señal de coordinación real
            if (a, b) in linked_by_dom:
                strong_links[(a, b)] += w["tight_timing"]
                strong_ev[(a, b)].add("tight_timing")
                strong_ev[(a, b)].add("same_domain")
            # si ambos son bursty y comparten texto near-dup, también
            elif "near_duplicate_text" in strong_ev.get((a, b), set()):
                strong_links[(a, b)] += w["tight_timing"]
                strong_ev[(a, b)].add("tight_timing")

    # ---- señales débiles (refuerzo) ----
    dom_accs = defaultdict(set)
    tag_accs = defaultdict(set)
    act_freq = {}
    for author, rows in acc_events.items():
        for r in rows:
            u = (r["url"] or "").strip()
            if u:
                d = extract_domain(u)
                if d:
                    dom_accs[d].add(author)
            for t in extract_hashtags(r["text"]):
                tag_accs[t].add(author)
        from collections import Counter
        c = Counter(r["action"].lower() for r in rows)
        act_freq[author] = tuple(sorted(c.items()))

    for dom, accs in dom_accs.items():
        accs = list(accs)
        if len(accs) >= 2:
            for a, b in itertools.combinations(sorted(accs)[:15], 2):
                if (a, b) in strong_links:
                    weak_links[(a, b)].add("same_domain")
    # hashtag: solo refuerza si es poco frecuente (específico de pocas cuentas)
    tag_counts = {t: len(a) for t, a in tag_accs.items()}
    for t, accs in tag_accs.items():
        accs = list(accs)
        if len(accs) >= 2 and len(accs) <= 30:
            for a, b in itertools.combinations(sorted(accs)[:15], 2):
                if (a, b) in strong_links:
                    weak_links[(a, b)].add("same_hashtag")
    freq_groups = defaultdict(list)
    for a, f in act_freq.items():
        freq_groups[f].append(a)
    for f, accs in freq_groups.items():
        if len(accs) >= 2:
            for a, b in itertools.combinations(sorted(accs)[:10], 2):
                if (a, b) in strong_links:
                    weak_links[(a, b)].add("same_action_pattern")

    # ---- ensamblar ----
    rows = []
    weak_w_map = {"same_domain": w["same_domain"], "same_hashtag": w["same_hashtag"],
                  "same_action_pattern": w["same_action_pattern"]}
    for (a, b), wstrong in strong_links.items():
        total = wstrong
        ev_set = set(strong_ev.get((a, b), set()))
        for lab in weak_links.get((a, b), set()):
            total += weak_w_map.get(lab, 0)
            ev_set.add(lab)
        rows.append({
            "source": a, "target": b, "weight": round(float(total), 2),
            "evidence": ";".join(sorted(ev_set)),
        })
    return rows


def build_graph(edges):
    g = nx.Graph()
    for e in edges:
        g.add_edge(e["source"], e["target"], weight=e["weight"], evidence=e["evidence"])
    return g
