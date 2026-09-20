#!/usr/bin/env python3
"""salud_keywords.py — ¿Están las keywords de cada tema capturando su ruido real?

Diagnostica el patrón "tema ciego": un tema con config válida y 0 errores que,
sin embargo, apenas ve eventos aunque el corpus contiene mucho material de su
ámbito. Caso real: oriente_medio usaba keywords FIMI-pur as ("campaña de
desinformación Israel") que los titulares reales ("Iran to designate maritime
zone near Hormuz") nunca matchean -> 37 eventos etiquetados de ~600 posibles.

Métricas por tema (ventana configurable, default 14 días):
  - ruido_potencial : eventos del corpus cuyo texto matchea las keywords del
                      tema **y pasa su gate `filtro`** (si lo tiene). Mismo
                      criterio que capture.py (temas_por_contenido + filtro).
  - etiquetados     : eventos en event_temas del tema.
  - cobertura %     : etiquetados / ruido_potencial. Baja con ruido alto =
                      tema posiblemente ciego (o keywords recién añadidas).
  - ruido_otro      : ruido_potencial que NO está etiquetado al tema (hueco).
  - keywords : por keyword, cuánto matchea (detecta keywords muertas) y si es
               de registro temático (términos del ámbito) o metodológico.

Solo informa: el dashboard/cron lo muestran; no decide ni altera config.

Uso:
  .venv/bin/python detection/salud_keywords.py            # JSON por consola
  .venv/bin/python detection/salud_keywords.py --html     # snippet HTML card
  .venv/bin/python detection/salud_keywords.py --tema oriente_medio
"""
import argparse
import json
import os
import sqlite3
import sys
import datetime
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "radar.db"
CONFIG = ROOT / "config.yaml"
STATE = ROOT / "data" / "keywords_estado.json"
CHAT = int(os.environ.get("FIMI_HEALTH_CHAT", "47652516"))
URL_DASH = "https://fimi.viajeinteligencia.com"

DIAS_DEFECTO = 14
# Umbral: si hay este nº de eventos del ámbito del tema sin etiquetar, se marca
# "posible keyword ciega / captura incompleta".
RUIDO_MIN_ALERTA = 50
# A partir de este nº de matches una keyword se considera "casi muerta": se
# muestra en la card aunque no llegue a 0 (p. ej. `Medgaz` con 2).
LOW_MAX = 3
# Palabras de registro metodológico (FIMI): una keyword compuesta casi solo de
# estas suele no matchear titulares reales (registro temático, no metodológico).
_METODOLOGICAS = {
    "desinformación", "desinformacion", "manipulación", "manipulacion",
    "propaganda", "campaña", "campaña de", "interferencia", "influencia",
    "informativa", "información", "informacion", "fimi", "guerra",
    "infiltration", "campaign", "disinformation", "manipulation",
    "propaganda", "interference", "fakenews", "fake news",
}


def _norm_tokens(texto):
    import unicodedata
    s = unicodedata.normalize("NFD", str(texto).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return set(w for w in s.split() if len(w) > 2)


def _tokens_kw(palabra):
    from normalizer.clasificar import normalizar, STOP
    return [t for t in normalizar(palabra).split() if len(t) > 2 and t not in STOP]


def es_metodologica(palabra):
    """True si la keyword es casi toda vocabulario FIMI (registro metodológico)
    y no contiene un término temático claro del ámbito (país/actor/lugar)."""
    toks = _tokens_kw(palabra)
    if not toks:
        return True
    meto = sum(1 for t in toks if t in _METODOLOGICAS)
    return meto >= max(2, len(toks) - 1)


def _cargar_config():
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    keywords = cfg.get("keywords", []) or []
    por_tema = {}
    for k in keywords:
        if not isinstance(k, dict):
            continue
        t = k.get("tema") or "frontera_sur"
        por_tema.setdefault(t, []).append(k.get("palabra", "").strip())
    # Gate de contenido por tema (temas.<tema>.filtro), igual que capture.py.
    filtros = {t: ((m or {}).get("filtro") or [])
               for t, m in (cfg.get("temas") or {}).items()}
    # Gate de contexto por tema (temas.<tema>.contexto), igual que capture.py.
    contextos = {t: ((m or {}).get("contexto") or [])
                 for t, m in (cfg.get("temas") or {}).items()}
    return por_tema, filtros, contextos


def analizar(dias=None):
    import sys as _s
    _s.path.insert(0, str(ROOT))
    from normalizer.clasificar import normalizar, _tokens, _matches, STOP

    dias = dias or DIAS_DEFECTO
    por_tema, filtros, contextos = _cargar_config()
    # Pre-normalizar el gate `filtro` por tema (consistencia con capture.py:
    # un tema con filtro solo cuenta como "ámbito" si el texto pasa el gate).
    filtros_pre = {}
    for _t, _terms in filtros.items():
        _prep = [(normalizar(str(x)), _tokens(str(x)))
                 for x in _terms if normalizar(str(x))]
        if _prep:
            filtros_pre[_t] = _prep
    # Pre-normalizar el gate `contexto` por tema (igual que capture.py).
    contextos_pre = {}
    for _t, _terms in contextos.items():
        _prep = [(normalizar(str(x)), _tokens(str(x)))
                 for x in _terms if normalizar(str(x))]
        if _prep:
            contextos_pre[_t] = _prep
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    t0 = int(datetime.datetime.now(datetime.timezone.utc).timestamp()) - dias * 86400
    eventos = con.execute(
        "SELECT id, text, title, source FROM events WHERE timestamp>?", (t0,)).fetchall()
    etiquetados = {}
    for r in con.execute(
            "SELECT event_id, tema_id FROM event_temas").fetchall():
        etiquetados.setdefault(r["tema_id"], set()).add(r["event_id"])

    # Pre-normalizar keywords una sola vez (con su tema).
    kws_meta = []   # (palabra, tema, kw_norm, kw_toks)
    for t, pals in por_tema.items():
        for p in pals:
            p = (p or "").strip()
            if not p:
                continue
            kws_meta.append((p, t, normalizar(p), _tokens(p)))

    # Una sola pasada: por evento se normaliza el texto UNA vez y se evalúan
    # todas las keywords contra esos tokens (antes se re-normalizaba 45×).
    match_por_evento = {}     # event_id -> set(temas)
    kw_matches = Counter()    # palabra -> nº de eventos que matchea
    for e in eventos:
        txt = ((e["title"] or "") + " " + (e["text"] or "")).strip()
        if not txt:
            continue
        nt = normalizar(txt)
        ntok = [t for t in nt.split() if len(t) > 2 and t not in STOP]
        temas_hit = set()
        for palabra, tema, kw_norm, kw_toks in kws_meta:
            if _matches(kw_norm, kw_toks, nt, ntok):
                temas_hit.add(tema)
                kw_matches[palabra] += 1
        # Gate `filtro`: un tema con filtro solo cuenta como "ámbito" si el texto
        # contiene >=1 término del filtro (igual que capture.py / gate / backfill).
        if temas_hit:
            for _t in list(temas_hit):
                _prep = filtros_pre.get(_t)
                if _prep and not any(_matches(tn, tk, nt, ntok) for tn, tk in _prep):
                    temas_hit.discard(_t)
                _prep = contextos_pre.get(_t)
                if _t in temas_hit and _prep and not any(
                        _matches(tn, tk, nt, ntok) for tn, tk in _prep):
                    temas_hit.discard(_t)
        if temas_hit:
            match_por_evento[e["id"]] = temas_hit

    resultado = {}
    for tema, pals in por_tema.items():
        pals = [p for p in pals if p]
        ruido = {eid for eid, ms in match_por_evento.items() if tema in ms}
        etiq = etiquetados.get(tema, set())
        n_ruido = len(ruido)
        # hueco real: material del ámbito (matchea keywords) que NO está
        # etiquetado al tema. Este es el dato que detecta el "tema ciego".
        n_etiq_del_ruido = len(ruido & etiq)
        n_faltan = n_ruido - n_etiq_del_ruido
        n_etiq = len(etiq)
        # cobertura sobre el material que debería capturar (0-1)
        cobertura = (n_etiq_del_ruido / n_ruido) if n_ruido else 1.0
        kw_stats = [{"palabra": p, "matches": kw_matches.get(p, 0),
                     "metodologica": es_metodologica(p)} for p in pals]
        alerta = bool(n_faltan >= RUIDO_MIN_ALERTA)
        # Patrón "keyword muerta": la mayoría de keywords no matchean nada en el
        # corpus (registro metodológico FIMI que los titulares reales no usan).
        # Es el caso original de oriente_medio (4/6 con 0 matches).
        n_kw = len(kw_stats)
        n_muertas = sum(1 for k in kw_stats if k["matches"] == 0)
        alerta_kw_muertas = n_kw >= 3 and n_muertas > n_kw / 2
        alerta = alerta or alerta_kw_muertas
        if alerta:
            if alerta_kw_muertas:
                motivo = (f"{n_muertas} de {n_kw} keywords no matchean NINGÚN evento "
                          f"del corpus en {dias}d: probable registro metodológico (FIMI) "
                          f"en vez de términos temáticos que los titulares usan. "
                          f"Ej. \"desinformación guerra Gaza\" no aparece; \"Gaza\" sí.")
            elif n_faltan >= RUIDO_MIN_ALERTA:
                motivo = (f"el corpus de {dias}d tiene {n_ruido} eventos de su ámbito "
                          f"pero {n_faltan} no están etiquetados al tema "
                          f"({cobertura*100:.0f}% capturado). "
                          f"¿keywords recién añadidas o clasificación pendiente?")
            else:
                motivo = ""
        else:
            motivo = ""
        resultado[tema] = {
            "dias": dias,
            "n_eventos_ventana": len(eventos),
            "ruido_potencial": n_ruido,
            "etiquetados_total": n_etiq,
            "etiquetados_del_ruido": n_etiq_del_ruido,
            "sin_etiquetar": n_faltan,
            "cobertura": round(cobertura, 3),
            "keywords_muertas": n_muertas,
            "casi_muertas": sum(1 for k in kw_stats if 0 < k["matches"] <= LOW_MAX),
            "keywords_revisar": [{"palabra": k["palabra"], "matches": k["matches"]}
                                 for k in kw_stats if k["matches"] <= LOW_MAX],
            "n_keywords": n_kw,
            "alerta": alerta,
            "motivo_alerta": motivo,
            "keywords": kw_stats,
        }
    con.close()
    return resultado


def _corpus_norm(con, t0):
    """Corpus (>=t0) pre-normalizado: lista de (id, texto_norm, tokens)."""
    from normalizer.clasificar import normalizar, STOP
    out = []
    for e in con.execute("SELECT id, text, title FROM events WHERE timestamp>?", (t0,)):
        txt = ((e["title"] or "") + " " + (e["text"] or "")).strip()
        if not txt:
            continue
        nt = normalizar(txt)
        ntok = {t for t in nt.split() if len(t) > 2 and t not in STOP}
        out.append((e["id"], nt, ntok))
    return out


def _subfrases(toks):
    """Todas las subfrases contiguas (listas de tokens) de una keyword."""
    n = len(toks)
    out = []
    for i in range(n):
        for j in range(i + 1, n + 1):
            out.append(toks[i:j])
    return out


# Palabras funcionales que `_matches` no filtra (STOP de clasificar.py es corto).
_STOP_SUG = {"des", "les", "une", "the", "and", "del", "los", "las", "por",
             "para", "con", "una", "und", "der", "die", "das", "of", "to",
             "from", "que", "sur", "auch", "mais", "e", "o", "y", "en"}
# Por encima de este nº de matches el término es demasiado genérico (p. ej.
# "estados", "sahel") y sustituir una keyword muerta por él añadiría ruido.
REC_MAX = 120


def _elegir(cands):
    """Candidata: la sub-frase MÁS LARGA con matches en [3, REC_MAX], sin
    palabras funcionales; evita recomendar términos genéricos o stopwords."""
    def valido(c):
        return (3 <= c["matches"] <= REC_MAX
                and not any(t in _STOP_SUG for t in c["frase"].split()))
    pool = [c for c in cands if valido(c)]
    if not pool:
        pool = [c for c in cands if c["matches"] <= REC_MAX
                and not any(t in _STOP_SUG for t in c["frase"].split())]
    if not pool:
        return None
    pool = sorted(pool, key=lambda x: (x["tokens"], x["matches"]), reverse=True)
    return pool[0]["frase"]


def sugerir(dias=None, tema=None, max_matches=None):
    """Variantes data-driven para keywords muertas/casi muertas.

    Para cada keyword con pocos matches propone las **sub-frases contiguas que
    SÍ matchean** en el corpus (14d, mismo `_matches` que capture) y los
    **tokens que no aparecen**. No altera config; `--save` persiste en
    data/keywords_sugerencias.json para que la card muestre las variantes.
    """
    import sys as _s
    _s.path.insert(0, str(ROOT))
    from normalizer.clasificar import normalizar, _tokens, _matches

    dias = dias or DIAS_DEFECTO
    umbral = LOW_MAX if max_matches is None else max_matches
    por_tema, _, _ = _cargar_config()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    t0 = int(datetime.datetime.now(datetime.timezone.utc).timestamp()) - dias * 86400
    corpus = _corpus_norm(con, t0)
    con.close()

    resultado = {}
    for t, pals in por_tema.items():
        if tema and t != tema:
            continue
        items = []
        for p in pals:
            p = (p or "").strip()
            if not p:
                continue
            ktok = _tokens(p)
            if not ktok:
                continue
            full = sum(1 for _, nt, ntok in corpus if _matches(normalizar(p), ktok, nt, ntok))
            if full > umbral:
                continue
            dead_toks = [tk for tk in ktok
                         if not any(tk in ntok for _, _, ntok in corpus)]
            cand = {}
            for sub in _subfrases(ktok):
                if sub == ktok:
                    continue
                key = " ".join(sub)
                c = sum(1 for _, nt, ntok in corpus if _matches(key, sub, nt, ntok))
                if c > 0:
                    cand[key] = max(cand.get(key, 0), c)
            cands = sorted(({"frase": k, "tokens": len(k.split()), "matches": v}
                            for k, v in cand.items()),
                           key=lambda x: (x["matches"], x["tokens"]), reverse=True)[:6]
            items.append({"palabra": p, "matches": full, "tokens_muertos": dead_toks,
                          "candidatos": cands, "recomendada": _elegir(cands)})
        if items:
            resultado[t] = items
    return resultado


def medir_cobertura_keywords(palabras, dias=None, etiquetado=False):
    """Simula cuánto capturarían unas keywords dadas en el corpus real (ventana
    `dias`). Se usa para VALIDAR keywords ANTES de añadirlas (temas_cli alta): si
    una frase es de registro metodológico ("campaña de desinformación X") apenas
    matchea titulares reales. Devuelve por keyword el nº de eventos que matchea
    y un booleano de aviso (0 matches, o todas las keywords < umbral mínimo).

    ``etiquetado=False``: mide solo el matcheo por contenido (lo que el tema
    vería de ruido). Con ``etiquetado=True`` devuelve además los eventos ya
    en event_temas del tema (solo tiene sentido con tema existente).
    """
    import sys as _s
    _s.path.insert(0, str(ROOT))
    from normalizer.clasificar import normalizar, _tokens, _matches, STOP

    dias = dias or DIAS_DEFECTO
    palabras = [p.strip() for p in (palabras or []) if p and p.strip()]
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    t0 = int(datetime.datetime.now(datetime.timezone.utc).timestamp()) - dias * 86400
    eventos = con.execute(
        "SELECT id, text, title FROM events WHERE timestamp>?", (t0,)).fetchall()
    kws_meta = [(p, normalizar(p), _tokens(p)) for p in palabras]
    totales = Counter()
    por_evento = {e["id"]: set() for e in eventos}
    for e in eventos:
        txt = ((e["title"] or "") + " " + (e["text"] or "")).strip()
        if not txt:
            continue
        nt = normalizar(txt)
        ntok = [t for t in nt.split() if len(t) > 2 and t not in STOP]
        for palabra, kw_norm, kw_toks in kws_meta:
            if _matches(kw_norm, kw_toks, nt, ntok):
                totales[palabra] += 1
                por_evento[e["id"]].add(palabra)
    n_eventos_mat = sum(1 for s in por_evento.values() if s)
    n_cero = sum(1 for p in palabras if totales.get(p, 0) == 0)
    n_metod = sum(1 for p in palabras if es_metodologica(p))
    por_kw = [{"palabra": p, "matches": totales.get(p, 0),
               "metodologica": es_metodologica(p)} for p in palabras]
    con.close()
    return {
        "dias": dias,
        "n_eventos_ventana": len(eventos),
        "n_eventos_matchean": n_eventos_mat,
        "n_keywords": len(palabras),
        "n_keywords_cero": n_cero,
        "n_keywords_metodologicas": n_metod,
        "keywords": por_kw,
    }


def _load_sugerencias():
    p = ROOT / "data" / "keywords_sugerencias.json"
    try:
        return (json.loads(p.read_text(encoding="utf-8")) or {}).get("temas", {})
    except Exception:
        return {}


def to_html(resultado):
    """Snippet HTML de la card 'Salud de keywords' (estilo del dashboard)."""
    sug = _load_sugerencias()
    cards = ""
    for tema, s in resultado.items():
        color = "#dc2626" if s["alerta"] else "#16a34a"
        lbl = "POSIBLE KEYWORD CIEGA" if s["alerta"] else "cobertura ok"
        revisar = [k for k in s["keywords"] if k["matches"] <= LOW_MAX]
        n_muertas = sum(1 for k in revisar if k["matches"] == 0)
        n_casi = len(revisar) - n_muertas
        rev_txt = ""
        if n_muertas:
            rev_txt += f" · <span style='color:#dc2626'>{n_muertas} sin matches</span>"
        if n_casi:
            rev_txt += f" · <span style='color:#d97706'>{n_casi} casi muertas (≤{LOW_MAX})</span>"
        sug_tema = {x["palabra"]: x for x in sug.get(tema, [])}
        rows = ""
        for k in sorted(revisar, key=lambda x: x["matches"]):
            info = sug_tema.get(k["palabra"]) or {}
            extra = ""
            if info.get("recomendada"):
                extra += f" → <b style='color:#15803d'>sugerido: {info['recomendada']}</b>"
            if info.get("tokens_muertos"):
                extra += (f" <span style='color:#94a3b8'>· tokens muertos: "
                          f"{', '.join(info['tokens_muertos'])}</span>")
            rows += (f"<div style='font-size:.75rem;color:#334155;margin-top:2px'>"
                     f"<code>{k['palabra']}</code> ({k['matches']}){extra}</div>")
        det = (f"<details style='margin-top:6px'><summary style='cursor:pointer;font-size:.76rem;"
               f"color:#64748b'>🔍 Keywords a revisar ({len(revisar)})</summary>{rows}</details>"
               if revisar else "")
        cards += (f"<div style='border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;"
                  f"margin:8px 0'>"
                  f"<div style='display:flex;justify-content:space-between;align-items:center;"
                  f"gap:8px;flex-wrap:wrap'>"
                  f"<b style='font-size:.9rem'>{tema}</b>"
                  f"<span style='font-size:.7rem;font-weight:800;color:{color};border:1px solid {color};"
                  f"border-radius:999px;padding:2px 10px'>{lbl}</span></div>"
                  f"<div style='font-size:.8rem;color:#475569;margin-top:4px;line-height:1.5'>"
                  f"Ámbito en corpus ({s['dias']}d): <b>{s['ruido_potencial']}</b> eventos · "
                  f"capturados al tema: <b>{s['etiquetados_del_ruido']}</b> · "
                  f"sin etiquetar: <b>{s['sin_etiquetar']}</b> · "
                  f"cobertura: <b>{s['cobertura']*100:.0f}%</b>{rev_txt}</div>"
                  + (f"<div style='font-size:.76rem;color:#b91c1c;margin-top:3px'>⚠ {s['motivo_alerta']}</div>"
                     if s["alerta"] else "")
                  + det
                  + "</div>")
    if not cards:
        cards = "<p class='caption'>Sin datos de keywords.</p>"
    return (f"<div class='card' id='salud-keywords'><h3>Salud de keywords por tema</h3>"
            f"<p class='caption'>¿Captura cada tema el ruido real de su ámbito? Se compara el "
            f"material del corpus (14d) que matchea las keywords del tema contra los eventos "
            f"realmente etiquetados. Un hueco grande (material del ámbito sin etiquetar) detecta "
            f"el patrón \"tema ciego\". Además se listan las <b>keywords a revisar</b> (sin "
            f"matches o con ≤{LOW_MAX}) y, si hay caché de sugerencias "
            f"(<code>salud_keywords.py --sugerir --save</code>), la <b>variante que sí matchea</b> "
            f"en el corpus y los <b>tokens muertos</b>. "
            f"<b>Solo informa: no decide ni altera config.</b></p>"
            f"{cards}</div>")


def load_env(filepath: Path):
    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


def notify(res, dias=None, dry_run=False):
    """Avisa por Telegram SOLO cuando un tema ENTRA en alerta (tema ciego /
    keywords muertas). Estado persistente en data/keywords_estado.json para no
    repetir el mismo aviso cada ciclo; se rearma cuando el tema se recupera.
    Patrón idéntico a notify_fuentes.py."""
    load_env(ROOT / ".env")
    token = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "")
    api = f"https://api.telegram.org/bot{token}"

    prev = {}
    if STATE.exists():
        try:
            prev = json.loads(STATE.read_text()) or {}
        except Exception:
            prev = {}

    primera_vez = not prev
    nuevos = []
    recuperados = []
    for tema, s in res.items():
        alerta = bool(s.get("alerta"))
        era = bool(prev.get(tema, {}).get("alerta"))
        prev[tema] = {"alerta": alerta,
                      "ruido_potencial": s.get("ruido_potencial", 0),
                      "sin_etiquetar": s.get("sin_etiquetar", 0),
                      "keywords_muertas": s.get("keywords_muertas", 0)}
        if primera_vez:
            continue
        if alerta and not era:
            nuevos.append(tema)
        elif era and not alerta:
            recuperados.append(tema)

    STATE.write_text(json.dumps(prev, ensure_ascii=False, indent=2))

    if not nuevos and not recuperados:
        print(f"[keywords] sin cambios de estado en salud de keywords")
        return

    if dry_run:
        print(f"[keywords][dry] nuevos: {nuevos} · recuperados: {recuperados}")
        return

    if not token or ":" not in token:
        print(f"[keywords] sin token — aviso NO enviado (nuevos: {nuevos})")
        return

    lineas = []
    for tema in nuevos:
        s = res.get(tema, {})
        lineas.append(f"⚠️ <b>Posible tema ciego: {tema}</b>\n{s.get('motivo_alerta') or ''}")
    for tema in recuperados:
        lineas.append(f"✅ <b>{tema}</b>: salud de keywords recuperada")
    lineas.append(f"Detalle: {URL_DASH}/#salud-keywords")
    text = "\n\n".join(lineas)
    try:
        import requests
        r = requests.post(f"{api}/sendMessage", data={
            "chat_id": str(CHAT), "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=30)
        print(f"[keywords] telegram HTTP {r.status_code} — nuevos {len(nuevos)}, recuperados {len(recuperados)}")
    except Exception as e:
        print(f"[keywords] error telegram: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--tema", default=None)
    ap.add_argument("--dias", type=int, default=DIAS_DEFECTO)
    ap.add_argument("--save", action="store_true",
                    help="persistir resultado en data/salud_keywords.json (para el cron)")
    ap.add_argument("--notify", action="store_true",
                    help="avisar por Telegram cuando un tema entra en alerta (patrón notify_fuentes)")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--sugerir", action="store_true",
                    help="proponer variantes data-driven para keywords muertas/casi muertas")
    args = ap.parse_args()
    if args.sugerir:
        sug = sugerir(args.dias, tema=args.tema)
        if args.save:
            from datetime import datetime as _dt, timezone as _tz
            estado = {"generado": _dt.now(_tz.utc).isoformat(), "dias": args.dias, "temas": sug}
            (ROOT / "data").mkdir(parents=True, exist_ok=True)
            (ROOT / "data" / "keywords_sugerencias.json").write_text(
                json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
            n = sum(len(v) for v in sug.values())
            print(f"keywords_sugerencias.json escrito · {n} keywords a revisar")
        if args.json or not args.save:
            print(json.dumps(sug, ensure_ascii=False, indent=1))
        return
    res = analizar(args.dias)
    if args.tema:
        res = {args.tema: res.get(args.tema, {})} if args.tema in res else {}
    if args.save:
        from datetime import datetime as _dt, timezone as _tz
        estado = {
            "generado": _dt.now(_tz.utc).isoformat(),
            "dias": args.dias,
            "temas": res,
        }
        (ROOT / "data").mkdir(parents=True, exist_ok=True)
        (ROOT / "data" / "salud_keywords.json").write_text(
            json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
        alertas = [t for t, s in res.items() if s.get("alerta")]
        print(f"salud_keywords: {len(res)} temas, alertas: {alertas or 'ninguna'}")
    if args.notify:
        notify(res, dias=args.dias, dry_run=args.dry)
    if args.html:
        print(to_html(res))
    elif args.json or not (args.save or args.notify):
        salida = res
        if args.tema:
            salida = res.get(args.tema, {})
        print(json.dumps(salida, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
