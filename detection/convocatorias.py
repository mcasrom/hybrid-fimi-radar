#!/usr/bin/env python3
"""Registro de convocatorias públicas y detector de candidatas.

No entra en grupos privados, DMs ni cuentas personales. El registro es curado;
el detector solo marca eventos públicos que mencionan una watchlist y una ciudad.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
REGISTRO = ROOT / "data" / "convocatorias.yaml"
JSON_OUT = Path("/var/www/fimi/datos/convocatorias.json")
TEMA = "protestas_juveniles"
CIUDADES = {
    "Barcelona": ["barcelona", "bcn"],
    "Madrid": ["madrid"],
    "Valencia": ["valencia", "valència"],
    "Bilbao": ["bilbao"],
    "Badalona": ["badalona"],
    "El Vendrell": ["vendrell"],
    "A Coruña": ["a coruna", "coruna"],
    "Sevilla": ["sevilla"],
    "Málaga": ["malaga"],
}


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                   if not unicodedata.combining(c))


def cargar_registro() -> dict:
    try:
        d = yaml.safe_load(REGISTRO.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {"actualizado": None, "watchlist": [], "convocatorias": []}
    if isinstance(d, list):
        d = {"actualizado": None, "watchlist": [], "convocatorias": d}
    d.setdefault("watchlist", [])
    d.setdefault("convocatorias", [])
    return d


def _ciudades(texto: str) -> list:
    t = _norm(texto)
    return [c for c, kws in CIUDADES.items() if any(k in t for k in kws)]


def detectar(conn: sqlite3.Connection, dias: int = 7) -> list:
    reg = cargar_registro()
    terms = [str(x).lower() for x in reg.get("watchlist", []) if x]
    known = {str(x.get("url_publica") or "") for x in reg.get("convocatorias", [])}
    if not terms:
        return []
    cutoff = datetime.now(timezone.utc).timestamp() - dias * 86400
    rows = conn.execute(
        "SELECT e.id, e.timestamp, e.source, e.author, e.title, e.text, e.url "
        "FROM events e JOIN event_temas et ON et.event_id=e.id "
        "WHERE et.tema_id=? AND e.timestamp>=? ORDER BY e.timestamp DESC",
        (TEMA, cutoff)).fetchall()
    out, seen = [], set()
    for r in rows:
        txt = _norm((r["title"] or "") + " " + (r["text"] or ""))
        if not any(t in txt for t in terms):
            continue
        ciudades = _ciudades(txt)
        if not ciudades:
            continue
        key = (r["url"] or "") or (r["title"] or "")[:120]
        if key in seen or key in known:
            continue
        seen.add(key)
        out.append({
            "id_local": r["id"],
            "fecha": datetime.fromtimestamp(float(r["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d"),
            "ciudades": ciudades,
            "fuente": r["source"],
            "titulo": r["title"],
            "url": r["url"],
            "estado_candidato": "revisar",
        })
    return out[:40]


def main() -> int:
    reg = cargar_registro()
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cand = detectar(conn)
    conn.close()
    data = {
        "generado": datetime.now(timezone.utc).isoformat(),
        "actualizado": reg.get("actualizado"),
        "watchlist": reg.get("watchlist", []),
        "convocatorias": reg.get("convocatorias", []),
        "candidatas": cand,
        "nota": ("Registro curado de llamadas públicas. El detector solo marca coincidencias "
                 "léxicas con watchlist + ciudad; no confirma convocatoria ni coordinación."),
    }
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[convocatorias] {len(data['convocatorias'])} registradas · {len(cand)} candidatas -> {JSON_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
