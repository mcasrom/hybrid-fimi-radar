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
    ("maniobras", "Maniobras militares", ["maniobra", "ejercicio militar", "ejercicios militares"], [], "nucleo"),
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
    ("soberania", "Soberania / aguas", ["soberan", "aguas territoriales", "aguas internacionales", "tratado de ceuta"], [], "contexto"),
]

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
        ids = [r[0] for r in con.execute(
            "SELECT e.id FROM events e JOIN event_temas et ON et.event_id=e.id "
            f"WHERE et.tema_id=? AND e.timestamp>=? AND ({like}){excl_sql}", p).fetchall()]
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
    if delta is None:
        delta_html = "<b>—</b><span>vs media 8 sem (núcleo)</span>"
    else:
        sign = "+" if delta >= 0 else ""
        col = "#b91c1c" if delta >= 0 else "#166534"
        delta_html = f"<b style='color:{col}'>{sign}{delta:.0f}%</b><span>vs media 8 sem (núcleo)</span>"

    manual_html = "".join(f"<p>{line}</p>" if line.strip() else "" for line in manual_txt.splitlines())
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
</div>

<h2>Nucleo hibrido</h2>
<div class="kpis">
<div class="kpi"><b>{_n(d['clusters_nucleo'])}</b><span>clusters nucleo</span></div>
<div class="kpi"><b>{_n(d['nucleo']['eventos'])}</b><span>eventos nucleo</span></div>
<div class="kpi"><b>{_n(d['nucleo']['autores'])}</b><span>autores nucleo</span></div>
<div class="kpi">{delta_html}</div>
</div>
<p class="sub">Serie semanal (eventos de nucleo; ult. semana {_n(d['sem_actual_nucleo'])} · media 8 sem {_n(d['media8_nucleo'])}):</p>
{_sparkline(d['serie_semanal_nucleo'])}
<table><thead><tr><th>Categoria (nucleo)</th><th class="num">Eventos</th></tr></thead>
<tbody>{tbl('nucleo')}</tbody></table>

<h2>Amplificación (núcleo)</h2>
<div class="kpis">
<div class="kpi"><b>{amp.get('top10_pct', 0)}%</b><span>top-10 autores</span></div>
<div class="kpi"><b>{amp.get('top5_pct', 0)}%</b><span>top-5 autores</span></div>
<div class="kpi"><b>{amp.get('gini', 0)}</b><span>Gini autores</span></div>
<div class="kpi"><b>{_n(amp.get('urls_compartidas', 0))}</b><span>URLs compartidas (≥2 autores)</span></div>
</div>
<p class="sub">{_n(amp.get('autores_distintos', 0))} autores distintos · {_n(amp.get('urls_distintas', 0))} URLs distintas. Lectura: <b>top-5 alto / Gini alto</b> o <b>many URLs compartidas</b> → amplificación concentrada; valores bajos → discusión repartida (sin amplificación). Medido en el núcleo, no en el contexto.</p>

<h2>Por qué estas categorías son el núcleo</h2>
<p>Mapeo de cada categoría de <b>núcleo</b> a un <b>medio</b> de la definición de la OTAN (arriba):</p>
<table><thead><tr><th>Categoría (núcleo)</th><th>Medio (definición OTAN)</th></tr></thead>
<tbody>
<tr><td>Buques de guerra</td><td>medio militar &mdash; &laquo;use of regular forces&raquo;</td></tr>
<tr><td>Maniobras militares</td><td>medio militar &mdash; &laquo;use of regular forces&raquo;</td></tr>
<tr><td>Drones</td><td>medio militar / tecnológico</td></tr>
<tr><td>Bloqueo aéreo / marítimo</td><td>coerción &mdash; &laquo;economic pressure&raquo; / presión no militar</td></tr>
<tr><td>Hostigamiento</td><td>presión sobre la población &mdash; &laquo;sow doubt&raquo; / presión</td></tr>
</tbody></table>
<p class="sub">Las categorías de <b>contexto</b> (salto a la valla, postura oficial, crítica internacional, soberanía) son <b>trasfondo migratorio/diplomático</b>: no corresponden a un «medio» de la definición, por eso van aparte y no cuentan como señal de presión híbrida.</p>

<h2>Contexto (no hibrido)</h2>
<p class="sub">Se muestra aparte para no inflar el nucleo: {_n(d['contexto']['eventos'])} eventos de contexto no se cuentan como senal hibrida.</p>
<table class="contexto"><thead><tr><th>Categoria (contexto)</th><th class="num">Eventos</th></tr></thead>
<tbody>{tbl('contexto')}</tbody></table>

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
