#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
from html import escape
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("SUBS_DB", ROOT / "data" / "subs.db"))
ENV_PATH = Path(os.environ.get("SUBS_ENV", "/home/deploy/newsletter/.env"))
BASE_URL = os.environ.get("SUBS_BASE_URL", "https://fimi.viajeinteligencia.com").rstrip("/")
API_PREFIX = "/api/observatorio"
DATA_DB = Path(os.environ.get("OBS_DATA_DB", "/home/deploy/observatorio/data/observatorio.db"))
DATA_LATEST = Path(os.environ.get("OBS_DATA_LATEST", "/var/www/fimi/observatorio/data/latest.json"))
REPLY_TO = os.environ.get("SUBS_REPLY_TO", "info-fimi@viajeinteligencia.com")
HOST = os.environ.get("SUBS_HOST", "127.0.0.1")
PORT = int(os.environ.get("SUBS_PORT", "3032"))
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
MAX_BODY = 16_384
PENDING_DAYS = 30
RESEND_WINDOW = 600
CONSENT_VERSION = "2026-10-30-v1"
SOURCE_RE = re.compile(r"^[a-z0-9_-]{1,40}$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip().strip('"').strip("'")
    except OSError as exc:
        print(f"subs_api: no se pudo leer {path}: {exc}", file=sys.stderr)
    return data


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS subscribers (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL CHECK (status IN ('pending','confirmed','unsubscribed')),
                source TEXT NOT NULL DEFAULT 'observatorio',
                page TEXT,
                utm_source TEXT,
                utm_medium TEXT,
                utm_campaign TEXT,
                referrer_host TEXT,
                created_at TEXT NOT NULL,
                confirmed_at TEXT,
                unsubscribed_at TEXT,
                last_sent_at TEXT,
                consent_version TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_subs_status ON subscribers(status);
            CREATE INDEX IF NOT EXISTS idx_subs_created ON subscribers(created_at);
            """
        )
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(subscribers)")}
        if "consent_version" not in cols:
            conn.execute("ALTER TABLE subscribers ADD COLUMN consent_version TEXT")
        conn.execute(
            "UPDATE subscribers SET consent_version = 'pre-2026-10-30' WHERE consent_version IS NULL"
        )


def prune_pending() -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=PENDING_DAYS)).isoformat(timespec="seconds")
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM subscribers WHERE status='pending' AND COALESCE(last_sent_at, created_at) < ?",
            (cutoff,),
        )
        return cur.rowcount


def clean_text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def norm_email(value: object) -> str:
    email = clean_text(value, 254).lower()
    return email if EMAIL_RE.match(email) else ""


def ref_host(value: object) -> str:
    raw = clean_text(value, 500)
    if not raw:
        return ""
    if "://" not in raw and not raw.startswith("//"):
        raw = "https://" + raw
    try:
        host = (urlsplit(raw).hostname or "").lower().strip(".")
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host[:120]


def clean_source(value: object) -> str:
    source = clean_text(value, 40).lower() or "observatorio"
    return source if SOURCE_RE.match(source) else "observatorio"


def subscribe(
    email: str,
    source: str = "observatorio",
    page: str = "",
    utm_source: str = "",
    utm_medium: str = "",
    utm_campaign: str = "",
    referrer: str = "",
) -> tuple[str, bool]:
    email = norm_email(email)
    if not email:
        raise ValueError("email inválido")
    stamp = now_iso()
    token = secrets.token_urlsafe(32)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT * FROM subscribers WHERE email = ?", (email,)).fetchone()
            if row and row["status"] == "confirmed":
                conn.commit()
                return row["id"], False
            if row:
                token = row["id"]
                last_sent = row["last_sent_at"] or ""
                if row["status"] == "pending" and last_sent:
                    try:
                        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_sent)).total_seconds()
                    except ValueError:
                        age = RESEND_WINDOW
                    if age < RESEND_WINDOW:
                        conn.commit()
                        return token, False
                conn.execute(
                    """
                    UPDATE subscribers
                    SET status='pending', source=?, page=?, utm_source=?, utm_medium=?,
                        utm_campaign=?, referrer_host=?, last_sent_at=?,
                        confirmed_at=NULL, unsubscribed_at=NULL, consent_version=?
                    WHERE id=?
                    """,
                    (
                        source,
                        page,
                        utm_source,
                        utm_medium,
                        utm_campaign,
                        ref_host(referrer),
                        stamp,
                        CONSENT_VERSION,
                        token,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO subscribers
                    (id, email, status, source, page, utm_source, utm_medium, utm_campaign,
                     referrer_host, created_at, last_sent_at, consent_version)
                    VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        token,
                        email,
                        source,
                        page,
                        utm_source,
                        utm_medium,
                        utm_campaign,
                        ref_host(referrer),
                        stamp,
                        stamp,
                        CONSENT_VERSION,
                    ),
                )
            conn.commit()
            return token, True
        except Exception:
            conn.rollback()
            raise


def is_confirmed(email: str) -> bool:
    email = norm_email(email)
    if not email:
        return False
    with db() as conn:
        row = conn.execute("SELECT status FROM subscribers WHERE email = ?", (email,)).fetchone()
    return bool(row and row["status"] == "confirmed")


def mark_confirmed(token: str) -> str:
    with db() as conn:
        row = conn.execute("SELECT status FROM subscribers WHERE id = ?", (token,)).fetchone()
        if not row or row["status"] == "unsubscribed":
            return "missing"
        if row["status"] == "confirmed":
            return "already"
        conn.execute(
            "UPDATE subscribers SET status='confirmed', confirmed_at=?, unsubscribed_at=NULL WHERE id=?",
            (now_iso(), token),
        )
        return "ok"


def mark_unsubscribed(token: str) -> str:
    with db() as conn:
        row = conn.execute("SELECT status FROM subscribers WHERE id = ?", (token,)).fetchone()
        if not row:
            return "missing"
        if row["status"] == "unsubscribed":
            return "already"
        conn.execute(
            """UPDATE subscribers
               SET status='unsubscribed', unsubscribed_at=?, source='observatorio', page=NULL,
                   utm_source=NULL, utm_medium=NULL, utm_campaign=NULL, referrer_host=NULL
               WHERE id=?""",
            (now_iso(), token),
        )
        return "ok"


def send_confirmation(email: str, token: str) -> bool:
    env = load_env(ENV_PATH)
    if os.environ.get("RESEND_DRY_RUN") == "1":
        print(f"subs_api: dry-run confirmation for {email} ({token})", file=sys.stderr)
        return True
    key = env.get("RESEND_API_KEY", "")
    if not key:
        raise RuntimeError("RESEND_API_KEY no configurada")
    sender = env.get("RESEND_FROM", "newsletter@viajeinteligencia.com")
    if "<" not in sender:
        sender = f"Observatorio de lo publicado <{sender}>"
    confirm_url = f"{BASE_URL}{API_PREFIX}/confirm?id={quote(token)}"
    unsub_url = f"{BASE_URL}{API_PREFIX}/unsubscribe?id={quote(token)}"
    text = (
        "Confirma tu suscripción al Observatorio de lo publicado.\n\n"
        f"{confirm_url}\n\n"
        "Si no has solicitado esta suscripción, ignora este mensaje.\n"
        f"Baja: {unsub_url}\n"
    )
    html = f"""<!doctype html><html lang="es"><body style="margin:0;background:#f6f3ed;color:#17202a;font-family:Georgia,serif">
<div style="max-width:560px;margin:0 auto;padding:32px 22px">
<p style="font-family:Arial,sans-serif;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#b4532a">Observatorio de lo publicado</p>
<h1 style="font-size:26px;line-height:1.2;margin:10px 0 14px">Confirma tu suscripción</h1>
<p style="font-size:16px;line-height:1.6">Te avisaré cuando publique nuevas fichas, episodios o cambios del calendario del observatorio. Sin ruido.</p>
<p style="margin:26px 0"><a href="{confirm_url}" style="display:inline-block;background:#17202a;color:#fff;text-decoration:none;padding:13px 20px;border-radius:4px;font-family:Arial,sans-serif">Confirmar suscripción</a></p>
<p style="font-size:13px;line-height:1.6;color:#59636e">Si no has solicitado esta suscripción, ignora este mensaje.</p>
<p style="font-size:13px;line-height:1.6"><a href="{unsub_url}" style="color:#59636e">Darse de baja</a></p>
</div></body></html>"""
    payload = json.dumps(
        {
            "from": sender,
            "to": [email],
            "reply_to": REPLY_TO,
            "subject": "Confirma tu suscripción al Observatorio de lo publicado",
            "text": text,
            "html": html,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; ObservatorioPublicado/1.0)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as exc:
        print(f"subs_api: Resend HTTP {exc.code}: {exc.read(500).decode('utf-8', 'replace')}", file=sys.stderr)
        return False
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"subs_api: Resend error: {exc}", file=sys.stderr)
        return False


class RateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < window]
            if len(hits) >= limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True


LIMITER = RateLimiter()
LAST_PRUNE = 0.0


def token_status(token: str) -> str | None:
    with db() as conn:
        row = conn.execute("SELECT status FROM subscribers WHERE id = ?", (token,)).fetchone()
    return row["status"] if row else None


def page_action(kind: str, token: str) -> str:
    if kind == "confirm":
        title = "Confirma tu suscripción"
        body = "Pulsa el botón para confirmar que quieres recibir el aviso. Así evito que un filtro de correo te suscriba sin querer."
        label = "Confirmar suscripción"
        action = API_PREFIX + "/confirm"
    else:
        title = "Darte de baja"
        body = "Pulsa el botón para dejar de recibir el aviso. La baja es inmediata."
        label = "Darse de baja"
        action = API_PREFIX + "/unsubscribe"
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{title} · Observatorio de lo publicado</title>
<style>body{{margin:0;background:#f6f3ed;color:#17202a;font-family:Georgia,serif}}main{{max-width:620px;margin:0 auto;padding:48px 22px}}p{{line-height:1.65;font-size:17px}}a{{color:#17202a}}.eyebrow{{font-family:Arial,sans-serif;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#b4532a}}h1{{font-size:30px;line-height:1.2;margin:10px 0 18px}}button{{font:inherit;font-weight:700;background:#17202a;color:#fff;border:0;border-radius:4px;padding:13px 20px;cursor:pointer}}</style></head>
<body><main><p class="eyebrow">Observatorio de lo publicado</p><h1>{title}</h1><p>{body}</p>
<form method="post" action="{action}"><input type="hidden" name="id" value="{escape(token)}"><button type="submit">{label}</button></form>
<p><a href="/observatorio/">Volver al observatorio</a></p></main></body></html>"""


def page(status: str) -> str:
    if status == "ok":
        title = "Suscripción confirmada"
        body = "Te he añadido a la lista. Solo escribiré cuando publique una ficha, un episodio o un cambio de calendario."
    elif status == "already":
        title = "Ya estabas suscrito"
        body = "No hace falta hacer nada más. Puedes darte de baja desde cualquier correo."
    elif status == "unsubscribed":
        title = "Baja completada"
        body = "No volverás a recibir avisos. Puedes suscribirte de nuevo cuando quieras."
    elif status == "already-unsubscribed":
        title = "Ya estabas de baja"
        body = "No hace falta hacer nada más."
    else:
        title = "Enlace no válido"
        body = "El enlace ha caducado o no existe. Vuelve a pedir la suscripción desde la web."
    color = "#2f6b4f" if status in ("ok", "already", "unsubscribed", "already-unsubscribed") else "#a33a2a"
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{title} · Observatorio de lo publicado</title>
<style>body{{margin:0;background:#f6f3ed;color:#17202a;font-family:Georgia,serif}}main{{max-width:620px;margin:0 auto;padding:48px 22px}}p{{line-height:1.65;font-size:17px}}a{{color:#17202a}}.eyebrow{{font-family:Arial,sans-serif;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#b4532a}}h1{{font-size:30px;line-height:1.2;margin:10px 0 18px}}b{{color:{color}}}</style></head>
<body><main><p class="eyebrow">Observatorio de lo publicado</p><h1>{title}</h1><p>{body}</p><p><b>Puedes cerrar esta pestaña.</b></p><p><a href="/observatorio/">Volver al observatorio</a></p></main></body></html>"""


def data_conn():
    if not DATA_DB.exists(): raise FileNotFoundError(str(DATA_DB))
    c=sqlite3.connect(f"file:{DATA_DB}?mode=ro",uri=True,timeout=10); c.row_factory=sqlite3.Row; return c

def item_query(params):
    topic=(parse_qs(params).get('topic') or [''])[0].strip()
    source=(parse_qs(params).get('source') or [''])[0].strip()
    since=(parse_qs(params).get('since') or [''])[0].strip()
    until=(parse_qs(params).get('until') or [''])[0].strip()
    q=(parse_qs(params).get('q') or [''])[0].strip()
    try: limit=max(1,min(200,int((parse_qs(params).get('limit') or ['50'])[0])))
    except ValueError: limit=50
    try: offset=max(0,int((parse_qs(params).get('offset') or ['0'])[0]))
    except ValueError: offset=0
    where=[]; args=[]
    if topic: where.append('topic=?'); args.append(topic)
    if source: where.append('source=?'); args.append(source)
    if since: where.append('published>=?'); args.append(since)
    if until: where.append('published<=?'); args.append(until)
    if q: where.append('(title LIKE ? OR source LIKE ?)'); args += ['%'+q+'%','%'+q+'%']
    w=(' WHERE '+' AND '.join(where)) if where else ''
    c=data_conn()
    total=c.execute('SELECT COUNT(*) n FROM items'+w,args).fetchone()['n']
    rows=c.execute('SELECT id,topic,title,url,source,source_type,published,fetched FROM items'+w+' ORDER BY published DESC LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
    c.close()
    return {'ok':True,'count':total,'limit':limit,'offset':offset,'items':[dict(r) for r in rows]}

def events_payload(params):
    q=parse_qs(params); topic=(q.get('topic') or ['frontera_sur'])[0].strip(); status=(q.get('status') or [''])[0].strip()
    try: limit=max(1,min(100,int((q.get('limit') or ['30'])[0])))
    except ValueError: limit=30
    try: offset=max(0,int((q.get('offset') or ['0'])[0]))
    except ValueError: offset=0
    c=data_conn(); where=['e.topic=?']; args=[topic]
    if status: where.append('e.status=?'); args.append(status)
    w=' AND '.join(where)
    total=c.execute('SELECT COUNT(*) n FROM events e WHERE '+w,args).fetchone()['n']
    rows=c.execute('SELECT e.*,(SELECT COUNT(*) FROM event_items ei JOIN items i ON i.id=ei.item_id WHERE ei.event_id=e.id AND i.source_type=\'official\') official_count FROM events e WHERE '+w+' ORDER BY e.last_published DESC LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
    out=[]
    for r in rows:
        d=dict(r); its=c.execute('SELECT i.id,i.title,i.url,i.source,i.source_type,i.published FROM event_items ei JOIN items i ON i.id=ei.item_id WHERE ei.event_id=? ORDER BY i.published DESC LIMIT 5',(r['id'],)).fetchall(); d['publications']=[dict(x) for x in its]
        d['daily']=[dict(x) for x in c.execute('SELECT substr(i.published,1,10) d,COUNT(*) n FROM event_items ei JOIN items i ON i.id=ei.item_id WHERE ei.event_id=? GROUP BY substr(i.published,1,10) ORDER BY d',(r['id'],)).fetchall()]
        out.append(d)
    c.close(); return {'ok':True,'count':total,'limit':limit,'offset':offset,'events':out}

def event_detail(eid):
    c=data_conn(); r=c.execute('SELECT * FROM events WHERE id=?',(eid,)).fetchone()
    if not r: c.close(); return None
    d=dict(r); d['publications']=[dict(x) for x in c.execute('SELECT i.id,i.title,i.url,i.source,i.source_type,i.published FROM event_items ei JOIN items i ON i.id=ei.item_id WHERE ei.event_id=? ORDER BY i.published DESC',(eid,)).fetchall()]
    d['daily']=[dict(x) for x in c.execute('SELECT substr(i.published,1,10) d,COUNT(*) n FROM event_items ei JOIN items i ON i.id=ei.item_id WHERE ei.event_id=? GROUP BY substr(i.published,1,10) ORDER BY d',(eid,)).fetchall()]
    d['responses']=[dict(x) for x in c.execute('SELECT actor,response,url,published FROM event_responses WHERE event_id=? ORDER BY published',(eid,)).fetchall()]
    c.close(); return d

def admin_events_payload(params):
    q=parse_qs(params); topic=(q.get('topic') or ['frontera_sur'])[0].strip()
    c=data_conn(); rows=c.execute("SELECT * FROM events WHERE topic=? AND needs_review=1 AND COALESCE(review_status,'auto')='auto' ORDER BY last_published DESC LIMIT 100",(topic,)).fetchall()
    out=[]
    for r in rows:
        d=dict(r); d['publications']=[dict(x) for x in c.execute('SELECT i.id,i.title,i.url,i.source,i.source_type,i.published FROM event_items ei JOIN items i ON i.id=ei.item_id WHERE ei.event_id=? ORDER BY i.published DESC LIMIT 6',(r['id'],)).fetchall()]; out.append(d)
    c.close(); return {'ok':True,'count':len(out),'events':out}

def review_event(eid,action):
    if action not in ('approve','hide'): raise ValueError('action')
    c=sqlite3.connect(DATA_DB,timeout=15); status='approved' if action=='approve' else 'hidden'
    cur=c.execute("UPDATE events SET review_status=?,needs_review=0,reviewed_at=? WHERE id=?",(status,now_iso(),eid)); c.commit(); c.close()
    return cur.rowcount>0

def sources_payload():
    p=DATA_LATEST.parent/'feed_health.json'
    try: return json.loads(p.read_text(encoding='utf-8'))
    except Exception: return {'total':0,'ok':0,'error':0,'feeds':[]}

def topics_payload():
    c=data_conn(); rows=c.execute('SELECT topic,COUNT(*) n FROM items GROUP BY topic').fetchall(); c.close()
    return {'ok':True,'topics':[dict(r) for r in rows]}

def export_rows(params,fmt):
    d=item_query(params)
    if fmt=='csv':
        b=io.StringIO(); w=csv.writer(b); w.writerow(['id','topic','title','url','source','published','fetched'])
        for x in d['items']: w.writerow([x['id'],x['topic'],x['title'],x['url'],x['source'],x['published'],x['fetched']])
        return b.getvalue(),'text/csv; charset=utf-8'
    return '\n'.join(json.dumps(x,ensure_ascii=False) for x in d['items'])+'\n','application/x-ndjson; charset=utf-8'

def openapi_payload():
    return {'openapi':'3.0.3','info':{'title':'Observatorio de lo publicado API','version':'0.1.0'},'paths':{'/api/observatorio/v1/items':{'get':{'summary':'Titulares capturados'}},'/api/observatorio/v1/topics':{'get':{'summary':'Temas y recuentos'}},'/api/observatorio/v1/sources':{'get':{'summary':'Salud de fuentes'}},'/api/observatorio/v1/export.csv':{'get':{'summary':'Exportación CSV'}},'/api/observatorio/v1/export.ndjson':{'get':{'summary':'Exportación NDJSON'}}}}

class Handler(BaseHTTPRequestHandler):
    server_version = "ObservatorioPublicado/1.0"
    sys_version = ""

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.log_date_time_string()} {fmt % args}", file=sys.stderr)

    def send_body(self, code: int, body: str, ctype: str) -> None:
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def send_json(self, code: int, data: dict) -> None:
        self.send_body(code, json.dumps(data, ensure_ascii=False), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == API_PREFIX + "/admin/events":
            try: self.send_json(200,admin_events_payload(parsed.query))
            except Exception as e: self.send_json(500,{"ok":False,"error":str(e)[:160]})
            return
        if parsed.path.startswith(API_PREFIX + "/v1/"):
            try:
                p=parsed.path[len(API_PREFIX)+4:]
                if p in ("health","health.json"):
                    self.send_json(200,{"ok":True,"service":"observatorio-data","items":topics_payload(),"sources":sources_payload()})
                elif p in ("events","events.json"):
                    self.send_json(200,events_payload(parsed.query))
                elif p.startswith("events/"):
                    eid=p[len("events/"):].strip("/")
                    d=event_detail(eid)
                    self.send_json(200,d) if d else self.send_json(404,{"ok":False,"error":"event_not_found"})
                elif p in ("items","items.json"):
                    self.send_json(200,item_query(parsed.query))
                elif p in ("topics","topics.json"):
                    self.send_json(200,topics_payload())
                elif p in ("sources","sources.json"):
                    self.send_json(200,sources_payload())
                elif p in ("openapi.json","openapi"):
                    self.send_json(200,openapi_payload())
                elif p in ("export.csv","export.ndjson"):
                    body,ctype=export_rows(parsed.query,'csv' if p.endswith('.csv') else 'ndjson')
                    self.send_body(200,body,ctype)
                else:
                    self.send_json(404,{"ok":False,"error":"not_found"})
            except FileNotFoundError as e:
                self.send_json(503,{"ok":False,"error":"data_db_missing","detail":str(e)})
            except Exception as e:
                self.send_json(500,{"ok":False,"error":"data_error","detail":str(e)[:160]})
            return
        if parsed.path == API_PREFIX + "/health":
            env = load_env(ENV_PATH)
            self.send_json(200, {"ok": True, "service": "observatorio-subs", "email_configured": bool(env.get("RESEND_API_KEY"))})
            return
        if parsed.path in (API_PREFIX + "/confirm", API_PREFIX + "/unsubscribe"):
            token = (parse_qs(parsed.query).get("id") or [""])[0].strip()
            if not token or len(token) > 80:
                self.send_body(400, page("missing"), "text/html; charset=utf-8")
                return
            status = token_status(token)
            if status is None:
                self.send_body(404, page("missing"), "text/html; charset=utf-8")
                return
            if parsed.path == API_PREFIX + "/confirm":
                if status == "confirmed":
                    self.send_body(200, page("already"), "text/html; charset=utf-8")
                elif status == "pending":
                    self.send_body(200, page_action("confirm", token), "text/html; charset=utf-8")
                else:
                    self.send_body(404, page("missing"), "text/html; charset=utf-8")
            else:
                if status == "unsubscribed":
                    self.send_body(200, page("already-unsubscribed"), "text/html; charset=utf-8")
                else:
                    self.send_body(200, page_action("unsubscribe", token), "text/html; charset=utf-8")
            return
        self.send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        global LAST_PRUNE
        path = urlsplit(self.path).path
        if path.startswith(API_PREFIX + "/admin/events/"):
            try: length=int(self.headers.get("Content-Length","0"))
            except ValueError: length=0
            if length<=0 or length>MAX_BODY:
                self.send_json(413,{"ok":False,"error":"body"}); return
            try: data=json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                self.send_json(400,{"ok":False,"error":"json"}); return
            eid=path[len(API_PREFIX)+len("/admin/events/"):].strip("/")
            try:
                ok=review_event(eid,data.get("action"))
                self.send_json(200,{"ok":ok})
            except ValueError:
                self.send_json(400,{"ok":False,"error":"action"})
            except Exception as e:
                self.send_json(500,{"ok":False,"error":str(e)[:160]})
            return
        if path in (API_PREFIX + "/confirm", API_PREFIX + "/unsubscribe"):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_BODY:
                self.send_body(413, page("missing"), "text/html; charset=utf-8")
                return
            try:
                form = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
            except UnicodeDecodeError:
                self.send_body(400, page("missing"), "text/html; charset=utf-8")
                return
            token = (form.get("id") or [""])[0].strip()
            if not token or len(token) > 80:
                self.send_body(400, page("missing"), "text/html; charset=utf-8")
                return
            if path == API_PREFIX + "/confirm":
                result = mark_confirmed(token)
                status = result if result in ("ok", "already") else "missing"
            else:
                result = mark_unsubscribed(token)
                status = "unsubscribed" if result == "ok" else ("already-unsubscribed" if result == "already" else "missing")
            self.send_body(200 if status != "missing" else 404, page(status), "text/html; charset=utf-8")
            return
        if path != API_PREFIX + "/subscribe":
            self.send_json(404, {"ok": False, "error": "not_found"})
            return
        ip = self.client_address[0]
        if not LIMITER.allow(f"ip:{ip}", 5, 600):
            self.send_json(429, {"ok": False, "error": "rate_limited"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self.send_json(413, {"ok": False, "error": "body"})
            return
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"ok": False, "error": "json"})
            return
        if not isinstance(data, dict):
            self.send_json(400, {"ok": False, "error": "json"})
            return
        if data.get("consent") is not True:
            self.send_json(400, {"ok": False, "error": "consent"})
            return
        email = norm_email(data.get("email"))
        if not email:
            self.send_json(400, {"ok": False, "error": "email"})
            return
        if is_confirmed(email):
            self.send_json(200, {
                "ok": True,
                "already": True,
                "message": "Ya estabas suscrito. No hace falta confirmar ni volver a pedir el aviso.",
            })
            return
        if not LIMITER.allow(f"email:{email}", 2, 600):
            self.send_json(429, {"ok": False, "error": "rate_limited"})
            return
        if time.monotonic() - LAST_PRUNE > 3600:
            try:
                prune_pending()
            except sqlite3.Error as exc:
                print(f"subs_api: prune: {exc}", file=sys.stderr)
            LAST_PRUNE = time.monotonic()
        source = clean_source(data.get("source"))
        page_path = clean_text(data.get("page"), 160)
        utm_source = clean_text(data.get("utm_source"), 80)
        utm_medium = clean_text(data.get("utm_medium"), 80)
        utm_campaign = clean_text(data.get("utm_campaign"), 80)
        referrer = clean_text(data.get("referrer"), 500)
        token, should_send = subscribe(email, source, page_path, utm_source, utm_medium, utm_campaign, referrer)
        if should_send and not send_confirmation(email, token):
            self.send_json(502, {"ok": False, "error": "send"})
            return
        self.send_json(200, {"ok": True, "message": "Si el correo es válido, te he enviado un enlace de confirmación."})


def main() -> int:
    init_db()
    try:
        prune_pending()
    except sqlite3.Error as exc:
        print(f"subs_api: prune inicial: {exc}", file=sys.stderr)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.daemon_threads = True
    print(f"subs_api: {HOST}:{PORT} db={DB_PATH}", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
