"""Informe de discrepancias radar vs consistencia independiente (Fase 0, congelado).

CAPA DE TRANSPARENCIA — NO es atribución ni validación externa. Lee solo eventos
reales; el overall_score del radar se usa SOLO para comparar.
Salida: reports/validation_<fecha>.{md,csv}
"""
import csv
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from validation import loader, nullmodel
from validation.dimensions import DIMS, intra_ratio

ROOT = Path("/home/deploy/hybrid-fimi-radar")
SEED = 42
B = 200
W = {"temporal_sync": 1 / 3, "content_similarity": 1 / 3, "network_density": 1 / 3}
DISCLAIMER = ("Capa de discrepancias y consistencia. NO es atribución ni validación "
              "externa (no hay ground truth). Señala dónde el radar y una medida "
              "independiente basada en eventos NO coinciden, para revisión humana.")


def band_of(s):
    s = s or 0
    return ("CRITICAL" if s >= 80 else "HIGH" if s >= 60 else
            "ANOMALOUS" if s >= 40 else "WATCH" if s >= 20 else "NORMAL")


def score_from_z(z):
    return max(0, min(100, round(50 + 16.6 * z)))


def category(s):
    return ("NO_SIGNAL" if s < 20 else "WEAK_SIGNAL" if s < 40 else
            "MODERATE_SIGNAL" if s < 60 else "STRONG_SIGNAL")


def comparison(radar, indep, cat, intra):
    if cat in ("INSUFFICIENT_DATA", "AMBIGUOUS"):
        return cat
    if radar >= 60 and indep >= 60:
        return "STRONG_SUPPORTED"
    if radar >= 60 and indep <= 39:
        return "POSSIBLE_FALSE_POSITIVE"
    if radar < 60 and indep >= 60:
        return "POSSIBLE_FALSE_NEGATIVE"
    if radar < 40 and indep < 40:
        return "CONSISTENT_LOW"
    return "UNCERTAIN"


def eligible(conn, min_ev=5, min_acc=3):
    conn.row_factory = None
    return [dict(zip(("label", "tema", "radar", "n", "a"), r)) for r in conn.execute(
        "SELECT c.cluster_label, c.tema_id, c.overall_score, COUNT(ce.id) n,"
        " COUNT(DISTINCT ce.author) a FROM clusters c JOIN cluster_events ce"
        " ON ce.cluster_id=c.id GROUP BY c.id HAVING n>=? AND a>=?",
        (min_ev, min_acc)).fetchall()]


def main():
    conn = loader.connect_ro()
    pool = eligible(conn)
    out = []
    for c in pool:
        ev = loader.load_cluster_events(c["label"], conn)
        if not ev:
            continue
        n_acc = len(set(e.get("author") for e in ev if e.get("author")))
        if len(ev) < 5 or n_acc < 3:
            out.append({**c, "cat": "INSUFFICIENT_DATA", "indep": "", "intra": "",
                        "cmp": "INSUFFICIENT_DATA", "zs": {}})
            continue
        ev = ev[:150]
        zres, amb = {}, 0
        for d, (fn, k) in DIMS.items():
            _, _, std, z = nullmodel.excess(fn, ev, kind=k, B=B, seed=SEED)
            a = std < 1e-9
            amb += a
            zres[d] = (z, a)
        if amb == len(DIMS):
            indep, cat = None, "AMBIGUOUS"
        else:
            den = sum(W[d] for d, (z, a) in zres.items() if not a)
            indep = round(sum(score_from_z(z) * W[d] for d, (z, a) in zres.items()
                              if not a) / den)
            cat = category(indep)
        intra = intra_ratio(ev)
        if cat not in ("AMBIGUOUS", "INSUFFICIENT_DATA") and intra > 0.7:
            indep = min(indep, 39)
            cat = "WEAK_SIGNAL"
        cmp_ = comparison(c["radar"], indep if indep is not None else 0, cat, intra)
        out.append({**c, "cat": cat, "indep": indep, "intra": round(intra, 2),
                    "cmp": cmp_, "zs": {d: round(z, 1) for d, (z, a) in zres.items()}})

    # resumen
    from collections import Counter
    cc = Counter(o["cmp"] for o in out)
    fecha = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M")
    d = ROOT / "reports"
    d.mkdir(exist_ok=True)
    md = [f"# Informe de discrepancias radar vs consistencia — {fecha}",
          "", f"> {DISCLAIMER}", "",
          f"Clusters elegibles analizados: **{len(out)}** (n>=5 eventos y >=3 autores).",
          f"Seed={SEED} · B={B} · pesos independent={W}", "",
          "## Resumen por veredicto", ""]
    for k, v in cc.most_common():
        md.append(f"- {k}: **{v}**")
    md += ["", "## Detalle", "",
           "| cluster | tema | radar | band | indep | cat | intra | veredicto |",
           "|---|---|---|---|---|---|---|---|"]
    for o in sorted(out, key=lambda x: -x["radar"]):
        md.append(f"| {o['label']} | {o['tema']} | {o['radar']:.0f} | "
                  f"{band_of(o['radar'])} | {o['indep']} | {o['cat']} | "
                  f"{o['intra']} | {o['cmp']} |")
    (d / f"validation_{fecha}.md").write_text("\n".join(md), encoding="utf-8")
    with open(d / f"validation_{fecha}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["cluster", "tema", "radar", "banda", "independent", "categoria",
                    "intra_ratio", "veredicto", "z_sync", "z_sim", "z_dens"])
        for o in out:
            w.writerow([o["label"], o["tema"], f"{o['radar']:.0f}", band_of(o["radar"]),
                        o["indep"], o["cat"], o["intra"], o["cmp"],
                        o["zs"].get("temporal_sync"), o["zs"].get("content_similarity"),
                        o["zs"].get("network_density")])
    print(f"OK — {len(out)} clusters · {dict(cc)}")
    print(f"informes: {d}/validation_{fecha}.md · .csv")


if __name__ == "__main__":
    main()
