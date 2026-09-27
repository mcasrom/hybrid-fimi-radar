#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
accesos.py — Registro histórico de accesos al observatorio (humanos vs máquinas).

Por qué existe esto: los logs de nginx rotan (`rotate 14`), así que en local solo
hay ~15 días. Y el daily anterior era un texto enviado por Telegram/email: nada
acumulaba. Aquí se guarda **una fila por petición** en SQLite, con un cursor de
lectura incremental, de modo que el histórico no vuelve a depender de la rotación.

Clasificación (4 vías, alineada con scripts/monitor_lectores.py del ecosistema):
  - INTERNAL:        monitor propio, healthchecks, UA del servidor. Nunca lector.
  - DUENO:           tu propio navegador (red DIGI). Humano, pero no es lectura.
  - BOT:             crawler/escáner/data-center (por UA, ruta o red de hosting).
  - HUMANO_PROBABLE: navegador desde IP residencial externa que no es tuya ni
                     una nube. Es la única que puede ser "persona de verdad", y
                     solo cuenta como lectura si además abrió contenido.

Privacidad: las IPs de terceros son datos personales. En la base se guarda un
seudónimo estable (`h-xxxxxxxx`) derivado de un salt que vive en
`data/accesos.salt` con permisos 600 — un hash sin salt secreto es reversible
por fuerza bruta sobre el espacio IPv4, así que el salt es lo que protege. La IP
en claro solo se escribe si se pide explícitamente (`--guardar-raw`), y siempre
en una tabla aparte para poder borrarla sin tocar el histórico.

Profundidad: `/` es una visita de paso (landing). Se marca `es_profundo=1` solo
cuando la petición es de contenido real del observatorio: research, glosario,
docs, sobre, api, operativa, costes, apoyo, o el permalink `/c/<id>`. Es el mismo
principio que en el blog: landing-sí / posts-no.
"""

import gzip
import hashlib
import ipaddress
import os
import re
import sqlite3
import time
from datetime import datetime

# --- Rutas -------------------------------------------------------------------

DATA_DIR = os.environ.get("FIMI_DATA", "data")
DB_PATH = os.path.join(DATA_DIR, "accesos.db")
SALT_PATH = os.path.join(DATA_DIR, "accesos.salt")
LOG_DIR = os.environ.get("FIMI_LOG_DIR", "/var/log/nginx")
SITIO = "fimi.viajeinteligencia.com"

# --- Red del dueño ------------------------------------------------------------
# Tu ISP (DIGI) mueve el IPv4 entre 79.116.x y 79.117.x según la sesión; si solo
# se fija 79.116. tu propia IP se cuela como "humano externo" en cada informe.
OWNER_PREFIXES = ("79.116.", "79.117.", "2a0c:5a83")
OWNER_IPS = {"178.105.80.193"}

# --- Redes de hosting y nubes (CIDR) -----------------------------------------
# El detector antiguo comparaba con `ip.startswith()` sobre una lista enorme
# ("34.1", "34.3", ...): eso marca como bot TODO 34.x, incluidas IP residenciales
# legítimas, y deja pasar AWS/Cloudflare. Aquí son CIDR reales.
#
# Regla para ampliarla: **solo con datos, y verificado contra la lista oficial
# del proveedor**. Comprobado el 2026-09-27 contra ip-ranges.amazonaws.com:
# `18.128.0.0/9` NO es de AWS (se quitó) y `52.88` es /15, no /13. Contra
# cloudflare.com/ips-v4, la lista de abajo es la oficial literal.
#
# Sin GeoIP/ASN en el server (no hay BBDD ni módulo `geoip2`), esto es una
# heurística acotada, no un detector de verdad: por eso lo no reconocido se
# reporta como *candidato*, nunca como humano probado. La vía seria es
# cachear las listas oficiales de AWS/GCP/Hetzner en vez de teclearlas aquí.
DATACENTER_CIDRS = [
    # AWS — observado: 44.205.70.55, 44.216.112.73 (ambos = 44.192.0.0/11)
    "44.192.0.0/11", "52.88.0.0/15", "13.32.0.0/15", "35.168.0.0/13",
    # Cloudflare — lista oficial literal (cloudflare.com/ips-v4)
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
    # OVH / Scaleway — observado: 51.81.242.85
    "51.80.0.0/12", "51.68.0.0/14", "51.158.0.0/15",
    # Hosting[barn] — observado: 94.154.43.84, 94.154.43.125
    "94.154.0.0/18", "94.130.0.0/15", "62.8.0.0/15", "62.210.0.0/16",
    "77.91.104.0/21", "80.241.0.0/16", "176.32.96.0/19", "178.17.0.0/16",
    # Hetzner — observado: 178.16.53.77 (y nuestro servidor es 178.105.x,
    # fuera de /12, así que no hay colisión con el dueño)
    "178.16.0.0/12", "5.9.0.0/16", "78.46.0.0/15", "88.198.0.0/16",
    "94.136.0.0/13", "95.216.0.0/13", "116.203.0.0/16", "135.63.0.0/16",
    "167.89.0.0/16", "195.90.0.0/16", "213.165.0.0/16",
    # DigitalOcean / Vultr / Linode
    "45.55.0.0/16", "104.131.0.0/16", "159.65.0.0/16", "157.245.0.0/16",
    "139.59.0.0/16", "68.183.0.0/16", "134.209.0.0/16", "164.92.0.0/14",
    # Azure / GCP (sin uso residencial conocido)
    "20.0.0.0/11", "51.4.0.0/15", "51.8.0.0/16", "51.10.0.0/15",
    "34.64.0.0/10", "35.184.0.0/13", "35.224.0.0/12", "104.196.0.0/14",
]

_DATACENTER = None


def _datacenter():
    global _DATACENTER
    if _DATACENTER is None:
        vistos, utiles = set(), []
        for c in DATACENTER_CIDRS:
            if c in vistos:
                continue
            vistos.add(c)
            try:
                utiles.append(ipaddress.ip_network(c))
            except ValueError:
                continue
        _DATACENTER = utiles
    return _DATACENTER


# --- Clasificación de UA ------------------------------------------------------

UA_PROPIO = re.compile(
    r"ecosystem-healthcheck|uptime.?kuma|uptimerobot|node-fetch|axios|"
    r"requests/|go-http-client|curl/|wget|python-requests|"
    r"canary|scrapy|headlesschrome|phantomjs|python-urllib",
    re.I,
)

UA_BOT = re.compile(
    r"bot\b|bots\b|crawler|spider|scrap|slurp|search|archiver|monitor|"
    r"fetcher|indexer|checker|validator|preview|facebookexternalhit|"
    r"whatsapp|telegrambot|discordbot|twitterbot|linkedinbot|"
    r"ahrefs|semrush|mj12|dotbot|petalbot|yandex|baidu|bingpreview|"
    r"google-|applebot|feedfetcher|mediapartners|adsbot|ia_archiver|"
    r"curl|wget|python|java/|okhttp|libwww|java-http|nutch|"
    r"dataprovider|pingdom|gtmetrix|lighthouse|pagespeed|"
    r"cf-?bot|claudebot|perplexity|amazonbot|applebot-extended|"
    r"img2txt|getprox|virus|scan|masscan|zgrab|nmap|sqlmap|nikto",
    re.I,
)

ASSET_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".css",
             ".js", ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".webm", ".xml",
             ".txt", ".json", ".pdf", ".zip", ".map")
ASSET_EXACT = ("/favicon.ico", "/sw.js", "/manifest.webmanifest",
               "/manifest.json", "/robots.txt", "/sitemap.xml", "/humans.txt")

SCAN_MARKERS = (
    "/.env", "/.git", "/wp-admin", "/wp-login", "/xmlrpc", "/.aws",
    "/phpmyadmin", "/vendor/", "/config.json", "/cgi-bin", "/.ssh",
    "/api/../", "/cgi", "/shell", "/cmd", "/etc/passwd", "/wp-content",
    "/admin/", "/manager/", "/solr", "/jenkins", "/console", "/elmah",
    "/server-status", "/actuator", "/druid", "/api/v2/../../",
)

# Contenido = lectura real. `/` NO lo es: es la visita de paso.
RUTAS_PROFUNDAS = (
    "/research.html", "/glosario.html", "/docs.html", "/sobre.html",
    "/api.html", "/operativa.html", "/costes.html", "/apoyo.html",
    "/suscribirse.html", "/privacidad.html", "/aviso-legal.html",
    "/radar.html",
)

INTERNAL_NETS = tuple(
    ipaddress.ip_network(n)
    for n in ("127.0.0.0/8", "::1/128", "172.16.0.0/12", "10.0.0.0/8",
              "192.168.0.0/16", "169.254.0.0/16")
)


def es_dueno(ip):
    return ip in OWNER_IPS or any(ip.startswith(p) for p in OWNER_PREFIXES)


def es_internal(ip, ua):
    if UA_PROPIO.search(ua or ""):
        return True
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if any(a in n for n in INTERNAL_NETS):
        return True
    return False


def es_datacenter(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return any(a in n for n in _datacenter())


def es_scan(path):
    p = (path or "").lower()
    if any(m in p for m in SCAN_MARKERS):
        return True
    if p.endswith(ASSET_EXT):
        return True
    if p in ASSET_EXACT:
        return True
    return False


def es_profunda(path):
    """True si la ruta es contenido del observatorio (no la portada, no la API)."""
    p = (path or "").lower()
    if p == "/" or p == "":
        return False
    if p.startswith("/api/") or p.startswith("/api."):
        return False
    if p.startswith("/c/") and len(p) > 3:
        return True
    ruta = p.split("#")[0].split("?")[0].rstrip("/")
    if not ruta:
        ruta = "/"
    for r in RUTAS_PROFUNDAS:
        if ruta == r:
            return True
    # /posts/ no aplica aquí, pero el dashboard sirve assets con hash: no cuenta.
    return False


CACHE_BUSTER = re.compile(
    r"[?&](cb|_|rnd|random|nonce|t|ts|time|cachebust|nocache|v)=(\d{6,}|\[?\"?[0-9a-f]{8,})",
    re.I,
)


def es_cachebuster(path):
    """Cliente automatico que anade marca de tiempo para saltar cache.

    En el historico real esto era el "lector" mas activo del periodo: 8 dias,
    45 peticiones, todas a `/?cb=1789553091`. Los query strings hacen que
    `COUNT(DISTINCT ruta)` cuente como rutas distintas lo que es la misma
    pagina, asi que ademas se cuenta sobre `ruta_base`.
    """
    return bool(CACHE_BUSTER.search(path or ""))


def es_api(path):
    """La API pública es una interfaz de MÁQUINAS aunque la pida una IP
    residencial: `/api.html` (la documentación) sí es de gente, `/api/v1/...`
    no. Clasificar la API como 'humano' inflaba el recuento de lectores con
    raspadores del endpoint de exportación."""
    p = (path or "").lower().split("?")[0]
    return p.startswith("/api/") or p == "/api"


def clasificar(ip, ruta, status, ua):
    """Devuelve (categoria, es_scan, es_profunda)."""
    scan = es_scan(ruta)
    prof = es_profunda(ruta)
    if es_internal(ip, ua):
        return "INTERNAL", scan, prof
    if es_dueno(ip):
        return "DUENO", scan, prof
    if es_api(ruta):
        return "API", scan, prof
    if es_cachebuster(ruta):
        return "BOT", scan, prof
    if UA_BOT.search(ua or ""):
        return "BOT", scan, prof
    if scan:
        return "BOT", scan, prof
    if status != 200:
        # Un 404 de escáner es bot; un 404 de persona también, pero no es lectura.
        return "BOT", scan, prof
    if es_datacenter(ip):
        return "BOT", scan, prof
    return "HUMANO_PROBABLE", scan, prof


# --- Seudonización ------------------------------------------------------------

def _salt():
    if not os.path.exists(SALT_PATH):
        os.makedirs(os.path.dirname(SALT_PATH) or ".", exist_ok=True)
        fd = os.open(SALT_PATH, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(os.urandom(32).hex())
        os.chmod(SALT_PATH, 0o600)
    with open(SALT_PATH) as fh:
        return fh.read().strip()


def seudonimo(ip, salt=None):
    s = salt or _salt()
    return "h-" + hashlib.sha256((s + "|" + ip).encode()).hexdigest()[:8]


# --- Esquema ------------------------------------------------------------------

DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS accesos (
    id           INTEGER PRIMARY KEY,
    ts           TEXT NOT NULL,
    dia          TEXT NOT NULL,
    host         TEXT NOT NULL,
    metodo       TEXT,
    ruta         TEXT,
    ruta_base    TEXT,
    status       INTEGER,
    bytes        INTEGER,
    ip_pseudo    TEXT NOT NULL,
    ua           TEXT,
    categoria    TEXT NOT NULL,
    es_scan      INTEGER NOT NULL DEFAULT 0,
    es_profundo  INTEGER NOT NULL DEFAULT 0,
    fuente       TEXT NOT NULL DEFAULT 'nginx'
);
CREATE INDEX IF NOT EXISTS ix_accesos_dia ON accesos(dia);
CREATE INDEX IF NOT EXISTS ix_accesos_pseudo ON accesos(ip_pseudo);
CREATE INDEX IF NOT EXISTS ix_accesos_cat ON accesos(categoria);
CREATE INDEX IF NOT EXISTS ix_accesos_prof ON accesos(es_profundo);
CREATE INDEX IF NOT EXISTS ix_accesos_base ON accesos(ruta_base);

CREATE TABLE IF NOT EXISTS ip_dia (
    ip_pseudo   TEXT NOT NULL,
    dia         TEXT NOT NULL,
    categoria   TEXT NOT NULL,
    requests    INTEGER NOT NULL DEFAULT 0,
    profundas   INTEGER NOT NULL DEFAULT 0,
    rutas       TEXT,
    primera_ts  TEXT,
    ultima_ts   TEXT,
    PRIMARY KEY (ip_pseudo, dia)
);

-- IPs en claro, solo si se pide. Tabla separada para poder borrarla entera.
CREATE TABLE IF NOT EXISTS ip_raw (
    ip_pseudo TEXT PRIMARY KEY,
    ip        TEXT NOT NULL,
    primera   TEXT,
    ultima    TEXT
);

-- Cursor de lectura incremental por fichero (rotación por inodo).
-- `leidas`/`ok` no son decorativos: si un fichero trae líneas y no parsea
-- ninguna, es que el parser se ha roto (cambió el log_format) y hay que
-- loudly avisar en vez de advancing el cursor en silencio.
CREATE TABLE IF NOT EXISTS cursor_log (
    fichero   TEXT PRIMARY KEY,
    ino       INTEGER,
    offset    INTEGER NOT NULL DEFAULT 0,
    completo  INTEGER NOT NULL DEFAULT 0,
    leido_ts  TEXT,
    leidas    INTEGER NOT NULL DEFAULT 0,
    ok        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT
);
"""


def _migrar(con):
    """Añade columnas nuevas a tablas existentes (CREATE TABLE no las mete)."""
    for tabla, col, decl in (("cursor_log", "leidas", "INTEGER DEFAULT 0"),
                             ("cursor_log", "ok", "INTEGER DEFAULT 0")):
        cols = {f["name"] for f in con.execute(f"PRAGMA table_info({tabla})")}
        if col not in cols:
            con.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {decl}")
    con.commit()


def conectar(path=DB_PATH):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(DDL)
    _migrar(con)
    return con


# --- Ingesta ------------------------------------------------------------------

# OJO con el `+` final. El log_format global del servidor es
#   ... "$http_referer" "$http_user_agent"" host=$host
# con una comilla de sobra al final del UA (error cosmético de formato heredado).
# Un parser que exija el cierre limpio no lee **ninguna** línea de este log: el
# backfill devolvía 0 sobre 9.004 líneas reales. El `+` tolera 1 o 2 comillas.
LINE_RE = re.compile(
    r"^(?P<ip>\S+) - - \[(?P<ts>[^\]]+)\] \"(?P<request>[^\"]*)\" "
    r"(?P<status>\d+) \S+ \"(?P<referer>[^\"]*)\" \"(?P<ua>[^\"]*)\"+"
    r"(?:\s*host=(?P<host>\S+))?\s*$"
)

MESES = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
         "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def parse_line(line):
    m = LINE_RE.match(line)
    if not m:
        return None
    g = m.groupdict()
    partes = (g["request"] or "").split(" ")
    metodo = partes[0] if partes else ""
    ruta = partes[1] if len(partes) > 1 else "/"
    d = re.match(r"(\d{2})/(\w{3})/(\d{4}):(\d{2}):(\d{2}):(\d{2})", g["ts"] or "")
    if not d:
        return None
    dd, mon, yy, hh, mm, ss = d.groups()
    mes = MESES.get(mon)
    if not mes:
        return None
    iso = f"{yy}-{mes:02d}-{dd}T{hh}:{mm}:{ss}Z"
    try:
        status = int(g["status"])
    except (TypeError, ValueError):
        status = 0
    return {
        "ts": iso,
        "dia": f"{yy}-{mes:02d}-{dd}",
        "host": (g.get("host") or SITIO).strip(),
        "metodo": metodo,
        "ruta": ruta,
        "status": status,
        "ua": g.get("ua") or "",
        "referer": g.get("referer") or "",
    }


def ficheros_log(log_dir=LOG_DIR, max_rot=14):
    """access.log + sus rotados. Prueba .gz porque al rotar siempre se comprime."""
    out = []
    base = os.path.join(log_dir, "access.log")
    if os.path.exists(base):
        out.append(base)
    for i in range(1, max_rot + 1):
        cand = os.path.join(log_dir, f"access.log.{i}")
        if os.path.exists(cand):
            out.append(cand)
        elif os.path.exists(cand + ".gz"):
            out.append(cand + ".gz")
    return out


def _abrir(f):
    if f.endswith(".gz"):
        return gzip.open(f, "rt", errors="replace")
    return open(f, "r", errors="replace")


def ingestar(con, log_dir=LOG_DIR, host=SITIO, guardar_raw=False, verbose=False):
    """Lee solo lo nuevo de cada fichero. Idempotente vía cursor (ino, offset)."""
    salt = _salt()
    anadidas = 0
    salt_obj = con.cursor()
    for f in ficheros_log(log_dir):
        try:
            st = os.stat(f)
        except OSError as exc:
            print(f"[accesos] AVISO: no puedo stat {f}: {exc}", flush=True)
            continue
        fila = con.execute(
            "SELECT ino, offset, completo, leidas, ok FROM cursor_log"
            " WHERE fichero=?", (f,)
        ).fetchone()
        previo_offset = 0
        gz = f.endswith(".gz")
        if fila:
            if gz and fila["completo"]:
                continue
            if fila["ino"] == st.st_ino and not gz:
                previo_offset = min(fila["offset"], st.st_size)
            elif fila["ino"] == st.st_ino and gz:
                previo_offset = 0
        if not gz and previo_offset >= st.st_size and st.st_size > 0:
            continue

        try:
            with _abrir(f) as fh:
                if gz:
                    lineas = fh.readlines()
                else:
                    fh.seek(previo_offset)
                    lineas = fh.readlines()
        except OSError as exc:
            print(f"[accesos] AVISO: no puedo leer {f}: {exc}", flush=True)
            continue

        lote = []
        for ln in lineas:
            r = parse_line(ln)
            if not r or host not in r["host"]:
                continue
            r["ip"] = ln.split(" ", 1)[0]
            cat, scan, prof = clasificar(r["ip"], r["ruta"], r["status"], r["ua"])
            r["categoria"] = cat
            r["es_scan"] = int(scan)
            r["es_profundo"] = int(prof)
            r["ip_pseudo"] = seudonimo(r["ip"], salt)
            lote.append(r)

        for r in lote:
            salt_obj.execute(
                "INSERT INTO accesos (ts, dia, host, metodo, ruta, ruta_base,"
                " status, bytes, ip_pseudo, ua, categoria, es_scan, es_profundo,"
                " fuente) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["ts"], r["dia"], r["host"], r["metodo"], r["ruta"],
                 r["ruta"].split("?")[0], r["status"], 0, r["ip_pseudo"],
                 r["ua"], r["categoria"], r["es_scan"], r["es_profundo"],
                 "nginx"),
            )
            salt_obj.execute(
                "INSERT INTO ip_dia (ip_pseudo, dia, categoria, requests, profundas,"
                " rutas, primera_ts, ultima_ts) VALUES (?,?,?,1,?,?,?,?)"
                " ON CONFLICT(ip_pseudo, dia) DO UPDATE SET"
                " requests = requests + 1,"
                " profundas = profundas + excluded.profundas,"
                " rutas = rutas || '|' || excluded.rutas",
                (r["ip_pseudo"], r["dia"], r["categoria"], r["es_profundo"],
                 r["ruta"], r["ts"], r["ts"]),
            )
            if guardar_raw:
                salt_obj.execute(
                    "INSERT INTO ip_raw (ip_pseudo, ip, primera, ultima)"
                    " VALUES (?,?,?,?) ON CONFLICT(ip_pseudo) DO UPDATE SET"
                    " ultima = excluded.ultima",
                    (r["ip_pseudo"], r["ip"], r["ts"], r["ts"]),
                )
        anadidas += len(lote)

        offset = st.st_size if not gz else 0
        con.execute(
            "INSERT INTO cursor_log (fichero, ino, offset, completo, leido_ts,"
            " leidas, ok) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(fichero) DO UPDATE SET"
            " ino=excluded.ino, offset=excluded.offset, completo=excluded.completo,"
            " leido_ts=excluded.leido_ts, leidas=excluded.leidas, ok=excluded.ok",
            (f, st.st_ino, offset, 1 if gz else 0,
             time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             len(lineas), len(lote)),
        )
        con.commit()
        # Umbral de 50 líneas: por debajo es ruido. Sin él, el aviso salta en
        # falso cada vez que nginx rota (el access.log nuevo tiene unas pocas
        # líneas y las de ayer ya están en access.log.1, así que da 0 de FIMI
        # durante un rato). FIMI recibe ~15 peticiones/hora, así que 50 líneas
        # sin una sola fila suya sí es el parser roto.
        if len(lineas) >= 50 and not lote and (fila["ok"] if fila else 0) > 0:
            # Este fichero antes SÍ daba filas para FIMI y ahora ninguna: eso no
            # es "sin tráfico", es el parser roto. Con el bug de la comilla
            # duplicada pasaba en silencio y aun así marcaba el fichero como
            # leído, así que esas líneas quedaban irrecuperables.
            print(f"[accesos] AVISO: {f} leía {len(lineas)} líneas y ahora da 0"
                  f" filas para FIMI (antes {fila['ok']}). ¿Cambió el"
                  " log_format? Revisa LINE_RE antes de fiarte de esta base.",
                  flush=True)
        if verbose and lote:
            print(f"[accesos] {f}: {len(lote)} de {len(lineas)} líneas",
                  flush=True)
    return anadidas


def resumen_dia(con, dia):
    filas = con.execute(
        "SELECT categoria, COUNT(*) n, COUNT(DISTINCT ip_pseudo) ips,"
        " SUM(es_profundo) profundas"
        " FROM accesos WHERE dia=? GROUP BY categoria", (dia,)
    ).fetchall()
    return {f["categoria"]: {"req": f["n"], "ips": f["ips"],
                             "profundas": f["profundas"] or 0} for f in filas}


def humanos_dia(con, dia, solo_profundo=True):
    sql = ("SELECT ip_pseudo, COUNT(*) req, SUM(es_profundo) profundas"
           " FROM accesos WHERE dia=? AND categoria IN ('HUMANO_PROBABLE','DUENO')"
           " AND (?=0 OR es_profundo=1) GROUP BY ip_pseudo ORDER BY req DESC")
    return [dict(f) for f in con.execute(sql, (dia, 1 if solo_profundo else 0))]


def rutas_humanas(con, dia):
    return [dict(f) for f in con.execute(
        "SELECT ruta, COUNT(*) n, COUNT(DISTINCT ip_pseudo) ips"
        " FROM accesos WHERE dia=? AND categoria IN ('HUMANO_PROBABLE','DUENO')"
        " GROUP BY ruta ORDER BY n DESC", (dia,))]


def stats(con):
    return dict(con.execute(
        "SELECT COUNT(*) req, COUNT(DISTINCT ip_pseudo) ips,"
        " MIN(dia) desde, MAX(dia) hasta FROM accesos").fetchone())


# --- Lectores del día ---------------------------------------------------------
# Un solo GET a `/` no demuestra que haya una persona detrás: la mitad del
# tráfico "no-bot" son previsualizadores y escáneres raros. Así que un seudónimo
# solo cuenta como LECTOR si acumula alguna señal de lectura real:
   #   - abrió contenido (`es_profundo`), o
   #   - resolvió varias rutas distintas, o
   #   - volvió en días distintos.
# Si no, queda como VISITA y no entra en la cifra titular. Es el mismo criterio
# "landing-sí / posts-no" del blog aplicado a FIMI.

def _spano(desde, hasta):
    """Segundos entre dos marcas ISO, o None si no se pueden leer."""
    if not desde or not hasta:
        return None
    try:
        a = datetime.strptime(desde, "%Y-%m-%dT%H:%M:%SZ")
        b = datetime.strptime(hasta, "%Y-%m-%dT%H:%M:%SZ")
        return max(0.0, (b - a).total_seconds())
    except (TypeError, ValueError):
        return None


def lectores_del_dia(con, dia, incluir_dueno=False):
    """Ficheros-lector del día.

    Por defecto **excluye al dueño**: su navegador es humano pero no es un
    lector del observatorio, y mezclarlo inflaría la cifra titular exactamente
    como inflaba antes el monitor del ecosistema.
    """
    cats = ("HUMANO_PROBABLE", "DUENO") if incluir_dueno else ("HUMANO_PROBABLE",)
    qs = ",".join("?" * len(cats))
    filas = [dict(f) for f in con.execute(
        "SELECT a.ip_pseudo AS ip,"
        "       a.categoria   AS categoria,"
        "       COUNT(*)      AS req,"
        "       SUM(a.es_profundo)          AS profundas,"
        "       COUNT(DISTINCT a.ruta_base) AS rutas,"
        "       MIN(a.ts) AS primera, MAX(a.ts) AS ultima"
        " FROM accesos a"
        f" WHERE a.dia=? AND a.categoria IN ({qs})"
        " GROUP BY a.ip_pseudo, a.categoria", (dia, *cats))]
    salida = []
    for f in filas:
        hist = con.execute(
            "SELECT COUNT(*) n FROM ip_dia WHERE ip_pseudo=? AND requests>=1",
            (f["ip"],)).fetchone()["n"]
        f["dias"] = hist
        profundo = f["profundas"] or 0
        # Ráfaga: 3+ páginas en menos de 90 s no es una persona leyendo, es un
        # automat. En el histórico real del 18-sep esto era el 18 % de los
        # "lectores": IP distintas, 4 rutas cada una y cero contenido.
        # Una IP que mezcla lectura con tráfico automatizado no es un lector
        # limpio: el "mejor lector" del periodo (8 dias, 45 peticiones) hacia
        # la portada a la vez que la pedia con marca de tiempo para saltar cache.
        mezcla = con.execute(
            "SELECT COUNT(*) n FROM accesos WHERE ip_pseudo=? AND categoria='BOT'",
            (f["ip"],)).fetchone()["n"]
        f["automat"] = mezcla
        span = _spano(f.get("primera"), f.get("ultima"))
        f["rafaga"] = bool(f["req"] >= 3 and span is not None and span < 90)
        if mezcla:
            f["nivel"] = "VISITA"
            f["motivo"] = f"mixto: {mezcla} peticiones automatizadas"
        elif profundo >= 1 and not f["rafaga"]:
            f["nivel"] = "LECTOR"
            f["motivo"] = "abrió contenido"
        elif profundo >= 1:
            f["nivel"] = "VISITA"
            f["motivo"] = f"ráfaga de {span:.0f} s"
        elif f["rutas"] >= 3 and f["dias"] >= 2 and not f["rafaga"]:
            f["nivel"] = "LECTOR"
            f["motivo"] = f"{f['rutas']} rutas en {f['dias']} días"
        elif f["dias"] >= 3 and f["req"] >= 3 and not f["rafaga"]:
            f["nivel"] = "LECTOR"
            f["motivo"] = f"volvió {f['dias']} días"
        else:
            f["nivel"] = "VISITA"
            f["motivo"] = ("ráfaga automatizada" if f["rafaga"]
                           else "no concluyente")
        f.pop("primera", None)
        f.pop("ultima", None)
        salida.append(f)
    salida.sort(key=lambda x: (-(x["profundas"] or 0), -x["req"], x["ip"]))
    return salida


def rutas_del_dia(con, dia, categoria=("HUMANO_PROBABLE",)):
    qs = ",".join("?" * len(categoria))
    return [dict(f) for f in con.execute(
        f"SELECT ruta, COUNT(*) req, COUNT(DISTINCT ip_pseudo) ips,"
        f" SUM(es_profundo) profundas FROM accesos"
        f" WHERE dia=? AND categoria IN ({qs}) GROUP BY ruta"
        f" ORDER BY req DESC", (dia, *categoria))]


def daily_markdown(con, dia, db="data/accesos.db"):
    """Daily list del día. Fichero legible; las IPs van seudonizadas."""
    r = resumen_dia(con, dia)
    total = sum(v["req"] for v in r.values())
    total_ips = len({f["ip_pseudo"] for f in con.execute(
        "SELECT DISTINCT ip_pseudo FROM accesos WHERE dia=?", (dia,))})
    led = [f for f in lectores_del_dia(con, dia) if f["nivel"] == "LECTOR"]
    vis = [f for f in lectores_del_dia(con, dia) if f["nivel"] == "VISITA"]

    L = []
    L.append(f"# Accesos al observatorio — {dia}")
    L.append("")
    L.append("> IPs seudonizadas (hash con salt local). "
             "\"Lector\" = abrió contenido, varias rutas o volvió otro día.")
    L.append("")
    L.append("## Resumen")
    L.append("")
    L.append(f"- Peticiones: **{total}**")
    L.append(f"- Direcciones distintas: **{total_ips}**")
    for cat in ("HUMANO_PROBABLE", "DUENO", "API", "INTERNAL", "BOT"):
        v = r.get(cat)
        if v:
            L.append(f"- {cat}: {v['req']} peticiones · {v['ips']} IP")
    L.append(f"- **Lectores probables: {len(led)}** "
             f"(candidatos no concluyentes: {len(vis)})")
    dueno = r.get("DUENO")
    if dueno:
        L.append(f"- Tus visitas: {dueno['req']} peticiones "
                 f"({dueno['ips']} IP, no cuentan como lector)")
    L.append("")

    L.append("## Lectores")
    L.append("")
    if not led:
        L.append("_Sin lecturas confirmadas._")
    else:
        L.append("| IP | Peticiones | Contenido | Rutas | Días | Motivo |")
        L.append("|---|---:|---:|---:|---:|---|")
        for f in led:
            L.append(f"| `{f['ip']}` | {f['req']} | {f['profundas'] or 0} | "
                     f"{f['rutas']} | {f['dias']} | {f['motivo']} |")
    L.append("")

    rutas = [x for x in rutas_del_dia(con, dia)
             if x["profundas"] or x["req"] >= 2][:15]
    L.append("## Rutas abiertas por humanos candidatos")
    L.append("")
    if not rutas:
        L.append("_Sin datos._")
    else:
        L.append("| Ruta | Peticiones | IPs | Contenido |")
        L.append("|---|---:|---:|---:|")
        for x in rutas:
            L.append(f"| `{x['ruta']}` | {x['req']} | {x['ips']} | "
                     f"{x['profundas'] or 0} |")
    L.append("")

    if vis:
        L.append("## No concluyente (1 visita a la portada)")
        L.append("")
        L.append(", ".join(f"`{f['ip']}`" for f in vis[:40]))
        L.append("")

    L.append("---")
    L.append("")
    L.append(f"*Generado {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} "
             f"desde `{db}`.*")
    return "\n".join(L) + "\n"

