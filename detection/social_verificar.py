#!/usr/bin/env python3
"""social_verificar.py — ¿el ciclo social de hoy (mar/jue) está vivo?

Se ejecuta DESPUÉS del cron de las 07:15. Comprueba que la rotación generó
borrador o publicación y que el bot que atiende los botones está ONLINE.
Si algo falla, avisa por Telegram con sendMessage (independiente del
long-poll: si el bot no puede recibir updates, este aviso SÍ llega).

NO imprime credenciales.
Uso:  python detection/social_verificar.py [--fecha AAAAMMDD] [--json]
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "logs" / "social_rotacion.log"
ESTADO = ROOT / "data" / "rotacion_estado.json"
DRAFTS = Path("/home/deploy/social-poster")
WEB = "https://fimi.viajeinteligencia.com"


def _env():
    d = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            d[k.strip()] = v.strip()
    return d


def avisar(texto: str) -> bool:
    e = _env()
    tok = e.get("FIMI_TELEGRAM_BOT_TOKEN", "")
    chat = e.get("FIMI_OWNER_CHAT", "")
    if not tok or not chat:
        print("[verify] sin token/chat: no puedo avisar", file=sys.stderr)
        return False
    try:
        import requests
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          data={"chat_id": chat, "text": texto[:3900],
                                "parse_mode": "HTML"}, timeout=30)
        ok = bool(r.ok and r.json().get("ok"))
        print(f"[verify] aviso enviado={ok} rc={getattr(r, 'status_code', '?')}")
        return ok
    except Exception as ex:
        print(f"[verify] aviso fallo: {type(ex).__name__}: {ex}", file=sys.stderr)
        return False


def bot_online() -> bool:
    try:
        js = json.loads(subprocess.run(["pm2", "jlist"], capture_output=True,
                                       text=True, timeout=30).stdout or "[]")
        for a in js:
            if a.get("name") == "radar-fimi-bot":
                st = a.get("pm2_env", {}).get("status", "?")
                print(f"[verify] radar-fimi-bot status={st} "
                      f"uptime_ms={a.get('pm2_env', {}).get('pm_uptime', '?')}")
                return st == "online"
    except Exception as ex:
        print(f"[verify] pm2 jlist fallo: {ex}", file=sys.stderr)
    print("[verify] radar-fimi-bot NO encontrado en pm2")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", default=datetime.now(timezone.utc).strftime("%Y%m%d"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    fecha = args.fecha

    checks = []
    problems = []

    # 1) la rotación corrió hoy
    rotó = False
    if LOG.exists():
        txt = LOG.read_text(errors="ignore")
        rotó = "=== tema:" in txt or "[silencio]" in txt
    if not rotó:
        # el log rota a diario: mirar tambien el .1
        p1 = LOG.with_suffix(LOG.suffix + ".1")
        if p1.exists() and ("=== tema:" in p1.read_text(errors="ignore")):
            rotó = True
    checks.append(("rotacion_hoy", rotó, "social_rotacion.log sin marca de hoy"))
    if not rotó:
        problems.append("La rotación de las 07:15 no dejó rastro en el log "
                        "(puede no haber corrido, o falló antes de loguear).")

    # 2) publicacion de hoy?
    publicado = False
    tema_pub = None
    if ESTADO.exists():
        try:
            st = json.loads(ESTADO.read_text())
            hits = [p for p in st.get("publicados", []) if p.get("fecha") == fecha]
            publicado = bool(hits)
            tema_pub = hits[0].get("tema") if hits else None
        except Exception as ex:
            problems.append(f"rotacion_estado.json ilegible: {ex}")
    checks.append(("publicado_hoy", publicado, f"sin publicación hoy ({fecha})"))

    # 3) si no se publico, deberia existir borrador esperando aprobacion
    borrador = sorted(DRAFTS.glob(f"radar_{fecha}_*.md")) if DRAFTS.exists() else []
    if not publicado:
        checks.append(("borrador_para_aprobar", bool(borrador),
                       "no hay borrador del día: no hay nada que aprobar"))
        if not borrador:
            problems.append("No se publicó y no hay borrador del día: "
                            "no hay nada pendiente de aprobación.")

    # 4) el bot de los botones debe estar online
    on = bot_online()
    checks.append(("bot_online", on, "radar-fimi-bot no está online: los botones no responden"))
    if not on:
        problems.append("El bot <b>radar-fimi-bot</b> no está online: aunque te llegue "
                        "el borrador, los botones ✅/❌ no responderán. "
                        "Arranque: <code>pm2 start detection/radar_bot.py "
                        "--name radar-fimi-bot --cwd /home/deploy/hybrid-fimi-radar</code>")

    # 5) el radar PNG del tema debe existir (el post lo lleva)
    #    (informativo: se valida al publicar)

    if args.json:
        print(json.dumps({"fecha": fecha, "checks": checks,
                          "publicado": publicado, "tema": tema_pub,
                          "borradores": [p.name for p in borrador],
                          "problems": problems}, ensure_ascii=False, indent=1))
    else:
        for n, ok, why in checks:
            print(f"[verify] {'OK  ' if ok else 'FALLO'} {n:<22} {'' if ok else why}")
        if publicado:
            print(f"[verify] resumen: HAY publicación de hoy ({tema_pub}). No hace falta aprobar.")
        else:
            print(f"[verify] resumen: pendiente de aprobación "
                  f"({[p.name for p in borrador] or 'sin borrador'}).")

    if problems:
        avisar("⚠️ <b>Ciclo social FIMI con problemas</b> (" + fecha + ")\n\n"
               + "\n".join("• " + p for p in problems)
               + f"\n\nVer <code>logs/social_rotacion.log</code> y <code>{WEB}</code>")
        return 1
    print("[verify] todo correcto")
    return 0


if __name__ == "__main__":
    sys.exit(main())
