#!/usr/bin/env python3
"""temas_cli.py — Gestión del ciclo de vida de los temas del radar FIMI.

Alta y cierre REAL de un tema sin editar config.yaml a mano (respuesta a la
crítica de que "añadir/cerrar un tema requiere tocar código"). Todo lo que
escribe es YAML válido y hace backup previo de config.yaml.

ALTA:
  python3 detection/temas_cli.py --alta geopolitica_ue_marruecos2 \
      --nombre "Geopolítica UE-Marruecos (2)" --keywords "marruecos ue,marruecos bruselas"
  - Añade el bloque `temas.<slug>` con estado PILOTO (la política del proyecto:
    un tema nuevo pasa por calibración antes de producción).
  - Añade las keywords con `tema: <slug>` y plataformas bluesky+google-news
    (se pueden cambiar luego en config.yaml).
  - Los feeds RSS no se tocan: son globales y caen al default frontera_sur.

CIERRE real:
  python3 detection/temas_cli.py --cerrar <slug> --nota "volumen bajo sostenido"
  - 1) Exporta los datos del tema a data/export/<slug>-<fecha>.json
       (findings, clusters, bitácora, conteo de eventos) — archivo NO destructivo.
  - 2) Marca `temas.<slug>.estado: cerrado` en config.yaml.
  - 3) Registra el cierre en la bitácora (bitacora.registrar, tipo=cierre).
  - 4) Regenera el dashboard.
  A partir de ahí el cron/capture SALTAN el tema (ver change en cron_every_6h.sh
  y collectors/capture.py): no vuelve a capturar ni a generar clusters.
  Los datos quedan en la BD (retention 90d) y el export es el archivo permanente.

REABRIR (si fue un error o hay señal nueva):
  python3 detection/temas_cli.py --estado <slug> piloto --nota "reactivar por señal"
  - Vuelve a marcarlo activo en config.yaml (el cron vuelve a capturar).

Ver también: detection/check_cierre.py (avisa candidatos a cierre, no decide)
y detection/bitacora.py (registro de estados).
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("FIMI_DB", str(ROOT / "data" / "radar.db")))
CONFIG = Path(os.environ.get("FIMI_CONFIG", str(ROOT / "config.yaml")))
sys.path.insert(0, str(ROOT))

from detection.schema_bitacora import init as _init_bitacora_tabla  # noqa: E402
from detection.bitacora import registrar as bitacora_registrar  # noqa: E402

ESTADOS = {"produccion", "piloto", "candidato_a_cierre", "cerrado"}


def _slug_valido(slug):
    return bool(re.fullmatch(r"[a-z0-9_]{3,40}", slug))


def _backup():
    ts = time.strftime("%Y%m%d_%H%M%S")
    dst = ROOT / "backups" / f"config_before_temas_cli_{ts}.yaml"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(CONFIG, dst)
    print(f"[temas] backup config -> {dst}")


def _cargar():
    # ruamel round-trip: preserva comentarios y formato del config.yaml al
    # volcar. yaml.safe_dump borraba los comentarios `#` (documentación del
    # config: scale_floor, notas de fuentes, tuning por tema...) — bug conocido.
    from ruamel.yaml import YAML
    _y = YAML()
    _y.preserve_quotes = True
    try:
        return _y.load(open(CONFIG)) or {}
    except Exception:
        return yaml.safe_load(open(CONFIG)) or {}


def _guardar(cfg):
    # escritura round-trip: sin reordenar y SIN perder comentarios del original
    from ruamel.yaml import YAML
    _y = YAML()
    _y.preserve_quotes = True
    with open(CONFIG, "w") as f:
        _y.dump(cfg, f)


def _regen():
    try:
        subprocess.run([sys.executable, str(ROOT / "detection" / "gen_fimi_html.py")],
                       check=False, timeout=300)
        print("[temas] dashboard regenerado")
    except Exception as e:
        print(f"[temas] aviso: dashboard no regenerado ({e})")


def _kw_count(cfg, tema):
    return sum(1 for k in (cfg.get("keywords") or [])
               if (k.get("tema") or "frontera_sur") == tema)


def _bitacora_conn():
    """Conexión a temas_cli.DB (respeta FIMI_DB) con la tabla bitácora creada."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS bitacora (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " tema TEXT, tipo TEXT, fecha INTEGER, estado_anterior TEXT, estado_nuevo TEXT,"
        " motivo TEXT, origen TEXT DEFAULT 'manual', clave TEXT,"
        " UNIQUE(tema, tipo, estado_nuevo, clave));"
        " CREATE INDEX IF NOT EXISTS idx_bitacora_tema ON bitacora(tema, fecha);")
    return conn


def cmd_alta(args):
    cfg = _cargar()
    temas = cfg.setdefault("temas", {})
    if args.tema in temas:
        print(f"[temas] ERROR: el tema '{args.tema}' ya existe en config.yaml")
        return 1
    if not _slug_valido(args.tema):
        print(f"[temas] ERROR: slug inválido '{args.tema}' (usa [a-z0-9_], 3-40).")
        return 1
    if not args.keywords:
        print("[temas] ERROR: necesitas --keywords 'a,b,c' (al menos una).")
        return 1

    # --verifica: simula la cobertura de las keywords propuestas contra el
    # corpus antes de crear el tema. Evita el patrón "tema ciego" (keywords de
    # registro metodológico que los titulares reales no usan). No bloquea: un
    # tema de nicho legítimo puede matchear poco; solo informa para calibrar.
    # Se ejecuta también con --dry (simular sin crear).
    if args.verifica:
        _verificar_cobertura_keywords(args.keywords)

    if args.dry:
        print(f"[temas] [dry] crearía '{args.tema}' (piloto) con keywords: {args.keywords}")
        print(f"[temas] [dry] plataformas: {[p.strip() for p in (args.plataformas or 'bluesky,google-news').split(',') if p.strip()]}")
        return 0

    _backup()

    # 1) bloque temas
    temas[args.tema] = {"estado": "piloto", "nombre": args.nombre or args.tema}
    # 2) keywords con tema propio (bluesky + google-news por defecto)
    kws = cfg.setdefault("keywords", [])
    plataformas = [p.strip() for p in (args.plataformas or "bluesky,google-news").split(",") if p.strip()]
    for kw in args.keywords.split(","):
        k = kw.strip()
        if not k:
            continue
        kws.append({"palabra": k, "plataformas": plataformas, "tema": args.tema})

    _guardar(cfg)
    print(f"[temas] tema '{args.tema}' creado (estado piloto) con {len(args.keywords.split(','))} keywords")
    print(f"[temas] plataformas: {plataformas}")
    if not args.no_regen:
        _regen()
    else:
        print("[temas] --no-regen: regenera luego con detection/gen_fimi_html.py")
    return 0


def _verificar_cobertura_keywords(keywords_csv):
    """Mide cuánto matchearían las keywords dadas en el corpus (14d) y avisa si
    parecen de registro metodológico o matchean muy poco. Usa salud_keywords."""
    try:
        from detection.salud_keywords import medir_cobertura_keywords, DIAS_DEFECTO
        kws = [k.strip() for k in keywords_csv.split(",") if k.strip()]
        res = medir_cobertura_keywords(kws, dias=DIAS_DEFECTO)
    except Exception as e:
        print(f"[temas] aviso: no se pudo verificar cobertura ({e})")
        return
    print(f"[temas] verificación de cobertura ({res['dias']}d): "
          f"{res['n_eventos_matchean']} eventos del corpus matchearían estas keywords "
          f"({res['n_keywords_cero']}/{res['n_keywords']} con 0 matches).")
    for k in res["keywords"]:
        marca = "⚠ metodológica" if k["metodologica"] else ""
        if k["matches"] == 0:
            marca = "⚠ 0 matches — ¿registro metodológico en vez de término temático?" if not k["metodologica"] else "⚠ 0 matches"
        print(f"     - {k['palabra']}: {k['matches']} events {marca}".rstrip())
    if res["n_eventos_matchean"] < 20 and res["n_keywords"] >= 2:
        print("[temas] ⚠ COBERTURA BAJA: revisa las keywords antes de crear el tema. "
              "Un radar FIMI necesita el ruido temático real (p.ej. 'Gaza', 'Irán') "
              "para que el pipeline pueda detectar coordinación sobre él.")


def cmd_exportar(tema):
    """Exporta findings, clusters, bitácora y conteo de eventos del tema."""
    out_dir = ROOT / "data" / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = out_dir / f"{tema}-{time.strftime('%Y%m%d_%H%M%S')}.json"
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    def rows(q, p=()):
        return [dict(r) for r in conn.execute(q, p)]
    data = {
        "tema": tema,
        "exportado": datetime.now(timezone.utc).isoformat(),
        "findings": rows("SELECT fecha, tipo, titulo, detalle, n_sources, n_events, "
                         "intensidad, url FROM findings WHERE tema_id=? ORDER BY fecha", (tema,)),
        "clusters_activos": rows("SELECT cluster_label, overall_score, created_at "
                                 "FROM clusters WHERE tema_id=? ORDER BY created_at", (tema,)),
        "bitacora": rows("SELECT fecha, tipo, estado_anterior, estado_nuevo, motivo, origen "
                         "FROM bitacora WHERE tema=? ORDER BY fecha", (tema,)),
        "n_eventos": conn.execute(
            "SELECT COUNT(*) FROM events e JOIN event_temas t ON t.event_id=e.id"
            " WHERE t.tema_id=?", (tema,)).fetchone()[0],
    }
    conn.close()
    fname.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"[temas] export -> {fname} ({len(data['findings'])} findings, "
          f"{len(data['clusters_activos'])} clusters, {data['n_eventos']} eventos)")
    return str(fname)


def cmd_cerrar(args):
    cfg = _cargar()
    temas = cfg.setdefault("temas", {})
    if args.tema not in temas:
        print(f"[temas] ERROR: el tema '{args.tema}' no existe en config.yaml")
        return 1
    actual = temas[args.tema].get("estado")
    if actual == "cerrado":
        print(f"[temas] '{args.tema}' ya está cerrado. Usa --estado para reabrir.")
        return 0
    if args.dry:
        print(f"[temas] [dry] cerraría '{args.tema}' (estado actual: {actual})"
              + ("" if args.export_disable else " + export a data/export/"))
        return 0

    if not args.export_disable:
        cmd_exportar(args.tema)

    _backup()
    temas[args.tema]["estado"] = "cerrado"
    _guardar(cfg)
    conn = _bitacora_conn()
    bitacora_registrar(conn, args.tema, "cierre", actual, "cerrado",
                       args.nota or "cerrado por el dueño (temas_cli)")
    conn.commit()
    conn.close()
    print(f"[temas] '{args.tema}' marcado cerrado en config.yaml + bitácora")
    if not args.no_regen:
        _regen()
    return 0


def cmd_estado(args):
    cfg = _cargar()
    temas = cfg.setdefault("temas", {})
    if args.tema not in temas:
        print(f"[temas] ERROR: el tema '{args.tema}' no existe")
        return 1
    if args.nuevo_estado not in ESTADOS:
        print(f"[temas] ERROR: estado '{args.nuevo_estado}' no válido "
              f"({sorted(ESTADOS)})")
        return 1
    actual = temas[args.tema].get("estado")
    if actual == args.nuevo_estado:
        print(f"[temas] '{args.tema}' ya está en {args.nuevo_estado}")
        return 0
    if args.dry:
        print(f"[temas] [dry] '{args.tema}': {actual} -> {args.nuevo_estado}")
        return 0
    _backup()
    temas[args.tema]["estado"] = args.nuevo_estado
    _guardar(cfg)
    conn = _bitacora_conn()
    tipo = "cierre" if args.nuevo_estado == "cerrado" else "cambio_estado"
    bitacora_registrar(conn, args.tema, tipo, actual, args.nuevo_estado,
                       args.nota or f"cambio de estado a {args.nuevo_estado}")
    conn.commit()
    conn.close()
    print(f"[temas] '{args.tema}': {actual} -> {args.nuevo_estado} (config + bitácora)")
    if not args.no_regen:
        _regen()
    return 0


def cmd_list(args):
    cfg = _cargar()
    temas = cfg.get("temas", {}) or {}
    for t, meta in temas.items():
        est = meta.get("estado", "produccion")
        kw = _kw_count(cfg, t)
        print(f"  {t:<28} estado={est:<18} keywords={kw}")
    print(f"  total temas: {len(temas)}")


def main():
    ap = argparse.ArgumentParser(description="Gestión de temas del radar FIMI")
    sub = ap.add_subparsers(dest="cmd")

    pa = sub.add_parser("alta", help="crear un tema nuevo (estado piloto)")
    pa.add_argument("tema")
    pa.add_argument("--nombre", default=None)
    pa.add_argument("--keywords", required=True)
    pa.add_argument("--plataformas", default="bluesky,google-news")
    pa.add_argument("--no-regen", action="store_true")
    pa.add_argument("--dry", action="store_true")
    pa.add_argument("--verifica", action="store_true",
                    help="simular cobertura de las keywords contra el corpus antes de crear")

    pc = sub.add_parser("cerrar", help="cerrar un tema (export + config + bitácora)")
    pc.add_argument("tema")
    pc.add_argument("--nota", default="")
    pc.add_argument("--no-regen", action="store_true")
    pc.add_argument("--export-disable", action="store_true")
    pc.add_argument("--dry", action="store_true")

    pe = sub.add_parser("estado", help="cambiar estado de un tema (reabrir, etc.)")
    pe.add_argument("tema")
    pe.add_argument("nuevo_estado")
    pe.add_argument("--nota", default="")
    pe.add_argument("--no-regen", action="store_true")
    pe.add_argument("--dry", action="store_true")

    pl = sub.add_parser("list", help="listar temas y keywords")
    args = ap.parse_args()

    if args.cmd == "alta":
        return cmd_alta(args)
    if args.cmd == "cerrar":
        return cmd_cerrar(args)
    if args.cmd == "estado":
        return cmd_estado(args)
    if args.cmd == "list":
        return cmd_list(args)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
