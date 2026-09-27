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
]


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
