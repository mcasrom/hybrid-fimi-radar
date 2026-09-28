#!/usr/bin/env python3
"""detection/auditoria_subtipos.py — muestra estratificada para auditar a mano el rol narrativo.

El rol narrativo (`clusters.narrative_subtype`, asignado por `detection/subtipo.py`) nunca se ha
validado con una persona. Este script extrae una muestra **reproducible** (misma N por rol,
determinista con --seed, coordination_signal se toma entero cuando existe) con hasta `k` eventos
representativos por cluster, y la vuelca a CSV para que un anotador humano juzgue
`rol_anotado`/`observaciones`. NO toca score, bandas ni atribución.

Principios (acordados):
  - Solo lectura sobre `data/radar.db` (muestra acotada, consultas indexadas).
  - Deterministica: mismo --seed produce exactamente la misma muestra.
  - No mezclar con P1 (poda de keywords) ni P2 (validación ciega): contamina las muestras.

CLI:
    python detection/auditoria_subtipos.py                     # muestra por defecto a data/
    python detection/auditoria_subtipos.py --muestra 20 --sin-rol 25 --eventos 5 --seed 7
    python detection/auditoria_subtipos.py --delim ","         # CSV compatible con en-US
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from detection.scoring import band_for, load_bands  # noqa: E402

DEFAULTS = {
    "muestra": 20,          # por rol (official_response, incident_report, meta_analysis, potential_narrative)
    "sin_rol": 20,          # cuántos clusters sin rol
    "seed": 20260928,
    "eventos": 5,           # eventos representativos por cluster
    "max_text_len": 220,
}

ROLES = ["official_response", "incident_report", "meta_analysis",
         "potential_narrative", "coordination_signal"]
LABELS = {
    "official_response": "Respuesta oficial",
    "incident_report": "Incidente",
    "meta_analysis": "Meta-analisis",
    "potential_narrative": "Posible narrativa",
    "coordination_signal": "Senal de coordinacion",
    "sin_rol": "Sin rol",
}


def _load_cfg(config_path=None):
    import yaml
    p = Path(config_path) if config_path else (ROOT / "config.yaml")
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"[warn] auditoria_subtipos: no pude leer config ({e})", file=sys.stderr)
        return {}


def dominant(narrative_subtype):
    """Rol dominante (o 'sin_rol'). Nunca lanza."""
    try:
        d = json.loads(narrative_subtype or "")
    except Exception:
        d = None
    if isinstance(d, dict):
        dom = d.get("dominant")
        if dom:
            return str(dom)
    return "sin_rol"


def _counts(narrative_subtype):
    try:
        d = json.loads(narrative_subtype or "")
    except Exception:
        d = None
    if isinstance(d, dict) and isinstance(d.get("counts"), dict):
        return d["counts"]
    return {}


def _parse_json(raw, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception as e:
        print(f"[warn] auditoria_subtipos: JSON invalido ({e})", file=sys.stderr)
        return default


def agrupar(con):
    """Lee clusters + lineage_id y los agrupa por rol dominante."""
    rows = con.execute(
        "SELECT c.id, c.cluster_label, c.overall_score, c.confidence,"
        "       c.alternative_explanations, c.narrative_subtype, l.lineage_id"
        " FROM clusters c"
        " LEFT JOIN cluster_lineage l ON l.cluster_label = c.cluster_label"
    ).fetchall()
    groups = {r: [] for r in ROLES + ["sin_rol"]}
    for r in rows:
        groups[dominant(r["narrative_subtype"])].append(r)
    return groups


def seleccionar_muestra(groups, muestra, sin_rol, seed):
    """Muestra reproducible: shuffle por rol con el mismo seed."""
    rng = random.Random(seed)
    sel, universos = [], {}
    for rol in ROLES + ["sin_rol"]:
        pool = list(groups[rol])
        universos[rol] = len(pool)
        k = sin_rol if rol == "sin_rol" else muestra
        rng.shuffle(pool)
        for row in pool[:k]:
            sel.append((rol, row))
    return sel, universos


def _indices(n, k):
    """Posiciones repartidas a lo largo de una serie ordenada por ts (único cada una)."""
    if n == 0:
        return []
    if n == 1 or k <= 1:
        return [0]
    seen, out = set(), []
    for i in range(k):
        idx = round(i * (n - 1) / (k - 1))
        if idx not in seen:
            seen.add(idx)
            out.append(idx)
    return out


def _evento_texto(title, text, max_len):
    """Texto legible para un anotador: título + cuerpo, truncado."""
    title = (title or "").strip()
    text = (text or "").strip()
    if title and text:
        s = f"{title} :: {text}"
    else:
        s = title or text
    return s[:max_len]


def eventos_muestra(con, cid, k, max_text_len):
    """Hasta k eventos equidistantes en el tiempo, con fuente/autor/texto/url."""
    (n,) = con.execute("SELECT COUNT(*) FROM cluster_events WHERE cluster_id=?",
                       (cid,)).fetchone()
    out = []
    for idx in _indices(n, k):
        r = con.execute(
            "SELECT ts, source, author, title, text, url FROM cluster_events"
            " WHERE cluster_id=? ORDER BY ts ASC LIMIT 1 OFFSET ?",
            (cid, idx)).fetchone()
        if r is None:
            continue
        out.append({
            "ts": r["ts"],
            "origen": r["source"] or "",
            "autor": r["author"] or "",
            "texto": _evento_texto(r["title"], r["text"], max_text_len),
            "url": r["url"] or "",
        })
    return out


def caracterizar(con, rol, row, k, max_text_len, bands):
    cid = row["id"]
    n, cuentas, mn, mx = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT author), MIN(ts), MAX(ts)"
        " FROM cluster_events WHERE cluster_id=?", (cid,)).fetchone()
    ventana_h = round((mx - mn) / 3600.0, 1) if (mn is not None and mx is not None) else None
    score = row["overall_score"] or 0.0
    items = _parse_json(row["alternative_explanations"], [])
    expl = next((it.get("code") for it in items if it.get("status") == "supported"), "")
    return {
        "linaje": row["lineage_id"] or "",
        "cluster": row["cluster_label"],
        "rol": rol,
        "conteos": json.dumps(_counts(row["narrative_subtype"]), ensure_ascii=False),
        "banda": band_for(score, bands),
        "score": round(float(score), 1),
        "confianza": row["confidence"] or "",
        "explicacion": expl,
        "cuentas": cuentas or 0,
        "eventos": n or 0,
        "ventana_h": "" if ventana_h is None else ventana_h,
        "muestra": eventos_muestra(con, cid, k, max_text_len),
    }


def _columnas(csv_header, rec, k):
    fila = [rec["linaje"], rec["cluster"], rec["rol"], rec["conteos"], rec["banda"],
            rec["score"], rec["confianza"], rec["explicacion"], rec["cuentas"],
            rec["eventos"], rec["ventana_h"]]
    for i in range(1, k + 1):
        flag, em = "#", rec["muestra"][i - 1] if i - 1 < len(rec["muestra"]) else None
        if em is None:
            fila += [flag, "", ""]
            continue
        origen = em["origen"] or em["autor"] or ""
        fila += [em["texto"], origen, em["url"]]
    fila += ["", ""]  # rol_anotado, observaciones
    return fila


def emitir_csv(con, sel, k, max_text_len, bands, out, delim):
    header = ["linaje", "cluster", "rol", "conteos", "banda", "score", "confianza",
              "explicacion", "cuentas", "eventos", "ventana_h"]
    for i in range(1, k + 1):
        header += [f"ev_{i}", f"origen_{i}", f"url_{i}"]
    header += ["rol_anotado", "observaciones"]
    rows = [header]
    for rol, row in sel:
        rows.append(_columnas(header, caracterizar(con, rol, row, k, max_text_len, bands), k))
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=delim, quoting=csv.QUOTE_MINIMAL)
        w.writerows(rows)
    return len(rows) - 1


def emitir_manifesto(universos, sel, k, seed, out, fecha):
    total = sum(universos.values())
    lin = "- **Muestra**: {} clusters de {} (seed {}).\n".format(len(sel), total, seed)
    lin += "- Composición por rol: {}.\n".format(
        ", ".join("{} = {}".format(LABELS[r], sum(1 for x, _ in sel if x == r))
                  for r in ROLES + ["sin_rol"]))
    lin += "- Universos por rol (corpus): {}.\n".format(
        ", ".join("{} = {}".format(LABELS[r], universos[r]) for r in ROLES + ["sin_rol"]))
    if not universos.get("coordination_signal"):
        lin += ("- **Nota**: no hay ningún cluster `coordination_signal` en el corpus actual "
                "(el único señalado en sprints previos ya no existe).\n")
    lin += ("\n## Cómo anotar\n\nAbre el CSV (separador `;`; en LibreOffice: Texto en columnas). "
            "Para cada fila escribe en `rol_anotado` qué rol crees que es: `official_response`, "
            "`incident_report`, `meta_analysis`, `potential_narrative`, `coordination_signal`, "
            "`sin_rol` o `?` si es ambiguo. `observaciones` es libre. Devuélvemelo y se compara "
            "contra `rol` para medir la precisión de `subtipo.py`.\n")
    Path(out).write_text(f"# Auditoría de subtipos — {fecha}\n\n{lin}", encoding="utf-8")


def main():
    now = datetime.now(UTC).strftime("%Y%m%d")
    ap = argparse.ArgumentParser(description="Muestra estratificada del rol narrativo para auditar a mano.")
    ap.add_argument("--db", default=str(ROOT / "data" / "radar.db"))
    ap.add_argument("--config", default=None)
    ap.add_argument("--muestra", type=int, default=DEFAULTS["muestra"])
    ap.add_argument("--sin-rol", type=int, default=DEFAULTS["sin_rol"])
    ap.add_argument("--seed", type=int, default=DEFAULTS["seed"])
    ap.add_argument("--eventos", type=int, default=DEFAULTS["eventos"])
    ap.add_argument("--max-text-len", type=int, default=DEFAULTS["max_text_len"])
    ap.add_argument("--delim", default=";")
    ap.add_argument("--out", default=f"data/auditoria_subtipos_{now}.csv")
    ap.add_argument("--md", default=f"data/auditoria_subtipos_{now}.md")
    args = ap.parse_args()

    cfg = _load_cfg(args.config)
    bands = load_bands(cfg)
    db = Path(args.db)
    if not db.exists():
        print(f"[error] auditoria_subtipos: no existe {db}", file=sys.stderr)
        sys.exit(1)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    groups = agrupar(con)
    sel, universos = seleccionar_muestra(groups, args.muestra, args.sin_rol, args.seed)
    nrows = emitir_csv(con, sel, args.eventos, args.max_text_len, bands,
                       args.out, args.delim)
    emitir_manifesto(universos, sel, args.eventos, args.seed, args.md, now)
    con.close()

    print(f"auditoria_subtipos: {nrows} clusters a {args.out}")
    print(" - ".join("{}:{}".format(LABELS[r], universos[r]) for r in ROLES + ["sin_rol"]))
    print(f"composition: {', '.join('{}={}'.format(r, sum(1 for x,_ in sel if x==r)) for r in ROLES + ['sin_rol'])}")


if __name__ == "__main__":
    main()