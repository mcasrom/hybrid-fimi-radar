#!/usr/bin/env python3
"""gate_tema_contenido.py — Aplica el gate `filtro` de un tema a los datos YA
existentes (event_temas/events). El gate de captura (collectors/capture.py) lo
aplica a los eventos nuevos; este script limpia el histórico cuando se añade o
cambia el `filtro` de un tema (p. ej. tras recalibrar `energia`).

Un tema con `filtro` en config.yaml (temas.<tema>.filtro) solo se conserva si el
texto del evento contiene al menos un término del filtro. Los eventos que se
quedan sin ningún tema se eliminan (no se vuelcan al default frontera_sur).

Uso:
  .venv/bin/python detection/gate_tema_contenido.py [--tema X] [--dry]
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
sys.path.insert(0, str(ROOT))

from normalizer.clasificar import normalizar, _tokens, _matches  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema", default=None, help="solo este tema (por defecto, todos los que tengan filtro)")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    temas = cfg.get("temas", {}) or {}
    filtros = {t: (m or {}).get("filtro") for t, m in temas.items() if (m or {}).get("filtro")}
    contextos = {t: (m or {}).get("contexto") for t, m in temas.items() if (m or {}).get("contexto")}
    if args.tema:
        filtros = {k: v for k, v in filtros.items() if k == args.tema}
        contextos = {k: v for k, v in contextos.items() if k == args.tema}
    gates = {t: (filtros.get(t), contextos.get(t)) for t in set(filtros) | set(contextos)}
    if not gates:
        print("sin temas con filtro/contexto (config temas.<tema>.filtro|contexto)")
        return

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    total = 0
    for t, (terms, ctx_terms) in gates.items():
        prep = [(normalizar(str(x)), _tokens(str(x))) for x in (terms or []) if normalizar(str(x))]
        prep_ctx = [(normalizar(str(x)), _tokens(str(x))) for x in (ctx_terms or []) if normalizar(str(x))]
        rows = conn.execute(
            "SELECT et.event_id, e.text, e.title, e.tema_id FROM event_temas et"
            " JOIN events e ON e.id=et.event_id WHERE et.tema_id=?", (t,)).fetchall()
        fail = []
        for r in rows:
            nt = normalizar((r["text"] or "") + " " + (r["title"] or ""))
            ntok = [x for x in nt.split() if len(x) > 2]
            if prep and not any(_matches(tn, tk, nt, ntok) for tn, tk in prep):
                fail.append(r)
                continue
            if prep_ctx and not any(_matches(tn, tk, nt, ntok) for tn, tk in prep_ctx):
                fail.append(r)
        print(f"[{t}] {len(fail)} de {len(rows)} etiquetas fallan el filtro")
        if args.dry:
            continue
        for r in fail:
            eid = r["event_id"]
            conn.execute("DELETE FROM event_temas WHERE event_id=? AND tema_id=?", (eid, t))
            if r["tema_id"] == t:
                other = [x[0] for x in conn.execute(
                    "SELECT tema_id FROM event_temas WHERE event_id=?", (eid,)).fetchall()]
                if other:
                    conn.execute("UPDATE events SET tema_id=? WHERE id=?", (sorted(other)[0], eid))
                else:
                    conn.execute("DELETE FROM event_temas WHERE event_id=?", (eid,))
                    conn.execute("DELETE FROM events WHERE id=?", (eid,))
            total += 1
    if not args.dry:
        conn.commit()
    conn.close()
    print(f"total etiquetas eliminadas: {total}" + (" (dry)" if args.dry else ""))


if __name__ == "__main__":
    main()
