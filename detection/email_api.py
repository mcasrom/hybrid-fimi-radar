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
  POST /api/feedback          -> body JSON {"tema": "...", "voto": "si|no|ns"}
                                  Voto ligero "¿Te resulta útil este tema?". Rate-limit por IP.
  POST /api/sugerir           -> body JSON {"texto": "..."}
                                  Sugerencia de tema nuevo (web). Rate-limit por IP + reenvío
                                  al dueño por Telegram (chan FIMI_OWNER_CHAT).
  GET  /api/admin/feedback    -> resumen de votos y sugerencias. Header `x-admin-secret`
                                  (env/.env FIMI_ADMIN_SECRET). SOLO visible para el dueño:
                                  sin cómputo público (un radar FIMI no debe ser manipulable).

Envía con Resend (API key de /home/deploy/newsletter/.env, emisor newsletter@viajeinteligencia.com).
La tabla suscripciones la crea schema_suscripciones.py en data/radar.db; feedback/sugerencias
las crea schema_feedback.py.
"""
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
ENV_NEWSLETTER = Path("/home/deploy/newsletter/.env")
ENV_RADAR = ROOT / ".env"
PORT = 3311
BASE_URL = "https://fimi.viajeinteligencia.com"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LIMIT_PER_IP = 10          # subscribe: 10/h
LIMIT_FEEDBACK_IP = 20     # feedback/sugerir combinados: 20/h
TEMAS_VALIDOS = {"frontera_sur", "geopolitica_ue_marruecos", "politica_nacional"}
VOTOS_VALIDOS = {"si", "no", "ns"}
_hits = {}
_hits_fb = {}

import sqlite3
from schema_suscripciones import init as _init_schema
from schema_feedback import init as _init_feedback


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


def rate_feedback_ok(ip: str) -> bool:
    """Rate-limit combinado para feedback (votos) + sugerencias: 20/h por IP."""
    now = time.time()
    _hits_fb[ip] = [t for t in _hits_fb.get(ip, []) if now - t < 3600]
    if len(_hits_fb[ip]) >= LIMIT_FEEDBACK_IP:
        return False
    _hits_fb[ip].append(now)
    return True


def admin_secret() -> str:
    cfg = load_env(ENV_RADAR) or {}
    return os.environ.get("FIMI_ADMIN_SECRET", "") or cfg.get("FIMI_ADMIN_SECRET", "")


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
        if path == "/api/admin/feedback":
            # Solo el dueno: header x-admin-secret == FIMI_ADMIN_SECRET (env/.env).
            if self.headers.get("x-admin-secret", "") != admin_secret():
                return self._send(403, {"error": "prohibido"})
            conn = _init_feedback()
            votos = {}
            for row in conn.execute("SELECT tema, voto, COUNT(*) n FROM feedback GROUP BY tema, voto"):
                votos.setdefault(row["tema"], {})[row["voto"]] = row["n"]
            sugs = [dict(r) for r in conn.execute(
                "SELECT id, texto, canal, created_at AS fecha_alta FROM sugerencias ORDER BY id DESC LIMIT 50")]
            conn.close()
            return self._send(200, {"ok": True, "votos": votos, "sugerencias": sugs})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path not in ("/api/subscribe", "/api/feedback", "/api/sugerir"):
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return self._send(400, {"error": "sin cuerpo"})
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            return self._send(400, {"error": "json invalido"})
        if parsed.path == "/api/feedback":
            if not rate_feedback_ok(self._ip()):
                return self._send(429, {"error": "demasiadas peticiones"})
            tema = str(data.get("tema") or "").strip()
            voto = str(data.get("voto") or "").strip().lower()
            if tema not in TEMAS_VALIDOS:
                return self._send(400, {"error": "tema invalido"})
            if voto not in VOTOS_VALIDOS:
                return self._send(400, {"error": "voto invalido (si|no|ns)"})
            conn = _init_feedback()
            conn.execute("INSERT INTO feedback (tema, voto, ip) VALUES (?,?,?)",
                         (tema, voto, self._ip()))
            conn.commit()
            conn.close()
            return self._send(200, {"ok": True})
        if parsed.path == "/api/sugerir":
            if not rate_feedback_ok(self._ip()):
                return self._send(429, {"error": "demasiadas peticiones"})
            texto = (data.get("texto") or "").strip()
            if not texto:
                return self._send(400, {"error": "escribe una sugerencia"})
            if len(texto) > 500:
                texto = texto[:500]
            conn = _init_feedback()
            conn.execute("INSERT INTO sugerencias (texto, canal, ip) VALUES (?,?,?)",
                         (texto, "web", self._ip()))
            conn.commit()
            conn.close()
            self._avisar_dueno(texto, "web")
            return self._send(200, {"ok": True})
        email = (data.get("email") or "").strip().lower()
        if not rate_ok(self._ip()):
            return self._send(429, {"error": "demasiadas peticiones"})
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

    def _avisar_dueno(self, texto, canal="web"):
        """Reenvía una sugerencia de tema al dueño (Telegram + email info-fimi)."""
        token = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "") or (load_env(ENV_RADAR) or {}).get("FIMI_TELEGRAM_BOT_TOKEN", "")
        if ":" in token:
            chat = os.environ.get("FIMI_OWNER_CHAT", "") or (load_env(ENV_RADAR) or {}).get("FIMI_OWNER_CHAT", "47652516")
            msg = ("📥 <b>Sugerencia de tema</b> para el radar FIMI\n"
                   f"Canal: {canal}\n\n{texto}")
            data = {
                "chat_id": str(chat),
                "text": msg,
                "parse_mode": "HTML",
            }
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=urllib.parse.urlencode(data).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120"},
            )
            try:
                urllib.request.urlopen(req, timeout=15)
            except Exception as e:
                print(f"[telegram sugerencia] error: {e}")
        import html as _h
        send_email(
            "info-fimi@viajeinteligencia.com",
            "[Radar FIMI] Sugerencia de tema · " + texto[:60],
            f'<h3>📥 Nueva sugerencia de tema</h3>'
            f'<p><b>Canal:</b> {_h.escape(canal)}</p>'
            f'<p><b>Sugerencia:</b> {_h.escape(texto)}</p>'
            f'<p style="color:#888;font-size:.85rem">Radar FIMI · fimi.viajeinteligencia.com</p>',
        )


def main():
    _init_schema()
    _init_feedback()
    srv = HTTPServer(("127.0.0.1", PORT), H)
    print(f"[email_api] escuchando en 127.0.0.1:{PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
