"""SPIKE v2 (Fase 0): validador mínimo sobre clusters REALES con datos suficientes.

Cambios v2: métrica por umbral · penalización de eco intra-cuenta · muestreo solo
de clusters con n>=5 y autores>=3. Solo lectura. No escribe nada.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from validation import loader, nullmodel
from validation.dimensions import DIMS, intra_ratio

BANDS = ["CRITICAL", "HIGH", "ANOMALOUS", "WATCH", "NORMAL"]
SEED = 42
B = 200
PER_BAND = 6
W = {"temporal_sync": 1 / 3, "content_similarity": 1 / 3, "network_density": 1 / 3}  # pesos propios (iguales, documentados)


def band_of(score):
    s = score or 0
    return ("CRITICAL" if s >= 80 else "HIGH" if s >= 60 else
            "ANOMALOUS" if s >= 40 else "WATCH" if s >= 20 else "NORMAL")


def score_from_z(z):
    return max(0, min(100, round(50 + 16.6 * z)))


def category(s):
    return ("NO_SIGNAL" if s < 20 else "WEAK_SIGNAL" if s < 40 else
            "MODERATE_SIGNAL" if s < 60 else "STRONG_SIGNAL")


def eligible_clusters(conn, min_ev=5, min_acc=3):
    rows = conn.execute(
        "SELECT c.cluster_label, c.tema_id, c.overall_score, COUNT(ce.id) n,"
        " COUNT(DISTINCT ce.author) a FROM clusters c JOIN cluster_events ce"
        " ON ce.cluster_id=c.id GROUP BY c.id HAVING n>=? AND a>=?",
        (min_ev, min_acc)).fetchall()
    conn.row_factory = None
    return [{"cluster_label": r[0], "tema_id": r[1], "overall_score": r[2],
             "n": r[3], "a": r[4]} for r in rows]


def main():
    conn = loader.connect_ro()
    conn.row_factory = None
    pool = eligible_clusters(conn)
    by_band = {}
    for c in pool:
        by_band.setdefault(band_of(c["overall_score"]), []).append(c)
    rng = random.Random(SEED)
    sample = []
    for band in BANDS:
        p = by_band.get(band, [])
        rng.shuffle(p)
        sample += p[:PER_BAND]

    print(f"SPIKE v2 — {len(sample)} clusters con datos suficientes (de {len(pool)})"
          f" · seed={SEED} · B={B} · pesos independent={W}")
    print(f"{'cluster':<30}{'tema':<13}{'radar':>6}{'band':>10}{'indep':>7}{'cat':>17}"
          f"{'intra':>7}{'z_sync':>8}{'z_sim':>7}{'z_dens':>8}")
    rows = []
    for c in sample:
        ev = loader.load_cluster_events(c["cluster_label"], conn)
        if not ev:
            continue
        ev = ev[:100]  # cota de coste (spike); el motor real usará todas
        zs = {d: nullmodel.excess(fn, ev, kind=k, B=B, seed=SEED)[3]
              for d, (fn, k) in DIMS.items()}
        indep = round(sum(score_from_z(zs[d]) * W[d] for d in zs))
        intra = intra_ratio(ev)
        flag = " eco-intra" if intra > 0.7 else ""
        if intra > 0.7:  # penaliza: coordinación aparente = una cuenta en ráfaga
            indep = min(indep, 39)
        cat = category(indep)
        rows.append((c, indep, cat, zs, intra))
        print(f"{c['cluster_label']:<30}{c['tema_id'][:12]:<13}"
              f"{c['overall_score']:>6.0f}{band_of(c['overall_score']):>10}"
              f"{indep:>7}{cat:>17}{intra:>7.2f}"
              f"{zs['temporal_sync']:>8.1f}{zs['content_similarity']:>7.1f}"
              f"{zs['network_density']:>8.1f}{flag}")

    print("\n=== GATE (¿discrimina?) ===")
    if rows:
        import statistics as st
        radar = [r[0]["overall_score"] for r in rows]
        indep = [r[1] for r in rows]
        n = len(rows)
        mr, mi = sum(radar) / n, sum(indep) / n
        cov = sum((a - mr) * (b - mi) for a, b in zip(radar, indep))
        sr = sum((a - mr) ** 2 for a in radar) ** 0.5
        si = sum((b - mi) ** 2 for b in indep) ** 0.5
        print(f"  corr(Pearson) radar vs independent = {cov/(sr*si+1e-9):.2f}")
        hi = [r for r in rows if band_of(r[0]["overall_score"]) in ("CRITICAL", "HIGH")]
        fp = [r for r in hi if r[1] <= 39]
        sup = [r for r in hi if r[1] >= 60]
        print(f"  CRIT/HIGH: {len(hi)} · apoyados(>=60): {len(sup)} · "
              f"posibles FP(<=39): {len(fp)}")
        print(f"  mediana independent={st.median(indep):.0f} · radar={st.median(radar):.0f}")


if __name__ == "__main__":
    main()
