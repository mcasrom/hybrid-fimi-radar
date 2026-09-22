#!/usr/bin/env python3
"""Rotacion de posts del radar FIMI (distribucion semi-automatica).

Elige el SIGUIENTE tema EN ROTACION que tenga senal (>=1 cluster HIGH/CRITICAL),
prepara un post con el PNG del tema (radar-<tema>.png) y:

  - por defecto: deja un BORRADOR (no publica nada) y lo imprime.
  - con --publicar: publica en Mastodon + Bluesky (1 comando, sin tocar cada red).
  - siempre deja el borrador para X (publicacion manual).

Modo SILENCIO: si NINGUN tema tiene senal, no publica nada (el silencio informa).
Anti-repeticion: no repite el tema anterior.

Uso:
  python detection/social_rotacion.py            # borrador (revisar)
  python detection/social_rotacion.py --publicar # publicar Mastodon+Bluesky
  python detection/social_rotacion.py --tema X   # forzar un tema (pruebas)
  python detection/social_rotacion.py --dry      # solo imprime (no escribe draft)
"""
import argparse
import json
import random
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "radar.db"
ESTADO = ROOT / "data" / "rotacion_estado.json"
DRAFT_DIR = Path("/home/deploy/social-poster")
IMG_BASE = "https://fimi.viajeinteligencia.com"
WEB = "https://fimi.viajeinteligencia.com"

PLANTILLAS = [
    ("📡 {nombre}: {senales} en banda alta. {top}. "
     "Mapa y evidencia: {web}/#{tema}"),
    ("🛰️ Radar FIMI · {nombre}: {senales} en alerta (≥60). {top}. "
     "{web}/#{tema}"),
    ("📊 Así está {nombre} en el radar: {senales}. {top}. "
     "Método abierto: {web}/#{tema}"),
]


def _temas_activos():
    import yaml
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    return [(t, d.get("nombre", t)) for t, d in cfg.get("temas", {}).items()
            if d.get("estado") in ("produccion", "piloto")]


def _senal(tema):
    """(n_alta, top_label, top_score, banda) del snapshot actual del tema."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT cluster_label, overall_score FROM clusters WHERE tema_id=? "
            "ORDER BY overall_score DESC", (tema,)).fetchall()
    finally:
        conn.close()
    alta = [r for r in rows if (r["overall_score"] or 0) >= 60]
    if not rows:
        return 0, "", 0, ""
    top = rows[0]
    sc = top["overall_score"] or 0
    banda = ("CRITICAL" if sc >= 80 else "HIGH" if sc >= 60 else
             "ANOMALOUS" if sc >= 40 else "WATCH" if sc >= 20 else "NORMAL")
    return len(alta), top["cluster_label"], round(sc, 1), banda


def _cargar_estado():
    try:
        return json.loads(ESTADO.read_text())
    except Exception:
        return {"ultimo_tema": None, "publicados": []}


def _guardar_estado(st):
    ESTADO.write_text(json.dumps(st, ensure_ascii=False, indent=2))


def _publicar(texto, img_url):
    """Publica en Mastodon + Bluesky. Devuelve (ok_masto, ok_bsky)."""
    out = []
    for cmd in (
        ["python3", "/home/deploy/social-poster/publish_mastodon.py", texto, img_url],
        ["python3", "/home/deploy/social-poster/publish_bluesky.py", "-t", texto, "-s", img_url],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            out.append(r.returncode == 0)
            print(f"[pub] {cmd[1].split('/')[-1]}: rc={r.returncode} {r.stdout.strip()[:80]} {r.stderr.strip()[:80]}")
        except Exception as e:
            out.append(False)
            print(f"[pub] {cmd[1].split('/')[-1]}: error {e}")
    return out


def _notify_telegram(texto, img_path=None, tema=None):
    """Avisa al dueño por Telegram CON la imagen y botones Publicar/Descartar."""
    try:
        env = {}
        for line in open(ROOT / ".env"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
        tok = env.get("FIMI_TELEGRAM_BOT_TOKEN")
        chat = env.get("FIMI_OWNER_CHAT")
        if not tok or not chat:
            return
        import requests
        api = f"https://api.telegram.org/bot{tok}"
        kbd = None
        if tema:
            kbd = json.dumps({"inline_keyboard": [[
                {"text": "✅ Publicar", "callback_data": f"post:pub:{tema}"},
                {"text": "❌ Descartar", "callback_data": f"post:no:{tema}"}]]})
        if img_path and Path(img_path).exists():
            with open(img_path, "rb") as fh:
                data = {"chat_id": chat, "caption": texto[:1024]}
                if kbd:
                    data["reply_markup"] = kbd
                requests.post(f"{api}/sendPhoto",
                              data=data,
                              files={"photo": ("radar.png", fh, "image/png")}, timeout=60)
        else:
            data = {"chat_id": chat, "text": texto[:3900]}
            if kbd:
                data["reply_markup"] = kbd
            requests.post(f"{api}/sendMessage", data=data, timeout=20)
    except Exception as e:
        print("[notify] error:", e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--publicar", action="store_true", help="publica en Mastodon+Bluesky")
    ap.add_argument("--tema", help="forzar un tema (pruebas)")
    ap.add_argument("--dry", action="store_true", help="solo imprime")
    args = ap.parse_args()

    st = _cargar_estado()
    temas = _temas_activos()

    # senal por tema
    info = {}
    for t, nombre in temas:
        n, top, sc, banda = _senal(t)
        info[t] = {"nombre": nombre, "n": n, "top": top, "score": sc, "banda": banda}

    # elegir tema: en rotacion, con senal, sin repetir el anterior
    orden = [t for t, _ in temas]
    elegido = None
    if args.tema:
        elegido = args.tema if args.tema in info else None
    else:
        ultimo = st.get("ultimo_tema")
        idx = (orden.index(ultimo) + 1) if ultimo in orden else 0
        for k in range(len(orden)):
            t = orden[(idx + k) % len(orden)]
            if info[t]["n"] >= 1:
                elegido = t
                break

    if not elegido:
        print("[silencio] ningun tema con senal (>=1 HIGH/CRITICAL). No se publica.")
        return

    d = info[elegido]
    plantilla = random.choice(PLANTILLAS)
    top_txt = f"Top {d['top']} {d['score']:.0f}/100 {d['banda']}" if d["top"] else ""
    senales = f"{d['n']} señal" if d["n"] == 1 else f"{d['n']} señales"
    texto = plantilla.format(nombre=d["nombre"], n=d["n"], senales=senales, top=top_txt, tema=elegido, web=WEB)
    texto += "\n\n⚖️ Señal de coordinación, no atribución."
    if len(texto) > 300:  # limite Bluesky
        texto = texto[:296] + " …"

    img_url = f"{IMG_BASE}/radar-{elegido}.png"
    print(f"=== tema: {elegido} ({d['nombre']}) | {d['n']} alta(s) | {d['banda']} {d['score']} ===")
    print(texto)
    print(f"imagen: {img_url}")

    if args.dry:
        return

    # borrador para X (siempre)
    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    fecha = datetime.now(timezone.utc).strftime("%Y%m%d")
    draft = DRAFT_DIR / f"radar_{fecha}_{elegido}.md"
    draft.write_text(
        f"# Radar FIMI — {elegido} ({fecha})\n\n"
        f"**Mastodon/Bluesky (auto si --publicar):**\n\n{texto}\n\n"
        f"**Imagen:** {img_url}\n\n"
        f"**X (manual):**\n\n{texto}\n")
    print(f"[draft] {draft}")

    if args.publicar:
        ok = _publicar(texto, img_url)
        if any(ok):
            st["ultimo_tema"] = elegido
            st.setdefault("publicados", []).append(
                {"tema": elegido, "fecha": fecha, "ts": int(time.time())})
            _guardar_estado(st)
        print(f"\n[X-TEXTO]\n{texto}\n[/X-TEXTO]\n[X-IMG]{img_url}[/X-IMG]")
    else:
        print("[borrador] no publicado. Revisar y re-ejecutar con --publicar")
        _notify_telegram(
            f"📝 Borrador del radar — {elegido} ({d['banda']} {d['score']})\n\n{texto}",
            img_path=f"/var/www/fimi/radar-{elegido}.png", tema=elegido)


if __name__ == "__main__":
    main()
