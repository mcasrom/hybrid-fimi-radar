#!/usr/bin/env python3
"""Medición exploratoria de extensión entre países por coincidencia léxica.

No atribuye coordinación: cuenta eventos del tema que mencionan un símbolo o
demanda y un país, y mide cuántos países aparecen en una ventana de 72 h.
Los países se asignan por topónimos en el texto; no hay geolocalización.
"""
from __future__ import annotations

import sqlite3
import unicodedata

TEMA = "protestas_juveniles"
VENTANA_H = 72

PAISES = {
    "España": ["barcelona", "madrid", "valencia", "bilbao", "espana"],
    "Francia": ["francia", "paris", "marsella", "lyon", "lille", "burdeos", "orleans"],
    "Italia": ["italia", "milan", "turin", "bolonia"],
    "Albania": ["albania", "tirana"],
    "Nepal": ["nepal", "katmandu", "kathmandu"],
}

SIMBOLOS = [
    ("blocus", "Blocus", "consigna específica"),
    ("one piece", "One Piece", "símbolo"),
    ("gen z", "Gen Z", "etiqueta"),
    ("dimision", "Dimisión", "demanda"),
    ("renuncia", "Renuncia", "demanda"),
    ("huelga", "Huelga", "término genérico"),
    ("manifestacion", "Manifestación", "término genérico"),
]


def norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                   if not unicodedata.combining(c))


def _paises(texto: str) -> list:
    t = norm(texto)
    return [p for p, kws in PAISES.items() if any(k in t for k in kws)]


def _fila(rows, simbolo: str, etiqueta: str, tipo: str) -> dict:
    ev = []
    for r in rows:
        txt = norm((r["title"] or "") + " " + (r["text"] or ""))
        if simbolo not in txt:
            continue
        ps = _paises(txt)
        if ps and r["timestamp"]:
            ev.append((float(r["timestamp"]), r["author"], ps))
    if not ev:
        return {"simbolo": etiqueta, "tipo": tipo, "eventos": 0, "cuentas": 0,
                "paises": [], "max_paises_72h": 0, "paises_72h": [],
                "estado": "no observada"}
    ev.sort()
    best = (0, [])
    for i, (t, _, _) in enumerate(ev):
        ps = set()
        for t2, _, p2 in ev[i:]:
            if t2 - t > VENTANA_H * 3600:
                break
            ps.update(p2)
        if len(ps) > best[0]:
            best = (len(ps), sorted(ps))
    n_paises = len({p for _, _, ps in ev for p in ps})
    estado = ("extensión observada" if best[0] >= 2 and len(ev) >= 10
              else "señal débil" if best[0] >= 2 else "no observada")
    return {"simbolo": etiqueta, "tipo": tipo, "eventos": len(ev),
            "cuentas": len({a for _, a, _ in ev}),
            "paises": sorted({p for _, _, ps in ev for p in ps}),
            "max_paises_72h": best[0], "paises_72h": best[1], "estado": estado,
            "desde": min(t for t, _, _ in ev), "hasta": max(t for t, _, _ in ev)}


def calcular(conn: sqlite3.Connection, tema: str = TEMA) -> dict:
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute(
        "SELECT e.id, e.author, e.timestamp, e.title, e.text "
        "FROM events e JOIN event_temas et ON et.event_id=e.id WHERE et.tema_id=?",
        (tema,)))
    return {
        "ventana_h": VENTANA_H,
        "filas": [_fila(rows, s, label, t) for s, label, t in SIMBOLOS],
        "nota": ("Coincidencia léxica en título/texto; país por topónimo, no geolocalización. "
                 "Solo eventos con país identificable y timestamp. Mide extensión, no coordinación ni autoría."),
    }
