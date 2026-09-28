#!/usr/bin/env python3
"""purgar_tema_keyword.py — Quitar la etiqueta de un tema a los eventos que solo
estaban por keywords RETIRADAS de ese tema.

`backfill_tema_contenido.py` es **aditivo** (solo añade temas, por diseño
multi-tema). No sirve para el caso inverso: cuando una keyword se mueve de un
tema a otro (o se retira), los eventos ya etiquetados se quedan con la etiqueta
vieja, cuentan dos veces en el corpus del tema y distorsionan clusters y diales.

Criterio, conservador a propósito
--------------------------------
El pipeline etiqueta un evento por DOS rutas:
  (a) por contenido — `temas_por_contenido` + gate `filtro` (y `contexto`);
  (b) por consulta — la búsqueda de bluesky/google-news arrastra el tema, así que
      un post puede llegar por la query `wahlen` sin contener literalmente
      «wahlen» y aun así ser legítimamente de ese tema.
Por eso **NO** se recomputa la etiqueta desde cero (eso borraría la ruta (b) y
perdería eventos válidos). Solo se desetiqueta un evento si:
  1. matchea ≥1 keyword retirada (tenía el motivo), Y
  2. NO matchea ninguna keyword/filtro vigente del tema (no tiene otro motivo).
Un evento que matchea una retirada y otra vigente se conserva.

Uso
---
  venv/bin/python detection/purgar_tema_keyword.py --tema elecciones \\
      --retiradas midterms "election interference"              # dry, no escribe
  ... --aplicar                                                # borra de verdad

Por seguridad **no escribe nada** sin `--aplicar`: primero se mide, luego se
borra. Always imprime el desglose (intactos / a desetiquetar / fuera de
ventana / sin texto) para que el número sea auditable.
"""
from __future__ import annotations

import argparse
import datetime
import sqlite3
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from detection import tema_reglas as tr  # noqa: E402

normalizar, _tokens, _matches = tr.normalizar, tr._tokens, tr._matches


def _prep(terminos):
    """Compila una lista de términos al formato que espera _matches."""
    return [(normalizar(k), _tokens(k)) for k in terminos if normalizar(k)]


def _matchea(texto, precomp):
    nt = normalizar(texto)
    ntok = [x for x in nt.split() if len(x) > 2]
    return any(_matches(a, b, nt, ntok) for a, b in precomp)


def clasificar(con, tema, retiradas, dias, ahora=None):
    """Devuelve (a_desetiquetar, desglose) sin tocar la BD.

    `con` es una conexión sqlite3 con row_factory sqlite3.Row.
    """
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    if tema not in (cfg.get("temas") or {}):
        raise SystemExit(f"el tema {tema} no existe en config.yaml")
    baja = {str(t).lower() for t in retiradas}
    tcfg = cfg["temas"][tema] or {}
    # Las retiradas se EXCLUYEN de lo vigente aunque sigan en config: si alguien
    # deja la keyword retirada en la lista, el criterio "tiene otro motivo" se
    # cumpliria siempre y la herramienta no borraria nada en silencio (mismo tipo de
    # fallo que tocar config.yaml y que el default se reinyecte en el codigo).
    keywords_tema = [k["palabra"] for k in (cfg.get("keywords") or [])
                     if k.get("tema") == tema]
    sin_quitar = [k for k in keywords_tema if str(k).lower() in baja]
    # lo vigente = keywords del tema + su gate `filtro` (lo que puede mantenerlo)
    vigentes = [k for k in keywords_tema if str(k).lower() not in baja]
    filtro = [t for t in (tcfg.get("filtro") or []) if str(t).lower() not in baja]
    contexto = [t for t in (tcfg.get("contexto") or []) if str(t).lower() not in baja]
    if sin_quitar:
        print(f"AVISO: {', '.join(sin_quitar)} sigue(n) en keywords de {tema} en "
              f"config.yaml; se ignoran como motivo vigente, pero quitalas de "
              f"config.yaml o la captura volvera a etiquetar con ellas")
    ok = _prep(vigentes + filtro + contexto)
    ya = _prep(retiradas)

    ahora = ahora or datetime.datetime.now(datetime.timezone.utc).timestamp()
    t0 = int(ahora) - dias * 86400

    a_desetiquetar, intactos = [], []
    sin_motivo = fuera = sin_texto = 0
    ids = [r["event_id"] for r in con.execute(
        "SELECT event_id FROM event_temas WHERE tema_id=?", (tema,))]
    for eid in ids:
        r = con.execute(
            "SELECT title, text, timestamp FROM events WHERE id=?", (eid,)).fetchone()
        if r is None or (r["timestamp"] or 0) < t0:
            fuera += 1
            continue
        txt = (r["title"] or "") + " " + (r["text"] or "")
        if not txt.strip():
            sin_texto += 1
            continue
        if not _matchea(txt, ya):
            sin_motivo += 1
            continue
        (intactos if _matchea(txt, ok) else a_desetiquetar).append(eid)

    desglose = {
        "tema": tema, "retiradas": list(retiradas),
        "keywords_vigentes": len(vigentes), "filtro": len(filtro),
        "contexto": len(contexto),
        "etiquetados": len(ids),
        "sin_motivo_retirado": sin_motivo,
        "intactos_otro_motivo": len(intactos),
        "fuera_ventana": fuera, "sin_texto": sin_texto,
        "a_desetiquetar": len(a_desetiquetar),
    }
    return a_desetiquetar, desglose


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema", required=True)
    ap.add_argument("--retiradas", nargs="+", required=True,
                    help="keywords que se han retirado del tema (con comillas si "
                         "tienen espacios)")
    ap.add_argument("--dias", type=int, default=7300,
                    help="ventana hacia atrás (default: todo el histórico; el "
                         "pipeline agrupa el corpus sin ventana temporal)")
    ap.add_argument("--db", default=str(ROOT / "data" / "radar.db"))
    ap.add_argument("--aplicar", action="store_true",
                    help="ESCRIBE los cambios; sin esto es dry")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    a_desetiquetar, d = clasificar(con, args.tema, args.retiradas, args.dias)

    for k in ("keywords_vigentes", "filtro", "contexto", "etiquetados",
              "sin_motivo_retirado", "intactos_otro_motivo", "fuera_ventana",
              "sin_texto", "a_desetiquetar"):
        print(f"  {k:24s} {d[k]}")
    print(f"  {'retiradas':24s} {', '.join(d['retiradas'])}")

    if a_desetiquetar:
        print("\n  muestra de lo que se desetiqueta:")
        for eid in a_desetiquetar[:8]:
            r = con.execute("SELECT title, source FROM events WHERE id=?",
                            (eid,)).fetchone()
            print(f"    - [{r['source']}] {(r['title'] or '')[:80]}")

    if not args.aplicar:
        print("\nDRY: no se ha escrito nada (añade --aplicar para escribir)")
        con.close()
        return
    if not a_desetiquetar:
        print("\nnada que hacer")
        con.close()
        return

    con.executemany("DELETE FROM event_temas WHERE event_id=? AND tema_id=?",
                    [(e, args.tema) for e in a_desetiquetar])
    con.commit()
    resto = con.execute("SELECT COUNT(*) FROM event_temas WHERE tema_id=?",
                        (args.tema,)).fetchone()[0]
    print(f"\nOK: desetiquetados {len(a_desetiquetar)} | quedan en {args.tema}: {resto}")
    con.close()


if __name__ == "__main__":
    main()
