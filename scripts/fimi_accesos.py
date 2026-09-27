#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fimi_accesos.py — CLI del registro de accesos del observatorio.

    python3 scripts/fimi_accesos.py ingest            # lee lo nuevo de los logs
    python3 scripts/fimi_accesos.py daily             # daily list de ayer
    python3 scripts/fimi_accesos.py daily --dia 2026-09-21
    python3 scripts/fimi_accesos.py daily --todos --no-tg
    python3 scripts/fimi_accesos.py stats
    python3 scripts/fimi_accesos.py lectores
    python3 scripts/fimi_accesos.py origenes            # de dónde viene la gente
    python3 scripts/fimi_accesos.py reset --confirmar   # rebaca desde cero

El daily escribe `data/listas/AAAA-MM-DD.md` y avisa por Telegram. La base es
incremental: `ingest` solo lee lo que no se ha leído (cursor por inodo+offset),
así que se puede lanzar cada hora sin duplicar ni perder nada.

El titular NO es el número de páginas vistas sino de dónde viene la gente: en
las medidas reales, contar "humano probable" daba ~35 lecturas en 15 días y
todas eran rastreadores. El referrer es lo único que distingue a una persona de
una máquina, y se guardó en la BD precisamente por eso.
"""

import argparse
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detection.accesos import (  # noqa: E402
    DB_PATH, SITIO, asistentes_dia, conectar, conversiones_del_dia,
    daily_markdown, ingestar, lectores_del_dia, origenes_del_dia,
    origenes_reales, resumen_dia, stats,
)

FIMI_ENV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def _cfg():
    """Mismo cargador que usa el resto del ecosistema (envio_informe_semanal):
    el .env del repo, no el entorno, porque en cron no hay variables."""
    cfg = {}
    if os.path.exists(FIMI_ENV):
        with open(FIMI_ENV) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg.setdefault(k.strip(),
                                   v.strip().strip('"').strip("'"))
    return cfg


def _tg(texto):
    cfg = _cfg()
    TG_TOKEN = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN") or cfg.get(
        "FIMI_TELEGRAM_BOT_TOKEN", "")
    TG_CHAT = os.environ.get("FIMI_OWNER_CHAT") or cfg.get("FIMI_OWNER_CHAT", "")
    if not TG_TOKEN or not TG_CHAT:
        print("[accesos] Telegram no configurado; no se avisa", flush=True)
        return False
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    datos = urllib.parse.urlencode({
        "chat_id": TG_CHAT, "text": texto, "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    try:
        with urllib.request.urlopen(url, datos, timeout=20) as r:
            return r.status == 200
    except Exception as exc:  # noqa: BLE001
        print(f"[accesos] ERROR Telegram: {exc}", flush=True)
        return False


def cmd_ingest(args):
    con = conectar(args.db)
    antes = stats(con)
    n = ingestar(con, log_dir=args.log_dir, host=args.host,
                 guardar_raw=args.guardar_raw, verbose=args.verbose)
    despues = stats(con)
    con.close()
    print(f"[accesos] {n} peticiones nuevas "
          f"(total {antes.get('req', 0)} -> {despues.get('req', 0)})")
    if args.stats:
        print(f"[accesos] {despues}")
    return 0


def cmd_daily(args):
    con = conectar(args.db)
    hoy = time.strftime("%Y-%m-%d", time.gmtime())
    dias = [args.dia] if args.dia else [hoy]
    if args.todos:
        filas = [f["dia"] for f in con.execute(
            "SELECT DISTINCT dia FROM accesos ORDER BY dia")]
        dias = [d for d in filas
                if not args.todo_desde or d >= args.todo_desde]
    listas_dir = os.path.join(os.path.dirname(os.path.abspath(args.db)),
                             "listas")
    os.makedirs(listas_dir, exist_ok=True)
    enviados = 0
    for dia in dias:
        n = con.execute("SELECT COUNT(*) n FROM accesos WHERE dia=?",
                        (dia,)).fetchone()["n"]
        if not n:
            print(f"[accesos] {dia}: sin datos; se omite")
            continue
        md = daily_markdown(con, dia, db=args.db)
        ruta = os.path.join(listas_dir, f"{dia}.md")
        with open(ruta, "w") as fh:
            fh.write(md)
        led = [f for f in lectores_del_dia(con, dia) if f["nivel"] == "LECTOR"]
        r = resumen_dia(con, dia)
        org = origenes_del_dia(con, dia)
        ia = asistentes_dia(con, dia)
        conv = conversiones_del_dia(con, dia)
        ext = sum(v["req"] for v in origenes_reales(org).values())
        print(f"[accesos] {dia}: {ruta} "
              f"({r.get('HUMANO_PROBABLE', {}).get('req', 0)} probable(s), "
              f"{len(led)} lector(es), {ext} origen(es) externos)")
        if args.tg and dia == dias[-1] and not args.no_tg:
            org_txt = ", ".join(f"{k} {v['req']}"
                                for k, v in origenes_reales(org).items()) \
                or "sin orígenes externos"
            lineas = [
                f"<b>Accesos FIMI — {dia}</b>",
                f"Lectores: {len(led)}",
                f"Orígenes externos: {ext} ({org_txt})",
                f"IA con alguien detrás: {ia['gente']} apertura(s) "
                f"· crawlers de IA: {ia['crawlers']}",
                f"Conversiones: {len(conv)}",
                f"Probable: {r.get('HUMANO_PROBABLE', {}).get('req', 0)} · "
                f"bot {r.get('BOT', {}).get('req', 0)} · "
                f"interno {r.get('INTERNAL', {}).get('req', 0)}",
            ]
            if not ext and not ia["gente"] and not len(led):
                lineas.append("Sin gente. Todo esto fueron máquinas.")
            if _tg("\n".join(lineas)):
                enviados += 1
    con.close()
    if args.tg and not args.no_tg:
        print(f"[accesos] daily enviado a Telegram ({enviados})")
    return 0


def cmd_stats(args):
    con = conectar(args.db)
    s = stats(con)
    print(f"[accesos] {s}")
    print("\nPor día (dia · req · probables · IPs · lecturas externas):")
    print("  'lecturas' = contenido abierto por HUMANO_PROBABLE, sin contar el")
    print("  canario ni tus visitas. OJO: 'probables' NO son personas. En los")
    print("  15 días medidos, 18 de esas 'lecturas' fueron 18 rastreadores")
    print("  distintos con la misma UA de iOS 13. Usa `origenes`: el referrer")
    print("  es lo único que separa a una persona de una máquina.")
    for f in con.execute(
            "SELECT dia, COUNT(*) req,"
            " SUM(categoria='HUMANO_PROBABLE') prob,"
            " COUNT(DISTINCT ip_pseudo) ips,"
            " SUM(es_profundo AND categoria='HUMANO_PROBABLE') prof"
            " FROM accesos GROUP BY dia ORDER BY dia"):
        print(f"  {f['dia']}  {f['req']:>5}  {f['prob']:>4}  {f['ips']:>4}  "
              f"{f['prof']:>4}")
    con.close()
    return 0


def cmd_lectores(args):
    con = conectar(args.db)
    dias = [args.dia] if args.dia else [f["dia"] for f in con.execute(
        "SELECT DISTINCT dia FROM accesos ORDER BY dia")]
    total = {}
    for dia in dias:
        for f in lectores_del_dia(con, dia):
            if f["nivel"] != "LECTOR":
                continue
            e = total.setdefault(f["ip"], {"dias": 0, "req": 0, "prof": 0,
                                          "rutas": set()})
            e["dias"] += 1
            e["req"] += f["req"]
            e["prof"] += f["profundas"] or 0
            for r in con.execute(
                    "SELECT DISTINCT ruta FROM accesos WHERE dia=? AND ip_pseudo=?",
                    (dia, f["ip"])):
                e["rutas"].add(r["ruta"])
    print(f"IP seudonima  ·  días  ·  req  ·  contenido  ·  rutas")
    for ip, e in sorted(total.items(),
                        key=lambda kv: (-kv[1]["prof"], -kv[1]["dias"])):
        rutas = ", ".join(sorted(e["rutas"])[:6])
        print(f"{ip}  ·  {e['dias']:>2}  ·  {e['req']:>3}  ·  {e['prof']:>3}  ·  {rutas}")
    con.close()
    return 0


def cmd_origenes(args):
    """De dónde viene la gente. Esta es la cifra que sustituye a los pageviews."""
    con = conectar(args.db)
    dias = [args.dia] if args.dia else [f["dia"] for f in con.execute(
        "SELECT DISTINCT dia FROM accesos ORDER BY dia")]
    if args.desde:
        dias = [d for d in dias if d >= args.desde]
    tot = {}
    print(f"{'tipo de origen':<26} {'peticiones':>10} {'IP':>5}  ejemplos")
    for dia in dias:
        for k, v in origenes_del_dia(con, dia).items():
            e = tot.setdefault(k, {"req": 0, "ips": set(), "refs": set()})
            e["req"] += v["req"]
            e["ips"] |= v["ips"]
            e["refs"] |= v["refs"]
    for k, v in sorted(tot.items(), key=lambda kv: -kv[1]["req"]):
        ej = ", ".join(list(v["refs"])[:3])
        print(f"{k:<26} {v['req']:>10} {len(v['ips']):>5}  {ej[:60]}")

    ext = sum(v["req"] for v in origenes_reales(tot).values())
    gen = ("(ua LIKE '%Claude-User%' OR ua LIKE '%claude-web%'"
           " OR ua LIKE '%ChatGPT-User%' OR ua LIKE '%Perplexity-User%')")
    ia = con.execute(
        f"SELECT COUNT(*) req, COUNT(DISTINCT ip_pseudo) ips FROM accesos"
        f" WHERE categoria='ASISTENTE_IA'"
        + (f" AND dia>='{args.desde}'" if args.desde else "")
    ).fetchone()
    g = con.execute(
        f"SELECT COUNT(*) req, COUNT(DISTINCT ip_pseudo) ips FROM accesos"
        f" WHERE categoria='ASISTENTE_IA' AND {gen}"
        + (f" AND dia>='{args.desde}'" if args.desde else "")
    ).fetchone()
    conv = con.execute(
        "SELECT COUNT(*) n FROM accesos WHERE ruta_base IN"
        " ('/api/confirmar','/api/sugerir','/api/alta','/api/suscribir',"
        "  '/api/newsletter','/api/clave','/api/key')"
        + (f" AND dia>='{args.desde}'" if args.desde else "")
    ).fetchone()
    print(f"\nOrígenes externos totales: {ext}")
    print(f"IA con alguien detrás: {g['req']} apertura(s) · {g['ips']} IP")
    print(f"Crawlers de IA (indexan, no son público): {ia['req'] - g['req']}")
    print(f"Conversiones: {conv['n']}")
    print("\n'raíz de buscador' son previsualizadores y crawlers: se dejan")
    print("fuera del total de orígenes a propósito. Los crawlers de IA se")
    print("cuentan aparte de la gente a propósito: son las mismas máquinas")
    print("que descargan la página, pero detrás no hay ninguna persona.")
    con.close()
    return 0


def cmd_reset(args):
    if not args.confirmar:
        print("[accesos] reset requiere --confirmar")
        return 1
    import sqlite3
    con = sqlite3.connect(args.db)
    con.executescript("DELETE FROM accesos; DELETE FROM ip_dia;"
                      "DELETE FROM ip_raw; DELETE FROM cursor_log;")
    con.commit()
    con.close()
    print("[accesos] base vaciada. Siguiente `ingest` rebaca todo.")
    return 0


def main():
    p = argparse.ArgumentParser(description="Registro de accesos FIMI")
    p.add_argument("--db", default=DB_PATH)
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("ingest", help="lee lo nuevo de los logs de nginx")
    g.add_argument("--log-dir", default="/var/log/nginx")
    g.add_argument("--host", default=SITIO)
    g.add_argument("--guardar-raw", action="store_true",
                   help="conserva la IP en claro (tabla ip_raw)")
    g.add_argument("--stats", action="store_true")
    g.add_argument("-v", "--verbose", action="store_true")
    g.set_defaults(func=cmd_ingest)

    d = sub.add_parser("daily", help="genera el daily list")
    d.add_argument("--dia")
    d.add_argument("--todos", action="store_true",
                   help="regenera todos los días presentes en la base")
    d.add_argument("--todo-desde", default="",
                   help="solo días >= esta fecha (YYYY-MM-DD); vacío = todos")
    d.add_argument("--tg", action="store_true", help="avisa por Telegram")
    d.add_argument("--no-tg", action="store_true")
    d.set_defaults(func=cmd_daily)

    s = sub.add_parser("stats")
    s.set_defaults(func=cmd_stats)

    l = sub.add_parser("lectores", help="lectores acumulados de todo el histórico")
    l.add_argument("--dia")
    l.set_defaults(func=cmd_lectores)

    o = sub.add_parser("origenes",
                       help="de dónde viene la gente (la cifra que cuenta)")
    o.add_argument("--dia")
    o.add_argument("--desde", default="", help="solo días >= YYYY-MM-DD")
    o.set_defaults(func=cmd_origenes)

    r = sub.add_parser("reset")
    r.add_argument("--confirmar", action="store_true")
    r.set_defaults(func=cmd_reset)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
