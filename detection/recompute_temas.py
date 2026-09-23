#!/usr/bin/env python3
"""Recomputa event_temas SIN cajon por defecto: cada evento pertenece solo a
los temas cuyas keywords matchean su texto (+ gate `filtro`). Lo que no matchea
ningun tema activo se queda SIN tema (no se vuelca a frontera_sur).

Uso: recompute_temas.py [--dry]
"""
import sqlite3, sys, yaml
sys.path.insert(0, "/home/deploy/hybrid-fimi-radar")
from detection import tema_reglas as tr
temas_por_contenido, normalizar, _tokens, _matches = (
    tr.temas_por_contenido, tr.normalizar, tr._tokens, tr._matches)

DRY = "--dry" in sys.argv
ROOT = "/home/deploy/hybrid-fimi-radar"
cfg = yaml.safe_load(open(f"{ROOT}/config.yaml"))
kws = cfg.get("keywords", [])
temas_cfg = cfg.get("temas", {}) or {}
activos = set(tr.temas_activos(cfg))

# Gate por tema con el MISMO matcher que capture/backfill/salud (helper compartido
# en tema_reglas): el filtro/contexto es plural-tolerante y consistente.
_por_tema, _filtros_raw, _contextos_raw, _ = tr.reglas_por_tema(cfg)
filtros, contextos = tr.prep_gates(_filtros_raw, _contextos_raw)

def pasa_gate(tema, nt, ntok):
    fl = filtros.get(tema)
    if fl and not any(_matches(a, b, nt, ntok) for a, b in fl):
        return False
    ct = contextos.get(tema)
    if ct and not any(_matches(a, b, nt, ntok) for a, b in ct):
        return False
    return True

con = sqlite3.connect(f"{ROOT}/data/radar.db")
con.row_factory = sqlite3.Row
rows = con.execute("SELECT id, text, title FROM events").fetchall()
print(f"eventos: {len(rows)}", flush=True)

n_sin = 0
n_con = 0
n_multi = 0
upd = []
for i, r in enumerate(rows):
    txt = (r["text"] or "") + " " + (r["title"] or "")
    temas = temas_por_contenido(txt, kws)
    nt = normalizar(txt)
    ntok = [x for x in nt.split() if len(x) > 2]
    temas = sorted(t for t in temas if t in activos and pasa_gate(t, nt, ntok))
    if not temas:
        n_sin += 1
        upd.append((r["id"], []))
    else:
        n_con += 1
        if len(temas) > 1:
            n_multi += 1
        upd.append((r["id"], temas))
    if (i + 1) % 20000 == 0:
        print(f"  clasificados {i+1}/{len(rows)}", flush=True)

print(f"SIN tema: {n_sin} | con tema: {n_con} | multi: {n_multi}", flush=True)
if DRY:
    print("DRY: no se escribe", flush=True)
    sys.exit(0)

# reemplazar event_temas (delete + insert) y actualizar tema_id primario
con.execute("DELETE FROM event_temas")
for eid, temas in upd:
    for t in temas:
        con.execute("INSERT OR IGNORE INTO event_temas (event_id, tema_id) VALUES (?,?)", (eid, t))
    prim = "frontera_sur" if "frontera_sur" in temas else (temas[0] if temas else "")
    con.execute("UPDATE events SET tema_id=? WHERE id=?", (prim, eid))
con.commit()
tot = con.execute("SELECT COUNT(*) FROM event_temas").fetchone()[0]
print(f"event_temas recomputado: {tot} filas", flush=True)
con.close()
print("OK", flush=True)
