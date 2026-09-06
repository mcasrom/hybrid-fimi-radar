#!/usr/bin/env python3
"""temas_emergentes.py — Detecta volumen que NINGÚN tema activo cubre.

El radar captura por keywords del catálogo + feeds RSS. Los feeds RSS no
llevan tema y su evento cae en el default frontera_sur. Muchos de esos
eventos hablan de asuntos que NINGUNA keyword del catálogo matchea (p.ej.
Oriente Medio, política nacional de terceros países). Ese volumen es "tema
emergente no cubierto": señal para el dueño, que decide si añade keyword o
tema. El sistema NO añade nada automáticamente.

Definición (conservadora, para no ensuciar con el default frontera_sur):
  Un evento es "fuera de catálogo" si:
  1. Su única etiqueta de tema es 'frontera_sur' (el default), y
  2. Su texto NO matchea NINGUNA keyword del catálogo (todas las de
     config.yaml → keywords), con el mismo criterio que clasificar.py.

Agrupación: frecuencia de términos significativos (sin stopwords) en la
ventana; se exige un mínimo de eventos para evitar ruido de una sola fuente.
Salida: candidatos (término, nº de eventos, nº de fuentes distintas, ejemplo
de titular) ordenados por volumen.

Uso:
  .venv/bin/python detection/temas_emergentes.py [--dias 14] [--min 10]
  .venv/bin/python detection/temas_emergentes.py --html
"""
import argparse
import collections
import math
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
sys.path.insert(0, str(ROOT))

# Stopwords amplias: castellano + francés + inglés + árabe transliterado.
# Son genéricas (no pueden ser un "tema"), se ignoran en la agrupación.
STOP = set("""de la el en y a los las un una con por para se su sus al del que es no lo
e o u entre como mas ya fue han ha sobre desde hasta esta este esto estos estas su me te mi
les des the dans une sur est avec pas tout plus aux ses ces ont ils leur elle nous vous ont ete
etre fait cette sont mais vers qui dont and for the of to in is on that are was with from has
had been at it as its or an not but by what when can que com www http https dicho dice senor
tras contra sobre tambien muy aqui hoy ano anos hace semana dias miercoles jueves viernes sabado
domingo lunes martes dia ahora tras segun segun segun afirma asegura explica senala advierte pide
exige confirma publica informa anuncia acusa considera reclama destaca resalta incide insiste apunta
news radio euronews afp efe ep agencias google amp ver mas hace despues poco antes durante media
podemos tienen quiere haber estar tiene habia habian seria sido siendo son espanoles espanola gobierno
pais paises presidente ministro ministerio partido partidos elecciones politica politico judicial
fiscalia juez jueces tribunal justicia ley leyes reforma senado congreso diputados votos voto votar
madrid barcelona valencia sevilla bilbao
pour avec sans dans sur une les des plus aux ses sont mais cette celles ceux chez elle leur elles
says said tell tells told make makes made take takes took come comes came back year years time
would could should will shall may might must upon into than then there here when where which while
because before after until again already also still even ever every each both few more most other
only own same some such too very well under over through during around between against without""".split())

# Terminología propia de frontera_sur: aunque el texto no matchee la keyword
# exacta, estos términos sí son de frontera; se descartan como "emergente".
FRONTERA_VOCAB = set("""ceuta melilla migracion migraciones inmigracion inmigrante inmigrantes
emigracion frontera fronteras migrante migrantes salto saltos valla vallas ceuti ceuties
canoas patera pateras cayuco cayucos acogida refugiado refugiados asilo espana-marruecos""".split())


def _norm(s):
    s = unicodedata.normalize("NFD", str(s).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s


def _tokens(s):
    s = _norm(s)
    s = re.sub(r"[^a-z0-9# ]", " ", s)
    return [t for t in s.split() if len(t) > 2 and t not in STOP
            and not t.isdigit() and not re.fullmatch(r"\d{4}", t)]


def cargar_config():
    try:
        return yaml.safe_load(open(ROOT / "config.yaml"))
    except Exception:
        return {}


def _matches_any(texto, kws):
    tt = set(_tokens(texto))
    for kw in kws:
        kt = _tokens(kw)
        if not kt:
            continue
        if len(kt) == 1:
            if kt[0] in tt:
                return True
        else:
            need = len(kt) if len(kt) <= 2 else int(math.ceil(0.6 * len(kt)))
            if sum(1 for t in kt if t in tt) >= need:
                return True
    return False


def detectar(dias=14, min_eventos=10, conn=None):
    cerrar = conn is None
    if conn is None:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
    cfg = cargar_config()
    kws = [str(k.get("palabra") or "") for k in (cfg.get("keywords") or []) if k.get("palabra")]
    q = ("SELECT source, text, title, timestamp FROM events e "
         "WHERE NOT EXISTS (SELECT 1 FROM event_temas t WHERE t.event_id=e.id"
         " AND t.tema_id != 'frontera_sur') AND e.timestamp >= ?")
    inicio = int(conn.execute("SELECT strftime('%s','now',?)", (f"-{dias} days",)).fetchone()[0])
    rows = conn.execute(q, (inicio,)).fetchall()
    if cerrar:
        conn.close()

    eventos_fuera = []
    for r in rows:
        txt = (r["text"] or "") + " " + (r["title"] or "")
        if not _matches_any(txt, kws):
            eventos_fuera.append((r["source"], (r["title"] or r["text"] or "").strip()[:160]))

    # Frecuencia de términos (cada evento cuenta una vez por término)
    term_eventos = collections.Counter()
    term_sources = {}
    term_ejemplo = {}
    for src, txt in eventos_fuera:
        tset = set()
        for t in _tokens(txt):
            if t in FRONTERA_VOCAB or t.startswith("#"):
                continue
            term_eventos[t] += 1
            tset.add(t)
            term_sources.setdefault(t, set()).add(src)
        for t in tset:
            if t not in term_ejemplo:
                term_ejemplo[t] = txt[:160]

    cands = []
    for t, n in term_eventos.items():
        if n < min_eventos:
            continue
        fuentes = len(term_sources.get(t, set()))
        if fuentes < 2:
            continue  # un solo canal no es un "tema emergente"
        cands.append({
            "termino": t,
            "eventos": n,
            "fuentes": fuentes,
            "ejemplo": (term_ejemplo.get(t) or "")[:160],
        })
    cands.sort(key=lambda c: (-c["eventos"], -c["fuentes"]))
    return {"total_fuera": len(eventos_fuera), "dias": dias, "candidatos": cands[:10]}


def _html(res):
    cands = res.get("candidatos", [])
    if not cands:
        return ("<div class='card'><h3>Volumen fuera de catálogo</h3>"
                "<p class='caption'>Sin candidatos a tema emergente: todo el volumen reciente "
                "casa con alguna keyword del catálogo.</p></div>")
    rows = ""
    for c in cands:
        rows += (f"<div style='margin:8px 0;padding:8px 12px;border:1px solid #e2e8f0;"
                 f"border-radius:8px'>"
                 f"<div style='display:flex;justify-content:space-between;gap:10px;align-items:baseline'>"
                 f"<b style='font-size:.88rem;color:#1e293b'>{c['termino']}</b>"
                 f"<span style='font-size:.78rem;color:#c2410c;font-weight:700'>{c['eventos']} eventos · "
                 f"{c['fuentes']} fuentes</span></div>"
                 f"<div style='font-size:.78rem;color:#64748b;margin-top:3px;line-height:1.4'>"
                 f"{c['ejemplo']}</div></div>")
    return (f"<div class='card'><h3>Volumen fuera del catálogo (¿tema emergente?)</h3>"
            f"<p class='caption'>{res['total_fuera']} eventos en los últimos {res['dias']}d "
            f"no matchean ninguna keyword de los temas activos (llegaron por feeds generales al "
            f"default). Términos recurrentes que ningún tema cubre — no son conclusión, son "
            f"candidatos a revisar. El sistema no añade nada: el catálogo lo decide el dueño.</p>"
            f"{rows}"
            f"<p class='caption' style='margin-top:6px'>Lectura: si un término repite volumen y "
            f"fuentes, puede merecer una keyword o un tema nuevo en "
            f"<code>config.yaml</code>.</p></div>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=14)
    ap.add_argument("--min", type=int, default=10, dest="min_eventos")
    ap.add_argument("--html", action="store_true")
    args = ap.parse_args()
    res = detectar(dias=args.dias, min_eventos=args.min_eventos)
    if args.html:
        print(_html(res))
    else:
        import json
        print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
