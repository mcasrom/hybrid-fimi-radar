#!/usr/bin/env python3
"""bitacora.py — Bitácora del ciclo de vida de los temas del radar FIMI.

Documenta (en la tabla SQLite `bitacora` de radar.db) las decisiones sobre cada
tema monitorizado: inicio de ingesta, cambios de estado, cierre y notas.
La decisión de cambiar estado es SIEMPRE del dueño — este comando solo registra
el historial; el estado vigente se lee de config.yaml.

Uso:
  python3 detection/bitacora.py --seed
      Sembrar filas `inicio` para los temas de config.yaml (idempotente).
      La fecha se deriva del PRIMER hallazgo persistido del tema (findings).
  python3 detection/bitacora.py --tema T --nuevo-estado S --nota "motivo"
      Registrar un cambio de estado (S = produccion|piloto|candidato_a_cierre|cerrado).
      Si S == 'cerrado' se registra como tipo 'cierre' (fecha y motivo quedan
      visibles en el dashboard). El cambio real en config.yaml lo editas tú.
  python3 detection/bitacora.py --tema T --anotar "nota"
      Nota libre sin cambio de estado (tipo 'nota').
  python3 detection/bitacora.py --list [--tema T]
      Mostrar la bitácora de los temas (o de uno). --json para salida JSON.

--dry: muestra qué registraría sin escribir.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
sys.path.insert(0, str(ROOT))

from detection.schema_bitacora import init as binit  # noqa: E402

ESTADOS_VALIDOS = {"produccion", "piloto", "candidato_a_cierre", "cerrado"}


def cargar_config():
    import yaml
    try:
        return yaml.safe_load(open(ROOT / "config.yaml"))
    except Exception:
        return {}


def estado_vigente(tema, cfg=None):
    cfg = cfg or cargar_config()
    return (cfg.get("temas", {}) or {}).get(tema, {}).get("estado", "produccion")


def inicio_ingesta_bd(conn, tema):
    """Primer hallazgo persistido del tema (findings) = inicio real de ingesta.

    NO usar MIN(ts) de event_temas: coincide en 09/jun para los 3 temas porque
    es la fecha del backfill M2M, no del inicio efectivo de cada tema.
    """
    try:
        r = conn.execute(
            "SELECT MIN(fecha) FROM findings WHERE tema_id=?", (tema,)).fetchone()
        return r[0] if r and r[0] else None
    except Exception:
        return None


def registrar(conn, tema, tipo, estado_anterior, estado_nuevo, motivo, origen="manual"):
    ts = int(time.time())
    clave = hashlib.sha1((motivo or "").encode("utf-8")).hexdigest()[:20]
    try:
        conn.execute(
            "INSERT OR IGNORE INTO bitacora"
            " (tema, tipo, fecha, estado_anterior, estado_nuevo, motivo, origen, clave)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (tema, tipo, ts, estado_anterior, estado_nuevo, motivo, origen, clave),
        )
        conn.commit()
        return ts
    except Exception as e:
        print(f"[bitacora] error al registrar: {e}")
        return None


def seed(conn, dry=False):
    cfg = cargar_config()
    temas = cfg.get("temas", {}) or {}
    if not temas:
        print("[bitacora] sin temas en config.yaml")
        return
    for t, tcfg in temas.items():
        inicio = inicio_ingesta_bd(conn, t)
        f_s = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(inicio)) if inicio else "—"
        if inicio:
            motivo = f"Inicio de ingesta — primer hallazgo persistido (findings) {f_s}"
        else:
            motivo = "Inicio de ingesta — tema activado sin hallazgos aún"
        est = estado_vigente(t, cfg)
        if dry:
            print(f"[bitacora][dry] sembrar {t}: estado={est} inicio={f_s}")
        else:
            _ts = inicio if inicio else int(time.time())
            registrar(conn, t, "inicio", None, est, motivo, origen="sistema")
            # la fecha del `inicio` debe ser la de ingesta real (MIN findings),
            # no la de seed; auto-repara filas ya sembradas sin duplicar.
            conn.execute(
                "UPDATE bitacora SET fecha=? WHERE tema=? AND tipo='inicio'",
                (_ts, t))
            conn.commit()
            print(f"[bitacora] sembrado {t}: estado={est} inicio={f_s}")


def listar(conn, tema=None, as_json=False):
    if tema:
        rows = conn.execute(
            "SELECT * FROM bitacora WHERE tema=? ORDER BY fecha", (tema,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM bitacora ORDER BY tema, fecha").fetchall()
    if as_json:
        return [dict(r) for r in rows]
    for r in rows:
        f = time.strftime("%Y-%m-%d %H:%M", time.gmtime(r["fecha"]))
        print(f"{r['tema']:<28} {f}  [{r['tipo']:>16}]  "
              f"{r['estado_anterior'] or '-'} → {r['estado_nuevo'] or '-'}  "
              f"({r['origen']})\n    {r['motivo'] or ''}")
    if not rows:
        print("(sin entradas)" if tema else "(bitácora vacía — ejecuta --seed primero)")


def main():
    ap = argparse.ArgumentParser(description="Bitácora de temas del radar FIMI")
    ap.add_argument("--seed", action="store_true", help="sembrar filas `inicio` de los temas")
    ap.add_argument("--tema", help="tema (ej. politica_nacional)")
    ap.add_argument("--nuevo-estado", help="produccion|piloto|candidato_a_cierre|cerrado")
    ap.add_argument("--nota", help="motivo en lenguaje metodológico (no atribución)")
    ap.add_argument("--anotar", help="nota libre sin cambio de estado")
    ap.add_argument("--list", action="store_true", help="listar bitácora")
    ap.add_argument("--json", action="store_true", help="salida JSON (con --list)")
    ap.add_argument("--dry", action="store_true", help="no escribir, solo mostrar")
    args = ap.parse_args()

    conn = binit()

    if args.seed:
        seed(conn, dry=args.dry)
        return

    if args.list:
        data = listar(conn, tema=args.tema, as_json=args.json)
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    if args.anotar:
        if not args.tema or not args.nota:
            ap.error("--anotar requiere --tema y --nota")
        if args.dry:
            print(f"[bitacora][dry] nota en {args.tema}: {args.nota}")
        else:
            registrar(conn, args.tema, "nota", None, None, args.nota)
            print(f"[bitacora] nota registrada en {args.tema}")
        return

    if args.nuevo_estado:
        if not args.tema:
            ap.error("--nuevo-estado requiere --tema")
        if args.nuevo_estado not in ESTADOS_VALIDOS:
            ap.error(f"estado inválido: {args.nuevo_estado}. Válidos: {sorted(ESTADOS_VALIDOS)}")
        est_anterior = estado_vigente(args.tema)
        tipo = "cierre" if args.nuevo_estado == "cerrado" else "cambio_estado"
        nota = args.nota or (
            "Cierre del tema." if tipo == "cierre" else
            f"Cambio de estado {est_anterior} → {args.nuevo_estado}.")
        if args.dry:
            print(f"[bitacora][dry] registrar en {args.tema}: "
                  f"{est_anterior} → {args.nuevo_estado} ({tipo}): {nota}")
        else:
            registrar(conn, args.tema, tipo, est_anterior, args.nuevo_estado, nota)
            print(f"[bitacora] registrado {args.tema}: {est_anterior} → {args.nuevo_estado}")
        return

    ap.print_help()


if __name__ == "__main__":
    main()