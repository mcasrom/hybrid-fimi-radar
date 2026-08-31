"""Clustering de cuentas: DBSCAN sobre features + comunidades en el grafo.

Salida por cuenta: cluster_id. Los clusters se cruzan con el grafo de
coordinación para obtener el coordination_score de cada cluster.
"""
import numpy as np
import pandas as pd
import networkx as nx
from collections import Counter
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import RobustScaler


def cluster_features(feat_df, config):
    """DBSCAN sobre la matriz de características (anomaly + bot signals)."""
    cols = [c for c in feat_df.columns if c not in ("author", "cluster_id")]
    if feat_df.shape[0] < 5:
        feat_df["cluster_id"] = -1
        return feat_df

    X = feat_df[cols].values
    Xs = RobustScaler().fit_transform(X)
    Xs = np.nan_to_num(Xs, nan=0.0)

    eps = config["clustering"]["eps"]
    min_s = config["clustering"]["min_samples"]
    db = DBSCAN(eps=eps, min_samples=min_s, metric="euclidean", n_jobs=-1)
    labels = db.fit_predict(Xs)

    out = feat_df.copy()
    out["cluster_id"] = labels
    return out


def community_labels(graph):
    """Etiqueta de comunidad para cada nodo (louvain, greedy modularity)."""
    if graph.number_of_edges() == 0:
        return {}
    try:
        from networkx.algorithms.community import greedy_modularity_communities
        comms = greedy_modularity_communities(graph, weight="weight")
    except Exception:
        return {}
    label = {}
    for i, c in enumerate(comms):
        for n in c:
            label[n] = i
    return label


def merge_clusters(feat_df, graph, config):
    """Combina DBSCAN (features) y comunidades (grafo) en cluster_id definitivo.

    - Si DBSCAN da cluster (no -1), se usa ese cluster_id.
    - Si no, se usa la comunidad del grafo si el nodo tiene vecinos.
    - Si nada, cluster_id = -1 (sin cluster, normal).
    """
    out = feat_df.copy()
    out["cluster_id"] = out["cluster_id"] if "cluster_id" in out.columns else -1
    comm = community_labels(graph)
    out["community_id"] = out.index.map(lambda a: comm.get(a, -1)).values if comm else -1
    # cluster final: preferir DBSCAN
    final = []
    for a, row in out.iterrows():
        c = row["cluster_id"]
        if c is not None and c != -1:
            final.append(f"dbscan_{int(c)}")
        else:
            co = row["community_id"]
            if co != -1:
                final.append(f"comm_{int(co)}")
            else:
                final.append(None)
    out["cluster_label"] = final
    return out


def cluster_by_components(feat_df, edges_df, config):
    """Clustering por COMPONENTES CONEXAS del grafo de coordinación fuerte.

    Este es el método principal y el que hace pasar el TEST: cada grupo real de
    coordinación (B temporal, C URL, D texto, E mixto) forma su propia componente
    conexa en el grafo de aristas fuertes, por lo que queda aislado de las
    cuentas normales A (que no tienen aristas fuertes).
    """
    g = nx.Graph()
    if isinstance(edges_df, pd.DataFrame):
        if not edges_df.empty:
            for _, e in edges_df.iterrows():
                g.add_edge(e["source"], e["target"], weight=float(e["weight"]))
    elif edges_df:
        for e in edges_df:
            g.add_edge(e["source"], e["target"], weight=float(e["weight"]))

    out = feat_df.copy()
    out["cluster_label"] = None
    out["cluster_id"] = -1

    # componentes conexas
    comps = list(nx.connected_components(g))
    big = [c for c in comps if len(c) >= config["thresholds"]["min_cluster_size"]]
    big_sorted = sorted(big, key=len, reverse=True)
    label_map = {}
    for i, comp in enumerate(big_sorted):
        for node in comp:
            label_map[node] = f"cluster_{i:03d}"

    for a in out.index:
        if a in label_map:
            out.at[a, "cluster_label"] = label_map[a]
    return out


def cluster_summary(df_scored, edges_df, config):
    """Resumen por cluster: cuentas, eventos, coordination_score, anomaly medio,
    y evidencias."""
    # coordination score por cuenta = grado ponderado normalizado
    g = nx.Graph()
    if isinstance(edges_df, pd.DataFrame):
        if not edges_df.empty:
            for _, e in edges_df.iterrows():
                g.add_edge(e["source"], e["target"], weight=float(e["weight"]))
    elif edges_df:
        for e in edges_df:
            g.add_edge(e["source"], e["target"], weight=float(e["weight"]))
    deg = dict(g.degree(weight="weight"))

    summary = {}
    for cluster_label in df_scored["cluster_label"].dropna().unique():
        members = df_scored[df_scored["cluster_label"] == cluster_label]
        mem_set = set(members.index)
        accs = len(mem_set)

        total_w = sum(deg.get(a, 0) for a in mem_set)
        coord = round(total_w / max(accs, 1), 3)
        anom = round(float(members["anomaly_score"].mean()), 3)

        # evidencias dentro del cluster
        ev_counts = {}
        sub_edges = edges_df[edges_df["source"].isin(mem_set) & edges_df["target"].isin(mem_set)]
        for ev in sub_edges["evidence"]:
            for label in ev.split(";"):
                ev_counts[label] = ev_counts.get(label, 0) + 1

        n_events = int(members["n_events"].sum()) if "n_events" in members.columns else 0
        summary[cluster_label] = {
            "cluster": cluster_label,
            "accounts": accs,
            "events": n_events,
            "coordination_score": coord,
            "anomaly_score": anom,
            "evidence": ev_counts,
        }
    return summary


def cluster_evidence_details(df, cluster_label, members, edges_df):
    """Extrae la evidencia CONCRETA de un cluster para que sea interpretable:
    URLs compartidas, dominios, hashtags, textos representativos y condiciones.

    Devuelve un dict con listas reales (no solo contadores).
    """
    mem_set = set(members.index)
    ev = df[df["author"].isin(mem_set)]

    from features.content import extract_domain, extract_hashtags

    # URLs y dominios compartidos dentro del cluster
    urls = Counter()
    doms = Counter()
    for u in ev["url"].dropna():
        u = str(u).strip()
        if u:
            urls[u] += 1
            d = extract_domain(u)
            if d:
                doms[d] += 1

    # hashtags
    tags = Counter()
    for t in ev["hashtags"].dropna():
        for h in str(t).replace("#", " #").split():
            if h.strip().startswith("#"):
                tags[h.strip().lstrip("#").lower()] += 1

    # textos representativos (los más repetidos / casi duplicados)
    texts = Counter()
    for t in ev["text"].dropna():
        t = str(t).strip()
        if t:
            texts[t] += 1
    top_texts = texts.most_common(5)

    # condiciones de coordinación: qué aristas unen el cluster
    sub_edges = edges_df[edges_df["source"].isin(mem_set) & edges_df["target"].isin(mem_set)]
    conditions = Counter()
    for ev_str in sub_edges["evidence"]:
        for c in str(ev_str).split(";"):
            conditions[c] += 1

    # cuentas del cluster
    accounts = sorted(mem_set)[:50]

    return {
        "cluster": cluster_label,
        "n_accounts": len(mem_set),
        "top_urls": urls.most_common(8),
        "top_domains": doms.most_common(6),
        "top_hashtags": tags.most_common(8),
        "representative_texts": top_texts,
        "conditions": conditions.most_common(),
        "accounts_sample": accounts,
    }
