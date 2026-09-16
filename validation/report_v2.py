"""Informe v2 — validación independiente POR CUENTA (Fase 1). CAPA DE TRANSPARENCIA.

NO es atribución ni ground truth. Mide, para cada cluster, cuántas CUENTAS
coordinan por encima del azar (z>=Z_MIN en >=MIN_DIMS dimensiones) y el tamaño del
CORE conexo; lo compara con el overall_score del radar SOLO para señalar
discrepancias a revisión humana. Corrige la dilución de la Fase 0 (fracción de
todos los pares).

Salida: reports/validation_v2_<fecha>.{md,csv}
Uso:   .venv/bin/python validation/report_v2.py
"""
import csv
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from validation import loader
from validation.account_metrics import DIMS, author_pairs, largest_component, per_account_z

ROOT = Path("/home/deploy/hybrid-fimi-radar")
SEED = 42
B = 50
Z_MIN = 1.5
MIN_DIMS = 1
CAP = 90
DISCLAIMER = ("Capa de discrepancias y consistencia POR CUENTA. NO es atribución ni "
              "validación externa (no hay ground truth). Señala dónde el radar y una "
              "medida independiente (exceso por cuenta sobre un nulo de autor) NO "
              "coinciden, para revisión humana.")


def band_of(s):
    s = s or 0
    return ("CRITICAL" if s >= 80 else "HIGH" if s >= 60 else
            "ANOMALOUS" if s >= 40 else "WATCH" if s >= 20 else "NORMAL")


def category(s):
    return ("NO_SIGNAL" if s < 20 else "WEAK_SIGNAL" if s < 40 else
            "MODERATE_SIGNAL" if s < 60 else "STRONG_SIGNAL")


def score_from_core(core):
    """Score independiente a partir del tamaño del CORE coordinado (nº de cuentas)."""
    if core <= 0:
        return 0
    if core == 1:
        return 30
    if core == 2:
        return 45
    if core <= 4:
        return 60
    if core <= 7:
        return 75
    return 90


def comparison(radar, indep, cat):
    if cat == "AMBIGUOUS":
        return cat
    r, i = radar or 0, indep or 0
    if r >= 60 and i >= 60:
        return "STRONG_SUPPORTED"
    if r >= 60 and i <= 39:
        return "POSSIBLE_FALSE_POSITIVE"
    if r < 60 and i >= 60:
        return "POSSIBLE_FALSE_NEGATIVE"
    if r < 40 and i < 40:
        return "CONSISTENT_LOW"
    return "UNCERTAIN"


def eligible(conn, min_ev=5, min_acc=3):
    conn.row_factory = None
    return [dict(zip(("label", "tema", "radar", "n", "a"), r)) for r in conn.execute(
        "SELECT c.cluster_label, c.tema_id, c.overall_score, COUNT(ce.id) n,"
        " COUNT(DISTINCT ce.author) a FROM clusters c JOIN cluster_events ce"
        " ON ce.cluster_id=c.id GROUP BY c.id HAVING n>=? AND a>=?",
        (min_ev, min_acc)).fetchall()]


def analyze(ev):
    authors = sorted({e.get("author") for e in ev if e.get("author")})
    zs, sat = {}, 0
    for d in DIMS:
        _, z, s = per_account_z(ev, d, B=B, seed=SEED)
        zs[d], sat = z, sat + s
    coord = [a for a in authors
             if sum(1 for d in DIMS if zs[d].get(a) is not None and zs[d][a] >= Z_MIN) >= MIN_DIMS]
    edges = set()
    for d in DIMS:
        edges |= author_pairs(ev, d)
    core = largest_component(coord, edges)
    cores_by_dim = {d: sum(1 for a in authors if zs[d].get(a) is not None and zs[d][a] >= Z_MIN)
                    for d in DIMS}
    ambiguous = (len(coord) == 0 and len(authors) > 0 and sat >= len(authors))
    return {"n_coord": len(coord), "core": core, "sat": sat, "by_dim": cores_by_dim,
            "ambiguous": ambiguous}


def main():
    conn = loader.connect_ro()
    out = []
    for c in eligible(conn):
        ev = loader.load_cluster_events(c["label"], conn)
        if not ev:
            continue
        ev = ev[:CAP]
        if len(ev) < 5 or len({e.get("author") for e in ev if e.get("author")}) < 3:
            out.append({**c, "core": 0, "n_coord": 0, "sat": 0, "by_dim": {},
                        "indep": "", "cat": "INSUFFICIENT_DATA", "cmp": "INSUFFICIENT_DATA"})
            continue
        r = analyze(ev)
        indep = score_from_core(r["core"])
        cat = "AMBIGUOUS" if r["ambiguous"] else category(indep)
        out.append({**c, "core": r["core"], "n_coord": r["n_coord"], "sat": r["sat"],
                    "by_dim": r["by_dim"], "indep": indep, "cat": cat,
                    "cmp": comparison(c["radar"], indep, cat)})

    from collections import Counter
    cc = Counter(o["cmp"] for o in out)
    fecha = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M")
    d = ROOT / "reports"
    d.mkdir(exist_ok=True)
    md = [f"# Validación independiente por cuenta (v2) — {fecha}", "",
          f"> {DISCLAIMER}", "",
          f"Clusters elegibles: **{len(out)}** (n>=5 eventos, >=3 autores). "
          f"seed={SEED} · B={B} · z_min={Z_MIN} · dims_para_coordinar={MIN_DIMS}",
          f"CORE = mayor componente conexa entre las cuentas coordinadas (unión de "
          f"enlaces tiempo/contenido/url). Score independiente = f(core).", "",
          "## Resumen por veredicto", ""]
    for k, v in cc.most_common():
        md.append(f"- {k}: **{v}**")
    md += ["", "## Detalle", "",
           "| cluster | tema | radar | band | core | n_coord | idx_sync/sim/dens | indep | veredicto |",
           "|---|---|---|---|---|---|---|---|---|"]
    for o in sorted(out, key=lambda x: -x["radar"]):
        bd = o["by_dim"] or {}
        idx = f"{bd.get('temporal_sync','-')}/{bd.get('content_similarity','-')}/{bd.get('network_density','-')}"
        md.append(f"| {o['label']} | {o['tema']} | {o['radar']:.0f} | {band_of(o['radar'])} | "
                  f"{o['core']} | {o['n_coord']} | {idx} | {o['indep']} | {o['cmp']} |")
    (d / f"validation_v2_{fecha}.md").write_text("\n".join(md), encoding="utf-8")
    with open(d / f"validation_v2_{fecha}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["cluster", "tema", "radar", "banda", "core", "n_coord",
                    "core_sync", "core_sim", "core_dens", "independent", "veredicto"])
        for o in out:
            bd = o["by_dim"] or {}
            w.writerow([o["label"], o["tema"], f"{o['radar']:.0f}", band_of(o["radar"]),
                        o["core"], o["n_coord"], bd.get("temporal_sync"),
                        bd.get("content_similarity"), bd.get("network_density"),
                        o["indep"], o["cmp"]])
    print(f"OK — {len(out)} clusters · {dict(cc)}")
    print(f"informes: {d}/validation_v2_{fecha}.md · .csv")


if __name__ == "__main__":
    main()
