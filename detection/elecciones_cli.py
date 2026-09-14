#!/usr/bin/env python3
"""elecciones_cli.py — gestión del registro de elecciones (data/elecciones.yaml).

  list                       lista las filas (país, nombre, fecha, idioma, estado)
  alta --pais … --nombre … --fecha AAAA-MM-DD [--idioma de] [--keywords "a,b,c"]
  cerrar --pais … --nombre …  marca estado: cerrado (no borra)

Usa ruamel round-trip para preservar los comentarios del YAML.
"""
import argparse
from pathlib import Path

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parent.parent
REG = ROOT / "data" / "elecciones.yaml"


def _load():
    y = YAML()
    y.preserve_quotes = True
    data = None
    if REG.exists():
        with open(REG) as f:
            data = y.load(f)
    if data is None:
        data = []
    if isinstance(data, dict):
        data = data.get("elecciones") or []
    return y, data


def _save(y, data):
    REG.parent.mkdir(parents=True, exist_ok=True)
    with open(REG, "w") as f:
        y.dump(data, f)


def cmd_list():
    _, data = _load()
    if not data:
        print("(registro vacío)")
        return
    for e in data:
        print("%-10s | %-38s | %-12s | %-3s | %s" % (
            e.get("pais", "?"), e.get("nombre", ""), str(e.get("fecha", "—")),
            e.get("idioma", "?"), e.get("estado", "activo")))


def cmd_alta(a):
    y, data = _load()
    kws = [k.strip() for k in (a.keywords or "").split(",") if k.strip()]
    data.append({
        "pais": a.pais, "nombre": a.nombre, "fecha": a.fecha,
        "idioma": a.idioma, "estado": "activo", "keywords": kws,
    })
    _save(y, data)
    print("alta: %s · %s (%s) · %d keywords" % (a.pais, a.nombre, a.fecha, len(kws)))


def cmd_cerrar(a):
    y, data = _load()
    n = 0
    for e in data:
        if e.get("pais") == a.pais and e.get("nombre") == a.nombre:
            e["estado"] = "cerrado"
            n += 1
    _save(y, data)
    print("cerrado: %d fila(s)" % n)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list")
    pa = sub.add_parser("alta")
    pa.add_argument("--pais", required=True)
    pa.add_argument("--nombre", required=True)
    pa.add_argument("--fecha", required=True)
    pa.add_argument("--idioma", default="es")
    pa.add_argument("--keywords", default="")
    pc = sub.add_parser("cerrar")
    pc.add_argument("--pais", required=True)
    pc.add_argument("--nombre", required=True)
    a = ap.parse_args()
    if a.cmd == "list":
        cmd_list()
    elif a.cmd == "alta":
        cmd_alta(a)
    elif a.cmd == "cerrar":
        cmd_cerrar(a)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
