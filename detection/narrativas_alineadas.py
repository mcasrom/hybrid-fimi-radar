#!/usr/bin/env python3
"""narrativas_alineadas.py — Capa transversal "cluster-of-clusters" (05/Sep).

El radar agrupa cuentas en clusters de coordinación, pero NO decía si varios
clusters (del mismo tema o de temas distintos) están contando la MISMA
narrativa. Esta capa une clusters cuya conversación es semánticamente cercana
usando TF-IDF + similitud coseno sobre el texto real de cada cluster
(cluster_events), sin servicios externos ni modelos pesados (sklearn, ya en el
venv).

Método (MVP, honesto):
  1. Para cada cluster ACTIVO se agregan los textos de sus eventos miembros.
  2. TfidfVectorizer (ngrams 1-2, min_df=1, sin stopwords de es/fr/en).
  3. Matriz de similitud coseno entre clusters.
  4. Union-find sobre similitud >= umbral => "narrativas alineadas"
     (cluster-of-clusters): varias cuentas de distintos grupos hablando de lo
     mismo NO es por sí solo una campaña, pero es la base estructural que un
     analista debe revisar (la exculpación de Marruecos puede repetirse en un
     cluster de Le Monde y en comentarios de política nacional).

Limitación documentada: TF-IDF capta solapamiento léxico (mismo idioma o
préstamos), NO la equivalencia semántica entre idiomas distintos (un texto en
francés y otro en español sobre el mismo asunto no conectan si no comparten
léxico). Es una capa de apoyo al analista, no un veredicto.
"""
import math
import sqlite3

_UMBRAL = 0.18          # similitud coseno mínima para alinear dos clusters
_MAX_GRUPOS = 8         # grupos que se muestran en el dashboard
_MIN_EVENTOS = 2        # clusters con <2 eventos no participan (ruido)

_STOP = frozenset(
    "el la los las un una unos unas de del que y o en a al con por para es son fue han ha su sus "
    "se le lo les entre como mas pero si no ya este esta estos estas ese esa eso yo tu mi mis "
    "nos os me te ser estar habia ha habido sobre desde hasta contra durante sin bajo segun porque "
    "cual cuando donde quien quienes cuyo como que cuan quien donde the and of to in for on with at "
    "by from as or an if but not et les des une du dans sur pour avec pas est sont aussi mais ce cet "
    "cette ces il elle nous vous ils elles y en un uno uma os as ao aos das dos do da para com por "
    "que se nao em no na nas nem mais mas como esta foram foi pelo pela".split())


def _padre(padres, x):
    while padres[x] != x:
        padres[x] = padres[padres[x]]
        x = padres[x]
    return x


def _unir(padres, a, b):
    ra, rb = _padre(padres, a), _padre(padres, b)
    if ra != rb:
        padres[rb] = ra


def detectar(conn, umbral=_UMBRAL, min_eventos=_MIN_EVENTOS, max_grupos=_MAX_GRUPOS):
    """Devuelve lista de narrativas alineadas (cluster-of-clusters) activas.

    Cada grupo: {label, miembros: [cluster_label...], n_clusters, n_eventos,
    n_cuentas, temas: [...], score_max, primeros_terminos: [...], ejemplos}.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except Exception:
        return []  # sklearn no disponible: la capa se omite sin romper nada

    ce = conn.execute(
        "SELECT ce.cluster_id, ce.text, cl.cluster_label, cl.tema_id,"
        " (SELECT COUNT(DISTINCT author) FROM cluster_events x WHERE x.cluster_id=ce.cluster_id) n_c"
        " FROM cluster_events ce JOIN clusters cl ON cl.id=ce.cluster_id"
        " ORDER BY ce.cluster_id").fetchall()
    if not ce:
        return []

    docs = {}       # cluster_id -> (label, tema, texto agregado)
    for r in ce:
        txt = (str(r["text"]) or "").strip()
        if not txt:
            continue
        e = docs.setdefault(r["cluster_id"], {
            "label": r["cluster_label"], "tema": r["tema_id"],
            "n_cuentas": r["n_c"], "textos": [], "n_eventos": 0})
        if len(e["textos"]) < 40:
            e["textos"].append(txt)
        e["n_eventos"] += 1

    ids = [cid for cid, e in docs.items() if e["n_eventos"] >= min_eventos]
    if len(ids) < 2:
        return []

    corpus = []
    for cid in ids:
        corpus.append(" ".join(docs[cid]["textos"]))

    try:
        vec = TfidfVectorizer(
            lowercase=True, strip_accents="unicode",
            ngram_range=(1, 2), min_df=1, max_features=4000,
            stop_words=list(_STOP), sublinear_tf=True)
        X = vec.fit_transform(corpus)
        # coseno = normalizar L2 y multiplicar
        Xn = X.copy()
        from sklearn.preprocessing import normalize as _norm
        Xn = _norm(X)
        S = (Xn @ Xn.T).toarray()
    except Exception:
        return []

    n = len(ids)
    padres = list(range(n))
    for i in range(n):
        for j in range(i + 1, n):
            if S[i][j] >= umbral:
                _unir(padres, i, j)

    grupos = {}
    for i in range(n):
        g = _padre(padres, i)
        grupos.setdefault(g, []).append(i)

    resultado = []
    for miembros_idx in grupos.values():
        if len(miembros_idx) < 2:
            continue
        mem = [ids[i] for i in miembros_idx]
        cluster_labels = [docs[m]["label"] for m in mem]
        temas = sorted({docs[m]["tema"] for m in mem})
        n_cuentas = sum(docs[m]["n_cuentas"] for m in mem)
        n_eventos = sum(docs[m]["n_eventos"] for m in mem)
        # términos más característicos del grupo (media de pesos TF-IDF)
        sub = X[miembros_idx]
        mean_w = sub.mean(axis=0).A1 if hasattr(sub.mean(axis=0), "A1") else sub.mean(axis=0)
        feats = vec.get_feature_names_out()
        top_idx = mean_w.argsort()[::-1][:6]
        terminos = [str(feats[k]) for k in top_idx]
        score_max = max(
            conn.execute("SELECT overall_score FROM clusters WHERE cluster_label=?",
                         (lab,)).fetchone()[0] or 0 for lab in cluster_labels)
        ejemplo = docs[mem[0]]["textos"][0][:140] if docs[mem[0]]["textos"] else ""
        resultado.append({
            "label": cluster_labels[0] if len(cluster_labels) == 1 else " + ".join(cluster_labels[:3]),
            "miembros": cluster_labels,
            "n_clusters": len(cluster_labels),
            "n_eventos": n_eventos,
            "n_cuentas": n_cuentas,
            "temas": temas,
            "score_max": round(float(score_max), 1),
            "terminos": terminos,
            "ejemplo": ejemplo,
        })

    resultado.sort(key=lambda g: (-g["n_clusters"], -g["n_eventos"]))
    return resultado[:max_grupos]


def _html(grupos):
    """Renderiza el bloque "Narrativas alineadas (cluster-of-clusters)"."""
    if not grupos:
        return ("<div class='card'><h3 style='margin:0 0 2px'>Narrativas alineadas "
                "(cluster-of-clusters)</h3><p class='caption'>Todavía no hay pares de "
                "clusters distintos hablando de la misma narrativa con solapamiento "
                "léxico suficiente (umbral de similitud coseno). Se recalcula cada 6h.</p></div>")
    items = ""
    for g in grupos:
        temas = ", ".join(g["temas"])
        mem = " · ".join(f"<code>{m}</code>" for m in g["miembros"])
        terms = ", ".join(f"<i>{t}</i>" for t in g["terminos"][:4])
        items += (f"<div style='border:1px solid #e2e8f0;border-radius:10px;padding:10px 14px;margin:8px 0'>"
                  f"<div style='display:flex;flex-wrap:wrap;align-items:center;gap:10px'>"
                  f"<b style='font-size:.9rem'>{g['label'][:70]}</b>"
                  f"<span style='font-size:.74rem;color:#475569'>grupos: {g['n_clusters']} clusters · "
                  f"{g['n_cuentas']} cuentas · {g['n_eventos']} eventos</span>"
                  f"<span style='font-size:.72rem;color:#78716c'>temas: {temas}</span></div>"
                  f"<div style='font-size:.76rem;color:#64748b;margin-top:4px'>hablan de: {terms}</div>"
                  f"<div style='font-size:.74rem;color:#94a3b8;margin-top:2px'>{mem}</div>"
                  f"<div style='font-size:.72rem;color:#9ca3af;margin-top:4px;font-style:italic'>"
                  f"ej.: {g['ejemplo'][:120]}…</div></div>")
    return (f"<div class='card'><h3 style='margin:0 0 2px'>Narrativas alineadas "
            f"(cluster-of-clusters)</h3>"
            f"<p class='caption'>Varios clusters distintos hablando de lo mismo con solapamiento léxico. "
            f"No implica una campaña: es la base estructural que el analista debe revisar (p. ej. la "
            f"misma historia en un cluster de un medio y en cuentas de otro tema). Detección TF-IDF "
            f"sobre el texto real de cada cluster.</p>{items}</div>")
