#!/usr/bin/env python3
"""Aplica la cabecera editorial A a las páginas públicas del observatorio."""
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path("/var/www/fimi")
FEEDS = Path("/home/deploy/observatorio/feeds.json")
CSS = "/observatorio/header-a.css"
MADRID = ZoneInfo("Europe/Madrid")
NAV = {
    "inicio": ("Inicio", "/observatorio/"),
    "frontera_sur": ("Frontera Sur", "/observatorio/ceuta/"),
    "protestas": ("Protestas juveniles", "/observatorio/juventud/"),
    "elecciones": ("Elecciones generales", "/observatorio/campana/"),
    "infraestructuras": ("Infraestructuras", "/observatorio/infraestructuras/"),
    "eventos": ("Acontecimientos", "/observatorio/eventos/"),
    "metodo": ("Método", "/observatorio/metodo/"),
    "fuentes": ("Fuentes", "/observatorio/fuentes/"),
    "datos": ("Datos", "/observatorio/datos/"),
    "evidencia": ("Evidencia", "/observatorio/evidencia/"),
    "glosario": ("Glosario", "/observatorio/glosario/"),
    "ayuda": ("Ayuda", "/observatorio/ayuda/"),
    "sobre": ("Sobre", "/observatorio/sobre/"),
}


def current_key(path):
    rel = path.relative_to(ROOT).as_posix()
    if rel in ("index.html", "observatorio/index.html", "observatorio/home/index.html"):
        return "inicio"
    if "/ceuta/" in rel or "/casos/" in rel:
        return "frontera_sur"
    if "/juventud/" in rel:
        return "protestas"
    if "/campana/" in rel or "/casos/electoral/" in rel:
        return "elecciones"
    if "/infraestructuras/" in rel:
        return "infraestructuras"
    if "/eventos/" in rel or "/evento/" in rel:
        return "eventos"
    if "/metodo/" in rel or rel == "metodo.html":
        return "metodo"
    if "/fuentes/" in rel or rel == "fuentes.html":
        return "fuentes"
    if "/datos/" in rel or rel == "datos.html":
        return "datos"
    if "/evidencia/" in rel:
        return "evidencia"
    if "/glosario/" in rel or rel == "glosario.html":
        return "glosario"
    if "/ayuda/" in rel or rel == "ayuda.html":
        return "ayuda"
    if "/sobre/" in rel or rel == "sobre.html":
        return "sobre"
    return "inicio"


def link(label, href, active):
    attr = ' aria-current="page"' if active else ""
    return f'<a class="obs-navlink" href="{href}"{attr}>{label}</a>'


def header(path):
    current = current_key(path)
    try:
        nfeeds = len(json.loads(FEEDS.read_text(encoding="utf-8")))
    except Exception:
        nfeeds = 95
    fecha = datetime.now(MADRID).strftime("%d %b %Y").lstrip("0")
    def nav_link(key):
        label, href = NAV[key]
        return link(label, href, key == current)
    return f'''<header class="obs-masthead">
  <div class="obs-inner">
    <div class="obs-utility">
      <span class="obs-live"><i aria-hidden="true"></i> Registro abierto · actualizado cada 30 min</span>
      <span>{fecha} · {nfeeds} feeds · 4 temas</span>
      <nav aria-label="Accesos rápidos"><a href="/observatorio/api/">API</a><a href="/observatorio/datos/">Estado</a><a href="/observatorio/en/" lang="en" hreflang="en">EN</a></nav>
    </div>
    <div class="obs-brandrow">
      <a class="obs-brand" href="/observatorio/" aria-label="Observatorio de lo publicado, inicio">
        <span class="obs-mark" aria-hidden="true"><b>O</b></span>
        <span><span class="obs-wordmark">Observatorio<em>de lo publicado</em></span><span class="obs-context">Qué se publica, quién lo publica y qué falta.</span></span>
      </a>
      <div class="obs-actions">
        <a class="obs-btn obs-btn-ghost obs-kofi" href="https://ko-fi.com/m_castillo" target="_blank" rel="noopener">Ko-fi</a>
        <button id="themeToggle" class="obs-theme" type="button" aria-label="Cambiar tema claro u oscuro">Tema</button>
        <a class="obs-btn obs-btn-ghost" href="/observatorio/datos/">Datos abiertos</a>
        <a class="obs-btn obs-btn-primary" href="/observatorio/suscribirse/">Recibir avisos →</a>
      </div>
    </div>
    <nav class="obs-nav" aria-label="Principal"><div class="obs-navgrid">
      <div class="obs-navgroup"><span class="obs-navlabel">Temas</span>{nav_link("inicio")}{nav_link("frontera_sur")}{nav_link("protestas")}{nav_link("elecciones")}{nav_link("infraestructuras")}</div>
      <div class="obs-navgroup"><span class="obs-navlabel">Sistema</span>{nav_link("eventos")}{nav_link("metodo")}{nav_link("fuentes")}{nav_link("datos")}{nav_link("evidencia")}{nav_link("glosario")}{nav_link("ayuda")}{nav_link("sobre")}</div>
    </div></nav>
  </div>
</header>'''


def apply_file(path):
    try:
        s = path.read_text(encoding="utf-8")
    except OSError:
        return False
    new = header(path)
    if 'class="sitehead"' in s:
        s2 = re.sub(r'<div class="sitehead">.*?</div>\s*', new, s, count=1, flags=re.S)
    elif 'class="obs-masthead"' in s:
        s2 = re.sub(r'<header class="obs-masthead">.*?</header>\s*', new, s, count=1, flags=re.S)
    else:
        m = re.search(r'<body([^>]*)>', s, re.I)
        if not m:
            return False
        s2 = s[:m.end()] + "\n" + new + s[m.end():]
    if CSS not in s2:
        s2 = s2.replace("</head>", f'<link rel="stylesheet" href="{CSS}">\n</head>', 1)
    if "/observatorio/theme.js" not in s2:
        s2 = s2.replace("</body>", '<script src="/observatorio/theme.js" defer></script>\n</body>', 1)
    if s2 != s:
        path.write_text(s2, encoding="utf-8")
        return True
    return False


def main():
    files = [ROOT / "index.html"]
    files.extend((ROOT / "observatorio").rglob("index.html"))
    changed = 0
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if "/admin/" in f"/{rel}" or "/en/" in f"/{rel}":
            continue
        if apply_file(path):
            changed += 1
    print(f"cabecera aplicada a {changed} páginas")


if __name__ == "__main__":
    main()
