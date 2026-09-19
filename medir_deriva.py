import sqlite3, re, sys, unicodedata
from collections import Counter, defaultdict
from urllib.parse import urlparse

DB = "/home/deploy/hybrid-fimi-radar/data/radar.db"

THEME_KW = {
    "frontera_sur": ["Ceuta", "Melilla", "frontera Marruecos", "migración España",
                     "Ceuta Melilla frontera", "migración Canarias", "España Marruecos",
                     "migración", "Ceuta crise", "frontière sud Europe", "migration Maghreb",
                     "infiltration Ceuta", "FIMI Europe", "désinformation Russie Europe",
                     "inmigración irregular", "propaganda rusa Magreb"],
    "geopolitica_ue_marruecos": ["relaciones España Marruecos diplomacia",
                                 "acuerdo bilateral España Marruecos", "política exterior UE Magreb",
                                 "Marruecos Unión Europea relaciones", "accord Maroc Union européenne",
                                 "diplomatie Maroc UE"],
    "politica_nacional": ["gobierno España oposición", "partidos políticos España",
                          "congreso senado España", "política España elecciones", "crisis de gobierno"],
    "eeuu_politica": ["elecciones medio mandato EEUU 2026", "interferencia electoral EEUU",
                      "desinformación elecciones EEUU", "2026 midterms interference"],
    "oriente_medio": ["Gaza", "Gaza Israel", "Iran", "Houthi", "Hutíes", "Hormuz",
                      "Hezbollah", "Hezbolá", "Hamas", "Hamás", "Cisjordania", "West Bank",
                      "Líbano Israel", "Lebanon Israel"],
    "sahel": ["Sahel", "Mali", "Burkina Faso", "JNIM", "yihadismo", "Níger",
              "AES Alianza de Estados del Sahel", "Alliance des États du Sahel",
              "djihadiste Sahel", "yihadismo Sahel"],
}

def norm(s):
    if not s:
        return ""
    s = s.lower()
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")

def kw_matches(normtext, kw):
    nk = norm(kw)
    if " " in nk:
        return nk in normtext
    return re.search(r"\b" + re.escape(nk) + r"\b", normtext) is not None

def theme_matches(normtext, theme):
    return sum(1 for kw in THEME_KW[theme] if kw_matches(normtext, kw))

def top_domains(events, n=3):
    doms = Counter()
    for e in events:
        try:
            d = urlparse(e["url"]).netloc.lower().replace("www.", "")
        except Exception:
            d = ""
        if d:
            doms[d] += 1
    return doms.most_common(n)

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

last = {}
for r in conn.execute("select tema_id, max(created_at) m from clusters group by tema_id"):
    last[r["tema_id"]] = r["m"]

active = [r for r in conn.execute("select * from clusters") if r["created_at"] == last.get(r["tema_id"]) and r["tema_id"] == "frontera_sur"]
active.sort(key=lambda r: r["overall_score"] or 0, reverse=True)

themes = sorted(THEME_KW)
rows = []
total_ev = 0
for c in active:
    events = conn.execute("select source, author, title, text, url from cluster_events where cluster_id=?", (c["id"],)).fetchall()
    n_ev = len(events)
    total_ev += n_ev
    cuentas = len({(e["author"], e["source"]) for e in events})
    normtext = norm(" ".join((e["title"] or "") + " " + (e["text"] or "") for e in events))
    m = {t: theme_matches(normtext, t) for t in themes}
    fr = m["frontera_sur"]
    otros = {t: k for t, k in m.items() if t != "frontera_sur"}
    tot_otros = sum(otros.values())
    if fr == 0 and tot_otros == 0:
        dominio_tema = "SIN_TEMA(eco)"
    else:
        dominion = max(m, key=lambda t: m[t])
        if m[dominion] == 0:
            dominio_tema = "SIN_TEMA(eco)"
        else:
            dominio_tema = dominion
    rows.append((c["cluster_label"], c["overall_score"] or 0, cuentas, n_ev, dominio_tema, m, top_domains(events)))

# ---- Aggregate ----
print("=" * 78)
print(f"Snapshot activo frontera_sur: {len(active)} clusters | {total_ev} eventos | top {max(r[1] for r in rows):.1f}")
print("=" * 78)
verd = Counter()
verdscores = defaultdict(list)
ev_por = Counter()
alertas = 0
for label, score, cuentas, n_ev, dom_tema, m, domands in rows:
    verd[dom_tema] += 1
    verdscores[dom_tema].append(score)
    ev_por[dom_tema] += n_ev
    if score >= 60:
        alertas += 1

print(f"\nClusters por tema dominante ({len(active)}):")
for t in sorted(verd, key=lambda k: -verd[k]):
    scores = verdscores[t]
    print(f"  {t:28s} n={verd[t]:3d} | eventos={ev_por[t]:5d} | mediana score={sorted(scores)[len(scores)//2]:.1f} | max={max(scores):.1f}")

print(f"\nAlertas >=60: {alertas} de {len(active)}")
print("\nDesglose de Matches (clusters que tocan OTRO tema al menos una vez):")
toca_otro = Counter()
for label, score, cuentas, n_ev, dom_tema, m, domands in rows:
    for t in themes:
        if t != "frontera_sur" and m[t] > 0:
            toca_otro[t] += 1
for t in sorted(toca_otro, key=lambda k: -toca_otro[k]):
    print(f"  toca {t:28s} -> {toca_otro[t]:3d} clusters")

print("\n" + "=" * 78)
print("TOP 12 por score (verificación cualitativa):")
for label, score, cuentas, n_ev, dom_tema, m, domands in rows[:12]:
    dm = " | ".join(f"{t}:{m[t]}" for t in themes if m[t] > 0)
    dstr = ", ".join(f"{d}x{c}" for d, c in domands)
    print(f"\n  {label}  score={score:5.1f}  cuentas={cuentas:<4d} ev={n_ev:<5d}")
    print(f"    tema_dominante={dom_tema}  matches[{dm or 'ninguno'}]")
    print(f"    dominios: {dstr}")

# ---- CSV per-cluster ----
out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/deriva_frontera_sur.csv"
with open(out, "w") as f:
    f.write("label,score,cuentas,eventos,tema_dominante,frontera,geopolitica,eeuu,oriente,sahel,politica\n")
    for label, score, cuentas, n_ev, dom_tema, m, domands in rows:
        f.write(f"{label},{score},{cuentas},{n_ev},{dom_tema},{m['frontera_sur']},{m['geopolitica_ue_marruecos']},{m['eeuu_politica']},{m['oriente_medio']},{m['sahel']},{m['politica_nacional']}\n")
print(f"\nCSV -> {out}")