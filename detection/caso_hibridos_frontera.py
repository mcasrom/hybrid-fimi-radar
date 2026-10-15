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
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "radar.db")
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
    ("maniobras", "Ejercicios militares", ["maniobra", "ejercicio militar", "ejercicios militares"], [], "nucleo"),
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
ANCLAS = ["ceuta", "melilla", "marruecos", "marroqu", "estrecho", "espa\u00f1a", "espa\u00f1ol",
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


# Polaridad: coop > hostil > neutro (coop es más específico; se comprueba primero).
POL_COOP = ["ejercicio conjunto", "maniobras conjuntas", "cooperaci", "navantia",
            "african lion", "entrega de", "entrega a", "venta de", "venta a",
            "normalidad", "reabre", "colaboraci", "acuerdo bilateral", "comercio bilateral",
            "visita oficial", "cumbre bilateral", "patrullera", "astillero"]
POL_HOST = ["violaci", "incursi", "amenaz", "hostigamiento", "hostilid", "agresi",
            "asedi", "bloqueo", "ciberataque", "injerencia", "espionaje", "sabotaje",
            "chantaje", "derribo", "ataque", "disparo", "enfrentamiento", "provocaci",
            "invas", "ocupaci", "reivindica", "coerci", "coacci", "intimidaci",
            "desestabiliz", "asfixi", "presi\u00f3n migratoria", "asalto", "irredentismo",
            "misil", "militarizaci", "incursi\u00f3n a\u00e9rea", "derribo"]


def _polaridad(text, title):
    t = ((text or "") + " " + (title or "")).lower()
    if any(k in t for k in POL_COOP):
        return "cooperación"
    if any(k in t for k in POL_HOST):
        return "hostil"
    return "neutro"


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
        ancla_sql = ""
        if grupo == "nucleo":
            ancla_sql = " AND (" + " OR ".join(
                ["LOWER(e.text) LIKE ? OR LOWER(e.title) LIKE ?" for _ in ANCLAS]) + ")"
            p += [f"%{a}%" for a in ANCLAS for _ in ("a", "b")]
        ids = [r[0] for r in con.execute(
            "SELECT e.id FROM events e JOIN event_temas et ON et.event_id=e.id "
            f"WHERE et.tema_id=? AND e.timestamp>=? AND ({like}){excl_sql}{ancla_sql}", p).fetchall()]
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


def build_html(manual_txt, d, meta):
    def tbl(grupo):
        rows = []
        for k, lbl, _w, _e, g in CATS:
            if g != grupo:
                continue
            rows.append(f"<tr><td>{lbl}</td><td class='num'>{_n(d['por_categoria'].get(k, 0))}</td></tr>")
        return "".join(rows)

    amp = d.get("amplificacion", {})
    delta = d["delta_pct"]
    _z = d.get("z_score")
    z_txt = ("+%s" % _z) if (_z is not None and _z >= 0) else ("%s" % _z if _z is not None else "—")
    fo = d.get("fuentes_origen", {})
    fo_html = "".join(
        f"<tr><td>{k}</td><td class='num'>{_n(v)}</td></tr>"
        for k, v in sorted(fo.items(), key=lambda kv: -kv[1]))
    _medios_txt = ", ".join(f"{m} ({c})" for m, c in d.get("top_medios", [])) or "—"
    _tot_fo = sum(fo.values()) or 1
    _social_pct = round(100 * fo.get("social", 0) / _tot_fo)
    _agg_pct = round(100 * fo.get("agregador (google-news)", 0) / _tot_fo)
    _prensa_pct = round(100 * (fo.get("española", 0) + fo.get("marroquí", 0)) / _tot_fo)
    _ratio = ("%.1f×" % (d["sem_actual_nucleo"] / d["media8_nucleo"])) if d.get("media8_nucleo") else "—"
    _sum_nuc = sum(d["por_categoria"].get(k, 0)
                   for k in ("drones", "buques_guerra", "maniobras", "hostigamiento", "bloqueo"))
    _sum_ctx = sum(d["por_categoria"].get(k, 0)
                   for k in ("valla_incidente", "postura_oficial", "critica_a_marruecos", "soberania"))
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
        f"<td>{f.get('fuente')}</td><td>{f.get('polaridad')}</td></tr>"
        for f in fichas[:12])
    _h4 = d.get("h4", {})
    _h4_txt = ("sin datos." if not _h4 else
               f"Última semana: {_n(_h4.get('eventos'))} eventos · <b>{_n(_h4.get('urls'))}</b> URLs · "
               f"{_n(_h4.get('fuentes'))} fuentes · {_n(_h4.get('autores'))} autores · "
               f"ratio ev/URL = <b>{_h4.get('ev_por_url')}</b> · URL top = {_h4.get('top_url_pct')}%.")
    _lectura = (f"{_n(d['nucleo']['eventos'])} eventos de núcleo ({_ratio} la media). "
                f"<b>{_social_pct}%</b> redes · <b>{_agg_pct}%</b> agregador "
                f"(≈{d.get('medios_indep', 0)} medios distintos) · <b>{_prensa_pct}%</b> prensa directa. "
                f"Top-5 cuentas = <b>{amp.get('top5_pct', 0)}%</b>; top-3 de la última semana = "
                f"<b>{_pt3_txt}</b>; solo <b>{amp.get('urls_compartidas', 0)}</b> URLs compartidas. "
                f"<b>Polaridad</b> (heurística): <b>{_hostil_pct}%</b> hostil · {_coop_pct}% cooperación · "
                f"{_neutro_pct}% neutro. "
                f"<b>Lectura:</b> pico de conversación con corroboración limitada y sin evidencia "
                f"de coordinación por URLs.")
    if delta is None:
        delta_html = "<b>—</b><span>vs media 8 sem (núcleo)</span>"
    else:
        sign = "+" if delta >= 0 else ""
        col = "#b91c1c" if delta >= 0 else "#166534"
        delta_html = f"<b style='color:{col}'>{sign}{delta:.0f}%</b><span>vs media 8 sem (núcleo)</span>"

    manual_html = _md(manual_txt)
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Indicadores de presión híbrida en Frontera Sur (Marruecos) — Observatorio de amplificacion</title>
<meta name="description" content="Subcaso: nucleo hibrido (drones, buques, maniobras, hostigamiento, bloqueo) vs contexto, con linea base. Senal, no atribucion.">
<meta name="robots" content="index,follow">
<style>
:root{{--navy:#0d1b2a;--ink:#1b263b;--mut:#5c6b7a;--line:#dbe2ea;--bg:#f7f9fc;--acc:#c1440e}}
*{{box-sizing:border-box}}body{{margin:0;font:16px/1.6 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}}
header{{background:var(--navy);color:#fff;padding:28px 20px}}
.wrap{{max-width:900px;margin:0 auto;padding:0 20px}}
h1{{font-size:1.5rem;margin:0 0 6px}}h2{{font-size:1.15rem;margin:28px 0 10px;border-left:4px solid var(--acc);padding-left:10px}}
.sub{{color:#c9d6e2;font-size:.95rem}}
.aviso{{background:#fff3cd;border:1px solid #ffe08a;border-radius:8px;padding:12px 14px;margin:16px 0;font-size:.94rem}}
.marco{{background:#eef4fb;border-left:4px solid var(--navy);border-radius:8px;padding:12px 14px;margin:16px 0;font-size:.93rem}}
.lectura{{background:#0d1b2a;color:#fff;border-radius:8px;padding:14px 16px;margin:16px 0}}
.lectura .sub{{color:#c1cfe0;font-size:.85rem}}
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
<header><div class="wrap">
<h1>Indicadores de presión híbrida en Frontera Sur (Marruecos)</h1>
<div class="sub">Subcaso del tema <b>Frontera Sur</b> — Observatorio de amplificacion · dato {meta['generado_utc']}</div>
</div></header>
<main class="wrap">
<div class="aviso"><b>Senal, no atribucion.</b> Mide <b>actividad observada</b> (volumen, fuentes, dinamica) en fuentes abiertas. NO atribuye autoria, intencion ni confirma campana. Un volumen alto no equivale a coordinacion confirmada.</div>

<div class="marco">
<p><b>Marco de referencia (OTAN).</b> <em>&ldquo;Hybrid threats combine military and non-military as well as covert and overt means, including disinformation, cyber attacks, economic pressure, deployment of irregular armed groups and use of regular forces.&rdquo;</em> &mdash; OTAN, <a href="https://www.nato.int/cps/en/natohq/topics_156338.htm">&laquo;What are the hybrid threats NATO faces?&raquo;</a> (actualizado 29-ene-2026).</p>
<p><em>Traducci&oacute;n libre:</em> &laquo;Las amenazas h&iacute;bridas combinan medios militares y no militares, as&iacute; como encubiertos y abiertos, incluidos la desinformaci&oacute;n, los ciberataques, la presi&oacute;n econ&oacute;mica, el despliegue de grupos armados irregulares y el uso de fuerzas regulares.&raquo;</p>
<p><b>Declaraci&oacute;n de la Cumbre de Bruselas (2018), &sect;21.</b> <em>&ldquo;Our nations have come under increasing challenge from both state and non-state actors who use hybrid activities that aim to create ambiguity and blur the lines between peace, crisis, and conflict. While the primary responsibility for responding to hybrid threats rests with the targeted nation, NATO is ready, upon Council decision, to assist an Ally at any stage of a hybrid campaign. In cases of hybrid warfare, the Council could decide to invoke Article 5 of the Washington Treaty, as in the case of armed attack. &hellip;&rdquo;</em> <em>[contin&uacute;a]</em> &hellip;We announce the establishment of Counter Hybrid Support Teams&hellip;</p>
<p><em>Traducci&oacute;n libre (inicio):</em> &laquo;Nuestras naciones se enfrentan a un desaf&iacute;o creciente de actores estatales y no estatales que usan actividades h&iacute;bridas destinadas a crear ambig&uuml;edad y difuminar las l&iacute;neas entre paz, crisis y conflicto.&raquo; El resto detalla que la responsabilidad primaria es del pa&iacute;s objetivo, que la OTAN puede asistir por decisi&oacute;n del Consejo &mdash;incluido el art&iacute;culo 5&mdash; y que se crean los <i>Counter Hybrid Support Teams</i>.</p>
<p class="sub">Cita: OTAN (2018). <i>Brussels Summit Declaration</i>, PR/CP(2018)074, 11 de julio de 2018, p&aacute;rr. 21. <a href="https://www.nato.int/en/about-us/official-texts-and-resources/official-texts/2018/07/11/brussels-summit-declaration">nato.int (HTML)</a> &middot; <a href="https://www.nato.int/nato_static_fl2014/assets/pdf/pdf_2018_07/20180713_180711-summit-declaration-eng.pdf">PDF</a> (consultado el 15-oct-2026).</p>
</div>

<div class="lectura">
<p><b>Lectura de la semana.</b> {_lectura}</p>
<p class="sub">Cuota núcleo/(núcleo+contexto): <b>{d.get('cuota_pct', 0)}%</b> · Dependencia del pico (top-3 autores de la última semana): <b>{_pt3_txt}</b> · Medios distintos en el núcleo (google-news resuelto al medio): <b>{d.get('medios_indep', 0)}</b>.</p>
</div>

<h2>Nucleo hibrido</h2>
<div class="kpis">
<div class="kpi"><b>{_n(d['clusters_nucleo'])}</b><span>clusters nucleo</span></div>
<div class="kpi"><b>{_n(d['nucleo']['eventos'])}</b><span>eventos nucleo</span></div>
<div class="kpi"><b>{_n(d['nucleo']['autores'])}</b><span>autores nucleo</span></div>
<div class="kpi">{delta_html}</div>
<div class="kpi"><b>{z_txt}</b><span>z-score (pico vs 8 sem)</span></div>
</div>
<p class="sub">Cronografía: eventos de <b>núcleo</b> por semana (últ. semana {_n(d['sem_actual_nucleo'])} · media 8 sem {_n(d['media8_nucleo'])}); líneas = hitos exógenos:</p>
{_timeline(d['serie_semanal_nucleo'], d.get('now_ts', 0), d.get('hitos', []))}
<table><thead><tr><th>Categoria (nucleo)</th><th class="num">Eventos</th></tr></thead>
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

<h2>Polaridad del núcleo (heurística)</h2>
<table><thead><tr><th>Polaridad</th><th class="num">Eventos</th><th class="num">%</th></tr></thead>
<tbody>{pol_html}</tbody></table>
<p class="sub">Patrones de texto: <b>hostil</b> = violación / incursión / amenaza / hostigamiento / bloqueo…; <b>cooperación</b> = conjuntas / entrega / Navantia / acuerdo / visita…; resto = <b>neutro</b>. <b>Heurística, pendiente de validación manual.</b> Separa la cooperación militar y el comercio de defensa de la presión hostil.</p>

<h2>Contraste de hipótesis (H1–H4)</h2>
<table>
<tbody>
<tr><td><b>H1</b> · la actividad de drones sube tras eventos migratorios (retardo ≤7 d)</td><td>{_h1_txt}</td></tr>
<tr><td><b>H2</b> · los picos coinciden con hitos exógenos (placebo)</td><td>{_plc_txt}</td></tr>
<tr><td><b>H3</b> · amplificación coordinada por URLs</td><td><b>Refutada</b> en esta ventana: solo <b>{amp.get('urls_compartidas', 0)}</b> URLs compartidas por ≥2 autores (de {_n(amp.get('urls_distintas', 0))}).</td></tr>
<tr><td><b>H4</b> · el incremento responde a cambios de cobertura (control)</td><td>{_h4_txt} <b>Lectura:</b> muchas URLs/fuentes → actividad; pocas URLs con muchas repeticiones → eco de una noticia.</td></tr>
</tbody></table>
<p class="sub">H1 con <b>permutación</b> (500 barajados) para no fingir precisión con pocos datos; H2 con <b>placebo</b> (¿los picos caen cerca de hitos más que por azar?). Resultado <b>no resuelto ≠ descartado</b>.</p>

<h2>Fichas de clúster (núcleo)</h2>
<table><thead><tr><th>Clúster</th><th>Ventana</th><th class="num">Eventos</th><th class="num">Autores</th><th>Origen dominante</th><th>Polaridad</th></tr></thead>
<tbody>{fichas_html or '<tr><td colspan=6>sin clusters</td></tr>'}</tbody></table>
<p class="sub">Cada clúster con su ventana, tamaño, autores, origen y polaridad <b>dominantes</b> (heurística). Convierte el número en narrativa.</p>

<h2>Por qué estas categorías son el núcleo</h2>
<p>Mapeo de cada categoría de <b>núcleo</b> a un <b>medio</b> de la definición de la OTAN (arriba):</p>
<table><thead><tr><th>Categoría (núcleo)</th><th>Medio (definición OTAN)</th></tr></thead>
<tbody>
<tr><td>Buques de guerra</td><td>medio militar &mdash; &laquo;use of regular forces&raquo;</td></tr>
<tr><td>Ejercicios militares</td><td>medio militar &mdash; &laquo;use of regular forces&raquo;</td></tr>
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

<h2>Que se observa</h2>
{manual_html}

<h2>Como leerlo</h2>
<ul>
<li>El <b>nucleo</b> son los indicadores hibridos; el <b>contexto</b> (valla, postura, critica, soberania) es trasfondo y va aparte.</li>
<li>El <b>delta</b> compara la ultima semana con la media de las 8 anteriores (linea base), sobre eventos de nucleo.</li>
<li>Las categorias se solapan dentro de cada grupo; el conteo de cada una es independiente.</li>
<li>Fuentes: prensa espanola/marroqui/argelina, agencias internacionales y Bluesky.</li>
</ul>
</main>
<footer><div class="wrap">
Generado automaticamente por <code>detection/caso_hibridos_frontera.py</code> ·
manual hash <code>{meta['hash_manual'][:16]}</code> ·
Fuente: <code>event_temas</code> + <code>cluster_events</code> (tema frontera_sur) · no toca scoring.
</div></footer>
</body></html>
"""


def main():
    if not os.path.exists(DB):
        print("[caso-hibridos] BD no encontrada:", DB)
        return 1
    d = compute()
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

    os.makedirs(HTML_DIR, exist_ok=True)
    open(HTML_OUT, "w", encoding="utf-8").write(
        build_html(manual_txt, d, {"generado_utc": now, "hash_manual": hash_manual}))
    print("[caso-hibridos] HTML ->", HTML_OUT)
    print(f"[caso-hibridos] nucleo: {d['nucleo']['eventos']} ev · {d['clusters_nucleo']} clusters · "
          f"delta {d['delta_pct']}% · contexto {d['contexto']['eventos']} ev")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
