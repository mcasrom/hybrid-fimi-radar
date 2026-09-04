#!/usr/bin/env python3
"""email_api.py — Backend del newsletter por email del radar FIMI.

Servidor HTTP (solo stdlib, sin dependencias, mismo patrón que newsletter_api.py)
que escucha en 127.0.0.1:3311 y se expone por nginx como https://fimi.viajeinteligencia.com/api/*.

Endpoints:
  GET  /api/health            -> {"ok": true}
  POST /api/subscribe         -> body JSON {"email": "...", "temas": ["frontera_sur", ...]}
                                  Guarda canal='email' (confirmado=0), envía doble opt-in.
  GET  /api/confirmar?id=...  -> marca confirmado=1 (enlace del email). Redirige a la landing.
  GET  /api/baja?id=...       -> elimina la suscripción de email. Redirige a la landing.

Envía con Resend (API key de /home/deploy/newsletter/.env, emisor newsletter@viajeinteligencia.com).
La tabla suscripciones la crea schema_suscripciones.py en data/radar.db.
"""
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
ENV_NEWSLETTER = Path("/home/deploy/newsletter/.env")
ENV_RADAR = ROOT / ".env"
PORT = 3311
BASE_URL = "https://fimi.viajeinteligencia.com"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LIMIT_PER_IP = 10
_hits = {}

import sqlite3
from schema_suscripciones import init as _init_schema


def load_env(filepath: Path):
    cfg = {}
    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return cfg


def resend_cfg():
    cfg = load_env(ENV_NEWSLETTER) or load_env(ENV_RADAR)
    return cfg.get("RESEND_API_KEY", ""), cfg.get("RESEND_FROM", "")


def short_id(canal: str, destino: str) -> str:
    return hashlib.sha256(f"{canal}:{destino}".encode()).hexdigest()[:24]


def send_email(to, subject, html):
    """Envía un email vía Resend (urllib, User-Agent como el newsletter)."""
    key, frm = resend_cfg()
    if not key or not frm:
        return False
    ua = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120"}
    payload = json.dumps({"from": frm, "to": [to], "subject": subject, "html": html}).encode()
    h = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    h.update(ua)
    req = urllib.request.Request("https://api.resend.com/emails", data=payload, headers=h, method="POST")
    try:
        urllib.request.urlopen(req, timeout=30)
        return True
    except Exception:
        return False


def rate_ok(ip: str) -> bool:
    now = time.time()
    _hits[ip] = [t for t in _hits.get(ip, []) if now - t < 3600]
    if len(_hits[ip]) >= LIMIT_PER_IP:
        return False
    _hits[ip].append(now)
    return True


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj, ctype="application/json"):
        if isinstance(obj, str):
            body = obj.encode()
        else:
            body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

    def _redirect(self, url):
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _ip(self):
        return self.client_address[0]

    # ---------- rutas ----------
    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        q = urllib.parse.parse_qs(parsed.query)
        if path == "/api/health":
            return self._send(200, {"ok": True})
        if path == "/api/confirmar":
            sid = (q.get("id") or [""])[0]
            if not sid:
                return self._send(400, {"error": "falta id"})
            conn = _init_schema()
            conn.execute("UPDATE suscripciones SET confirmado=1 WHERE id=? AND canal='email'", (sid,))
            conn.commit()
            conn.close()
            return self._redirect(BASE_URL + "?confirmado=1")
        if path == "/api/baja":
            sid = (q.get("id") or [""])[0]
            if sid:
                conn = _init_schema()
                conn.execute("DELETE FROM suscripciones WHERE id=? AND canal='email'", (sid,))
                conn.commit()
                conn.close()
            return self._redirect(BASE_URL + "?baja=1")
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != "/api/subscribe":
            return self._send(404, {"error": "not found"})
        if not rate_ok(self._ip()):
            return self._send(429, {"error": "demasiadas peticiones"})
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return self._send(400, {"error": "sin cuerpo"})
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            return self._send(400, {"error": "json invalido"})
        email = (data.get("email") or "").strip().lower()
        temas = data.get("temas") or []
        if not EMAIL_RE.match(email):
            return self._send(400, {"error": "email invalido"})
        if not isinstance(temas, list) or not temas:
            return self._send(400, {"error": "selecciona al menos un tema"})
        temas = [str(t) for t in temas[:6]]
        sid = short_id("email", email)
        conn = _init_schema()
        row = conn.execute("SELECT * FROM suscripciones WHERE id=?", (sid,)).fetchone()
        if row:
            conn.execute("UPDATE suscripciones SET temas=?, confirmado=0 WHERE id=?",
                         (json.dumps(temas), sid))
            conn.commit()
            conn.close()
            self._reenviar_confirmacion(email, sid, temas)
            return self._send(200, {"ok": True, "confirmado": False})
        conn.execute(
            "INSERT INTO suscripciones (id, canal, destino, temas, frecuencia, confirmado)"
            " VALUES (?,?,?,?,?,0)",
            (sid, "email", email, json.dumps(temas), "semanal"))
        conn.commit()
        conn.close()
        self._reenviar_confirmacion(email, sid, temas)
        return self._send(200, {"ok": True, "confirmado": False})

    def _reenviar_confirmacion(self, email, sid, temas):
        link = f"{BASE_URL}/api/confirmar?id={sid}"
        html = ('<div style="font-family:system-ui;max-width:600px;margin:0 auto">'
                f'<h2>Radar FIMI · Confirma tu suscripción</h2>'
                f'<p>Te suscribiste al resumen semanal de: <b>{", ".join(temas)}</b>.</p>'
                f'<p>Para activar el envío, confirma tu email:</p>'
                f'<p><a href="{link}" style="background:#c2410c;color:#fff;padding:10px 18px;'
                f'border-radius:6px;text-decoration:none;font-weight:700">Confirmar suscripción</a></p>'
                f'<p>Si no fuiste tú, ignora este correo.</p>'
                f'<p style="font-size:.8rem;color:#888">Radar FIMI · fimi.viajeinteligencia.com</p></div>')
        send_email(email, "Radar FIMI · Confirma tu suscripción", html)


def main():
    _init_schema()
    srv = HTTPServer(("127.0.0.1", PORT), H)
    print(f"[email_api] escuchando en 127.0.0.1:{PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
