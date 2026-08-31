#!/usr/bin/env python3
"""Generador sintético FIMI — 6 escenarios del prompt (GROUND TRUTH).

  A — Difusión orgánica (muchas cuentas, diversidad alta, sin coordinación)
  B — Campaña coordinada doméstica (mismo contenido + ventana estrecha)
  C — Campaña coordinada extranjera (mismo contenido + infraestructura + transversal)
  D — Falsa alarma (pico de volumen pero diversidad, sin coordinación real)
  E — Evento real con enorme viralización orgánica (muchas cuentas, contenidos variados)
  F — Campaña con atribución desconocida (coordinación pero sin infraestructura clara)

El detector NO debe conocer estos grupos. Salida: events.csv (sin etiquetas) +
ground_truth.csv (solo para evaluación).
"""
import csv
import random
from pathlib import Path

random.seed(7)
OUT = Path(__file__).parent.parent / "data" / "raw"
OUT.mkdir(parents=True, exist_ok=True)

WORDS = ["frontera", "migracion", "Ceuta", "Melilla", "valla", "asilo", "crisis",
         "Europa", "fronteras", "acogida", "seguridad", "derechos", "humanitarios",
         "gobierno", "sociedad", "situacion", "proteccion", "solidaridad", "presion"]
DOMAINS = ["noticias.global.org", "prensa.europea.eu", "voz.frontera.es",
           "actualidad.info", "diario.civil.net"]

N_ACCOUNTS = 900


def rtext(n):
    return " ".join(random.choice(WORDS) for _ in range(n))


def mutate(t, p=0.08):
    ws = t.split()
    out = []
    for w in ws:
        out.append(w + "x" if random.random() < p else w)
    return " ".join(out)


def add(events, author, ts, text, url, tag, action="post", group="A", cluster="A"):
    events.append({"timestamp": ts, "author": author, "text": text, "url": url,
                   "hashtags": tag, "mentions": "", "action": action,
                   "source": "synthetic", "_group": group, "_cluster": cluster})


events = []

# ---- A: orgánico (900 cuentas normales) ----
for i in range(900):
    acc = f"u{i:04d}"
    for k in range(random.randint(1, 6)):
        add(events, acc, random.randint(1, 28) * 86400 + k * 3600,
            rtext(random.randint(3, 10)), "", random.choice(["", "#frontera", "#migracion"]),
            group="A", cluster="A")

# ---- B: campaña doméstica (40 cuentas, mismo texto + ventana estrecha) ----
B_SEED = rtext(12)
for i in range(40):
    acc = f"b{i:03d}"
    for burst in range(3):
        t0 = random.randint(2, 26) * 86400
        for k in range(random.randint(4, 7)):
            add(events, acc, t0 + k * random.randint(2, 6), mutate(B_SEED),
                f"https://{DOMAINS[1]}/c", "#frontera", group="B", cluster="B")

# ---- C: campaña extranjera (30 cuentas, infraestructura compartida + transversal) ----
C_SEED = rtext(14)
C_DOM = DOMAINS[0]
for i in range(30):
    acc = f"c{i:03d}"
    for k in range(random.randint(5, 9)):
        add(events, acc, random.randint(3, 25) * 86400 + k * 3600,
            mutate(C_SEED, 0.05), f"https://{C_DOM}/x{i % 3}", "#valla",
            action=random.choice(["post", "share"]), group="C", cluster="C")

# ---- D: falsa alarma (pico volumen, diversidad alta, sin coordinación) ----
for i in range(150):
    acc = f"d{i:03d}"
    t0 = random.randint(10, 12) * 86400  # concentrado en 2 días
    for k in range(random.randint(2, 4)):
        add(events, acc, t0 + random.randint(0, 3000),
            rtext(random.randint(4, 9)), "", "#frontera", group="D", cluster="D")

# ---- E: evento real viral (200 cuentas, contenidos variados, progresivo) ----
for i in range(200):
    acc = f"e{i:03d}"
    for k in range(random.randint(2, 5)):
        add(events, acc, random.randint(14, 18) * 86400 + k * random.randint(900, 7200),
            rtext(random.randint(4, 12)), random.choice([f"https://{d}/a" for d in DOMAINS]),
            random.choice(["#frontera", "#Ceuta", "#acogida", ""]),
            group="E", cluster="E")

# ---- F: campaña atribución desconocida (coordinación sin infraestructura clara) ----
F_SEED = rtext(10)
for i in range(35):
    acc = f"f{i:03d}"
    for burst in range(2):
        t0 = random.randint(5, 20) * 86400
        for k in range(random.randint(4, 8)):
            add(events, acc, t0 + k * random.randint(3, 9), mutate(F_SEED),
                "", "#migracion", group="F", cluster="F")

events.sort(key=lambda e: e["timestamp"])

with open(OUT / "events.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["timestamp", "author", "text", "url", "hashtags", "mentions", "action", "source"])
    w.writeheader()
    for e in events:
        w.writerow({k: e[k] for k in w.fieldnames})

seen = set()
with open(OUT / "ground_truth.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["author", "group", "cluster"])
    w.writeheader()
    for e in events:
        if e["author"] not in seen:
            w.writerow({"author": e["author"], "group": e["_group"], "cluster": e["_cluster"]})
            seen.add(e["author"])

print(f"Generados {len(events)} eventos, {len(seen)} cuentas")
from collections import Counter
print("por grupo:", dict(Counter(e["_group"] for e in events)))
