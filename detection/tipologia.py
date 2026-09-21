#!/usr/bin/env python3
"""Tipologia estructural de clusters (apoyo al analista FIMI).

Dado un cluster (o un tema, o todos), calcula rasgos ESTRUCTURALES a partir de
`cluster_events` y emite un `tipo` (indicio) + los rasgos + una lectura en una
linea. NO mide intencion ni atribuye autoría: describe la FORMA de la
amplificacion (que tipo de red parece, por su estructura).

Uso:
  python detection/tipologia.py --tema frontera_sur
  python detection/tipologia.py --cluster oriente_medio_cluster_053
  python detection/tipologia.py --all --min-score 60
  python detection/tipologia.py --tema elecciones --json
  python detection/tipologia.py --all --resumen
"""
import argparse
import collections
import json
import re
import sqlite3
import sys
import urllib.parse as up
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "radar.db"

try:
    from detection.mainstream import mainstream_frac
except Exception:
    def mainstream_frac(urls):
        return 0.0


# --- rasgos ---------------------------------------------------------------

def _host(url):
    try:
        return up.urlparse(url or "").netloc.replace("www.", "").lower()
    except Exception:
        return ""


def _boilerplate(texts, min_frac=0.5, n=5, min_chars=20):
    """Busca una frase (n-grama) repetida en >=min_frac de los textos.

    Devuelve (frase, fraccion) o None. Detecta pies/plantillas auto-generados.
    """
    toks = [re.findall(r"[a-z0-9áéíóúñü]+", (t or "").lower()) for t in texts]
    toks = [t for t in toks if len(t) >= n]
    if len(toks) < 3:
        return None
    cnt = collections.Counter()
    for tk in toks:
        for g in {" ".join(tk[i:i + n]) for i in range(len(tk) - n + 1)}:
            cnt[g] += 1
    if not cnt:
        return None
    frase, df = cnt.most_common(1)[0]
    if df >= min_frac * len(toks) and len(frase) >= min_chars:
        return (frase, df / len(toks))
    return None


def rasgos(evs, asm=None):
    """Rasgos estructurales de un conjunto de eventos (dict)."""
    n_ev = len(evs)
    autores = [(e["author"] or "").split(":", 1)[-1] for e in evs]
    cuentas = collections.Counter(a for a in autores if a)
    urls = [e["url"] for e in evs if e["url"]]
    doms = collections.Counter(_host(u) for u in urls if _host(u))
    ts = [e["ts"] for e in evs if e["ts"]]
    span_h = (max(ts) - min(ts)) / 3600.0 if len(ts) >= 2 else 0.0
    # URLs compartidas por >=2 cuentas distintas
    por_url = collections.defaultdict(set)
    for e in evs:
        if e["url"]:
            por_url[e["url"]].add((e["author"] or "").split(":", 1)[-1])
    same_url_max = max((len(v) for v in por_url.values()), default=0)
    dom_top, dom_n = (doms.most_common(1)[0] if doms else ("", 0))
    bp = _boilerplate([e["text"] or "" for e in evs])
    r = {
        "n_eventos": n_ev,
        "n_cuentas": len(cuentas),
        "n_urls": len(set(urls)),
        "span_h": round(span_h, 1),
        "dom_top": dom_top,
        "dom_top_share": round(dom_n / len(urls), 2) if urls else 0.0,
        "dom_unicos": len(doms),
        "mainstream_frac": round(mainstream_frac(urls), 2),
        "same_url_max": same_url_max,
        "boilerplate": ({"frase": bp[0], "frac": round(bp[1], 2)} if bp else None),
    }
    if asm is not None:
        try:
            r["kcore"] = asm["kcore"]
            r["kcore_size"] = asm["kcore_size"]
        except Exception:
            pass
    return r


def tipo_de(r):
    """(tipo_principal, flags, lectura) a partir de los rasgos."""
    f = []
    if r["mainstream_frac"] >= 0.8 and r["n_eventos"] >= 2:
        f.append("eco_prensa")
    if r["boilerplate"]:
        f.append("automatizado_plantilla")
    if r["dom_top_share"] >= 0.7 and r["n_cuentas"] >= 2 and r["n_urls"] >= 2:
        f.append("red_dominio_unico")
    if r["same_url_max"] >= 2:
        f.append("mismo_enlace_repetido")
    if r["n_urls"] <= 1 and r["n_eventos"] >= 2:
        f.append("eco_1_pieza")
    if r["n_cuentas"] >= 3 and r["n_urls"] >= 3:
        f.append("red_multidominio")
    if r.get("cross_tema"):
        f.append("cross_tema")
    if r["span_h"] >= 24 and r["n_eventos"] >= 10:
        f.append("sostenido")
    orden = ["eco_prensa", "automatizado_plantilla", "red_dominio_unico",
             "mismo_enlace_repetido", "eco_1_pieza", "red_multidominio"]
    tipo = next((t for t in orden if t in f), "senal_debil")

    def _lect(t):
        if t == "automatizado_plantilla":
            bp = r["boilerplate"] or {"frase": "", "frac": 0}
            return (f"textos con una plantilla comun ('{bp['frase'][:40]}…' en "
                    f"{int(bp['frac']*100)}%) → automatizado")
        if t == "red_dominio_unico":
            return f"{int(r['dom_top_share']*100)}% de los enlaces apuntan a un solo dominio ({r['dom_top']})"
        if t == "mismo_enlace_repetido":
            return f"un mismo enlace lo comparten hasta {r['same_url_max']} cuentas"
        if t == "eco_prensa":
            return f"{int(r['mainstream_frac']*100)}% de dominios son medios establecidos → eco de prensa"
        if t == "eco_1_pieza":
            return "una sola URL repetida → eco de 1 pieza"
        if t == "red_multidominio":
            return f"{r['n_cuentas']} cuentas amplificando {r['n_urls']} URLs distintas"
        return f"senal debil ({r['n_cuentas']} cuentas, {r['n_eventos']} eventos)"

    extra = [x for x in f if x != tipo]
    lectura = _lect(tipo) + ((" · " + ", ".join(extra)) if extra else "")
    return tipo, f, lectura


# --- carga ----------------------------------------------------------------

def cargar(conn, tema=None, cluster=None, min_score=0.0):
    q = ("SELECT c.id, c.cluster_label, c.tema_id, c.overall_score, "
         " a.kcore, a.kcore_size FROM clusters c "
         "LEFT JOIN assessments a ON a.cluster_id=c.id WHERE c.overall_score>=?")
    p = [min_score]
    if tema:
        q += " AND c.tema_id=?"; p.append(tema)
    if cluster:
        q += " AND c.cluster_label=?"; p.append(cluster)
    q += " ORDER BY c.tema_id, c.overall_score DESC"
    out = []
    for r in conn.execute(q, p):
        evs = conn.execute(
            "SELECT ts, author, url, text FROM cluster_events WHERE cluster_id=?",
            (r["id"],)).fetchall()
        if not evs:
            continue
        out.append({"label": r["cluster_label"], "tema": r["tema_id"],
                    "score": round(r["overall_score"] or 0, 1),
                    "evs": [dict(e) for e in evs],
                    "asm": r})
    return out


def mapa_cuentas(conn):
    """{cluster_label: set(cuentas)} y {tema: {cuenta: set(labels)}} para cross-tema."""
    por_tema = collections.defaultdict(lambda: collections.defaultdict(set))
    for r in conn.execute("SELECT id, cluster_label, tema_id FROM clusters"):
        cuentas = {(e["author"] or "").split(":", 1)[-1]
                   for e in conn.execute("SELECT author FROM cluster_events WHERE cluster_id=?", (r["id"],))}
        cuentas.discard("")
        for a in cuentas:
            por_tema[r["tema_id"]][a].add(r["cluster_label"])
    return por_tema


def cross_tema(label, tema, cuentas, por_tema):
    """¿Las cuentas de este cluster aparecen también en OTRO tema?"""
    otros = set()
    for t, mapa in por_tema.items():
        if t == tema:
            continue
        for a in cuentas:
            if a in mapa:
                otros.add(t)
    return sorted(otros)


# --- main -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Tipologia estructural de clusters FIMI")
    ap.add_argument("--tema")
    ap.add_argument("--cluster")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--min-score", type=float, default=0.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--resumen", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        por_tema = mapa_cuentas(conn)
        cl = cargar(conn, args.tema, args.cluster, args.min_score)
    finally:
        conn.close()

    res = []
    for c in cl:
        r = rasgos(c["evs"], c["asm"])
        cuentas = {(e["author"] or "").split(":", 1)[-1] for e in c["evs"]}
        cuentas.discard("")
        r["cross_tema"] = cross_tema(c["label"], c["tema"], cuentas, por_tema)
        tipo, flags, lectura = tipo_de(r)
        res.append({"cluster": c["label"], "tema": c["tema"], "score": c["score"],
                    "tipo": tipo, "flags": flags, "lectura": lectura, "rasgos": r})

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return
    if args.resumen:
        cnt = collections.Counter(x["tipo"] for x in res)
        print(f"Clusters analizados: {len(res)}")
        for t, n in cnt.most_common():
            print(f"  {t:24s} {n}")
        return
    for x in res:
        print(f"[{x['score']:5.1f}] {x['cluster']}  ({x['tema']})")
        print(f"        tipo: {x['tipo']}  | flags: {', '.join(x['flags'])}")
        print(f"        {x['lectura']}")
    print(f"\n{len(res)} clusters.", file=sys.stderr)


if __name__ == "__main__":
    main()
