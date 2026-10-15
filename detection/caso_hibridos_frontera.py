#!/usr/bin/env python3
"""caso_hibridos_frontera.py — Subcaso «Marruecos · actividad militar y de zona
gris en Frontera Sur» (AUTOMATICO).

Wayahead paso 1+2 (parcial): separa NUCLEO (drones, buques, maniobras,
hostigamiento, bloqueo) de CONTEXTO (valla, postura oficial, critica, soberania),
titular en CLUSTERS nucleo + delta% vs media de 8 semanas, y serie semanal.

Salida:
  - docs/casos/frontera_sur_hibridos.json
  - /var/www/fimi/casos/frontera_sur_hibridos/index.html

Solo lectura de la BD + escritura de esas 2 rutas. NO toca scoring/bandas.
Los eventos se cuentan por event_temas (regla 7).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
DB = os.path.join(ROOT, "data", "radar.db")
CURADOS = os.path.join(ROOT, "data", "caso_frontera_sur_hibridos", "episodios_curados.json")
MANUAL = os.path.join(ROOT, "data", "caso_frontera_sur_hibridos",
                      "caso_frontera_sur_hibridos_manual.md")
JSON_OUT = os.path.join(ROOT, "docs", "casos", "frontera_sur_hibridos.json")
HTML_DIR = "/var/www/fimi/casos/frontera_sur_hibridos"
HTML_OUT = os.path.join(HTML_DIR, "index.html")

TEMA = "frontera_sur"
TS_CASE = int(datetime(2026, 7, 30, tzinfo=timezone.utc).timestamp())
SEM = 7 * 86400

# (clave, etiqueta, incluir, excluir, grupo)  — grupo: "nucleo" | "contexto"
CATS = [
    # ---- NUCLEO (indicadores hibridos) ----
    ("drones", "Drones", ["drone", "dron"], [], "nucleo"),
    ("buques_guerra", "Buques de guerra",
     ["buque de guerra", "barco de guerra", "navio de guerra", "buque militar", "fragata", "patrullera"], [], "nucleo"),
    ("maniobras", "Ejercicios militares", ["maniobra", "ejercicio militar", "ejercicios militares"], [], "contexto"),
    ("hostigamiento", "Hostigamiento", ["hostigamiento", "presion migratoria", "desestabiliz", "asedio"], [], "nucleo"),
    ("bloqueo", "Bloqueo aereo / maritimo",
     ["bloqueo aereo", "bloqueo maritimo", "bloqueo del espacio aereo", "cierre del espacio aereo",
      "bloqueo naval", "bloqueo de ceuta"], [], "nucleo"),
    # ---- CONTEXTO (no hibrido) ----
    ("valla_incidente", "Salto a la valla / incidente", ["valla", "salto a la valla", "incursion", "asalto"], [], "contexto"),
    ("postura_oficial", "Postura oficial de Marruecos",
     ["gobierno marroquí", "gobierno de marruecos", "ministro marroquí", "ministra marroquí",
      "exteriores marroquí", "rey de marruecos", "mohamed vi",
      "marruecos rechaza", "marruecos niega", "marruecos advierte", "marruecos afirma"],
     ["fuera del mundial", "pintadas", "fascista", "irredentismo", "asesino",
      "acusa a marruecos", "acusa a rabat"], "contexto"),
    ("critica_a_marruecos", "Critica internacional a Marruecos",
     ["acusa a marruecos", "acusa a rabat", "responsabiliza a marruecos", "marruecos viola",
      "marruecos amenaza", "irredentismo", "ofensiva marroquí", "ataque marroquí", "presión marroquí"], [], "contexto"),
    ("soberania", "Soberania / aguas",
     ["soberan", "aguas territoriales", "aguas internacionales", "tratado de ceuta"], [], "contexto"),
]

# Ancla geografica: el NUCLEO exige contexto Ceuta/Melilla/Marruecos/Estrecho.
# Evita ruido tipo "dron" en Mexico/Polonia o "antidrones" migratorio.
ANCLAS = ["ceuta", "melilla", "marruecos", "marroqu", "estrecho",
          "rabat", "gibraltar", "albor", "frontera", "valla", "canarias", "magreb", "sahara",
          "melill", "penon", "pe\u00f1on"]

MES = {1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
       7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic"}


def _n(x):
    return f"{int(round(float(x or 0))):,}".replace(",", ".")


def _fecha(ts):
    d = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return f"{d.day}-{MES[d.month]}-{d.year}"


def _gini(xs):
    """Coeficiente de Gini (0 = reparto perfecto, 1 = concentrado)."""
    xs = sorted(int(x) for x in xs)
    n = len(xs)
    s = sum(xs)
    if n == 0 or s == 0:
        return 0.0
    acc = sum(x * (2 * i - n - 1) for i, x in enumerate(xs, 1))
    return acc / (n * s)


def _origen(source):
    """Clasifica la fuente por origen (para no mezclar sesgos opuestos)."""
    s = (source or "").lower()
    if s.startswith(("bluesky", "telegram", "reddit", "mastodon", "twitter", "x:")):
        return "social"
    if "google-news" in s:
        return "agregador (google-news)"
    if any(k in s for k in ("yabiladi", "hespress", "le360", "maroc", "map ")):
        return "marroquí"
    if "tsa" in s or "algerie" in s or "algérie" in s:
        return "argelina"
    if any(k in s for k in ("al jazeera", "bbc", "france 24", "rfi", "deutsche welle",
                            "reuters", "afp", "middle east", "politico", "euobserver",
                            "tagesschau", "sputnik", "tass", "rt ", "dw ")):
        return "internacional"
    return "española"


def _medio_titulo(title):
    """Resuelve el medio original del titular de google-news ('... - La Razón')."""
    t = (title or "").strip()
    for sep in (" - ", " – ", " | ", " — "):
        if sep in t:
            return t.rsplit(sep, 1)[-1].strip()[:40]
    return ""


_MEDIOS_DOM = {
    "the objective": "theobjective.com", "abc": "abc.es", "okdiario": "okdiario.com",
    "servimedia": "servimedia.es", "canarias en pleno": "canariasenpleno.com",
    "el nacional": "elnacional.cat", "el economista": "eleconomista.es",
    "la razón": "larazon.es", "el confidencial": "elconfidencial.com",
    "el país": "elpais.com", "el mundo": "elmundo.es", "eldiario": "eldiario.es",
    "europa press": "europapress.es", "infobae": "infobae.com", "tn8": "tn8.tv",
    "el faro de ceuta": "elfarodeceuta.es", "ceuta tv": "ceutatv.com",
    "melilla hoy": "melillahoy.es", "publico": "publico.es", "efe": "efe.com",
}


def _medio_link(name):
    import urllib.parse as _up
    d = _MEDIOS_DOM.get((name or "").lower().strip())
    return f"https://{d}" if d else "https://www.google.com/search?q=" + _up.quote(name or "")


# Geografía AJENA: se excluye del núcleo si menciona otro conflicto y NO la frontera sur.
AJENO = ["méxico", "mexico", "ucrania", "rusia", "estados unidos", "ee.uu", "leipzig",
         "polonia", "finlandia", "bielorrusia"]
CORE = ["ceuta", "melilla", "marruecos", "marroqu", "estrecho", "tarajal", "rabat", "gibraltar", "albor"]

# Polaridad: coop > hostil > neutro (coop es más específico; se comprueba primero).
POL_COOP = ["ejercicio conjunto", "maniobras conjuntas", "cooperaci", "navantia",
            "african lion", "entrega de", "entrega a", "venta de", "venta a",
            "normalidad", "reabre", "colaboraci", "acuerdo bilateral", "comercio bilateral",
            "visita oficial", "cumbre bilateral", "patrullera", "astillero"]
POL_HOST = ["violaci", "incursi", "intrusi", "amenaz", "hostigamiento", "hostilid", "agresi",
            "asedi", "bloqueo", "bloquear el espacio", "ciberataque", "injerencia", "espionaje", "sabotaje",
            "chantaje", "derribo", "ataque", "disparo", "enfrentamiento", "provocaci",
            "invas", "ocupaci", "reivindica", "coerci", "coacci", "intimidaci",
            "desestabiliz", "asfixi", "presi\u00f3n migratoria", "asalto", "irredentismo",
            "militarizaci", "incursi\u00f3n a\u00e9rea", "entrada de", "interfiere", "interferencia",
            "dron marroqu", "drones marroqu", "fragata marroqu", "fragatas marroqu",
            "buques marroqu", "barcos de guerra marroqu", "basta ya"]


def _polaridad(text, title):
    t = ((text or "") + " " + (title or "")).lower()
    if any(k in t for k in POL_COOP):
        return "cooperación"
    if any(k in t for k in POL_HOST):
        return "hostil"
    return "neutro"



HIST = os.path.join(ROOT, "data", "caso_frontera_sur_hibridos", "historial.jsonl")


def _hist_leer():
    if not os.path.exists(HIST):
        return []
    try:
        return [json.loads(l) for l in open(HIST, encoding="utf-8") if l.strip()]
    except Exception as e:  # noqa: BLE001
        print("[caso-hibridos] historial ilegible:", e, file=sys.stderr)
        return []


def snapshot(d, indic):
    """Un registro por día (dedup). Se conserva todo: serie de revisión del caso."""
    from datetime import datetime as _dt, timezone as _tz
    hoy = _dt.now(_tz.utc).strftime("%Y-%m-%d")
    rec = {"fecha": hoy, "nucleo": d["nucleo"]["eventos"], "autores": d["nucleo"]["autores"],
           "clusters": d["clusters_nucleo"],
           "urls_compartidas": (d.get("amplificacion") or {}).get("urls_compartidas", 0),
           "indic": {it["lbl"]: it["n"] for it in (indic or [])}}
    rows = [r for r in _hist_leer() if r.get("fecha") != hoy]
    rows.append(rec)
    rows.sort(key=lambda r: r.get("fecha", ""))
    os.makedirs(os.path.dirname(HIST), exist_ok=True)
    try:
        with open(HIST, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    except OSError as e:
        print("[caso-hibridos] no pude escribir historial:", e, file=sys.stderr)
    return rows


def compute():
    con = sqlite3.connect(DB)
    per_cat, grups = {}, {}
    for key, _lbl, words, excl, grupo in CATS:
        like = " OR ".join(["LOWER(e.text) LIKE ? OR LOWER(e.title) LIKE ?" for _ in words])
        p = [TEMA, TS_CASE] + [f"%{w}%" for w in words for _ in ("a", "b")]
        excl_sql = ""
        if excl:
            excl_sql = " AND NOT (" + " OR ".join(
                ["LOWER(e.text) LIKE ? OR LOWER(e.title) LIKE ?" for _ in excl]) + ")"
            p += [f"%{w}%" for w in excl for _ in ("a", "b")]
        ancla_sql = coop_sql = ajeno_sql = ""
        if grupo == "nucleo":
            ancla_sql = " AND (" + " OR ".join(
                ["LOWER(e.text) LIKE ? OR LOWER(e.title) LIKE ?" for _ in ANCLAS]) + ")"
            p += [f"%{a}%" for a in ANCLAS for _ in ("a", "b")]
            # 15-oct: la COOPERACION (ejercicios conjuntos, entrega Navantia…) NO es
            # presión -> se excluye del núcleo (va a contexto).
            coop_sql = " AND NOT (" + " OR ".join(
                ["LOWER(e.text) LIKE ? OR LOWER(e.title) LIKE ?" for _ in POL_COOP]) + ")"
            p += [f"%{w}%" for w in POL_COOP for _ in ("a", "b")]
            # geografía ajena (México/Rusia…) sin núcleo de frontera sur -> fuera
            ajeno_sql = (" AND NOT ( (" + " OR ".join(
                ["LOWER(e.text) LIKE ? OR LOWER(e.title) LIKE ?" for _ in AJENO])
                + ") AND NOT (" + " OR ".join(
                    ["LOWER(e.text) LIKE ? OR LOWER(e.title) LIKE ?" for _ in CORE]) + ") )")
            p += [f"%{x}%" for x in AJENO for _ in ("a", "b")] + [f"%{x}%" for x in CORE for _ in ("a", "b")]
        ids = [r[0] for r in con.execute(
            "SELECT e.id FROM events e JOIN event_temas et ON et.event_id=e.id "
            f"WHERE et.tema_id=? AND e.timestamp>=? AND ({like}){excl_sql}{ancla_sql}{coop_sql}{ajeno_sql}", p).fetchall()]
        per_cat[key] = ids
        grups[key] = grupo

    nucleo = set().union(*[set(v) for k, v in per_cat.items() if grups[k] == "nucleo"]) if per_cat else set()
    contexto = set().union(*[set(v) for k, v in per_cat.items() if grups[k] == "contexto"]) if per_cat else set()

    def agg(idset):
        if not idset:
            return dict(eventos=0, autores=0, fuentes=0, urls=0)
        ch = ",".join("?" * len(idset))
        r = con.execute(
            f"SELECT COUNT(*) n, COUNT(DISTINCT author) a, COUNT(DISTINCT source) s, "
            f"COUNT(DISTINCT url) u FROM events WHERE id IN ({ch})", list(idset)).fetchone()
        return dict(eventos=r[0], autores=r[1], fuentes=r[2], urls=r[3])

    # clusters que contienen >=1 evento de nucleo (por cluster_events)
    wa = " OR ".join(["LOWER(ce.text) LIKE ? OR LOWER(ce.title) LIKE ?"
                      for _k, _l, w, _e, g in CATS if g == "nucleo" for _ in w])
    wp = [f"%{w}%" for _k, _l, w, _e, g in CATS if g == "nucleo" for w in w for _ in ("a", "b")]
    clusters_nucleo = con.execute(
        "SELECT COUNT(DISTINCT ce.cluster_id) FROM cluster_events ce "
        "JOIN clusters c ON c.id=ce.cluster_id WHERE c.tema_id=? AND (" + wa + ")",
        [TEMA] + wp).fetchone()[0]
    clusters_tema = con.execute("SELECT COUNT(*) FROM clusters WHERE tema_id=?", (TEMA,)).fetchone()[0]

    # amplificacion (nucleo): concentracion de autores + URLs compartidas
    ids_n = list(nucleo)
    amp = {}
    if ids_n:
        ch = ",".join("?" * len(ids_n))
        por_autor = [r[0] for r in con.execute(
            f"SELECT COUNT(*) FROM events WHERE id IN ({ch}) GROUP BY author ORDER BY 1 DESC",
            ids_n).fetchall()]
        total_a = sum(por_autor)
        amp["autores_distintos"] = len(por_autor)
        amp["top5_pct"] = round(100.0 * sum(por_autor[:5]) / total_a, 1) if total_a else 0
        amp["top10_pct"] = round(100.0 * sum(por_autor[:10]) / total_a, 1) if total_a else 0
        amp["gini"] = round(_gini(por_autor), 2)
        u = con.execute(
            f"SELECT COUNT(*) n, SUM(CASE WHEN na>=2 THEN 1 ELSE 0 END) comp FROM ("
            f" SELECT url, COUNT(DISTINCT author) na FROM events WHERE id IN ({ch})"
            f" AND COALESCE(url,'')<>'' AND url<>'-' GROUP BY url)", ids_n).fetchone()
        amp["urls_distintas"] = u[0] or 0
        amp["urls_compartidas"] = u[1] or 0

    # serie semanal de eventos de NUCLEO (buckets de 7 d hacia atras desde ahora)
    now_ts = con.execute(
        "SELECT MAX(e.timestamp) FROM events e JOIN event_temas et ON et.event_id=e.id "
        "WHERE et.tema_id=?", (TEMA,)).fetchone()[0] or int(time.time())
    ids = list(nucleo)
    serie = []
    if ids:
        ch = ",".join("?" * len(ids))
        rows = con.execute(f"SELECT timestamp FROM events WHERE id IN ({ch})", ids).fetchall()
        n_weeks = int((now_ts - (now_ts - 11 * SEM)) / SEM)  # 11 buckets
        serie = [0] * 12
        for (ts,) in rows:
            b = int((now_ts - ts) // SEM)
            if 0 <= b < 12:
                serie[b] += 1
        serie = list(reversed(serie))  # [mas antigua ... ultima]
    sem_actual = serie[-1] if serie else 0
    base8 = serie[-9:-1] if len(serie) >= 9 else serie[:-1]
    media8 = (sum(base8) / len(base8)) if base8 else 0
    delta = ((sem_actual - media8) / media8 * 100) if media8 else None

    # hitos exogenos (fecha de primera aparicion de cada narrativa, DERIVADA)
    hitos = []
    for term, lbl in (("valla", "valla"), ("maniobras militares", "ejercicios"),
                      ("navantia", "Navantia")):
        r = con.execute(
            "SELECT MIN(e.timestamp) FROM events e JOIN event_temas et ON et.event_id=e.id "
            "WHERE et.tema_id=? AND (LOWER(e.text) LIKE ? OR LOWER(e.title) LIKE ?)",
            (TEMA, f"%{term}%", f"%{term}%")).fetchone()
        if r and r[0]:
            hitos.append([int(r[0]), lbl])

    # z-score del pico (vs base 8 sem) + mediana movil 28 d
    if len(base8) >= 2:
        _m = sum(base8) / len(base8)
        _sd = (sum((x - _m) ** 2 for x in base8) / len(base8)) ** 0.5
        z = round((sem_actual - _m) / _sd, 2) if _sd else None
    else:
        z = None
    _u4 = sorted(serie[-4:]) if len(serie) >= 4 else []
    mm28 = _u4[len(_u4) // 2] if _u4 else None

    # fuentes por origen (nucleo)
    fo = {}
    if ids_n:
        _ch2 = ",".join("?" * len(ids_n))
        for src, cnt in con.execute(
                f"SELECT source, COUNT(*) FROM events WHERE id IN ({_ch2}) GROUP BY source", ids_n):
            k = _origen(src)
            fo[k] = fo.get(k, 0) + cnt

    # --- fase 1: cuota normalizada, dependencia del pico, medios independientes ---
    ids_c = list(contexto)
    serie_ctx = [0] * len(serie)
    if ids_c and serie:
        _chc = ",".join("?" * len(ids_c))
        for (ts,) in con.execute(f"SELECT timestamp FROM events WHERE id IN ({_chc})", ids_c).fetchall():
            b = int((now_ts - ts) // SEM)
            if 0 <= b < len(serie):
                serie_ctx[len(serie) - 1 - b] += 1
    cuota_pct = round(100.0 * len(nucleo) / (len(nucleo) + len(contexto)), 1) if (nucleo or contexto) else 0
    cuota_sem = [round(100.0 * nu / (nu + nc)) if (nu + nc) else 0 for nu, nc in zip(serie, serie_ctx)]

    pico_top3 = None
    medios = {}
    if ids_n:
        _chp = ",".join("?" * len(ids_n))
        rows_p = con.execute(
            f"SELECT author, COUNT(*) FROM events WHERE id IN ({_chp}) AND timestamp>=?"
            " GROUP BY author ORDER BY 2 DESC", ids_n + [now_ts - SEM]).fetchall()
        tot_p = sum(r[1] for r in rows_p)
        if tot_p:
            pico_top3 = round(100.0 * sum(r[1] for r in rows_p[:3]) / tot_p, 1)
        for src, tit, cnt in con.execute(
                f"SELECT source, title, COUNT(*) FROM events WHERE id IN ({_chp})"
                " GROUP BY source, title", ids_n).fetchall():
            if "google-news" in (src or "").lower():
                mm = _medio_titulo(tit)
                if mm:
                    medios[mm] = medios.get(mm, 0) + cnt
    top_medios = sorted(medios.items(), key=lambda kv: -kv[1])[:5]

    # polaridad (heuristica) del nucleo
    pol = {"hostil": 0, "cooperación": 0, "neutro": 0}
    if ids_n:
        _chpol = ",".join("?" * len(ids_n))
        for t2, tit2 in con.execute(
                f"SELECT text, title FROM events WHERE id IN ({_chpol})", ids_n).fetchall():
            pol[_polaridad(t2, tit2)] += 1

    # --- fase 3: H1 (correlacion con retardo + permutacion) ---
    import random as _rnd
    nd = int((now_ts - TS_CASE) // 86400) + 1

    def _daily(idset):
        arr = [0] * nd
        if idset:
            _ch = ",".join("?" * len(idset))
            for (t,) in con.execute(f"SELECT timestamp FROM events WHERE id IN ({_ch})",
                                    list(idset)).fetchall():
                k = int((t - TS_CASE) // 86400)
                if 0 <= k < nd:
                    arr[k] += 1
        return arr

    dr = _daily(set(per_cat.get("drones", [])))
    mg = _daily(contexto)

    def _corr(a, b, lag):
        if lag >= 0:
            x = a[lag:]; y = b[:len(b) - lag] if lag else b
        else:
            x = a[:len(a) + lag]; y = b[-lag:]
        n = min(len(x), len(y)); x = x[:n]; y = y[:n]
        if n < 5:
            return 0.0
        mx = sum(x) / n; my = sum(y) / n
        num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
        dx = sum((xi - mx) ** 2 for xi in x) ** 0.5
        dy = sum((yi - my) ** 2 for yi in y) ** 0.5
        return num / (dx * dy) if dx and dy else 0.0

    lags = list(range(0, 15))
    obs = [_corr(dr, mg, l) for l in lags]
    r_max = round(max(obs), 2) if obs else 0
    lag_max = lags[obs.index(max(obs))] if obs else 0
    _rnd.seed(1)
    null = []
    for _ in range(500):
        mg2 = mg[:]; _rnd.shuffle(mg2)
        null.append(max(_corr(dr, mg2, l) for l in lags))
    p_h1 = round(sum(1 for v in null if v >= max(obs)) / len(null), 3) if null else 1.0
    h1 = {"r_max": r_max, "lag": lag_max, "p": p_h1, "n_dias": nd}

    # placebo de hitos: ¿los picos caen cerca de hitos más que por azar?
    placebo = None
    if serie and hitos:
        base_ts = now_ts - len(serie) * SEM

        def _wk(ts):
            return int((ts - base_ts) // SEM)

        hw = set()
        for ts, _l in hitos:
            w = _wk(ts)
            hw.update((w - 1, w, w + 1))
        picos = sorted(range(len(serie)), key=lambda i: -serie[i])[:3]
        cerca = sum(1 for i in picos if i in hw)
        esperado = round(len(hw) / len(serie) * len(picos), 1)
        placebo = {"picos_cerca": cerca, "de": len(picos), "esperado_azar": esperado}

    # --- fase 4: fichas de los clusters del nucleo (solo eventos de nucleo) ---
    fichas = []
    if ids_n:
        _nkw = [w.lower() for _k, _l, w, _e, g in CATS if g == "nucleo" for w in w]
        wa = " OR ".join(["LOWER(ce.text) LIKE ? OR LOWER(ce.title) LIKE ?"
                          for _k, _l, w, _e, g in CATS if g == "nucleo" for _ in w])
        wp = [f"%{w}%" for _k, _l, w, _e, g in CATS if g == "nucleo" for w in w for _ in ("a", "b")]
        cl = con.execute(
            "SELECT DISTINCT c.id, c.cluster_label FROM cluster_events ce "
            "JOIN clusters c ON c.id=ce.cluster_id WHERE c.tema_id=? AND (" + wa + ")",
            [TEMA] + wp).fetchall()
        for cid, lab in cl:
            fu = con.execute("SELECT source, title, text, ts, author FROM cluster_events WHERE cluster_id=?",
                             (cid,)).fetchall()
            ev = [f2 for f2 in fu
                  if any(kw in ((f2[2] or "") + " " + (f2[1] or "")).lower() for kw in _nkw)]
            if not ev:
                continue
            ts = [f2[3] for f2 in ev if f2[3]]
            sc, pcs = {}, {}
            for f2 in ev:
                k = _origen(f2[0]); sc[k] = sc.get(k, 0) + 1
                pp = _polaridad(f2[2], f2[1]); pcs[pp] = pcs.get(pp, 0) + 1
            fichas.append({"label": lab, "desde": _fecha(min(ts)) if ts else "—",
                           "hasta": _fecha(max(ts)) if ts else "—",
                           "eventos": len(ev), "autores": len(set(f2[4] for f2 in ev)),
                           "fuente": max(sc, key=sc.get) if sc else "—",
                           "polaridad": max(pcs, key=pcs.get) if pcs else "—"})
        fichas.sort(key=lambda x: -x["eventos"])

    # --- H4: control de cobertura (¿el pico es del fenómeno o de la observación?) ---
    h4 = {}
    if ids_n:
        lim = now_ts - SEM
        _ch4 = ",".join("?" * len(ids_n))
        r = con.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT url), COUNT(DISTINCT source), COUNT(DISTINCT author)"
            f" FROM events WHERE id IN ({_ch4}) AND timestamp>=?", ids_n + [lim]).fetchone()
        h4 = {"eventos": r[0], "urls": r[1], "fuentes": r[2], "autores": r[3]}
        top = con.execute(
            f"SELECT COUNT(*) FROM events WHERE id IN ({_ch4}) AND timestamp>=?"
            " AND COALESCE(url,'')<>'' AND url<>'-' GROUP BY url ORDER BY 1 DESC LIMIT 1",
            ids_n + [lim]).fetchone()
        h4["top_url"] = top[0] if top else 0
        h4["top_url_pct"] = round(100 * top[0] / r[0]) if top and r[0] else 0
        h4["ev_por_url"] = round(r[0] / r[1], 2) if r[1] else 0

    # evidencia abierta (nucleo): eventos con enlace a la fuente + cuentas top
    evid, cuentas = [], []
    if ids_n:
        _che = ",".join("?" * len(ids_n))
        for r in con.execute(
                f"SELECT timestamp, author, source, title, url, bsky_uri FROM events"
                f" WHERE id IN ({_che}) ORDER BY timestamp DESC LIMIT 80", ids_n).fetchall():
            evid.append({"ts": int(r[0] or 0), "author": r[1] or "", "source": r[2] or "",
                         "title": (r[3] or "").replace("\n", " ")[:130],
                         "url": r[4] or "", "bsky": r[5] or ""})
        for r in con.execute(
                f"SELECT author, COUNT(*) FROM events WHERE id IN ({_che})"
                " GROUP BY author ORDER BY 2 DESC LIMIT 12", ids_n).fetchall():
            cuentas.append({"author": r[0] or "", "n": r[1]})

    out = {
        "nucleo": agg(nucleo),
        "contexto": agg(contexto),
        "clusters_nucleo": clusters_nucleo,
        "clusters_tema": clusters_tema,
        "amplificacion": amp,
        "por_categoria": {k: len(v) for k, v in per_cat.items()},
        "grupo": grups,
        "serie_semanal_nucleo": serie,
        "sem_actual_nucleo": sem_actual,
        "media8_nucleo": round(media8, 1),
        "delta_pct": round(delta, 1) if delta is not None else None,
        "hitos": hitos,
        "now_ts": int(now_ts),
        "z_score": z,
        "mediana28": mm28,
        "fuentes_origen": fo,
        "serie_contexto": serie_ctx,
        "cuota_pct": cuota_pct,
        "pico_top3_pct": pico_top3,
        "medios_indep": len(medios),
        "top_medios": top_medios,
        "polaridad": pol,
        "h1": h1,
        "placebo": placebo,
        "fichas": fichas,
        "h4": h4,
        "evidencia": evid,
        "cuentas": cuentas,
        "_ids": {"nucleo": sorted(nucleo), "contexto": sorted(contexto)},
        "periodo": {"desde": _fecha(TS_CASE), "hasta": _fecha(now_ts)},
    }
    con.close()
    return out


def _sparkline(serie):
    if not serie or max(serie) == 0:
        return ""
    W, H, pad = 560, 90, 6
    n = len(serie)
    bw = (W - 2 * pad) / n
    mx = max(serie)
    bars = []
    for i, v in enumerate(serie):
        h = (H - 2 * pad) * v / mx
        x = pad + i * bw
        y = H - pad - h
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw*0.7:.1f}" height="{h:.1f}" fill="#c1440e"/>')
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:560px;height:auto" '
            f'role="img" aria-label="Serie semanal de eventos nucleo">'
            f'<line x1="{pad}" y1="{H-pad}" x2="{W-pad}" y2="{H-pad}" stroke="#cbd5e1"/>'
            + "".join(bars) + '</svg>')


def _timeline(serie, now_ts, hitos):
    """Cronografia: barras = eventos de nucleo por semana; lineas = hitos exogenos."""
    if not serie or max(serie) == 0 or not now_ts:
        return ""
    W, H, pad, base = 820, 180, 12, 150
    n = len(serie)
    span = n * SEM
    x0 = now_ts - span
    bw = (W - 2 * pad) / n
    mx = max(serie) or 1
    parts = [f'<line x1="{pad}" y1="{base}" x2="{W - pad}" y2="{base}" stroke="#cbd5e1"/>']
    for i, v in enumerate(serie):
        h = (base - pad) * v / mx
        x = pad + i * bw
        y = base - h
        col = "#c1440e" if v == mx else "#e8a07a"
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw * 0.68:.1f}" height="{h:.1f}" fill="{col}"/>')
        parts.append(f'<text x="{x + bw * 0.34:.1f}" y="{base + 11}" font-size="8" fill="#5c6b7a" text-anchor="middle">{v}</text>')
    for ts, lbl in hitos:
        if ts < x0 or ts > now_ts:
            continue
        x = pad + (ts - x0) / span * (W - 2 * pad)
        parts.append(f'<line x1="{x:.1f}" y1="{pad + 2}" x2="{x:.1f}" y2="{base}" stroke="#0d1b2a" stroke-dasharray="3 3" opacity="0.75"/>')
        parts.append(f'<text x="{x:.1f}" y="{pad}" font-size="9" fill="#0d1b2a" text-anchor="middle">{lbl}</text>')
    f0 = datetime.fromtimestamp(x0, tz=timezone.utc).strftime("%d-%m")
    f1 = datetime.fromtimestamp(now_ts, tz=timezone.utc).strftime("%d-%m")
    parts.append(f'<text x="{pad}" y="{base + 22}" font-size="9" fill="#5c6b7a">{f0}</text>')
    parts.append(f'<text x="{W - pad}" y="{base + 22}" font-size="9" fill="#5c6b7a" text-anchor="end">{f1}</text>')
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:820px;height:auto" '
            f'role="img" aria-label="Cronografia semanal del nucleo con hitos exogenos">'
            + "".join(parts) + '</svg>')


def _md_inline(s):
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
    return s


def _md(text):
    """Markdown mínimo -> HTML (headings, listas, negrita, cursiva)."""
    out, ul, ol = [], False, False

    def _close():
        nonlocal ul, ol
        if ul:
            out.append("</ul>"); ul = False
        if ol:
            out.append("</ol>"); ol = False

    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            _close(); continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            _close()
            out.append(f"<h{min(len(m.group(1)) + 1, 4)}>{_md_inline(m.group(2))}</h{min(len(m.group(1)) + 1, 4)}>")
            continue
        m = re.match(r"^[-*]\s+(.*)$", line)
        if m:
            if ol:
                out.append("</ol>"); ol = False
            if not ul:
                out.append("<ul>"); ul = True
            out.append(f"<li>{_md_inline(m.group(1))}</li>")
            continue
        m = re.match(r"^\d+\.\s+(.*)$", line)
        if m:
            if ul:
                out.append("</ul>"); ul = False
            if not ol:
                out.append("<ol>"); ol = True
            out.append(f"<li>{_md_inline(m.group(1))}</li>")
            continue
        _close()
        out.append(f"<p>{_md_inline(line)}</p>")
    _close()
    return "".join(out)



MARRUECOS_SRC = ("yabiladi", "hespress", "le360", "le 360", "medias24", "telquel",
                 "nouvelle tribune", "akhbar", "assabah", "2m", "map ", "maroc")
CHINA_SRC = ("cgtn", "global times", "xinhua", "people's daily", "china daily", "cri ", "cctv")
INT_SRC = ("al jazeera", "rfi", "france 24", "euobserver", "tsa algerie", "algerie360", "faz", "bbc",
           "tagesschau", "deutsche welle", "politico", "middle east", "le monde", "der spiegel",
           "svenska", "dagens", "rt ", "sputnik", "tass", "presstv", "euronews", "reuters", "afp")


def compute_hechos(ids):
    """Radar A: hechos PUBLICADOS (no verificados) deduplicados por titular (fuentes no sociales)."""
    import re as _re
    import unicodedata as _ud
    from collections import defaultdict

    def _norm(s):
        s = _ud.normalize("NFKD", (s or "").lower())
        s = "".join(ch for ch in s if not _ud.combining(ch))
        s = _re.sub("[^a-z0-9 ]+", " ", s)
        return " ".join(s.split())

    if not ids:
        return {"n": 0, "historias": [], "publicaciones": 0, "medios": []}
    con = sqlite3.connect(DB)
    chq = ",".join("?" * len(ids))
    rows = con.execute(
        "SELECT timestamp, source, title, url FROM events WHERE id IN (" + chq + ")", list(ids)).fetchall()
    con.close()
    gr = defaultdict(list)
    pubs = 0
    for ts, src, tit, url in rows:
        if (src or "").lower().startswith("bluesky"):
            continue
        pubs += 1
        gr[_norm(tit)].append((int(ts or 0), src or "", tit or "", url or ""))
    historias = []
    for v in gr.values():
        v.sort()
        t0 = v[0][2]
        med = ""
        for sep in (" - ", " | "):
            if sep in t0:
                med = t0.rsplit(sep, 1)[-1].strip()[:40]
                break
        u = next((x[3] for x in v if (x[3] or "").startswith("http")), "")
        historias.append({"fecha": min(x[0] for x in v), "medio": med,
                          "titulo": t0, "url": u, "n": len(v),
                          "pubs": [{"source": x[1], "url": x[3], "ts": x[0]} for x in v]})
    historias.sort(key=lambda h: -h["fecha"])
    medios = sorted({h["medio"] for h in historias if h["medio"]})
    return {"n": len(historias), "historias": historias, "publicaciones": pubs, "medios": medios,
            "eventos": _fusionar_episodios(historias)}



_STOP = set(("de la el los las un una unos unas y o en a al del por para con sin sobre entre que se su sus "
             "lo le les es son ser esta este estas estos esa ese esas esos como mas más ya tras segun según "
             "ni muy dos tres sus ante bajo cabe contra desde hasta hacia hasta donde cuando quien cuales "
             "sera será fue han ha hay solo sólo tan todo toda todos todas otro otra otros otras mismo misma "
             "asi así ahora hoy ayer durante puede pueden tras sobre nuevo nueva tras gran grandes primer "
             "primera ultimo última vez caso parte dice dijo sobre este esa esto eso mas").split())


def _fusionar_episodios(historias):
    """Agrupa historias del MISMO acontecimiento (greedy, acotado, sin encadenar).

    Une un titular a un evento si comparte >=2 tokens poco frecuentes con su
    representante, o Jaccard >= 0.34. Evita el sobre-agrupado transitivo.
    """
    if not historias:
        return []
    import unicodedata as _ud

    def _toks(s):
        s = _ud.normalize("NFKD", (s or "").lower())
        s = "".join(c for c in s if not _ud.combining(c))
        s = "".join(c if c.isalnum() or c == " " else " " for c in s)
        return {w for w in s.split() if len(w) >= 4 and w not in _STOP and not w.isdigit()}

    sets = [_toks(h.get("titulo", "")) for h in historias]
    fechas = [h.get("fecha", 0) for h in historias]
    WIN = 7 * 86400  # no unir titulares a mas de 7 dias del evento
    N = len(historias)
    df = {}
    for s in sets:
        for w in s:
            df[w] = df.get(w, 0) + 1
    umbral = max(4, int(0.45 * N))
    eventos = []
    for i in range(N):
        best, best_sc = None, 0.0
        for k, ev in enumerate(eventos):
            if abs(fechas[i] - ev.get("last", 0)) > WIN:
                continue
            inter = sets[i] & ev["rep"]
            raros = sum(1 for w in inter if df.get(w, 0) <= umbral)
            jac = len(inter) / max(1, len(sets[i] | ev["rep"]))
            sc = raros + jac
            if (raros >= 2 or jac >= 0.34) and sc > best_sc:
                best, best_sc = k, sc
        if best is None:
            eventos.append({"rep": set(sets[i]), "idxs": [i], "last": fechas[i]})
        else:
            eventos[best]["idxs"].append(i)
            eventos[best]["rep"] |= sets[i]
            eventos[best]["last"] = min(eventos[best].get("last", fechas[i]), fechas[i])
    out = []
    for ev in eventos:
        idxs = ev["idxs"]
        pubs = []
        for i in idxs:
            pubs.extend(historias[i].get("pubs") or [])
        tit = min((historias[i].get("titulo", "") for i in idxs), key=lambda x: len(x or ""))
        fechas = [historias[i]["fecha"] for i in idxs if historias[i].get("fecha")]
        out.append({"titulo": tit, "n_pubs": len(pubs), "n_h": len(idxs),
                    "desde": min(fechas) if fechas else 0, "hasta": max(fechas) if fechas else 0,
                    "pubs": pubs})
    out.sort(key=lambda e: -e["hasta"])
    return out



def compute_series(ids, hechos, dias=30):
    """Serie diaria: publicaciones (nucleo) vs historias NUEVAS (primera publicacion)."""
    import datetime as _dt
    con = sqlite3.connect(DB)
    pub = {}
    if ids:
        chq = ",".join("?" * len(ids))
        for (ts,) in con.execute("SELECT timestamp FROM events WHERE id IN (" + chq + ")", list(ids)):
            k = _dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
            pub[k] = pub.get(k, 0) + 1
    con.close()
    his = {}
    for x in (hechos or {}).get("historias", []):
        k = _dt.datetime.utcfromtimestamp(x["fecha"]).strftime("%Y-%m-%d")
        his[k] = his.get(k, 0) + 1
    dz = sorted(set(pub) | set(his))[-dias:]
    return {"dias": dz, "pub": [pub.get(k, 0) for k in dz], "his": [his.get(k, 0) for k in dz]}


def _svg_doble(serie):
    """Grafico de doble serie: barras=publicaciones/dia, linea+dots=historias nuevas/dia."""
    dias = (serie or {}).get("dias") or []
    pub = (serie or {}).get("pub") or []
    his = (serie or {}).get("his") or []
    if not dias:
        return ""
    W, H, pad = 700, 210, 34
    base = H - pad
    n = len(dias)
    bw = (W - 2 * pad) / n
    mp = max(pub) or 1
    mh = max(his) or 1
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="max-width:700px;height:auto" '
         'role="img" aria-label="Publicaciones y acontecimientos nuevos por dia">' % (W, H)]
    p.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#cbd5e1"/>' % (pad, base, W - pad, base))
    for i, v in enumerate(pub):
        h = (base - pad) * v / mp
        x = pad + i * bw
        p.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#9db4c8"/>' % (x + bw * 0.15, base - h, bw * 0.7, h))
    pts = []
    for i, v in enumerate(his):
        x = pad + i * bw + bw / 2
        y = base - (base - pad) * v / mh
        pts.append("%.1f,%.1f" % (x, y))
    p.append('<polyline points="%s" fill="none" stroke="#c1440e" stroke-width="2"/>' % " ".join(pts))
    for pt in pts:
        cx, cy = pt.split(",")
        p.append('<circle cx="%s" cy="%s" r="3" fill="#c1440e"/>' % (cx, cy))
    p.append('<text x="%d" y="%d" font-size="10" fill="#5c6b7a">%s</text>' % (pad, base + 14, dias[0]))
    p.append('<text x="%d" y="%d" font-size="10" fill="#5c6b7a" text-anchor="end">%s</text>' % (W - pad, base + 14, dias[-1]))
    p.append('<text x="%d" y="%d" font-size="11" fill="#334155">&#9632; publicaciones/dia (max %d) '
             '&#8212; &#9679; historias nuevas/dia (max %d)</text>' % (pad, 16, mp, mh))
    p.append('</svg>')
    return "".join(p)



def compute_periodos(ids, now):
    """Conteos por periodo: 30 d, 90 d y acumulado (30-jul). Para el selector."""
    con = sqlite3.connect(DB)
    chq = ",".join("?" * len(ids)) if ids else None
    out = {}
    for etq, dias in (("30", 30), ("90", 90), ("acum", None)):
        since = (now - dias * 86400) if dias else TS_CASE
        nucl = aut = 0
        if chq:
            r = con.execute("SELECT COUNT(*), COUNT(DISTINCT author) FROM events WHERE id IN (" + chq + ") AND timestamp>=?",
                            list(ids) + [since]).fetchone()
            nucl, aut = r[0], r[1]
        out[etq] = {"nucleo": nucl, "autores": aut,
                    "indic": compute_indicadores(TEMA, since)}
    con.close()
    return out


def compute_prensa(tema):
    """Volumen + titulares de la esfera marroqui y china en el tema (y su hueco)."""
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT e.source, COUNT(DISTINCT e.id) FROM events e JOIN event_temas et "
        "ON et.event_id=e.id WHERE et.tema_id=? GROUP BY e.source", (tema,)).fetchall()

    def _pick(keys):
        out = []
        for s, k in rows:
            if any(key in (s or "").lower() for key in keys):
                ur = con.execute(
                    "SELECT e.url FROM events e JOIN event_temas et ON et.event_id=e.id "
                    "WHERE et.tema_id=? AND e.source=? AND e.url LIKE 'http%' "
                    "ORDER BY e.timestamp DESC LIMIT 1", (tema, s)).fetchone()
                out.append((s, k, (ur[0] if ur else "")))
        out.sort(key=lambda x: -x[1])
        return out

    def _samp(keys, k=6):
        out = []
        for s, _k2, _u2 in _pick(keys)[:4]:
            for tit, u, ts in con.execute(
                    "SELECT e.title, e.url, e.timestamp FROM events e JOIN event_temas et "
                    "ON et.event_id=e.id WHERE et.tema_id=? AND e.source=? "
                    "ORDER BY e.timestamp DESC LIMIT 2", (tema, s)).fetchall():
                out.append({"fuente": s, "titulo": (tit or "")[:150], "url": u or "", "ts": int(ts or 0)})
        return out[:k]

    try:
        chi_corpus = con.execute(
            "SELECT source, COUNT(*) FROM events WHERE " +
            " OR ".join(["LOWER(source) LIKE ?"] * len(CHINA_SRC)),
            ["%" + c + "%" for c in CHINA_SRC]).fetchall()
    except sqlite3.Error as _e:
        print("[caso-hibridos] chi_corpus:", _e, file=sys.stderr)
        chi_corpus = []
    _mar_samp = _samp(MARRUECOS_SRC)
    _mar = _pick(MARRUECOS_SRC)
    _int = _pick(INT_SRC)
    _chi = _pick(CHINA_SRC)
    con.close()
    return {"mar": _mar, "int": _int, "chi": _chi,
            "mar_samp": _mar_samp, "chi_corpus": chi_corpus}


INDIC = [
    ("Buques de guerra / aguas españolas", ["fragata", "buque de guerra", "aguas espa", "aguas territoriales"], "L1"),
    ("Drones", ["dron"], "L1"),
    ("Bloqueo naval / aéreo", ["bloqueo naval", "bloqueo mar", "bloqueo aer", "cierre del espacio aereo"], "L1"),
    ("Ejercicios militares con terceros", ["ejercicio conjunto", "maniobras conjuntas", "african lion", "flintlock"], "L1"),
    ("Presión energética", ["gasoducto", "suministro eléctrico", "suministro electrico", "apagón"], "L2"),
    ("Candidatos a verificación (desinformación NO confirmada)", ["bulo", "desinformaci", "manipulaci"], "L3"),
    ("Discurso oficial / rey", ["gobierno marroqu", "mohamed vi", "rey de marruecos"], "L4"),
    ("Soberanía / reivindicación Ceuta-Melilla", ["soberan", "anexi", "irredentis", "españolidad"], "L4"),
    ("Cadáveres / repatriación", ["cadáver", "cadaver", "repatriac"], "L4"),
    ("Presión migratoria (Ceuta/Melilla/Canarias)", ["presión migratoria", "presion migratoria", "asalto", "valla"], "L5"),
    ("Acuerdos tecnología/armas (China/EEUU/Israel/Emiratos)", ["armamento", "navantia", "material militar", "f-35"], "L6"),
    ("Colonización / asentamiento territorial", ["coloniz", "colono", "asentamiento", "empadron"], "L7"),
    ("Narrativa demográfica (reemplazo/natalidad/matrimonios)", ["reemplaz", "sustituc", "natalid", "matrimoni", "nacionalid"], "L7"),
]


def compute_indicadores(tema, since=None):
    con = sqlite3.connect(DB)
    out = []
    for lbl, words, lin in INDIC:
        like = " OR ".join(["LOWER(e.text) LIKE ? OR LOWER(e.title) LIKE ?" for _ in words])
        p = [tema] + [f"%{w}%" for w in words for _ in ("a", "b")]
        extra = ""
        if since:
            extra = " AND e.timestamp>=?"
            p.append(since)
        cnt = con.execute(
            "SELECT COUNT(DISTINCT e.id) FROM events e JOIN event_temas et ON et.event_id=e.id "
            "WHERE et.tema_id=? AND (" + like + ")" + extra, p).fetchone()[0]
        out.append({"lbl": lbl, "n": cnt, "linea": lin})
    con.close()
    return out



def _barchart(items, w=640, rowh=22, color="#0d1b2a"):
    """Grafico de barras horizontal (SVG) para (etiqueta, valor)."""
    items = [(str(a), float(b or 0)) for a, b in (items or [])]
    if not items:
        return ""
    mx = max(v for _, v in items) or 1
    h = rowh * len(items) + 8
    lw = 250
    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="max-width:%dpx;height:auto" '
         'role="img" aria-label="grafico de barras">' % (w, h, w)]
    for i, (lab, val) in enumerate(items):
        y = 4 + i * rowh
        bw = max(1.0, (w - lw - 56) * (val / mx))
        p.append('<text x="0" y="%d" font-size="12" fill="#334155">%s</text>' % (y + 15, lab[:40]))
        p.append('<rect x="%d" y="%d" width="%.1f" height="%d" fill="%s" rx="2"/>' % (lw, y + 3, bw, rowh - 8, color))
        p.append('<text x="%.1f" y="%d" font-size="12" fill="#334155">%s</text>' % (lw + bw + 6, y + 15, _n(val)))
    p.append('</svg>')
    return "".join(p)


_SELPER_HTML = """<style>.spb{border:1px solid #cbd5e1;background:#fff;border-radius:14px;padding:3px 12px;font-size:.85rem;cursor:pointer}.spb-on{background:#0d1b2a;color:#fff;border-color:#0d1b2a}</style>
<script>function selP(k){var b=document.querySelectorAll(".spb");for(var i=0;i<b.length;i++)b[i].className="spb"+(i==k?" spb-on":"");var el=document.querySelectorAll(".np");for(var j=0;j<el.length;j++){var v=JSON.parse(el[j].getAttribute("data-p"));el[j].textContent=v[k].toLocaleString("es-ES");}var n=document.getElementById("perNota");if(n)n.textContent=["(30 dias)","(90 dias)","(todo el caso)"][k];}</script>"""


def build_html(manual_txt, d, hechos, prensa, indic, hist, series, periodos, meta):
    def tbl(grupo):
        rows = []
        for k, lbl, _w, _e, g in CATS:
            if g != grupo:
                continue
            rows.append(f"<tr><td>{lbl}</td><td class='num'>{_n(d['por_categoria'].get(k, 0))}</td></tr>")
        return "".join(rows)

    amp = d.get("amplificacion", {})

    # --- piezas del caso (catálogo + Radar A + prensa) ---
    _per = periodos or {}
    def _per_val(i, etq, default):
        lst = (_per.get(etq) or {}).get("indic") or []
        return lst[i]["n"] if i < len(lst) else default
    _indic_rows = "".join(
        "<tr><td>%s</td><td>%s</td><td>mención</td>"
        "<td class='num np' data-p='[%s,%s,%s]'>%s</td></tr>"
        % (it["lbl"], it["linea"], _per_val(_i, "30", it["n"]), _per_val(_i, "90", it["n"]),
           _per_val(_i, "acum", it["n"]), _n(it["n"]))
        for _i, it in enumerate(indic or [])) or "<tr><td colspan=4>sin datos</td></tr>"
    _hh = (hechos or {}).get("historias", [])
    _hechos_n = _n((hechos or {}).get("n", len(_hh)))
    _hechos_pub = _n((hechos or {}).get("publicaciones", 0))
    _hechos_med = _n(len((hechos or {}).get("medios", [])))
    _n_eventos = _n(len((hechos or {}).get("eventos", []) or []))
    _hrows = []
    for _h in _hh[:40]:
        _u = _h.get("url") or ""
        _lk = ('<a href="%s" target="_blank" rel="noopener">fuente</a>' % _u) if _u else "&mdash;"
        _hrows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            _fecha(_h["fecha"]), _h.get("medio") or "&mdash;", (_h.get("titulo") or "")[:160], _lk))
    _hechos_rows = "".join(_hrows) or "<tr><td colspan=4>sin noticias</td></tr>"
    _pre = prensa or {}

    def _prow(esfera, it):
        s, k, u = (list(it) + ["", 0, ""])[:3]
        cell = ('<a href="%s" target="_blank" rel="noopener" title="ver una pieza de esta fuente">%s</a>' % (u, s)) if u else ("%s" % s)
        return "<tr><td>%s</td><td>%s</td><td class='num'>%s</td></tr>" % (esfera, cell, _n(k))

    _prows = [_prow("Marruecos", it) for it in (_pre.get("mar", []) or [])]
    _prows += [_prow("Internacional / EE.UU.", it) for it in (_pre.get("int", []) or [])]
    _prows.append("<tr><td>China (estatal)</td><td>CGTN / Global Times</td><td class='num'>0</td></tr>")
    _prensa_rows = "".join(_prows)
    _indic_chart = _barchart([(it['lbl'], it['n']) for it in (indic or [])])
    _prensa_chart = _barchart([(s, k) for s, k, _u in ((_pre.get('mar', []) or []) + (_pre.get('int', []) or []))])

    def _samp_rows(lst):
        if not lst:
            return "<tr><td colspan=4>&mdash;</td></tr>"
        out = []
        for _h in lst:
            _u = _h.get("url") or ""
            _lk = ('<a href="%s" target="_blank" rel="noopener">fuente</a>' % _u) if _u else "&mdash;"
            out.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                _fecha(_h["ts"]), _h.get("fuente") or "", (_h.get("titulo") or "")[:160], _lk))
        return "".join(out)

    _mar_samp_rows = _samp_rows(_pre.get("mar_samp", []))
    _evs = (hechos or {}).get("eventos", []) or []
    _epi_rows = []
    for _i, _ev in enumerate(_evs[:25], 1):
        _pubs = _ev.get("pubs") or []
        _links = []
        for _p in _pubs[:16]:
            _pu = _p.get("url") or ""
            _ln = ('<a href="%s" target="_blank" rel="noopener">%s</a>' % (_pu, (_p.get("source") or "enlace")[:44])) if _pu else ((_p.get("source") or "")[:44])
            _links.append("<li>%s</li>" % _ln)
        _eid = "CEU-2026-%03d" % _i
        _rango = _fecha(_ev["desde"]) if _ev.get("desde") == _ev.get("hasta") else (_fecha(_ev["desde"]) + " &rarr; " + _fecha(_ev["hasta"]))
        _pub_txt = ("%d publicaciones · %d titulares" % (_ev.get("n_pubs", 0), _ev.get("n_h", 0))) if _ev.get("n_h", 1) > 1 else "1 publicación"
        _epi_rows.append(
            '<details class="seccion"><summary>%s · %s</summary>'
            '<p><b>Periodo de publicación:</b> %s · <b>%s</b>.</p>'
            '<p><b>Afirmación principal:</b> %s</p>'
            '<p><b>Publicaciones:</b></p><ul>%s</ul>'
            '<p><b>Estado de verificación:</b> <b>no verificado</b> por el observatorio &mdash; '
            'agrupa publicaciones; no confirma el hecho.</p>'
            '<p><b>Explicación alternativa:</b> no evaluada (pendiente de contraste con fuentes primarias).</p>'
            '<p><b>Límites:</b> el número de publicaciones <b>no</b> es el número de hechos.</p>'
            '</details>'
            % (_eid, (_ev.get("titulo") or "")[:90], _rango, _pub_txt,
               (_ev.get("titulo") or "")[:220], "".join(_links)))
    _epi_fichas = "".join(_epi_rows) or '<p class="sub">sin episodios</p>'
    try:
        _cur = json.load(open(CURADOS, encoding="utf-8")).get("episodios", [])
    except Exception as _ec:
        print("[caso-hibridos] curados ilegible:", _ec, file=sys.stderr)
        _cur = []
    _cura_rows = []
    for _c in _cur:
        _ff = "".join("<li>%s</li>" % x for x in (_c.get("fuente") or []))
        _cura_rows.append(
            '<details class="seccion"><summary>%s &middot; %s</summary>'
            '<p><b>Periodo:</b> %s &middot; <b>Tipo:</b> %s</p>'
            '<p><b>Qué se afirma:</b> %s</p>'
            '<p><b>Actores:</b> %s</p>'
            '<p><b>Fuentes (enlaces del corpus):</b></p><ul>%s</ul>'
            '<p><b>Fuente primaria:</b> %s</p>'
            '<p><b>Estado de verificación:</b> %s</p>'
            '<p><b>Explicación alternativa:</b> %s</p>'
            '<p><b>Límites:</b> %s</p>'
            '</details>'
            % (_c.get("id"), (_c.get("titulo") or "")[:90], _c.get("periodo"), _c.get("tipo"),
               _c.get("afirmacion"), _c.get("actores"), _ff, _c.get("fuente_primaria"),
               _c.get("estado_verificacion"), _c.get("explicacion_alternativa"), _c.get("limites")))
    _cura_html = "".join(_cura_rows) or '<p class="sub">sin episodios curados</p>' 
    _hist = list(hist or [])
    _sp = (series or {}).get("pub") or []
    _sh = (series or {}).get("his") or []
    _sdias = (series or {}).get("dias") or []
    _tp, _th = sum(_sp), sum(_sh)
    _ratio = (_tp / _th) if _th else 0
    if _sp:
        _pi = _sp.index(max(_sp))
        _pp = _sp[_pi]; _ph = _sh[_pi] if _pi < len(_sh) else 0; _pd = _sdias[_pi] if _pi < len(_sdias) else "-"
    else:
        _pp = _ph = 0; _pd = "-"
    _respuesta = ("<b>Respuesta (calculada este ciclo):</b> los picos los <b>abren hechos nuevos</b> que luego <b>se reproducen</b>. "
                  "Día punta <b>%s</b>: <b>%d publicaciones</b> de <b>%d historias nuevas</b> (%.1f por historia). "
                  "En la <b>serie de 30 d</b>: %d publicaciones de %d historias (%.1f por historia). "
                  "→ <b>hechos nuevos + difusión</b>, no solo difusión de lo ya conocido.") % (
                  _pd, _pp, _ph, (_pp / _ph if _ph else 0), _tp, _th, _ratio)
    _hist_chart = _barchart([(r.get("fecha", ""), r.get("nucleo", 0)) for r in _hist[-30:]],
                            rowh=18, color="#c1440e")
    _hist_rows = ""
    _prev = None
    for _r in _hist[-30:][::-1]:
        _dd = ""
        if _prev is not None:
            _dif = _r.get("nucleo", 0) - _prev
            _dd = ("%+d" % _dif) if _dif else "="
        _ind = "; ".join("%s: %s" % (k, v) for k, v in (_r.get("indic") or {}).items() if v)
        _hist_rows += ("<tr><td>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
                       "<td class='num'>%s</td><td class='num'>%s</td><td>%s</td></tr>"
                       % (_r.get("fecha", ""), _n(_r.get("nucleo", 0)), _dd, _n(_r.get("autores", 0)),
                          _n(_r.get("clusters", 0)), _n(_r.get("urls_compartidas", 0)), _ind))
        _prev = _r.get("nucleo", 0)
    if not _hist_rows:
        _hist_rows = "<tr><td colspan=7>sin histórico todavía (empieza hoy)</td></tr>"
    from collections import defaultdict as _ddict
    import datetime as _dtm
    _wk = _ddict(list)
    for _r in _hist:
        try:
            _iso = _dtm.date.fromisoformat(_r.get("fecha", ""))
            _y, _w, _wd = _iso.isocalendar()
            _wk["%d-S%02d" % (_y, _w)].append(_r.get("nucleo", 0))
        except Exception as _e:
            print("[caso-hibridos] semana ISO:", _e, file=sys.stderr)
    _wk_rows = "".join("<tr><td>%s</td><td class='num'>%d</td><td class='num'>%d</td><td class='num'>%d</td></tr>"
                       % (k, len(v), sum(v), max(v)) for k, v in sorted(_wk.items(), reverse=True))
    if not _wk_rows:
        _wk_rows = "<tr><td colspan=4>&mdash;</td></tr>"
    _chi_corpus = ", ".join("%s: %s" % (s, _n(k)) for s, k in (_pre.get("chi_corpus") or []))
    if _chi_corpus:
        _chi_note = ("<b>Hueco declarado:</b> medios chinos estatales presentes en el corpus (%s) pero "
                     "<b>0 eventos del tema</b>: no publican sobre Ceuta/Marruecos. La esfera china se muestra "
                     "como <b>ausencia real</b>, no como narrativa.") % _chi_corpus
    else:
        _chi_note = "<b>Hueco declarado:</b> sin medios chinos en el corpus para este foco."

    delta = d["delta_pct"]
    _z = d.get("z_score")
    z_txt = ("+%s" % _z) if (_z is not None and _z >= 0) else ("%s" % _z if _z is not None else "—")
    fo = d.get("fuentes_origen", {})
    fo_html = "".join(
        f"<tr><td>{k}</td><td class='num'>{_n(v)}</td></tr>"
        for k, v in sorted(fo.items(), key=lambda kv: -kv[1]))
    _medios_txt = ", ".join(
        f'<a href="{_medio_link(m)}" target="_blank" rel="noopener">{m}</a> ({c})'
        for m, c in d.get("top_medios", [])) or "—"
    import urllib.parse as _up
    _page = "https://fimi.viajeinteligencia.com/casos/frontera_sur_hibridos/"
    _stxt = (f"Indicadores de presión híbrida en Frontera Sur (Marruecos): "
             f"{d.get('clusters_nucleo', 0)} clusters núcleo · señal, no atribución.")
    _sq = _up.quote
    _sx = f"https://twitter.com/intent/tweet?text={_sq(_stxt)}&url={_sq(_page)}"
    _sm = f"https://mastodon.social/share?text={_sq(_stxt + ' ' + _page)}"
    _sb = f"https://bsky.app/intent/compose?text={_sq(_stxt + ' ' + _page)}"
    _sw = f"https://wa.me/?text={_sq(_stxt + ' ' + _page)}"
    _tot_fo = sum(fo.values()) or 1
    _social_pct = round(100 * fo.get("social", 0) / _tot_fo)
    _agg_pct = round(100 * fo.get("agregador (google-news)", 0) / _tot_fo)
    _prensa_pct = round(100 * (fo.get("española", 0) + fo.get("marroquí", 0)) / _tot_fo)
    _ratio = ("%.1f×" % (d["sem_actual_nucleo"] / d["media8_nucleo"])) if d.get("media8_nucleo") else "—"
    _sum_nuc = sum(d["por_categoria"].get(k, 0)
                   for k in ("drones", "buques_guerra", "hostigamiento", "bloqueo"))
    _sum_ctx = sum(d["por_categoria"].get(k, 0)
                   for k in ("valla_incidente", "postura_oficial", "critica_a_marruecos", "soberania", "maniobras"))
    _pt3 = d.get("pico_top3_pct")
    _pt3_txt = ("%s%%" % _pt3) if _pt3 is not None else "n/d"
    pol = d.get("polaridad", {})
    _pol_tot = sum(pol.values()) or 1
    _hostil_pct = round(100 * pol.get("hostil", 0) / _pol_tot)
    _coop_pct = round(100 * pol.get("cooperación", 0) / _pol_tot)
    _neutro_pct = round(100 * pol.get("neutro", 0) / _pol_tot)
    pol_html = "".join(
        f"<tr><td>{k}</td><td class='num'>{_n(v)}</td><td class='num'>{round(100 * v / _pol_tot)}%</td></tr>"
        for k, v in sorted(pol.items(), key=lambda kv: -kv[1]))
    _h1 = d.get("h1", {})
    _plc = d.get("placebo") or {}
    _h1_txt = ("sin datos." if not _h1 else
               f"r<sub>máx</sub> = {_h1.get('r_max')} (retardo {_h1.get('lag')} d) · "
               f"<b>p = {_h1.get('p')}</b> (permutación, {_h1.get('n_dias')} días) → "
               + ("<b>se sostiene</b> (p&lt;0,05)." if (_h1.get('p') is not None and _h1.get('p') < 0.05)
                  else "<b>NO se sostiene</b> (p≥0,05 en esta ventana)."))
    _plc_txt = ("n/d." if not _plc else
                f"{_plc.get('picos_cerca')}/{_plc.get('de')} picos dentro de ±1 semana de un hito "
                f"(esperado por azar {_plc.get('esperado_azar')}).")
    fichas = d.get("fichas", [])
    fichas_html = "".join(
        f"<tr><td>{f.get('label')}</td><td>{f.get('desde')} → {f.get('hasta')}</td>"
        f"<td class='num'>{_n(f.get('eventos'))}</td><td class='num'>{_n(f.get('autores'))}</td>"
        f"<td>{f.get('fuente')}</td><td>{f.get('polaridad')}</td>"
        f"<td><a href=\"/api/export?cluster={f.get('label')}&amp;fmt=csv\">datos</a></td></tr>"
        for f in fichas[:12])
    _h4 = d.get("h4", {})
    _h4_txt = ("sin datos." if not _h4 else
               f"Última semana: {_n(_h4.get('eventos'))} eventos · <b>{_n(_h4.get('urls'))}</b> URLs · "
               f"{_n(_h4.get('fuentes'))} fuentes · {_n(_h4.get('autores'))} autores · "
               f"ratio ev/URL = <b>{_h4.get('ev_por_url')}</b> · URL top = {_h4.get('top_url_pct')}%.")
    kw_html = "".join(
        f"<tr><td>{lbl}</td><td style='font-size:.82rem'>{' · '.join(w)}</td><td>{g}</td></tr>"
        for k, lbl, w, e, g in CATS)

    def _acct(a):
        a = a or ""
        if a.startswith("bsky:"):
            h = a[5:]
            return f'<a href="https://bsky.app/profile/{h}" target="_blank" rel="noopener">{h}</a>'
        return a

    def _lnk(e):
        u = e.get("url") or ""
        b = e.get("bsky") or ""
        if not u and b.startswith("at://"):
            p = b.split("/")
            if len(p) >= 5:
                u = f"https://bsky.app/profile/{p[2]}/post/{p[-1]}"
        return u

    evid_rows = []
    for e in d.get("evidencia", [])[:40]:
        u = _lnk(e)
        src = f'<a href="{u}" target="_blank" rel="noopener">fuente</a>' if u else "—"
        evid_rows.append(
            f"<tr><td>{_fecha(e['ts'])}</td><td>{_acct(e['author'])}</td>"
            f"<td>{e['title']}</td><td>{src}</td></tr>")
    evid_html = "".join(evid_rows)
    cuentas_txt = " · ".join(f"{_acct(c['author'])} ({c['n']})" for c in d.get("cuentas", [])[:8])
    _lectura = (f"<ul style='margin:6px 0 0 0;padding-left:20px'>"
                f"<li><b>Volumen:</b> {_n(d['nucleo']['eventos'])} eventos de núcleo en el periodo (arriba); "
                f"la <b>última semana</b> ({_n(d['sem_actual_nucleo'])}) es parte de ese total.</li>"
                f"<li><b>Fuentes:</b> <b>{_social_pct}%</b> redes · <b>{_agg_pct}%</b> agregador "
                f"(≈{d.get('medios_indep', 0)} medios) · <b>{_prensa_pct}%</b> prensa directa.</li>"
                f"<li><b>Concentración:</b> top-5 cuentas = <b>{amp.get('top5_pct', 0)}%</b>; solo "
                f"<b>{amp.get('urls_compartidas', 0)}</b> URLs compartidas de {_n(amp.get('urls_distintas', 0))}.</li>"
                f"<li><b>Polaridad</b> (heurística): <b>{_hostil_pct}%</b> hostil · {_coop_pct}% cooperación · "
                f"{_neutro_pct}% neutro.</li>"
                f"<li><b>Lectura:</b> conversación amplia sobre un episodio reciente (fragata en Ceuta) con "
                f"<b>amplificación coordinada NO medida</b> — señal a vigilar, no conclusión.</li></ul>")
    if delta is None:
        delta_html = "<b>—</b><span>vs media 8 sem (núcleo)</span>"
    else:
        sign = "+" if delta >= 0 else ""
        col = "#b91c1c" if delta >= 0 else "#166534"
        delta_html = f"<b style='color:{col}'>{sign}{delta:.0f}%</b><span>vs media 8 sem (núcleo)</span>"

    manual_html = _md(manual_txt)
    try:
        from detection.captacion import captacion_block
        capt = captacion_block(["frontera_sur"])
    except Exception as _e:
        capt = ""
        print("[caso-hibridos] captacion no disponible:", repr(_e))
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Frontera Sur: actividad militar, presión fronteriza y amplificación informativa — Observatorio de amplificación</title>
{_SELPER_HTML}
<meta name="description" content="Observación de publicaciones sobre un núcleo de indicadores (buques, drones, bloqueo, hostigamiento, migración, soberanía) en el entorno de Ceuta, Melilla y Canarias, y su amplificación. Evalúa hipótesis de presión híbrida; no confirma autoría, intención ni operación.">
<meta name="robots" content="index,follow">
<meta property="og:type" content="website">
<meta property="og:title" content="Frontera Sur: actividad militar, presión fronteriza y amplificación informativa">
<meta property="og:description" content="Señales híbridas frente a contexto: clusters, amplificación, polaridad y contraste H1-H4. Señal, no atribución; no confirma una operación híbrida.">
<meta property="og:url" content="https://fimi.viajeinteligencia.com/casos/frontera_sur_hibridos/">
<meta property="og:image" content="https://fimi.viajeinteligencia.com/casos/frontera_sur_hibridos/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="https://fimi.viajeinteligencia.com/casos/frontera_sur_hibridos/og.png">
<style>
:root{{--navy:#0d1b2a;--ink:#1b263b;--mut:#5c6b7a;--line:#dbe2ea;--bg:#f7f9fc;--acc:#c1440e}}
*{{box-sizing:border-box}}body{{margin:0;font:16px/1.6 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}}
header{{background:var(--navy);color:#fff;padding:28px 20px}}
.wrap{{max-width:900px;margin:0 auto;padding:0 20px}}
h1{{font-size:1.5rem;margin:0 0 6px}}h2{{font-size:1.15rem;margin:28px 0 10px;border-left:4px solid var(--acc);padding-left:10px}}
.sub{{color:#c9d6e2;font-size:.95rem}}
p.sub,span.sub,h3.sub,h4.sub,ul.sub,ul.sub li{{color:#475569}}
.aviso{{background:#fff3cd;border:1px solid #ffe08a;border-radius:8px;padding:12px 14px;margin:16px 0;font-size:.94rem}}
.marco{{background:#eef4fb;border-left:4px solid var(--navy);border-radius:8px;padding:12px 14px;margin:16px 0;font-size:.93rem}}
.lectura{{background:#0d1b2a;color:#fff;border-radius:8px;padding:14px 16px;margin:16px 0}}
.lectura .sub{{color:#c1cfe0;font-size:.85rem}}
.topnav{{background:#08111c;font-size:.9rem}}
.topnav .wrap{{display:flex;flex-wrap:wrap;gap:14px;padding:8px 20px}}
.topnav a{{color:#c1cfe0;text-decoration:none}}.topnav a:hover{{color:#fff}}
.share{{margin-left:auto}}.share summary{{cursor:pointer;color:#c1cfe0}}.share summary:hover{{color:#fff}}
.shpanel{{display:flex;flex-wrap:wrap;gap:10px;padding:8px 0}}
details.seccion{{border:1px solid var(--line);border-radius:8px;padding:6px 14px;margin:16px 0;background:#fff}}
details.seccion>summary{{cursor:pointer;font-weight:700;color:var(--navy);padding:8px 0;font-size:1.05rem}}
details.seccion>summary::marker{{color:var(--acc)}}
.kpis{{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}}
.kpi{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 16px;min-width:130px}}
.kpi b{{display:block;font-size:1.5rem;color:var(--navy)}}
.kpi span{{font-size:.82rem;color:var(--mut)}}
table{{border-collapse:collapse;width:100%;background:#fff;border:1px solid var(--line);border-radius:8px;overflow:hidden;margin-bottom:8px}}
th,td{{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);font-size:.94rem}}
th{{background:#eef2f7}}td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums}}
.contexto th{{background:#f1f5f9}}.contexto td{{color:#64748b}}
footer{{color:var(--mut);font-size:.85rem;padding:24px 0;border-top:1px solid var(--line);margin-top:28px}}
code{{background:#eef2f7;padding:1px 5px;border-radius:4px;font-size:.85rem}}
</style></head><body>
<nav class="topnav"><div class="wrap">
<a href="/">&larr; Radar</a>
<a href="/casos/ceuta/">Ceuta</a>
<a href="/casos/electoral/">Electoral 2026</a>
<a href="/consulta.html">Consulta</a>
<a href="/api.html">API</a>
<a href="/metodo.html">Método</a>
<a href="datos.csv" download>&#11015; CSV</a>
<details class="share"><summary>Compartir ▾</summary><div class="shpanel">
<a href="{_sx}" target="_blank" rel="noopener">X</a>
<a href="{_sm}" target="_blank" rel="noopener">Mastodon</a>
<a href="{_sb}" target="_blank" rel="noopener">Bluesky</a>
<a href="{_sw}" target="_blank" rel="noopener">WhatsApp</a>
<a href="#" onclick="navigator.clipboard.writeText('{_page}');return false">Copiar enlace</a>
</div></details>
</div></nav>
<header><div class="wrap">
<h1>Frontera Sur: actividad militar, presión fronteriza y amplificación informativa</h1>
<div class="sub">Evaluación de <b>hipótesis</b> de presión híbrida (entorno España–Marruecos). <b>Sin atribución confirmada.</b></div>
<div class="sub">Subcaso del tema <b>Frontera Sur</b> — Observatorio de amplificacion · dato {meta['generado_utc']}</div>
</div></header>
<main class="wrap">
<div style="background:#fff;border:1px solid var(--line);border-radius:10px;padding:16px;margin:16px 0">
<h2 style="margin-top:0">Resumen ejecutivo</h2>
<p><b>Qué es.</b> Observación de <b>publicaciones</b> sobre un núcleo de indicadores (buques, drones, bloqueo, hostigamiento, migración, soberanía…) en el entorno de <b>Ceuta, Melilla y Canarias</b>, y de su <b>amplificación</b>. Marco: <b>guerra/conflicto híbrido</b> (OTAN). <b>Periodo:</b> {(d.get("periodo") or dict()).get("desde","")} &rarr; {(d.get("periodo") or dict()).get("hasta","")}.</p><p><b>Qué mide cada cifra.</b> Todo el catálogo son <b>publicaciones que mencionan</b> un término (<b>no</b> acciones verificadas): una mención de «fragata» no es una incursión; una mención de «bulo» no es un bulo confirmado. La verificación de los hechos <b>no</b> la hace este observatorio.</p>
<p><b>Tres escenarios, el mismo pico.</b> Un pico de publicaciones puede venir de (1) un <b>acontecimiento real</b> con mucha cobertura; (2) <b>narrativas que circulan y se amplifican</b> sin coordinación demostrada; o (3) <b>coordinación</b> con indicios verificables. El volumen solo no los distingue: <b>los distingue la evidencia</b>. Esta página mide (1)/(2) y busca (3) sin afirmarlo.</p>
<p><b>Qué NO dice.</b> No confirma un plan, ni autoría, ni intención. Los hechos del catálogo están <b>publicados</b>, no verificados por este observatorio.</p>
<table><thead><tr><th>Dimensión</th><th>Estado</th></tr></thead><tbody>
<tr><td>Actividad informativa</td><td>Elevada &mdash; <b>línea base no comparable</b> (la captura creció ~100&times;)</td></tr>
<tr><td>Calidad de la evidencia</td><td><b>Parcial</b>: muchas noticias con fuente, sin verificación propia</td></tr>
<tr><td>Coordinación informativa</td><td><b>No observada</b> ({_n(amp.get("urls_compartidas", 0))} URLs compartidas entre autores)</td></tr>
<tr><td>Hipótesis de plan híbrido</td><td><b>En evaluación</b> (evidencia a favor y en contra)</td></tr>
</tbody></table>
<div style="background:#0d1b2a;color:#fff;border-radius:8px;padding:10px 14px;margin:12px 0;font-weight:700;letter-spacing:.2px">Señal detectada &middot; Coordinación <u>no demostrada</u> &middot; Atribución <u>no confirmada</u></div>
<p class="sub"><b>Líneas de esfuerzo (doctrina híbrida):</b></p>
<ul class="sub" style="margin:6px 0 0 0;padding-left:20px">
<li><b>L1</b> coerción militar (buques, drones, bloqueo naval/aéreo)</li>
<li><b>L2</b> presión energética</li>
<li><b>L3</b> guerra informativa / desinformación</li>
<li><b>L4</b> presión diplomática / jurídica (soberanía, no reconocer cadáveres)</li>
<li><b>L5</b> migración como arma</li>
<li><b>L6</b> alineamientos exteriores y tecnología</li>
<li><b>L7</b> societal / demográfico (asentamiento, empadronamiento, nacionalidad, natalidad, matrimonios) + ambigüedad</li>
</ul>
<p class="sub"><b>Nota de encuadre (L7):</b> las dimensiones <b>demográfico-societales</b> se muestran como <b>narrativa observada</b> (lo que circula, con su volumen y fuentes) y como <b>hipótesis a evaluar</b>; <b>no</b> se afirman como táctica verificada por este observatorio.</p>
</div>
<div class="marco" style="background:#eef4fb"><p><b>Cómo se actualiza esta página.</b> Se <b>recalcula cada 6 h</b> (ciclo del radar `30 */6`): el paso 3g relee la BD (<code>event_temas</code> del tema <b>frontera_sur</b>) y recomputa todo. Los datos que la captura ingiere <b>a diario</b> se <b>suman</b> al periodo del caso (30-jul-2026 → hoy): por eso el <b>núcleo, el catálogo y los episodios crecen</b> con las publicaciones nuevas. Además, se guarda <b>un registro diario</b> (histórico) → la sección «Evolución» gana una fila/día. No hay edición manual: lo que ves es el último ciclo.</p></div>
<div class="aviso"><b>Senal, no atribucion.</b> Mide <b>actividad observada</b> (volumen, fuentes, dinamica) en fuentes abiertas. NO atribuye autoria, intencion ni confirma campana. Un volumen alto no equivale a coordinacion confirmada. <br><b>Nota de comparabilidad:</b> el volumen de captura del radar ha crecido mucho durante el periodo, asi que la linea base semanal no es comparable &mdash; por eso esta pagina <b>no publica un % de subida semanal</b>.</div>

<div class="marco">
<p><b>Marco de referencia (OTAN).</b> <em>&ldquo;Hybrid threats combine military and non-military as well as covert and overt means, including disinformation, cyber attacks, economic pressure, deployment of irregular armed groups and use of regular forces.&rdquo;</em> &mdash; OTAN, <a href="https://www.nato.int/cps/en/natohq/topics_156338.htm">&laquo;What are the hybrid threats NATO faces?&raquo;</a> (actualizado 29-ene-2026).</p>
<p><em>Traducci&oacute;n libre:</em> &laquo;Las amenazas h&iacute;bridas combinan medios militares y no militares, as&iacute; como encubiertos y abiertos, incluidos la desinformaci&oacute;n, los ciberataques, la presi&oacute;n econ&oacute;mica, el despliegue de grupos armados irregulares y el uso de fuerzas regulares.&raquo;</p>
<p><b>Declaraci&oacute;n de la Cumbre de Bruselas (2018), &sect;21.</b> <em>&ldquo;Our nations have come under increasing challenge from both state and non-state actors who use hybrid activities that aim to create ambiguity and blur the lines between peace, crisis, and conflict. While the primary responsibility for responding to hybrid threats rests with the targeted nation, NATO is ready, upon Council decision, to assist an Ally at any stage of a hybrid campaign. In cases of hybrid warfare, the Council could decide to invoke Article 5 of the Washington Treaty, as in the case of armed attack. &hellip;&rdquo;</em> <em>[contin&uacute;a]</em> &hellip;We announce the establishment of Counter Hybrid Support Teams&hellip;</p>
<p><em>Traducci&oacute;n libre (inicio):</em> &laquo;Nuestras naciones se enfrentan a un desaf&iacute;o creciente de actores estatales y no estatales que usan actividades h&iacute;bridas destinadas a crear ambig&uuml;edad y difuminar las l&iacute;neas entre paz, crisis y conflicto.&raquo; El resto detalla que la responsabilidad primaria es del pa&iacute;s objetivo, que la OTAN puede asistir por decisi&oacute;n del Consejo &mdash;incluido el art&iacute;culo 5&mdash; y que se crean los <i>Counter Hybrid Support Teams</i>.</p>
<p class="sub">Cita: OTAN (2018). <i>Brussels Summit Declaration</i>, PR/CP(2018)074, 11 de julio de 2018, p&aacute;rr. 21. <a href="https://www.nato.int/en/about-us/official-texts-and-resources/official-texts/2018/07/11/brussels-summit-declaration">nato.int (HTML)</a> (consultado el 15-oct-2026).</p>
</div>

<div class="lectura">
<p><b>Lectura de la semana.</b> {_lectura}</p>
<p class="sub">Cuota núcleo/(núcleo+contexto): <b>{d.get('cuota_pct', 0)}%</b> · Dependencia del pico (top-3 autores de la última semana): <b>{_pt3_txt}</b> · Medios distintos en el núcleo (google-news resuelto al medio): <b>{d.get('medios_indep', 0)}</b>.</p>
</div>

<div class="selper" style="margin:10px 0"><b>Periodo:</b> <button onclick="selP(0)" class="spb spb-on">30 d</button> <button onclick="selP(1)" class="spb">90 d</button> <button onclick="selP(2)" class="spb">Todo el caso</button> <span class="sub" id="perNota">(30 días)</span></div>
<h2>Catálogo de acciones observadas (L1&ndash;L7)</h2>
<p class="sub">Todas las cifras son <b>publicaciones del tema que mencionan</b> el término (pueden solaparse). <b>No</b> son acciones verificadas: son <b>menciones</b>. Niveles: <b>mención</b> (esta tabla) → <b>afirmación publicada</b> (una fuente lo sostiene) → <b>hecho corroborado</b> (varias fuentes independientes) → <b>interpretación</b> (hipótesis). Esta tabla solo muestra el primero.<br><b>Ámbito:</b> cifras del <b>tema (90 d)</b>. El bloque «<b>Radar B</b>» cuenta el <b>núcleo</b> (subconjunto estricto con ancla geográfica): por eso algunas cifras difieren (p. ej. <i>drones</i>). Cada tabla declara su ámbito.</p>
{_indic_chart}
<details class="seccion"><summary>Ver tabla completa &middot; clic para abrir</summary>
<table><thead><tr><th>Indicador</th><th>Línea</th><th>Nivel</th><th class="num">Publicaciones</th></tr></thead><tbody>{_indic_rows}</tbody></table>
</details>

<h2>Evolución diaria · publicaciones vs acontecimientos nuevos</h2>
<p class="sub">Barras = <b>publicaciones/día</b> del núcleo; línea = <b>historias NUEVAS/día</b> (primera vez que aparece un titular). Sirve para ver si un pico son <b>hechos nuevos</b> o <b>difusión de lo ya conocido</b>.</p>
{_svg_doble(series)}

<h2>Radar A · Episodios informativos <span class="sub">(publicaciones agrupadas; no verificadas)</span></h2>
<p class="sub"><b>{_hechos_n}</b> episodios en <b>{_hechos_pub}</b> publicaciones de <b>{_hechos_med}</b> medios. Un <b>evento</b> agrupa titulares del <b>mismo acontecimiento</b> (entidades compartidas): <b>{_hechos_pub} publicaciones ≠ {_hechos_n} historias ≠ {_n_eventos} eventos</b>. <b>La agrupación es automática y aproximada</b> (heurística de texto): puede unir titulares de un mismo tema o no unir variantes; es <b>revisable</b> y no altera los recuentos de origen (en el CSV). Clic en cada ficha para ver <b>fuentes, estado de verificación, explicación alternativa y límites</b>. (Tabla completa en el CSV.)</p>
{_epi_fichas}

<h2>Episodios clave <span class="sub">(curados a mano)</span></h2>
<p class="sub">5 episodios revisados a mano: <b>qué se afirma, con qué fuente, estado de verificación, explicación alternativa y límites</b>. Cuando la <b>fuente primaria</b> (comunicado oficial) no está localizada, se dice.</p>
{_cura_html}

<h2>Prensa marroquí y extranjera (L3)</h2>
<p class="sub">Qué publica cada esfera. En un régimen donde el rey concentra el poder, los medios marroquíes estatales o afines son parte del aparato informativo. Se muestran con su <b>volumen real</b>; donde no hay datos, se dice.</p>
{_prensa_chart}
<details class="seccion"><summary>Ver tabla completa &middot; clic para abrir</summary>
<table><thead><tr><th>Esfera</th><th>Medio</th><th class="num">Eventos</th></tr></thead><tbody>{_prensa_rows}</tbody></table>
</details>
<p class="sub">{_chi_note}</p>
<p class="sub"><b>Hueco EE.UU.:</b> el radar no captura diarios estadounidenses (The New York Times, The Washington Post, WSJ, NPR) en este tema; lo que llega de EE.UU. va agregado dentro de Google News. Se dice, no se inventa.</p>

<h2>Radar B · Conversación <span class="sub">(núcleo)</span></h2>
<div class="kpis">
<div class="kpi"><b>{_n(d['nucleo']['eventos'])}</b><span>eventos nucleo (periodo)</span></div>
<div class="kpi"><b>{_n(d['clusters_nucleo'])}</b><span>clusters nucleo</span></div>
<div class="kpi"><b>{_n(d['nucleo']['autores'])}</b><span>autores nucleo</span></div>
<div class="kpi"><b>{_n(amp.get('urls_compartidas', 0))}</b><span>URLs compartidas (&ge;2 autores)</span></div>
</div>
<p class="sub">Cronografía: eventos de <b>núcleo</b> por semana (últ. semana {_n(d['sem_actual_nucleo'])}); líneas = <b>hitos derivados del propio corpus</b> (primera aparición del término; <b>no</b> son externos):</p>
{_timeline(d['serie_semanal_nucleo'], d.get('now_ts', 0), d.get('hitos', []))}
<table><thead><tr><th>Categoría (núcleo, con ancla geográfica)</th><th class="num">Publicaciones (núcleo)</th></tr></thead>
<tbody>{tbl('nucleo')}</tbody></table>
<p class="sub">Suma de categorías {_n(_sum_nuc)} (con solapes; un evento puede caer en dos) → <b>unión {_n(d['nucleo']['eventos'])}</b>.</p>

<h2>Amplificación (núcleo)</h2>
<div class="kpis">
<div class="kpi"><b>{amp.get('top10_pct', 0)}%</b><span>top-10 autores</span></div>
<div class="kpi"><b>{amp.get('top5_pct', 0)}%</b><span>top-5 autores</span></div>
<div class="kpi"><b>{amp.get('gini', 0)}</b><span>Gini autores</span></div>
<div class="kpi"><b>{_n(amp.get('urls_compartidas', 0))}</b><span>URLs compartidas (≥2 autores)</span></div>
</div>
<p class="sub">{_n(amp.get('autores_distintos', 0))} autores distintos · {_n(amp.get('urls_distintas', 0))} URLs distintas. Lectura: <b>top-5 alto / Gini alto</b> o <b>many URLs compartidas</b> → amplificación concentrada; valores bajos → discusión repartida (sin amplificación). Medido en el núcleo, no en el contexto.</p>

<h2>Tono del mensaje (heurística) — no mide hostilidad del hecho</h2>
<table><thead><tr><th>Polaridad</th><th class="num">Eventos</th><th class="num">%</th></tr></thead>
<tbody>{pol_html}</tbody></table>
<p class="sub"><b>Aviso:</b> mide <b>vocabulario del texto</b>, no hostilidad del hecho: un titular que dice «incursión» y otro que dice «patrullaje ordinario» pueden describir el mismo episodio. Patrones: <b>hostil</b> = violación / incursión / intrusión / amenaza / hostigamiento / bloqueo / dron-fragata-buque marroquí…; <b>cooperación</b> = conjuntas / entrega / Navantia / acuerdo…; resto = <b>neutro</b>. <b>Validación manual: 158/165 = 96 %</b> sobre una muestra de 165 eventos (14-oct-2026); esta tabla clasifica <b>{_pol_tot}</b> eventos (el denominador no coincide porque cambia la ventana). Separa la cooperación militar y el comercio de defensa de la presión hostil.</p>
<details class="seccion"><summary>Ficha de validación del clasificador de tono</summary>
<ul><li><b>Qué se validó:</b> la etiqueta de <b>tono</b> (hostil/neutro/cooperación), no la relevancia temática ni la veracidad.</li>
<li><b>Muestra:</b> 165 eventos; <b>fecha:</b> 14-oct-2026. Selección: núcleo de entonces (cambia con la ventana → el denominador de la tabla difiere).</li>
<li><b>Criterio:</b> concordancia entre la etiqueta automática (palabras clave) y el juicio del revisor.</li>
<li><b>Concordancia:</b> 158/165 = 96 %. <b>Errores típicos:</b> titulares que citan la acusación de otro (no la sostienen) y negaciones.</li>
<li><b>Límite:</b> es <b>precisión de clasificación de texto</b>, no una medida de amenaza. Requiere validación periódica y por categoría.</li></ul>
</details>

<h2>Contraste de hipótesis (H1–H4)</h2>
<table>
<thead><tr><th>Hipótesis</th><th>Evidencia a favor</th><th>Evidencia en contra</th><th>Estado</th></tr></thead>
<tbody>
<tr><td><b>HC</b> · las acciones responden a un <b>plan de presión híbrida</b> sobre Ceuta/Melilla/Canarias (¿anexión?, inferencia)</td><td>Coincidencia temporal (buques + drones + cobertura); <b>Navantia entrega una patrullera "sin pompa" en plena crisis</b>; F-35/EE.UU., Israel (24 % del armamento), EDGE/Emiratos en el periodo</td><td><b>Sin coordinación medida</b> por URLs; deltas contaminados por la captura; existe <b>cooperación</b> real (ejercicios, comercio); «anexión» no es texto literal (27)</td><td><b>En evaluación</b></td></tr>
<tr><td><b>H1</b> · drones suben tras eventos migratorios <a href="#metodo-h" class="sub">(cómo se calcula ↓)</a></td><td>{_h1_txt}</td><td>Permutación simple → p optimista (autocorrelación)</td><td><b>En evaluación</b></td></tr>
<tr><td><b>H2</b> · los picos coinciden con hitos <a href="#metodo-h" class="sub">(cómo se calcula ↓)</a></td><td>{_plc_txt}</td><td>«Hitos» <b>derivados</b> del corpus → circular</td><td><b>Inconclusa</b></td></tr>
<tr><td><b>H3a</b> · amplificación coordinada por <b>URLs idénticas</b></td><td>&mdash;</td><td>{amp.get('urls_compartidas', 0)} URLs compartidas por ≥2 autores (de {_n(amp.get('urls_distintas', 0))})</td><td><b>Sin evidencia</b></td></tr>
<tr><td><b>H4</b> · el incremento responde a cambios de cobertura</td><td>{_h4_txt}</td><td>Captura global creció mucho en el periodo</td><td><b>Sesgo probable</b></td></tr>
</tbody></table>
<p class="sub">H1 con <b>permutación</b> (500 barajados) para no fingir precisión con pocos datos; H2 con <b>placebo</b> (¿los picos caen cerca de hitos más que por azar?). Resultado <b>no resuelto ≠ descartado</b>.</p>
<details class="seccion" id="metodo-h"><summary>Método de H1 y H2 (auditable)</summary>
<ul><li><b>H1 · variables:</b> <i>drones</i> = publicaciones del núcleo que mencionan «dron»; <i>migratorio</i> = eventos de contexto (valla/incidentes). Ambas series <b>diarias</b>. Se prueban retardos 0–14 d y se informa el máximo; el nulo (500 permutaciones) <b>también</b> maximiza sobre retardos.</li>
<li><b>H1 · límites:</b> la permutación simple <b>no corrige la autocorrelación</b> → p optimista; correlación ≠ causalidad (puede haber causa común o eco mediático).</li>
<li><b>H2 · método:</b> «hitos» = <b>primera aparición</b> del término en el corpus (valla, ejercicios, Navantia). <b>No son externos</b> → prueba <b>circular</b>; debe repetirse con hitos fechados por fuente externa.</li>
<li><b>Estado:</b> H1 <b>en evaluación</b>; H2 <b>inconclusa</b>; H3a <b>sin evidencia</b> (URLs idénticas); H4 <b>sesgo probable</b> (captura).</li></ul>
</details>

<h2>Fichas de clúster (núcleo)</h2>
<table><thead><tr><th>Clúster</th><th>Ventana</th><th class="num">Eventos</th><th class="num">Autores</th><th>Origen dominante</th><th>Polaridad</th><th>Datos</th></tr></thead>
<tbody>{fichas_html or '<tr><td colspan=6>sin clusters</td></tr>'}</tbody></table>
<p class="sub">Cada clúster con su ventana, tamaño, autores, origen y polaridad <b>dominantes</b> (heurística). Convierte el número en narrativa.</p>

<h2>Por qué estas categorías son el núcleo</h2>
<p>Mapeo de cada categoría de <b>núcleo</b> a un <b>medio</b> de la definición de la OTAN (arriba):</p>
<table><thead><tr><th>Categoría (núcleo)</th><th>Medio (definición OTAN)</th></tr></thead>
<tbody>
<tr><td>Buques de guerra</td><td>medio militar &mdash; &laquo;use of regular forces&raquo;</td></tr>
<tr><td>Drones</td><td>medio militar / tecnológico</td></tr>
<tr><td>Bloqueo aéreo / marítimo</td><td>coerción &mdash; &laquo;economic pressure&raquo; / presión no militar</td></tr>
<tr><td>Hostigamiento</td><td>presión sobre la población &mdash; &laquo;sow doubt&raquo; / presión</td></tr>
</tbody></table>
<p class="sub">Las categorías de <b>contexto</b> (salto a la valla, postura oficial, crítica internacional, soberanía) son <b>trasfondo migratorio/diplomático</b>: no corresponden a un «medio» de la definición, por eso van aparte y no cuentan como señal de presión híbrida.</p>

<h2>Fuentes (núcleo) por origen</h2>
<table><thead><tr><th>Origen</th><th class="num">Eventos</th></tr></thead>
<tbody>{fo_html}</tbody></table>
<p class="sub">Separadas por origen para no mezclar sesgos opuestos (prensa española vs marroquí vs argelina, agencias, red social).</p>
<p class="sub">Medios concretos del núcleo (google-news resuelto al medio original): {_medios_txt}.</p>

<h2>Contexto (no hibrido)</h2>
<p class="sub">Se muestra aparte para no inflar el nucleo: {_n(d['contexto']['eventos'])} eventos de contexto no se cuentan como senal hibrida.</p>
<table class="contexto"><thead><tr><th>Categoria (contexto)</th><th class="num">Eventos</th></tr></thead>
<tbody>{tbl('contexto')}</tbody></table>
<p class="sub">Suma de categorías {_n(_sum_ctx)} (con solapes) → <b>unión {_n(d['contexto']['eventos'])}</b>.</p>

<details class="seccion" open><summary>Qué se observa (análisis V1)</summary>
{manual_html}
</details>

<details class="seccion"><summary>Evidencia abierta · eventos del núcleo (enlace a la fuente)</summary>
<table><thead><tr><th>Fecha</th><th>Cuenta</th><th>Titular</th><th>Fuente</th></tr></thead><tbody>{evid_html or '<tr><td colspan=4>sin eventos</td></tr>'}</tbody></table>
<p class="sub">Cada fila enlaza al <b>post o noticia original</b> (o al perfil en Bluesky). Top cuentas del núcleo: {cuentas_txt}.</p>
</details>

<details class="seccion"><summary>Metodología · categorías y keywords</summary>
<table><thead><tr><th>Categoría</th><th>Keywords</th><th>Grupo</th></tr></thead><tbody>{kw_html}</tbody></table>
<p class="sub">Núcleo = indicadores híbridos (exige <b>ancla geográfica</b>: {' · '.join(ANCLAS[:10])}…); contexto = trasfondo migratorio/diplomático. Fuentes: prensa ES/MA/AR/FR, agencias, Bluesky, Google News. <a href="datos.csv" download>Descargar CSV ↩</a></p>
</details>

<h2>Evolución · diario / semanal / histórico</h2>
<p class="sub">Se guarda <b>un registro por día</b> (se conserva todo). <b>Diario</b> = cada jornada; <b>semanal</b> = agregado por semana ISO; <b>histórico</b> = la serie completa; <b>revisión</b> = Δ frente al día anterior. Comparación entre fechas, en la tabla. Serie descargable: <a href="/api/v1/caso/frontera_sur_hibridos/historial">JSON</a> · <a href="/api/v1/caso/frontera_sur_hibridos/historial.csv">CSV</a>.</p>
<p style="background:#eef4fb;border-left:4px solid #0d1b2a;border-radius:8px;padding:10px 14px;margin:10px 0"><b>Pregunta guía:</b> ¿los picos reflejan <b>acontecimientos nuevos</b> o, sobre todo, <b>mayor difusión de lo ya conocido</b>?<br>{_respuesta}</p>
{_hist_chart}
<details class="seccion" open><summary>Diario (revisión: Δ vs día anterior)</summary>
<table><thead><tr><th>Fecha</th><th class="num">Núcleo</th><th class="num">Δ</th><th class="num">Autores</th><th class="num">Clústeres</th><th class="num">URLs comp.</th><th>Indicadores (n)</th></tr></thead><tbody>{_hist_rows}</tbody></table>
</details>
<details class="seccion"><summary>Semanal (agregado ISO)</summary>
<table><thead><tr><th>Semana</th><th class="num">Días</th><th class="num">Σ núcleo</th><th class="num">Máx/día</th></tr></thead><tbody>{_wk_rows}</tbody></table>
</details>

<h2>Como leerlo</h2>
<ul>
<li>El <b>nucleo</b> son los indicadores hibridos; el <b>contexto</b> (valla, postura, critica, soberania) es trasfondo y va aparte.</li>
<li>El <b>delta</b> compara la ultima semana con la media de las 8 anteriores (linea base), sobre eventos de nucleo.</li>
<li>Las categorias se solapan dentro de cada grupo; el conteo de cada una es independiente.</li>
<li>Fuentes: prensa espanola/marroqui/argelina, agencias internacionales y Bluesky.</li>
</ul>
{capt}
</main>
<footer><div class="wrap">
<p><a href="/">&larr; Volver al radar</a> · <a href="/casos/ceuta/">Caso Ceuta</a> · <a href="/consulta.html">Consulta</a></p>
Generado automaticamente por <code>detection/caso_hibridos_frontera.py</code> ·
manual hash <code>{meta['hash_manual'][:16]}</code> ·
Fuente: <code>event_temas</code> + <code>cluster_events</code> (tema frontera_sur) · no toca scoring.
</div></footer>
</body></html>
"""


def _write_csv(con, ids, path):
    import csv
    nuc = set(ids.get("nucleo", []))
    allids = sorted(nuc | set(ids.get("contexto", [])))
    if not allids:
        return
    ch = ",".join("?" * len(allids))
    data = {r[0]: r for r in con.execute(
        f"SELECT id, timestamp, source, title, text, url, author FROM events WHERE id IN ({ch})", allids)}
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "grupo", "origen", "polaridad", "fecha", "fuente", "autor",
                    "url", "titular"])
        for eid in allids:
            r = data.get(eid)
            if not r:
                continue
            _i, ts, src, tit, txt, url, aut = r
            fecha = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d") if ts else ""
            w.writerow([eid, "nucleo" if eid in nuc else "contexto", _origen(src),
                        _polaridad(txt, tit), fecha, src or "", (aut or "")[:60],
                        url or "", (tit or "").replace("\n", " ")[:160]])
    print("[caso-hibridos] CSV ->", path)


def main():
    if not os.path.exists(DB):
        print("[caso-hibridos] BD no encontrada:", DB)
        return 1
    d = compute()
    _ids0 = d.get("_ids", {}).get("nucleo", [])
    hechos = compute_hechos(_ids0)
    series = compute_series(_ids0, hechos)
    prensa = compute_prensa(TEMA)
    indic = compute_indicadores(TEMA)
    periodos = compute_periodos(_ids0, d.get("now_ts") or 0)
    hist = snapshot(d, indic)
    ids = d.pop("_ids", {})
    manual_txt = open(MANUAL, encoding="utf-8").read() if os.path.exists(MANUAL) else ""
    import hashlib
    hash_manual = hashlib.sha256(manual_txt.encode()).hexdigest()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    frozen = None
    if os.path.exists(JSON_OUT):
        try:
            frozen = json.load(open(JSON_OUT, encoding="utf-8")).get("frozen")
        except Exception:
            frozen = None
    if frozen is None:
        frozen = {"tipo": "subcaso_tematico", "version": "V1", "congelado_utc": "2026-10-14",
                  "nota": "Subcaso tematico. Bloque 'live' se recalcula cada ciclo.", "manual_sha256": hash_manual}
    else:
        frozen["manual_sha256"] = hash_manual  # el manual es la narrativa; mantiene el hash al dia
    d["catalogo"] = indic
    d["prensa"] = {k: v for k, v in (prensa or {}).items() if k != "mar_samp"}
    doc = {"caso": "frontera_sur_hibridos",
           "url": "https://fimi.viajeinteligencia.com/casos/frontera_sur_hibridos/",
           "meta": {"generado_utc": now, "frozen_version": frozen.get("version", "V1"),
                    "aviso": "Senal, no atribucion. 'live' se recalcula cada ciclo."},
           "frozen": frozen, "live": d}
    _dlt = ("+%.0f%%" % d["delta_pct"]) if d.get("delta_pct") is not None else "—"
    _txt = (f"Indicadores de presión híbrida en Frontera Sur (Marruecos): "
            f"{d['clusters_nucleo']} clusters núcleo · {d['nucleo']['eventos']} eventos · "
            f"{_dlt} vs media 8 sem (top-5 {d['amplificacion'].get('top5_pct', 0)}% autores). "
            f"Señal, no atribución.")
    _url = doc["url"]
    doc["social"] = {
        "titulo": "Indicadores de presión híbrida · Frontera Sur (Marruecos)",
        "mastodon": _txt + " " + _url,
        "bluesky": _txt + " " + _url,
        "x": (f"Presión híbrida en Frontera Sur (Marruecos): {d['clusters_nucleo']} clusters "
              f"núcleo, {d['nucleo']['eventos']} eventos, {_dlt} vs 8 sem. Señal, no atribución. {_url}"),
    }
    os.makedirs(os.path.dirname(JSON_OUT), exist_ok=True)
    json.dump(doc, open(JSON_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("[caso-hibridos] JSON ->", JSON_OUT)
    # JSON publico (citable / API / periodistas): /datos/casos/frontera_sur_hibridos.json
    pub = "/var/www/fimi/datos/casos/frontera_sur_hibridos.json"
    try:
        os.makedirs(os.path.dirname(pub), exist_ok=True)
        json.dump(doc, open(pub, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("[caso-hibridos] JSON publico ->", pub)
    except OSError as _e:
        print("[caso-hibridos] no pude escribir el JSON publico:", _e)

    os.makedirs(HTML_DIR, exist_ok=True)
    open(HTML_OUT, "w", encoding="utf-8").write(
        build_html(manual_txt, d, hechos, prensa, indic, hist, series, periodos, {"generado_utc": now, "hash_manual": hash_manual}))
    print("[caso-hibridos] HTML ->", HTML_OUT)
    _c = sqlite3.connect(DB)
    _write_csv(_c, ids, os.path.join(HTML_DIR, "datos.csv"))
    _c.close()
    print(f"[caso-hibridos] nucleo: {d['nucleo']['eventos']} ev · {d['clusters_nucleo']} clusters · "
          f"delta {d['delta_pct']}% · contexto {d['contexto']['eventos']} ev")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
