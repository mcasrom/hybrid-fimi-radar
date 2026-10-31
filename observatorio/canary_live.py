#!/usr/bin/env python3
"""Canario del observatorio: captura fresca, páginas con datos y sin errores JS."""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
BASE = "https://fimi.viajeinteligencia.com"
LATEST = BASE + "/observatorio/data/latest.json"
CHROME = "/home/deploy/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome"
STATE = Path(os.environ.get("OBS_CANARY_STATE", ROOT / "data" / "canary_state.json"))
ENV = Path("/home/deploy/hybrid-fimi-radar/.env")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
MAX_AGE_MIN = 90
PAGES = [
    ("infraestructuras", "infraestructuras_espana"),
    ("ceuta", "frontera_sur"),
    ("juventud", "protestas_juveniles"),
    ("campana", "elecciones_generales"),
]


def load_env():
    data = {}
    try:
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return data


def telegram(text):
    env = load_env()
    token = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN") or env.get("FIMI_TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("FIMI_OWNER_CHAT") or env.get("FIMI_OWNER_CHAT")
    if not token or not chat:
        print("telegram: sin credenciales", file=sys.stderr)
        return False
    body = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request("https://api.telegram.org/bot" + token + "/sendMessage", data=body)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception as e:
        print("telegram:", e, file=sys.stderr)
        return False


def check_latest(errors):
    try:
        req = urllib.request.Request(LATEST + "?x=" + str(int(datetime.now().timestamp())), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.load(resp)
    except Exception as e:
        errors.append(f"latest.json: {e}")
        return
    try:
        updated = datetime.fromisoformat(data["updated_at"])
        age = (datetime.now(timezone.utc) - updated).total_seconds() / 60
        if age > MAX_AGE_MIN:
            errors.append(f"captura con {age:.0f} min (max {MAX_AGE_MIN})")
    except Exception as e:
        errors.append(f"updated_at: {e}")
    topics = data.get("topics") or {}
    for _slug, topic in PAGES:
        if not topics.get(topic):
            errors.append(f"tema sin datos: {topic}")
    status = data.get("status") or {}
    if not (status.get("topics") or {}):
        errors.append("status por tema ausente")


def check_pages(errors):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=CHROME, args=["--no-sandbox"])
        context = browser.new_context(user_agent=UA)
        for slug, topic in PAGES:
            page = context.new_page()
            page_errors = []
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            try:
                page.goto(f"{BASE}/observatorio/{slug}/", wait_until="networkidle", timeout=45000)
                page.wait_for_timeout(600)
                text = page.locator(".livebox").inner_text(timeout=5000)
                if "No se pudo" in text or "Cargando" in text or "publicaciones" not in text:
                    errors.append(f"{slug}: livebox sin datos")
                if page_errors:
                    errors.append(f"{slug}: JS {page_errors[0][:120]}")
            except Exception as e:
                errors.append(f"{slug}: {str(e)[:160]}")
            finally:
                page.close()
        browser.close()


def main():
    errors = []
    check_latest(errors)
    check_pages(errors)
    previous = "up"
    try:
        previous = json.loads(STATE.read_text(encoding="utf-8")).get("status", "up")
    except Exception:
        pass
    if errors:
        msg = "🚨 Observatorio: " + " | ".join(errors[:6])
        print(msg)
        if previous != "down" and "--dry" not in sys.argv:
            telegram(msg)
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({"status": "down", "at": datetime.now(timezone.utc).isoformat()}) + "\n", encoding="utf-8")
        return 1
    print("OK observatorio")
    if previous == "down" and "--dry" not in sys.argv:
        telegram("✅ Observatorio OK de nuevo: captura y páginas con datos")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"status": "up", "at": datetime.now(timezone.utc).isoformat()}) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
