# -*- coding: utf-8 -*-
"""
Test del clasificador de accesos.

Fija los casos que estaban mal antes: el detector antiguo usaba
`ip.startswith()` sobre una lista enorme, así que marcaba como bot IPs
residenciales legítimas mientras dejaba pasar AWS, Cloudflare, OVH y Hetzner.
La red del dueño (79.116.x) además cambiaba a 79.117.x y hacía que tu propia
navegación contara como "humano externo".

IP de ejemplo (navegador real, 200 OK, sin marca de bot):
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detection.accesos import (  # noqa: E402
    es_datacenter, es_dueno, es_profunda, es_scan, clasificar,
)

CHROME = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

# (ip, categoria_esperada, porque)
CASOS_IP = [
    ("79.117.150.124", "DUENO", "tu IP actual (DIGI 79.117.x) es tuya"),
    ("79.116.4.9", "DUENO", "tu rango anterior (DIGI 79.116.x)"),
    ("178.105.80.193", "DUENO", "el propio servidor"),
    ("44.205.70.55", "BOT", "AWS (se colaba como humano)"),
    ("44.216.112.73", "BOT", "AWS (se colaba como humano)"),
    ("173.245.48.5", "BOT", "rango oficial de Cloudflare"),
    ("104.30.167.164", "HUMANO_PROBABLE",
     "NO es Cloudflare (verificado): sin evidencia, no se marca a ciegas"),
    ("51.81.242.85", "BOT", "OVH (se colaba como humano)"),
    ("94.154.43.84", "BOT", "hosting (se colaba como humano)"),
    ("178.16.53.77", "BOT", "Hetzner (se colaba como humano)"),
    ("88.13.206.136", "HUMANO_PROBABLE", "residencial: no debe tocarse"),
    ("83.51.14.172", "HUMANO_PROBABLE", "residencial: no debe tocarse"),
    ("71.167.4.40", "HUMANO_PROBABLE", "residencial: no debe tocarse"),
    ("209.151.149.77", "HUMANO_PROBABLE", "móvil: no debe tocarse"),
    ("46.222.153.79", "HUMANO_PROBABLE", "residencial: no debe tocarse"),
    ("88.188.15.150", "HUMANO_PROBABLE", "residencial: no debe tocarse"),
]

# (ruta, es_profunda_esperada, porque)
CASOS_RUTA = [
    ("/", False, "la portada es visita de paso, no lectura"),
    ("/index.html", False, "la portada por otro nombre tampoco cuenta"),
    ("/research.html", True, "contenido del observatorio"),
    ("/glosario.html", True, "contenido del observatorio"),
    ("/docs.html", True, "contenido del observatorio"),
    ("/sobre.html", True, "contenido del observatorio"),
    ("/c/abc123", True, "permalink de cluster"),
    ("/api/v1/temas", False, "la API es de máquinas, no lectura"),
    ("/radar-energia.png", False, "asset"),
    ("/sitemap.xml", False, "asset"),
    ("/sw.js", False, "asset"),
    ("/.env", False, "escaneo"),
    ("/wp-admin/", False, "escaneo"),
]

# (ua, ruta, status, categoria_esperada, porque)
CASOS_UA = [
    ("ecosystem-healthcheck/1.0", "/health", 200, "INTERNAL", "monitor propio"),
    ("curl/8.5.0", "/", 200, "INTERNAL", "sin UA de navegador"),
    (CHROME, "/api/v1/temas", 200, "API", "la API es de máquinas, no lector"),
    (CHROME, "/api/export?cluster=x&fmt=csv", 200, "API",
     "el endpoint de export se estaban raspando con IP residenciales"),
    (CHROME, "/?cb=1789553091", 200, "BOT",
     "cache-buster: automatable, no es una lectura"),
    (CHROME, "/research.html?v=3", 200, "HUMANO_PROBABLE",
     "un ?v= normal no debe disqualificar a nadie"),
    ("Mozilla/5.0 (compatible; Googlebot/2.1)", "/", 200, "BOT", "crawler"),
    ("facebookexternalhit/1.1", "/", 200, "BOT", "previsualizador"),
    ("Mozilla/5.0 Chrome/140", "/.env", 404, "BOT", "escaneo con UA de navegador"),
    (CHROME, "/no-existe", 404, "BOT", "404 no es lectura"),
    (CHROME, "/", 200, "HUMANO_PROBABLE", "navegador + 200 + IP residencial"),
    # --- casos reales medidos en el log los días 13-27 de septiembre de 2026 ---
    ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
     " Chrome/120.0 Safari/537.36", "/", 200, "BOT",
     "Chrome con la versión mal formada: 579 peticiones, el patrón dominante"),
    ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
     " Chrome/126 Safari/537.36", "/research.html", 200, "BOT",
     "Chrome/126 sin parche: un Chrome real manda 4 componentes"),
    ("Mozilla/5.0 (compatible; SkyWatch/1.0; "
     "+https://github.com/skywatch-bsky/skywatch-automod)", "/", 200, "BOT",
     "moderador de Bluesky: se colaba como lector recurrente"),
    ("Mozilla/5.0 (compatible; UnifiedPaths/1.0)", "/", 200, "BOT", "crawler"),
    ("Mozilla/5.0 (compatible; NuxtFyi/0.1; +https://nuxt.com)", "/", 200, "BOT",
     "escáner de sitios Nuxt"),
    ("Mozilla/5.0 (compatible; SkyWatch/1.0)", "/research.html", 200, "BOT",
     "no debe abrir contenido como lector por ser crawler nombrado"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10.11; rv:49.0) Gecko/20100101"
     " Firefox/49.0 (FlipboardProxy)", "/", 200, "BOT",
     "Flipboard: el UA de 2016 que se colaba en la regla de 'volvió N días'"),
    ("Mozilla/5.0 (compatible; Claude-User/1.0; +claude-user@anthropic.com)",
     "/research.html", 200, "ASISTENTE_IA",
     "una persona abre el enlace en Claude: no es un lector, pero es señal"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
     " (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36; compatible;"
     " OAI-SearchBot/1.4; +https://openai.com/searchbot", "/", 200,
     "ASISTENTE_IA", "OpenAI indexando: máquina, no persona"),
    ("Mozilla/5.0 (compatible; PerplexityBot/1.0; +https://perplexity.ai)",
     "/", 200, "ASISTENTE_IA", "rastreador de asistente"),
    ("Mozilla/5.0 (compatible; GPTBot/1.0; +https://openai.com/gptbot)",
     "/", 200, "ASISTENTE_IA", "rastreador de OpenAI"),
]


def test_ia_con_gente_separa_de_ia_crawler():
    """65 crawlers de OpenAI frente a 23 personas: sumarlos multiplicaba por
    tres el canal que de verdad trae audiencia."""
    from detection.accesos import es_ia_gente
    assert es_ia_gente("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko);"
                       " compatible; Claude-User/1.0;"
                       " +claude-user@anthropic.com")
    assert es_ia_gente("Mozilla/5.0 ...; compatible; ChatGPT-User/1.0;"
                       " +https://openai.com/bot")
    assert not es_ia_gente("Mozilla/5.0 (Macintosh) AppleWebKit/537.36"
                           " (KHTML, like Gecko) Chrome/131.0.0.0"
                           " Safari/537.36; compatible; OAI-SearchBot/1.4;"
                           " +https://openai.com/searchbot"), \
        "OAI-SearchBot indexa por su cuenta: no hay nadie detrás"
    assert not es_ia_gente("Mozilla/5.0 (compatible; ClaudeBot/1.0)"), \
        "ClaudeBot es crawler; Claude-User es la persona"
    assert not es_ia_gente(CHROME)

# La IP propia del servidor por IPv6. El canario y Uptime-Kuma salen por ahí y
# `es_internal` solo miraba 127.0.0.0/8 y ::1/128, así que ~250 peticiones/día
# de monitor propio contaban como "humano probable".
IP_PROPIA_V6 = "2a01:4f8:1c1e:92d2::1"


def _fallos():
    fallos = []
    for ip, esperado, porque in CASOS_IP:
        cat, _, _ = clasificar(ip, "/research.html", 200, CHROME)
        if cat != esperado:
            fallos.append(f"IP {ip}: {cat} != {esperado} ({porque})")
    for ruta, esperado, porque in CASOS_RUTA:
        if es_profunda(ruta) != esperado:
            fallos.append(f"ruta {ruta}: es_profunda != {esperado} ({porque})")
    for ua, ruta, status, esperado, porque in CASOS_UA:
        ip = "88.13.206.136"
        cat, _, _ = clasificar(ip, ruta, status, ua)
        if cat != esperado:
            fallos.append(f"UA {ua[:28]}!r {ruta}: {cat} != {esperado} ({porque})")
    return fallos


def test_redes_de_hosting():
    for ip, _c, porque in CASOS_IP:
        if "residencial" in porque or "móvil" in porque:
            assert not es_datacenter(ip), f"{ip} marcado como datacenter"
    assert es_dueno("79.117.150.124") and es_dueno("79.116.1.1")
    assert not es_dueno("88.13.206.136")


def test_parse_line_formato_real():
    """El log_format del servidor cierra el UA con comilla de sobra.

    Esta línea es un recorte LITERAL de /var/log/nginx/access.log. Con el regex
    anterior no parseaba ninguna línea del log real y el backfill devolvía 0.
    """
    from detection.accesos import parse_line
    linea = ('2a01:4f8:1c1e:92d2::1 - - [27/Sep/2026:00:00:09 +0000] '
             '"GET / HTTP/1.1" 200 1001758 "-" '
             '"Mozilla/5.0 (X11; Linux x86_64) canary-urls/1.0"" '
             'host=fimi.viajeinteligencia.com')
    r = parse_line(linea)
    assert r is not None, "no parsea una linea real del log"
    assert r["ruta"] == "/" and r["status"] == 200
    assert r["host"] == "fimi.viajeinteligencia.com"
    assert r["dia"] == "2026-09-27"
    assert r["ua"] == "Mozilla/5.0 (X11; Linux x86_64) canary-urls/1.0"


def test_escaneos():
    from detection.accesos import es_api, es_cachebuster
    assert es_cachebuster("/?cb=1789553091")
    assert not es_cachebuster("/?page=2")
    assert es_api("/api/v1/temas")
    assert es_api("/api/export?cluster=x&fmt=csv")
    assert not es_api("/api.html"), "/api.html es la doc: eso sí es de gente"
    assert es_scan("/.env") and es_scan("/wp-admin/") and es_scan("/a.js")
    assert not es_scan("/") and not es_scan("/research.html")


def test_clasificador():
    fallos = _fallos()
    assert not fallos, "regresiones:\n  " + "\n  ".join(fallos)


def test_ip_propia_por_ipv6():
    """El tráfico del propio server sale por su IPv6, no por 127.0.0.1.

    Sin esto, el canario y Uptime-Kuma entraban como "humano probable" y en los
    días que el canario usa UA de navegador hasta se colaban en el recuento de
    lectores.
    """
    from detection.accesos import es_internal
    assert es_internal(IP_PROPIA_V6, CHROME), \
        f"{IP_PROPIA_V6} es el propio servidor y debe ser INTERNAL"
    assert es_internal("127.0.0.1", CHROME)
    assert not es_internal("88.13.206.136", CHROME), "una IP de fuera no es propia"


def test_referrers_no_confunden():
    """Clasificar_origen separa lo que es gente de lo que no.

    Los previsualizadores de enlaces y la raíz de los buscadores llegan con
    referrer propio y NO son tráfico humano: contarlos inflaba el alcance.
    """
    from detection.accesos import clasificar_origen
    assert clasificar_origen("-") is None, 'nginx escribe "-" si no hay Referer'
    assert clasificar_origen("") is None
    assert clasificar_origen(None) is None
    assert clasificar_origen("https://fimi.viajeinteligencia.com/") is None, \
        "navegar dentro del propio dashboard no es un origen (eran 2.035)"
    assert clasificar_origen("https://fimi.viajeinteligencia.com/sobre.html") is None
    assert clasificar_origen("https://www.pruebapublica.com/posts/x") == \
        "sitio propio (CTA)", "el blog propio es una métrica aparte, no 'externo'"
    assert clasificar_origen("https://go.bsky.app/") == "red social"
    assert clasificar_origen("android-app://com.google.android.gm/") == "correo", \
        "la app de Gmail es una persona, no un buscador"
    assert clasificar_origen("https://www.opengraph.io") is None, \
        "OpenGraph.io abre enlaces para ver la vista previa: es un bot"
    assert clasificar_origen("https://www.google.com/search?q=viajeinteligencia") \
        == "buscador"
    assert clasificar_origen("https://www.google.com") == "raíz de buscador (bot)", \
        "la raíz de google.com es un previsualizador, no una búsqueda"
    assert clasificar_origen("https://edmo.eu/noticia") == "prensa / institucional"
    assert clasificar_origen("https://x.com/PruebaPublica") == "red social"


def test_una_pagina_sola_no_es_lector():
    """El caso que motivó el cambio: 9 IP distintas, la misma UA de iOS 13
    (diciembre de 2019) y una página cada una, sin referer. Un crawler
    recorriendo el sitemap, no nueve personas."""
    import tempfile
    import os as _os
    from detection.accesos import conectar, lectores_del_dia, clasificar, seudonimo
    d = tempfile.mkdtemp()
    con = conectar(_os.path.join(d, "t.db"))
    ip = "88.13.206.136"
    cat, scan, prof = clasificar(ip, "/sobre.html", 200, CHROME)
    assert cat == "HUMANO_PROBABLE" and prof
    con.execute(
        "INSERT INTO accesos (ts, dia, host, metodo, ruta, ruta_base, status,"
        " bytes, ip_pseudo, ua, categoria, es_scan, es_profundo, referer,"
        " fuente) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("2026-09-25T10:00:00Z", "2026-09-25", "fimi.viajeinteligencia.com",
         "GET", "/sobre.html", "/sobre.html", 200, 0, seudonimo(ip, "s" * 64),
         CHROME, cat, int(scan), int(prof), "-", "nginx"))
    con.commit()
    led = lectores_del_dia(con, "2026-09-25")
    assert led, "debe devolver el candidato"
    assert led[0]["nivel"] == "VISITA", \
        "una página y un día no es un lector: en los datos reales era un crawler"
    assert led[0]["motivo"] == "abrió 1 página y no volvió"
    con.close()


def _linea(ip, ts, ruta, referer="-", ua=CHROME, status=200):
    return (f'{ip} - - [{ts}] "GET {ruta} HTTP/1.1" {status} 512 "{referer}" '
            f'"{ua}"" host=fimi.viajeinteligencia.com')


def test_referer_se_guarda_y_llega_al_daily():
    """El referrer se parseaba pero `ingestar` lo tiraba: se perdía la única
    señal que distingue a una persona de un crawler."""
    import tempfile
    import os as _os
    from detection.accesos import (conectar, ingestar, daily_markdown,
                                   origenes_del_dia)
    d = tempfile.mkdtemp()
    logs = _os.path.join(d, "logs")
    _os.makedirs(logs)
    ip = "88.13.206.136"
    # Dos IP, tres días, con referrer real: esto SÍ es un lector.
    lineas = [
        _linea(ip, "25/Sep/2026:10:00:00", "/sobre.html", "https://go.bsky.app/"),
        _linea("83.51.14.172", "25/Sep/2026:11:00:00", "/glosario.html",
               "https://go.bsky.app/"),
        _linea(ip, "26/Sep/2026:10:00:00", "/research.html", "https://go.bsky.app/"),
        _linea(ip, "27/Sep/2026:10:00:00", "/api/confirmar", "https://go.bsky.app/"),
    ]
    with open(_os.path.join(logs, "access.log"), "w") as fh:
        fh.write("\n".join(lineas) + "\n")

    con = conectar(_os.path.join(d, "t.db"))
    n = ingestar(con, log_dir=logs)
    assert n == 4, f"debe leer 4 líneas, leyó {n}"

    guardados = con.execute("SELECT DISTINCT referer FROM accesos").fetchall()
    assert any("bsky" in f["referer"] for f in guardados), \
        "el referrer debe quedar en la BD, no solo en memoria"

    org = origenes_del_dia(con, "2026-09-25")
    assert "red social" in org and org["red social"]["req"] == 2, \
        f"origen mal agrupado: {org}"
    assert len(org["red social"]["ips"]) == 2, \
        "las IP se cuentan como conjunto: 2 direcciones distintas, no 1"

    # El daily ya no debe titular por pageviews.
    md = daily_markdown(con, "2026-09-25")
    assert "## Titular" in md
    assert "red social" in md
    assert "Orígenes externos: 2" in md

    conv = con.execute("SELECT COUNT(*) c FROM accesos"
                       " WHERE ruta_base='/api/confirmar'").fetchone()
    assert conv["c"] == 1, "una confirmación de alta es una conversión"
    assert "Conversiones" in daily_markdown(con, "2026-09-27")
    con.close()


def test_rotacion_no_duplicatea_el_dia():
    """La rotación de nginx RENOMBRA el fichero (mismo inodo, otro nombre).

    Con el cursor indexado por ruta, el día se leía dos veces: la parcial de la
    mañana como `access.log` y la completa al día siguiente como `access.log.1`.
    Medido en producción: 29-Sep 990 filas (748 únicas) y 30-Sep 1.659 (1.205).
    El cursor va por INODO: un inodo consumido no se relee, tampoco comprimido.
    """
    import tempfile
    import os as _os
    import gzip as _gzip
    from detection.accesos import conectar, ingestar
    d = tempfile.mkdtemp()
    logs = _os.path.join(d, "logs")
    _os.makedirs(logs)
    ip = "88.13.206.136"
    dia = [_linea(ip, f"29/Sep/2026:1{i}:00:00", "/research.html") for i in range(6)]
    log = _os.path.join(logs, "access.log")
    with open(log, "w") as fh:
        fh.write("\n".join(dia[:3]) + "\n")

    con = conectar(_os.path.join(d, "t.db"))
    assert ingestar(con, log_dir=logs) == 3

    # Rotación: el fichero pasa a .1 (mismo inodo) y nginx abre uno nuevo que
    # solo trae líneas nuevas, como en producción.
    _os.rename(log, _os.path.join(logs, "access.log.1"))
    with open(log, "w") as fh:
        fh.write("\n".join(dia[3:]) + "\n")
    # Segunda pasada del mismo día: lee solo lo nuevo del log vivo.
    assert ingestar(con, log_dir=logs) == 3, "solo las 3 líneas nuevas"

    # Al día siguiente el rotado se comprime y se vuelve a barrer todo.
    with open(_os.path.join(logs, "access.log.1")) as fh:
        contenido = fh.read()
    _os.remove(_os.path.join(logs, "access.log.1"))
    with _gzip.open(_os.path.join(logs, "access.log.2.gz"), "wt") as fh:
        fh.write(contenido)
    ingestar(con, log_dir=logs)

    total = con.execute("SELECT COUNT(*) c FROM accesos").fetchone()["c"]
    assert total == 6, f"sin duplicados: 6 filas, hay {total}"
    unicas = con.execute("SELECT COUNT(DISTINCT ts||ruta||ip_pseudo) c"
                         " FROM accesos").fetchone()["c"]
    assert unicas == 6, f"sin duplicados exactos: 6, hay {unicas}"
    filas_cursor = con.execute("SELECT COUNT(*) c FROM cursor_log").fetchone()["c"]
    assert filas_cursor <= 3, f"una fila de cursor por inodo, hay {filas_cursor}"
    con.close()


def test_migracion_rehace_el_cursor_con_clave_inodo():
    """La BD en producción tenía `cursor_log` con PK en `fichero`.

    Al migrar a PK=inodo hay que reconstruir la tabla, y esa rama no se ejercita
    en un install nuevo (ahí el CREATE TABLE ya trae la clave buena). Sin este
    test el SQL de la migración se rompio en silencio: la reindexación del 2-oct
    falló con «9 values for 8 columns» y la base quedó vacía.
    """
    import tempfile
    import os as _os
    import sqlite3 as _sqlite3
    from detection.accesos import conectar
    p = _os.path.join(tempfile.mkdtemp(), "t.db")
    legacy = _sqlite3.connect(p)
    legacy.executescript(
        """
        CREATE TABLE cursor_log (
            fichero   TEXT PRIMARY KEY,
            ino       INTEGER,
            offset    INTEGER NOT NULL DEFAULT 0,
            completo  INTEGER NOT NULL DEFAULT 0,
            leido_ts  TEXT
        );
        INSERT INTO cursor_log (fichero, ino, offset, leido_ts) VALUES
            ('/l/access.log', 4242, 500, '2026-10-01T07:00:00Z'),
            ('/l/access.log.1', 4242, 500, '2026-10-02T07:00:00Z'),
            ('/l/viejo.log', NULL, 10, NULL);
        """
    )
    legacy.commit()
    legacy.close()

    con = conectar(p)   # debe migrar sin reventar
    pk = [c["name"] for c in con.execute("PRAGMA table_info(cursor_log)") if c["pk"]]
    assert pk == ["ino"], f"la clave primaria debe ser el inodo, es {pk}"
    filas = con.execute("SELECT ino, fichero, leido_ts FROM cursor_log").fetchall()
    assert len(filas) == 1, f"un inodo = una fila (la NULL se descarta): {filas}"
    assert filas[0]["fichero"] == "/l/access.log.1", \
        f"debe quedarse la fila más reciente del inodo: {dict(filas[0])}"
    assert filas[0]["leido_ts"] == "2026-10-02T07:00:00Z"
    con.close()


def test_previsualizadores_no_son_origen():
    """Slack, WhatsApp y Facebook abren enlaces para la vista previa. Vienen con
    referrer propio, pero no son una persona: contarlos inflaba el alcance.

    El matiz importante: `t.co` SÍ es gente (pulsa "Compartir" en X), mientras
    que `l.facebook.com/l.php` es Facebook comprobando que el enlace exista.
    """
    from detection.accesos import clasificar_origen
    for ref, porque in (
        ("https://slack.com/links", "Slack"),
        ("https://l.facebook.com/l.php?u=https://x", "preview de Facebook"),
        ("https://telegram.org/", "web de Telegram"),
        ("https://api.slack.com/chat.open", "Slack API"),
    ):
        assert clasificar_origen(ref) is None, \
            f"{porque}: {ref!r} no debe contar como origen de gente"
    # Y los clics de verdad sí cuentan.
    for ref, porque in (
        ("https://t.co/abc", "clic desde X"),
        ("https://t.me/canal/123", "clic desde Telegram"),
        ("https://www.facebook.com/PruebaPublica", "clic desde Facebook"),
    ):
        assert clasificar_origen(ref) == "red social", \
            f"{porque}: {ref!r} sí es una persona"


def test_migracion_de_base_antigua():
    """Una base creada antes de la columna `referer` debe seguir abriéndose.

    El DDL crea índices; si el índice de `referer` se crease antes de que
    `_migrar` añadiera la columna, `conectar()` reventaría y el registro de
    accesos dejaría de funcionar del todo.
    """
    import sqlite3
    import tempfile
    import os as _os
    from detection.accesos import conectar
    d = tempfile.mkdtemp()
    p = _os.path.join(d, "vieja.db")
    con = sqlite3.connect(p)
    con.executescript(
        "CREATE TABLE accesos (id INTEGER PRIMARY KEY, ts TEXT NOT NULL,"
        " dia TEXT NOT NULL, host TEXT NOT NULL, metodo TEXT, ruta TEXT,"
        " ruta_base TEXT, status INTEGER, bytes INTEGER, ip_pseudo TEXT,"
        " ua TEXT, categoria TEXT, es_scan INTEGER NOT NULL DEFAULT 0,"
        " es_profundo INTEGER NOT NULL DEFAULT 0,"
        " fuente TEXT NOT NULL DEFAULT 'nginx');"
        "INSERT INTO accesos (ts, dia, host, ruta, ruta_base, ip_pseudo,"
        " categoria) VALUES ('2026-09-13T00:00:00Z','2026-09-13','h','/',"
        "'/','h-x','BOT');")
    con.commit()
    con.close()

    con = conectar(p)
    cols = {f["name"] for f in con.execute("PRAGMA table_info(accesos)")}
    assert "referer" in cols, "la migración debe añadir la columna referer"
    n = con.execute("SELECT COUNT(*) n FROM accesos").fetchone()["n"]
    assert n == 1, "la migración no debe perder filas"
    con.close()


if __name__ == "__main__":
    # Ejecuta TODAS las funciones test_*: si solo se llama a _fallos(), las
    # demás pasan sin ejecutarse y el "OK" no significa nada.
    f = _fallos()
    if f:
        print("FALLOS de clasificacion:")
        for x in f:
            print("  -", x)
    funciones = [(n, o) for n, o in sorted(globals().items())
                 if n.startswith("test_") and callable(o)]
    for nombre, fn in funciones:
        try:
            fn()
            print(f"  ok  {nombre}")
        except AssertionError as exc:
            print(f"  FALLO  {nombre}: {exc}")
            f.append(nombre)
    if f:
        sys.exit(1)
    print(f"OK — {len(funciones)} tests, {len(CASOS_IP)} IPs, "
          f"{len(CASOS_RUTA)} rutas, {len(CASOS_UA)} User-Agents")
