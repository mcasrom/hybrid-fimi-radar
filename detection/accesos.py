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
import socket
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
    r"img2txt|getprox|virus|scan|masscan|zgrab|nmap|sqlmap|nikto|"
    r"skywatch|unifiedpaths|nuxtfyi|lightpanda|hunter/|undici|"
    r"rootevidence|wordpress/|opengraph\.io|flipboard",
    re.I,
)

# Asistentes de IA: ni personas ni crawlers "clásicos". `Claude-User` lo
# dispara alguien (abre el enlace dentro de Claude), pero quien descarga la
# página es el agente. No cuentan como lector, pero SÍ son una vía de entrada
# con público real: en 15 días (13→27/Sep) fueron 23 aperturas con alguien
# detrás (12 Claude-User + 11 ChatGPT-User) frente a 65 peticiones de crawlers
# de IA. Por eso van en categoría propia en vez de diluirse en BOT, y por eso
# se separan SIEMPRE antes de reportar.
UA_IA = re.compile(
    r"claude-user|claude-web|chatgpt-user|gptbot|oai-searchbot|"
    r"perplexitybot|perplexity-user|google-extended|ccbot|bytespider|"
    r"anthropic-ai|meta-externalagent|applebot-extended|omgili|youbot|"
    r"claudebot",
    re.I,
)

# La categoría ASISTENTE_IA mezcla dos cosas muy distintas y hay que separarlas
# SIEMPRE antes de contar nada, porque una tapa a la otra:
#   · "gente": alguien preguntó a un asistente y el asistente abrió el enlace
#     (Claude-User, ChatGPT-User, Perplexity-User). Es tráfico humano, aunque
#     lo descargue la máquina. En los 15 días medidos: 23 aperturas.
#   · "crawlers": OpenAI, Anthropic y demás indexando para sus modelos.
#     En los mismos 15 días: 65 peticiones. Contarlas como "gente" multiplicaba
#     por tres el canal que de verdad trae audiencia.
UA_IA_GENTE = re.compile(
    r"claude-user|claude-web|chatgpt-user|perplexity-user", re.I
)

# Un Chrome de verdad manda SIEMPRE cuatro componentes de versión
# (`Chrome/120.0.0.0`). "Chrome/120.0" o "Chrome/126" los manda un crawler que
# se hace pasar por navegador: en los 15 días medidos fueron 737 peticiones
# (el patrón dominante del tráfico candidato) con la marca mal formada.
UA_CHROME = re.compile(r"Chrome/", re.I)
UA_CHROME_REAL = re.compile(r"Chrome/\d+\.\d+\.\d+\.\d+")

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

# Direcciones del propio servidor que NO caen en INTERNAL_NETS.
#
# La IPv6 está porque sale en el log del propio servidor: es la primera línea
# literal de un access.log real usada como fixture en los tests
# (`2a01:4f8:1c1e:92d2::1 - - [27/Sep/2026:00:00:09 +0000] "GET / HTTP/1.1"`)
# y por ahí salen el canario y Uptime-Kuma. No es una suposición: está
# observada. Aun así se puede ampliar sin tocar código con la variable de
# entorno FIMI_IPS_PROPIAS (lista separada por comas).
IPS_PROPIAS_EXTRA = ("2a01:4f8:1c1e:92d2::1",)

_PROPIAS = None


def _ips_propias():
    """Direcciones del propio servidor, IPv4 **e IPv6**.

    Esto no es cosmético: el canario y Uptime-Kuma salen por la IPv6 del server
    y `es_internal` solo miraba `127.0.0.0/8` y `::1/128`. Resultado: cientos
    de peticiones/día de monitor propio contadas como "humano probable", y en
    los días que el canario usa UA de navegador colaban en el recuento de
    lectores. El propio tráfico, excluido.
    """
    global _PROPIAS
    if _PROPIAS is None:
        ips = set(IPS_PROPIAS_EXTRA)
        ips.update(x.strip() for x in
                   os.environ.get("FIMI_IPS_PROPIAS", "").split(",")
                   if x.strip())
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None):
                ips.add(info[4][0])
        except OSError as exc:
            print(f"[accesos] AVISO: no puedo resolver las IP propias del"
                  f" servidor ({exc}); el trafico propio puede colarse como"
                  " humano. Anadelas a FIMI_IPS_PROPIAS.", flush=True)
        _PROPIAS = ips
    return _PROPIAS


def es_dueno(ip):
    return ip in OWNER_IPS or any(ip.startswith(p) for p in OWNER_PREFIXES)


def es_internal(ip, ua):
    if UA_PROPIO.search(ua or ""):
        return True
    if ip in _ips_propias():
        return True
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if any(a in n for n in INTERNAL_NETS):
        return True
    return False


def es_ua_imitada(ua):
    """Se hace pasar por navegador sin saber imitarlo."""
    u = ua or ""
    return bool(UA_CHROME.search(u) and not UA_CHROME_REAL.search(u))


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
    if UA_IA.search(ua or ""):
        return "ASISTENTE_IA", scan, prof
    if UA_BOT.search(ua or "") or es_ua_imitada(ua):
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
    referer      TEXT,
    fuente       TEXT NOT NULL DEFAULT 'nginx'
);
CREATE INDEX IF NOT EXISTS ix_accesos_dia ON accesos(dia);
CREATE INDEX IF NOT EXISTS ix_accesos_pseudo ON accesos(ip_pseudo);
CREATE INDEX IF NOT EXISTS ix_accesos_cat ON accesos(categoria);
CREATE INDEX IF NOT EXISTS ix_accesos_prof ON accesos(es_profundo);
CREATE INDEX IF NOT EXISTS ix_accesos_base ON accesos(ruta_base);
-- El índice de `referer` lo crea `_migrar`, no aquí: en una base ya existente
-- la columna todavía no existe cuando se ejecuta este DDL, y un CREATE INDEX
-- sobre una columna ausente aborta el script entero.

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

-- Cursor de lectura incremental con clave primaria **INODO** (2-oct).
-- La rotación de nginx RENOMBRA (`access.log` -> `access.log.1`) sin cambiar el
-- inodo y luego REUSA la ruta `access.log`: con la clave en `fichero` el
-- `ON CONFLICT` sobrescribía la fila del inodo viejo con el nuevo y el día
-- volvía a leerse entero (doble conteo medido: 29-Sep 990 filas/748 únicas).
-- Una fila por inodo: si el inodo ya se consumió, no se relee ni comprimido.
-- `bytes` detecta reutilización de inodo (fichero que mengua = contenido nuevo).
-- `leidas`/`ok` no son decorativos: si un fichero trae líneas y no parsea
-- ninguna, es que el parser se ha roto (cambió el log_format) y hay que
-- loudly avisar en vez de advancing el cursor en silencio.
CREATE TABLE IF NOT EXISTS cursor_log (
    ino       INTEGER PRIMARY KEY,
    fichero   TEXT,
    offset    INTEGER NOT NULL DEFAULT 0,
    completo  INTEGER NOT NULL DEFAULT 0,
    leido_ts  TEXT,
    leidas    INTEGER NOT NULL DEFAULT 0,
    ok        INTEGER NOT NULL DEFAULT 0,
    bytes     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT
);
"""


def _migrar(con):
    """Añade columnas nuevas a tablas existentes (CREATE TABLE no las mete)."""
    for tabla, col, decl in (("cursor_log", "leidas", "INTEGER DEFAULT 0"),
                             ("cursor_log", "ok", "INTEGER DEFAULT 0"),
                             ("cursor_log", "bytes", "INTEGER DEFAULT 0"),
                             ("accesos", "referer", "TEXT")):
        cols = {f["name"] for f in con.execute(f"PRAGMA table_info({tabla})")}
        if col not in cols:
            con.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {decl}")
    # Reubica la clave primaria del cursor: debe ser el INODO (ver el
    # COMMENT del CREATE TABLE). Tablas antiguas con PK en `fichero` se
    # reconstruyen; de cada inodo se queda la fila más reciente.
    pk = [c["name"] for c in con.execute("PRAGMA table_info(cursor_log)") if c["pk"]]
    if pk and pk[0] != "ino":
        con.executescript(
            """
            DROP TABLE IF EXISTS cursor_log_nueva;
            CREATE TABLE cursor_log_nueva (
                ino       INTEGER PRIMARY KEY,
                fichero   TEXT,
                offset    INTEGER NOT NULL DEFAULT 0,
                completo  INTEGER NOT NULL DEFAULT 0,
                leido_ts  TEXT,
                leidas    INTEGER NOT NULL DEFAULT 0,
                ok        INTEGER NOT NULL DEFAULT 0,
                bytes     INTEGER NOT NULL DEFAULT 0
            );
            INSERT OR REPLACE INTO cursor_log_nueva
                (ino, fichero, offset, completo, leido_ts, leidas, ok, bytes)
            SELECT ino, fichero, offset, completo, MAX(leido_ts), leidas, ok, bytes
              FROM cursor_log WHERE ino IS NOT NULL GROUP BY ino;
            DROP TABLE cursor_log;
            ALTER TABLE cursor_log_nueva RENAME TO cursor_log;
            """
        )
    con.execute("CREATE INDEX IF NOT EXISTS ix_accesos_ref ON accesos(referer)")
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
    """Lee solo lo nuevo de cada fichero.

    Idempotencia por **inodo**, no por nombre (2-oct, bug de doble conteo). La
    rotación de nginx *renombra* el fichero (`access.log` -> `access.log.1`) sin
    cambiar su inodo, así que indexando el cursor por ruta el mismo día se leía
    dos veces: la parcial de la mañana como `access.log` y la completa al día
    siguiente como `access.log.1`. Medido: 29-Sep 990 filas (748 únicas), 30-Sep
    1.659 (1.205) y el día en curso siempre corto (1-Oct: 248 de 835 reales).
    Con el cursor por inodo, un inodo ya consumido no se vuelve a leer, y su
    versión comprimida (.gz) se salta siempre. `bytes` protege del caso raro de
    reutilización de inodo: si el fichero mengua, es contenido nuevo.
    """
    salt = _salt()
    anadidas = 0
    salt_obj = con.cursor()
    for f in ficheros_log(log_dir):
        try:
            st = os.stat(f)
        except OSError as exc:
            print(f"[accesos] AVISO: no puedo stat {f}: {exc}", flush=True)
            continue
        # El cursor se busca por INODO: al rotar, nginx renombra el fichero y el
        # mismo inodo aparece con otro nombre. Buscar por ruta lleva a releer el
        # día entero (bug del doble conteo, 2-oct).
        fila = con.execute(
            "SELECT fichero, ino, offset, completo, leidas, ok, bytes"
            " FROM cursor_log WHERE ino=? ORDER BY leido_ts DESC LIMIT 1",
            (st.st_ino,)
        ).fetchone()
        previo_offset = 0
        gz = f.endswith(".gz")
        if fila:
            if gz:
                # Ya consumimos este inodo cuando estaba en claro (o ya lo
                # leímos comprimido): no se vuelve a leer jamás.
                continue
            # Reutilización de inodo (raro, pero posible): el fichero mengua,
            # luego es contenido nuevo y hay que releerlo desde el principio.
            if fila["bytes"] and fila["bytes"] > st.st_size:
                previo_offset = 0
            else:
                previo_offset = min(fila["offset"], st.st_size)
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
                " referer, fuente) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["ts"], r["dia"], r["host"], r["metodo"], r["ruta"],
                 r["ruta"].split("?")[0], r["status"], 0, r["ip_pseudo"],
                 r["ua"], r["categoria"], r["es_scan"], r["es_profundo"],
                 (r.get("referer") or "")[:300], "nginx"),
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
        # Clave primaria = inodo. La ruta se REUTILIZA al rotar (`access.log`),
        # así que no puede ser la clave: sobrescribiría la fila del inodo viejo
        # y el rotado volvería a leerse entero (el bug que esto arregla).
        con.execute(
            "INSERT INTO cursor_log (ino, fichero, offset, completo, leido_ts,"
            " leidas, ok, bytes) VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(ino) DO UPDATE SET fichero=excluded.fichero,"
            " offset=excluded.offset, completo=excluded.completo,"
            " leido_ts=excluded.leido_ts, leidas=excluded.leidas, ok=excluded.ok,"
            " bytes=excluded.bytes",
            (st.st_ino, f, offset, 1 if gz else 0,
             time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             len(lineas), len(lote), st.st_size),
        )
        con.commit()
        # Poda: un inodo por fichero y quedan pocos, pero sin poda crecería sin
        # límite. 60 días deja margen de sobra para cualquier rotación.
        con.execute("DELETE FROM cursor_log WHERE leido_ts IS NULL OR leido_ts<?",
                    (time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                   time.gmtime(time.time() - 60 * 86400)),))
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
        elif profundo >= 1 and f["rafaga"]:
            f["nivel"] = "VISITA"
            f["motivo"] = f"ráfaga de {span:.0f} s"
        elif profundo >= 1 and (f["req"] >= 2 or f["dias"] >= 2):
            f["nivel"] = "LECTOR"
            f["motivo"] = "abrió contenido y volvió"
        elif profundo >= 1:
            # Contenido sí, pero una sola petición y un solo día. En los datos
            # reales esto era SIEMPRE un crawler: 9 IP distintas con la misma
            # UA de iOS 13 (diciembre de 2019) abriendo una página cada una, sin
            # referer, una detrás de otra por el sitemap. Una persona que llega
            # por un enlace trae referer y al menos un par de peticiones.
            f["nivel"] = "VISITA"
            f["motivo"] = "abrió 1 página y no volvió"
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


# --- De dónde viene la gente ---------------------------------------------------
# El referrer es la ÚNICA señal que separa a una persona de un crawler: un clic
# trae referer, un rastreo no. En los 15 días medidos (13→27/Sep, 9.051
# peticiones) había solo 8 referrers externos distintos y sumaban esto:
#   · 16 clics de `google.com/search?q=viajeinteligencia` desde 14 IP — la
#     búsqueda de MARCA funciona; es el primer canal orgánico real
#   · 2 de redes (Facebook móvil y Bluesky) y 1 de la app de Gmail
#   · 20 desde nuestros propios sitios (blog + landing) → CTA, no alcance ajeno
#   · 11 de la raíz de `google.com` → previsualizadores, no búsquedas
# Además, 23 aperturas desde asistentes de IA con alguien detrás y 65 crawlers
# de IA. Por eso el KPI titular ya no son los pageviews: son los orígenes.
# La cifra vieja "35 humanos" era de `HUMANO_PROBABLE` sin mirar el referrer;
# con referrer, casi todo lo externo eran previsualizadores y rastreadores.

_OWN = ("pruebapublica.com", "viajeinteligencia.com")

ORIGENES = (
    # El ORDEN IMPORTA: se evalúa de arriba abajo y gana la primera coincidencia.
    # "correo" y "asistente IA" van antes que "buscador" porque
    # `android-app://com.google.android.gm/` y `gemini.google` contienen
    # "google." y acabarían clasificados como búsquedas.
    ("correo", ("com.google.android.gm", "mail.google", "outlook.live",
                "mail.yahoo")),
    ("asistente IA", ("chatgpt", "openai", "claude", "anthropic", "perplexity",
                      "gemini.google", "copilot.microsoft", "you.com", "phind",
                      "poe.")),
    ("red social", ("mastodon", "bsky", "bluesky", "twitter", "x.com", "t.co",
                    "linkedin", "reddit", "t.me", "telegram", "facebook",
                    "instagram", "tiktok", "threads.net", "news.ycombinator",
                    "lobste.rs", "ok.ru", "vk.com", "weibo")),
    ("buscador", ("google.", "bing.", "duckduckgo", "yandex", "baidu", "ecosia",
                  "brave.", "mojeek", "startpage", "qwant", "search.brave",
                  "googleusercontent")),
    ("prensa / institucional", ("efe", "eldiario", "elpais", "el pais",
                                "lavanguardia", "abc.", "20minutos", "elmundo",
                                "el mundo", "rtve", "ceuta", "northdata",
                                "verenna", "nlnet", "europa.eu", "eui.eu",
                                "enisa", "edmo", "unitary", "gdelt")),
    ("otro sitio", ()),
)

# Abstención deliberada: NO todo referrer de una plataforma es una persona.
# Estas son máquinas que abren el enlace para enseñar la vista previa. Se
# distinguen de un clic real por el subdominio: `t.co` es alguien que pulsa
# "Compartir" en X (gente), `l.facebook.com/l.php` es Facebook comprobando que
# el enlace exista (bot). Confundirlos era exactamente el error que inflaba el
# alcance: un solo enlace de Telegram puede generar decenas de peticiones.
PREVISUALIZADORES = (
    "l.facebook.com", "facebookexternalhit", "telegram.org", "slack.com",
    "slack-imgproxy", "discord.com", "discordapp.com", "embedly.com",
    "iframely.com", "nuzzel.com", "outbrain.com", "skypeuripreview",
    "vkshare", "pinterest.com", "redditbot", "linkedinbot", "quora.com",
    "opengraph.io", "googleweblight",
)
# OJO: la raíz de `google.com` NO va aquí a propósito. Una búsqueda real llega
# como `google.com/search?q=...` y comparte prefijo con
# `https://www.google.com` a secas, que es un previsualizador. Se resuelve más
# abajo, en el bucle de ORIGENES, donde se puede mirar la ruta entera. Meter
# "google.com" aquí habría matado también las búsquedas de verdad.


def clasificar_origen(referer):
    """Etiqueta un referrer externo. `None` si no es un origen real.

    nginx escribe `-` cuando no hay cabecera Referer, y los previsualizadores
    de redes (facebookexternalhit, WhatsApp, Slack…) también llegan con
    referrer propio: ninguno de los dos es tráfico de gente.
    """
    ref = (referer or "").strip()
    if not ref or ref == "-":
        return None
    low = ref.lower()
    if SITIO in low:
        # Navegar de /sobre.html a /research.html dentro del propio dashboard.
        # Con esta regla salían 2.035 peticiones y 69 IP de "origen": es el
        # público que ya estaba dentro, no alcance nuevo. No se cuenta.
        return None
    for propio in _OWN:
        if propio in low:
            return "sitio propio (CTA)"
    for marca in PREVISUALIZADORES:
        if marca in low:
            return None
    for etiqueta, marcas in ORIGENES:
        for m in marcas:
            if m in low:
                if etiqueta == "buscador" and "www.google.com" in low \
                        and "/search" not in low and "/url" not in low:
                    # La raíz de google.com como referrer es un previsualizador
                    # o un crawler, no alguien que buscó y pinchó.
                    return "raíz de buscador (bot)"
                return etiqueta
    return "otro sitio"


# Lo que NO cuenta como alcance externo de gente:
#  · la raíz de los buscadores: previsualizadores y crawlers
#  · nuestros propios sitios (blog, landing): si el CTA funciona es una
#    métrica nuestra ("¿el blog alimenta al radar?"), no alcance ajeno
#    ("¿el blog alimenta al radar?"), no alcance ajeno
SIN_CUENTAS = ("raíz de buscador (bot)", "sitio propio (CTA)")


def origenes_reales(org):
    return {k: v for k, v in org.items() if k not in SIN_CUENTAS}


def origenes_del_dia(con, dia):
    """De dónde viene la gente DE VERDAD ese día, agrupado por tipo de origen.

    `ips` es un CONJUNTO de seudónimos, no un entero. La versión anterior sumaba
    `COUNT(DISTINCT ip_pseudo)` por referer en un set de enteros, así que el
    recuento de IPs era el número de magnitudes distintas, no de direcciones:
    los 16 clics de `google.com/search?q=viajeinteligencia` desde 14 IP salían
    como "1 IP" y parecían un scraper. Eran personas.
    """
    filas = con.execute(
        "SELECT referer, ip_pseudo FROM accesos"
        " WHERE dia=? AND COALESCE(referer,'')<>''", (dia,)
    ).fetchall()
    salida = {}
    for f in filas:
        et = clasificar_origen(f["referer"])
        if not et:
            continue
        d = salida.setdefault(et, {"req": 0, "ips": set(), "refs": set()})
        d["req"] += 1
        d["ips"].add(f["ip_pseudo"])
        d["refs"].add(f["referer"][:70])
    return salida


# Acciones que solo hace una persona si quiere algo: darse de alta, confirmar
# el alta, sugerir un cluster, pedir clave. Un pageview no se puede atribuir;
# esto sí.
RUTAS_CONVERSION = (
    "/api/confirmar", "/api/sugerir", "/api/alta", "/api/suscribir",
    "/api/newsletter", "/api/clave", "/api/key",
)


def conversiones_del_dia(con, dia):
    filas = con.execute(
        "SELECT ruta, metodo, ip_pseudo, ts FROM accesos"
        " WHERE dia=? AND ruta_base IN (%s)"
        " ORDER BY ts" % ",".join("?" * len(RUTAS_CONVERSION)),
        (dia, *RUTAS_CONVERSION)
    ).fetchall()
    return [dict(f) for f in filas]


def es_ia_gente(ua):
    """True si el User-Agent es el de un asistente al que UNA PERSONA pidió
    algo (y el asistente vino a leer el enlace). False si es un crawler que
    indexa por su cuenta. Nunca contarlos juntos."""
    return bool(UA_IA_GENTE.search(ua or ""))


def asistentes_dia(con, dia):
    """Aperturas desde asistentes de IA, separadas por si hay alguien detrás.

    Devuelve los tres: sin el desglose, 'asistentes' es una cifra que no quiere
    decir nada (65 crawlers de OpenAI pueden tapar a 23 personas reales).
    """
    f = con.execute(
        "SELECT COUNT(*) req, COUNT(DISTINCT ip_pseudo) ips FROM accesos"
        " WHERE dia=? AND categoria='ASISTENTE_IA'", (dia,)
    ).fetchone()
    g = con.execute(
        "SELECT COUNT(*) req, COUNT(DISTINCT ip_pseudo) ips FROM accesos"
        " WHERE dia=? AND categoria='ASISTENTE_IA' AND"
        " (ua LIKE '%Claude-User%' OR ua LIKE '%claude-web%'"
        "  OR ua LIKE '%ChatGPT-User%' OR ua LIKE '%Perplexity-User%')",
        (dia,)
    ).fetchone()
    total = f["req"] or 0
    gente = g["req"] or 0
    return {"req": total, "ips": f["ips"] or 0,
            "gente": gente, "gente_ips": g["ips"] or 0,
            "crawlers": total - gente}


def _n(num, sing, plur=None):
    """'1 petición' / '3 peticiones'. Los números sueltos en un daily parecen
    un descuido aunque el dato sea correcto."""
    return f"{num} {sing if num == 1 else (plur or sing + 's')}"


def daily_markdown(con, dia, db="data/accesos.db"):
    """Daily list del día. Fichero legible; las IPs van seudonizadas."""
    r = resumen_dia(con, dia)
    total = sum(v["req"] for v in r.values())
    total_ips = len({f["ip_pseudo"] for f in con.execute(
        "SELECT DISTINCT ip_pseudo FROM accesos WHERE dia=?", (dia,))})
    todos = lectores_del_dia(con, dia)
    led = [f for f in todos if f["nivel"] == "LECTOR"]
    vis = [f for f in todos if f["nivel"] == "VISITA"]
    org = origenes_del_dia(con, dia)
    ia = asistentes_dia(con, dia)
    conv = conversiones_del_dia(con, dia)
    ext = sum(v["req"] for v in origenes_reales(org).values())

    ext_por_tipo = ", ".join(f"{k} {v['req']}"
                          for k, v in origenes_reales(org).items())
    L = []
    L.append(f"# Accesos al observatorio — {dia}")
    L.append("")
    L.append("> IPs seudonizadas (hash con salt local). Una visita de una sola")
    L.append("> página y sin referer **no se cuenta como lector**: en los datos")
    L.append("> reales ese patrón era un crawler. El titular es \"de dónde viene")
    L.append("> la gente\", no el número de páginas vistas.")
    L.append("")
    L.append("## Titular")
    L.append("")
    L.append(f"- **Lectores: {len(led)}**")
    L.append(f"- **Orígenes externos: {_n(ext, 'petición', 'peticiones')}** — "
             f"{ext_por_tipo or 'sin ninguno'}")
    L.append(f"- **Alguien preguntó a una IA y vino a leer: {ia['gente']}** "
             f"({_n(ia['gente_ips'], 'IP')}) — junto con la búsqueda de marca, "
             f"el canal que trae gente de fuera")
    L.append(f"- Crawlers de IA (OpenAI, Anthropic…): {ia['crawlers']} — "
             f"indexan, no son público")
    L.append(f"- **Conversiones: {len(conv)}** (alta, confirmar, sugerir, clave)")
    L.append("")

    L.append("## Resumen del tráfico")
    L.append("")
    L.append(f"- Peticiones: **{total}**")
    L.append(f"- Direcciones distintas: **{total_ips}**")
    for cat in ("HUMANO_PROBABLE", "ASISTENTE_IA", "DUENO", "API", "INTERNAL", "BOT"):
        v = r.get(cat)
        if v:
            L.append(f"- {cat}: {_n(v['req'], 'petición', 'peticiones')} · {_n(v['ips'], 'IP')}")
    dueno = r.get("DUENO")
    if dueno:
        L.append(f"- Tus visitas: {_n(dueno['req'], 'petición', 'peticiones')} "
                 f"({dueno['ips']} IP, no cuentan como lector)")
    L.append("")

    L.append("## De dónde viene la gente")
    L.append("")
    if not org:
        L.append("_Nadie llega desde fuera: ni buscador, ni red social, ni chat._")
        L.append("")
        L.append("Los previsualizadores de enlaces (Slack, WhatsApp, Telegram,")
        L.append("Facebook) y la raíz de los buscadores no se cuentan como")
        L.append("origen: entran, pero no son una persona.")
    else:
        L.append("| Origen | Peticiones | IP | Ejemplos |")
        L.append("|---|---:|---:|---|")
        for k, v in sorted(org.items(), key=lambda kv: -kv[1]["req"]):
            ej = ", ".join(f"`{x}`" for x in list(v["refs"])[:2])
            L.append(f"| {k} | {v['req']} | {len(v['ips'])} | {ej} |")
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

    if conv:
        L.append("## Conversiones")
        L.append("")
        for c in conv:
            L.append(f"- `{c['metodo']} {c['ruta']}` · `{c['ip_pseudo']}` · {c['ts']}")
        L.append("")

    rutas = [x for x in rutas_del_dia(con, dia)
             if x["profundas"] or x["req"] >= 2][:15]
    L.append("## Rutas abiertas por los candidatos a humano")
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
        L.append(f"## No concluyente ({len(vis)} IP)")
        L.append("")
        L.append("Abrieron una página y no volvieron, o solo pasaron por la")
        L.append("portada. Mayormente rastreadores; se listan por completitud.")
        L.append("")
        L.append(", ".join(f"`{f['ip']}`" for f in vis[:40]))
        L.append("")

    L.append("---")
    L.append("")
    L.append(f"*Generado {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} "
             f"desde `{db}`.*")
    return "\n".join(L) + "\n"

