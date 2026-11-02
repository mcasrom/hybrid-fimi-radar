#!/usr/bin/env python3
"""Genera una ficha de situación a partir de las fichas curadas y un JSON de contexto."""
import argparse
import html
import json
import math
import re
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
DEFAULT_EP = HERE.parents[1] / "data/caso_frontera_sur_hibridos/episodios_curados.json"
DEFAULT_SIT = HERE / "situacion_frontera_sur.json"
DEFAULT_KPIS = HERE / "situacion_kpis.json"
DEFAULT_OUT = HERE.parent / "ceuta/situacion/index.html"

ROLE_CLASS = {
    "primaria": "role-primary",
    "oficial": "role-official",
    "agencia": "role-agency",
    "especializada": "role-specialist",
    "local": "role-local",
    "extranjera": "role-foreign",
    "estatal": "role-state",
    "medio": "role-media",
}


def e(value):
    return html.escape(str(value or ""))


def urls(text):
    return re.findall(r"https?://[^\s)<>\"]+", text or "")


def domain(url):
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def link(url, label=None):
    return f'<a href="{e(url)}" target="_blank" rel="noopener">{e(label or url)}</a>'


def fmt_num(n):
    return f"{int(n):,}".replace(",", ".")


def fmt_pct(v):
    return "s/d" if v is None else f"{v:.1f} %".replace(".", ",")


def short(value, n=32):
    value = str(value or "")
    return value if len(value) <= n else value[: n - 1] + "…"


def svg_activity(act):
    daily = act.get("daily") or []
    if not daily:
        return '<p class="muted">Sin datos diarios.</p>'
    w, h, left, right, top, bottom = 660, 220, 42, 12, 18, 34
    pw, ph = w - left - right, h - top - bottom
    maxn = max((d["n"] for d in daily), default=0)
    ceiling = max(10, int(math.ceil(maxn / 10.0)) * 10)
    step = pw / len(daily)
    bars, points = [], []
    for i, d in enumerate(daily):
        x = left + i * step + 1
        bh = ph * d["n"] / ceiling
        bars.append(
            f'<rect x="{x:.1f}" y="{top + ph - bh:.1f}" width="{max(step - 1, 1):.1f}" '
            f'height="{bh:.1f}" fill="#b45309" opacity=".72"><title>{e(d["date"])}: {d["n"]}</title></rect>'
        )
        points.append(f'{left + i * step + step / 2:.1f},{top + ph - (ph * d["ma7"] / ceiling):.1f}')
    grid = []
    for frac in (0, 0.5, 1):
        y = top + ph - frac * ph
        grid.append(f'<line x1="{left}" x2="{w - right}" y1="{y:.1f}" y2="{y:.1f}" stroke="#e2e8f0"/>')
        grid.append(f'<text x="{left - 5}" y="{y + 4:.1f}" text-anchor="end" font-size="10" fill="#64748b">{round(frac * ceiling)}</text>')
    labels = []
    for i in range(0, len(daily), 7):
        d = daily[i]
        x = left + i * step + step / 2
        labels.append(f'<text x="{x:.1f}" y="{h - 12}" text-anchor="middle" font-size="10" fill="#64748b">{e(d["date"][8:10])}/{e(d["date"][5:7])}</text>')
    last = daily[-1]
    labels.append(f'<text x="{left + (len(daily) - 1) * step + step / 2:.1f}" y="{h - 12}" text-anchor="middle" font-size="10" fill="#64748b">{e(last["date"][8:10])}/{e(last["date"][5:7])}</text>')
    return (
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Actividad diaria y media móvil de siete días">'
        f'<title>Publicaciones diarias y media móvil de 7 días</title>{"".join(grid)}{"".join(bars)}'
        f'<polyline points="{" ".join(points)}" fill="none" stroke="#1e293b" stroke-width="1.8"/>'
        f'{"".join(labels)}</svg>'
    )


def svg_sources(src):
    top = list(src.get("top") or [])[:8]
    total = int(src.get("total_publications") or 0)
    distinct = int(src.get("distinct") or 0)
    if not top or not total:
        return '<p class="muted">Sin datos de fuentes.</p>'
    rest_n = max(total - sum(int(x["n"]) for x in top), 0)
    rows = top + ([{"source": f"resto · {max(distinct - len(top), 0)} fuentes", "n": rest_n}] if rest_n else [])
    w, h, left, right, top_y, row_h = 460, 24 + len(rows) * 27, 150, 16, 12, 27
    bar_max = max((int(x["n"]) for x in rows), default=1)
    out = []
    for i, row in enumerate(rows):
        y = top_y + i * row_h
        n = int(row["n"])
        bw = (w - left - right) * n / bar_max
        label = short(row["source"], 24)
        fill = "#b45309" if i < len(top) else "#94a3b8"
        out.append(
            f'<text x="{left - 8}" y="{y + 13}" text-anchor="end" font-size="10" fill="#334155">{e(label)}</text>'
            f'<rect x="{left}" y="{y + 2}" width="{bw:.1f}" height="16" rx="3" fill="{fill}"><title>{e(row["source"])}: {n}</title></rect>'
            f'<text x="{left + bw + 5:.1f}" y="{y + 14}" font-size="10" fill="#64748b">{n}</text>'
        )
    return f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Publicaciones por fuente"><title>Fuentes con más publicaciones</title>{"".join(out)}</svg>'


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def source_links(ep):
    out = []
    for raw in ep.get("fuente", []):
        for url in urls(raw):
            clean = re.sub(r"https?://[^\s)<>\"]+", "", raw).strip(" ()·-")
            out.append((url, clean or domain(url)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodios", type=Path, default=DEFAULT_EP)
    ap.add_argument("--situacion", type=Path, default=DEFAULT_SIT)
    ap.add_argument("--kpis", type=Path, default=DEFAULT_KPIS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    sit = load_json(args.situacion)
    kpis = load_json(args.kpis) if args.kpis.exists() else None
    eps = load_json(args.episodios)["episodios"]
    by_id = {x["id"]: x for x in eps}
    order = sit["episode_order"]
    missing = [x for x in order if x not in by_id]
    if missing:
        raise SystemExit(f"Fichas ausentes: {missing}")
    ordered = [by_id[x] for x in order]

    all_urls = []
    domains = {}
    for ep in eps:
        for url, _ in source_links(ep):
            if url not in all_urls:
                all_urls.append(url)
            d = domain(url)
            domains[d] = domains.get(d, 0) + 1
    unknown = sorted(d for d in domains if d not in sit["source_roles"])
    if unknown:
        raise SystemExit(f"Fuentes sin clasificar: {unknown}")

    statuses = [sit["episode_status"][x["id"]] for x in ordered]
    status_counts = {}
    for s in statuses:
        status_counts[s] = status_counts.get(s, 0) + 1

    def status_chip(ep):
        key = sit["episode_status"][ep["id"]]
        label = sit["status_labels"][key]
        return f'<span class="chip st-{e(key)}">{e(label)}</span>'

    timeline = "".join(
        f'<li><time>{e(x.get("periodo"))}</time> <a href="#{e(x["id"])}">{e(x.get("titulo"))}</a>'
        f' <span class="id">{e(x["id"])}</span></li>'
        for x in ordered
    )

    actors = "".join(
        f'<article class="actor"><h3>{e(a["nombre"])}</h3><p class="muted">{e(a["tipo"])}</p>'
        f'<p><b>Interés analítico.</b> {e(a["interes"])}</p>'
        f'<p class="caveat">{e(a["cautela"])}</p></article>'
        for a in sit["actors"]
    )

    relations = "".join(
        f'<tr><td><b>{e(r["desde"])}</b> → <b>{e(r["hacia"])}</b></td>'
        f'<td>{e(r["tipo"])}</td><td>{e(r["estado"])}</td>'
        f'<td>{", ".join(e(i) for i in r["evidencia"])}</td></tr>'
        for r in sit["relations"]
    )

    evidence = "".join(
        f'<tr id="{e(x["id"])}"><td><b>{e(x["id"])}</b><br><span class="muted">{e(x.get("periodo"))}</span></td>'
        f'<td>{e(x.get("afirmacion"))}</td><td>{status_chip(x)}</td>'
        f'<td>{e(sit["episode_missing"][x["id"]])}</td></tr>'
        for x in ordered
    )

    contradictions = "".join(
        f'<li><b>{e(c["id"])}</b> — {e(c["texto"])}</li>' for c in sit["contradicciones"]
    )
    questions = "".join(f"<li>{e(q)}</li>" for q in sit["open_questions"])
    changes = "".join(f"<li>{e(c)}</li>" for c in sit["changes"])
    limits = "".join(f"<li>{e(x)}</li>" for x in sit["limites"])

    roles = "".join(
        f'<tr><td><a href="https://{e(d)}" target="_blank" rel="noopener">{e(d)}</a></td>'
        f'<td><span class="chip {ROLE_CLASS.get(sit["source_roles"][d]["role"], "role-media")}">'
        f'{e(sit["source_roles"][d]["label"])}</span></td>'
        f'<td>{domains[d]}</td></tr>'
        for d in sorted(domains, key=lambda x: (sit["source_roles"][x]["role"], x))
    )

    primary_count = sum(1 for d in domains if sit["source_roles"][d]["role"] == "primaria")
    official_count = sum(1 for d in domains if sit["source_roles"][d]["role"] == "oficial")
    declared_count = status_counts.get("declaracion_publica", 0)
    pending_count = len(ordered) - declared_count

    if kpis:
        act = kpis["activity"]
        src = kpis["sources"]
        ev = kpis.get("evidence") or {}
        lang = (kpis.get("languages", {}).get("top") or [{}])[0]
        delta = act.get("delta_pct")
        delta_abs = act.get("delta_abs", 0)
        delta_txt = "sin base" if delta is None else f"{delta:+.1f} %".replace(".", ",")
        delta_txt = f"{delta_txt} ({delta_abs:+d})" if delta is not None else delta_txt
        if act["previous7_complete"]["n"] < 50:
            delta_txt += " · base baja"
        q = kpis.get("quality") or {}
        quality = (
            f'{fmt_num(q.get("raw_publications", 0))} capturas · '
            f'{fmt_num(q.get("dedup_publications", act["total"]))} tras dedup · '
            f'{fmt_num(q.get("duplicates_removed", 0))} duplicadas · '
            f'{fmt_num(q.get("empty_titles", 0))} sin título · '
            f'{fmt_pct(q.get("aggregator_share"))} Google News'
        )
        kpi_html = f'''<div class="kpis">
<div class="kpi"><b>{fmt_num(act["total"])}</b><span>publicaciones · {kpis["period"]["days"]} d</span><small>{act["days_with_data"]} días con datos</small></div>
<div class="kpi"><b>{fmt_num(src["distinct"])}</b><span>dominios directos</span><small>top-3: {fmt_pct(src.get("top3_share"))}</small></div>
<div class="kpi"><b>{e(lang.get("lang", "s/d"))}</b><span>idioma principal</span><small>{fmt_num(lang.get("n", 0))} publicaciones</small></div>
<div class="kpi"><b>{fmt_num(ev.get("primary_sources", primary_count))}</b><span>fuentes primarias</span><small>{ev.get("reported_pending", pending_count)} fichas pendientes</small></div>
</div>'''
        charts_html = f'''<h2>1. Indicadores de situación</h2>
<p class="muted">Serie de publicaciones capturadas, no de hechos confirmados. Periodo: {e(kpis["period"]["from"])} → {e(kpis["period"]["to"])}; hoy es un día parcial.</p>
<section class="charts">
<article class="chart"><h3>Actividad diaria</h3><p class="muted">Barras: publicaciones. Línea: media móvil de 7 días. Últimos 7 días completos: <b>{fmt_num(act["last7_complete"]["n"])}</b> frente a <b>{fmt_num(act["previous7_complete"]["n"])}</b> ({delta_txt}).</p>{svg_activity(act)}<div class="legend"><span><i class="swatch bar"></i> publicaciones</span><span><i class="swatch line"></i> media 7 d</span></div></article>
<article class="chart"><h3>Dominios directos con más publicaciones</h3><p class="muted">{fmt_num(src["distinct"])} dominios directos; el primero concentra el {fmt_pct(src.get("top1_share"))} y los tres primeros el {fmt_pct(src.get("top3_share"))}. Google News se mide aparte como agregador.</p>{svg_sources(src)}</article>
</section>
<div class="box neutral"><b>Calidad de la captura.</b> {e(quality)}. La deduplicación solo une la misma fecha, título normalizado y fuente; no colapsa medios distintos.</div>
<div class="box neutral"><b>Cómo leer estos indicadores.</b> Miden actividad y procedencia, no coordinación, intención ni gravedad. Un pico puede ser un acontecimiento real, una decisión editorial o una consulta que captura más. El denominador y los días sin datos quedan visibles.</div>'''
    else:
        kpi_html = f'''<div class="kpis"><div class="kpi"><b>{len(ordered)}</b><span>fichas</span></div><div class="kpi"><b>{len(all_urls)}</b><span>enlaces únicos</span></div><div class="kpi"><b>{primary_count}</b><span>fuentes primarias</span></div><div class="kpi"><b>{len(sit["open_questions"])}</b><span>preguntas abiertas</span></div></div>'''
        charts_html = ""

    doc = f'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(sit["titulo"])} — Observatorio de lo publicado</title>
<meta name="description" content="Ficha de situación de Frontera Sur: qué se publica, qué actores aparecen, qué evidencia existe y qué no se puede concluir.">
<link rel="canonical" href="https://fimi.viajeinteligencia.com/observatorio/ceuta/situacion/">
<meta property="og:type" content="article"><meta property="og:title" content="{e(sit["titulo"])}">
<meta property="og:description" content="Qué se publica, qué está documentado y qué falta sobre Ceuta y Marruecos.">
<meta property="og:url" content="https://fimi.viajeinteligencia.com/observatorio/ceuta/situacion/">
<meta property="og:image" content="https://fimi.viajeinteligencia.com/observatorio/og-frontera-sur.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="https://fimi.viajeinteligencia.com/observatorio/og-frontera-sur.png">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Article","headline":"{e(sit["titulo"])}","dateModified":"{e(sit["actualizado"])}","isPartOf":{{"@type":"WebSite","name":"Observatorio de lo publicado","url":"https://fimi.viajeinteligencia.com/observatorio/"}}}}</script>
<style>
:root{{--a:#b45309;--i:#1e293b;--m:#64748b;--l:#fde68a;--bg:#fffaf5}}
*{{box-sizing:border-box}}body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:linear-gradient(180deg,#fff,var(--bg));color:var(--i);line-height:1.6}}
.wrap{{max-width:1010px;margin:0 auto;padding:28px 18px 60px}}a{{color:var(--a)}}h1{{font-size:1.8rem;line-height:1.2;margin:0 0 6px}}h2{{font-size:1.15rem;border-bottom:2px solid var(--l);padding-bottom:5px;margin:30px 0 10px}}h3{{margin:0 0 5px}}.lead{{font-size:1rem;color:#334155;max-width:72ch}}.muted{{color:var(--m);font-size:.84rem}}.id{{font-weight:800;color:var(--a);font-size:.78rem}}.sitehead{{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;border-bottom:1px solid #e2e8f0;padding-bottom:12px;margin-bottom:18px}}.brand{{font-weight:800;text-decoration:none;font-size:1.05rem}}.sitehead nav{{display:flex;gap:6px;flex-wrap:wrap;font-size:.82rem}}.sitehead nav a{{text-decoration:none;padding:4px 7px;border-radius:6px}}.sitehead nav a:hover{{background:#fff7ed}}
.hero{{border-left:5px solid var(--a);padding:0 0 0 16px;margin:8px 0 18px}}.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}}.kpi{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:12px 10px;text-align:center}}.kpi b{{display:block;font-size:1.5rem;color:var(--a);line-height:1.1}}.kpi span{{font-size:.76rem;color:var(--m);display:block;margin-top:3px}}.kpi small{{display:block;font-size:.72rem;color:#475569;margin-top:4px}}.charts{{display:grid;grid-template-columns:1.55fr 1fr;gap:14px;margin:14px 0}}.chart{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px;min-width:0}}.chart h3{{margin:0 0 4px;font-size:.98rem}}.chart svg{{display:block;width:100%;height:auto;margin-top:8px;overflow:visible}}.legend{{display:flex;gap:14px;flex-wrap:wrap;font-size:.76rem;color:var(--m);margin-top:6px}}.swatch{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:middle}}.swatch.bar{{background:#b45309;opacity:.72}}.swatch.line{{background:#1e293b;height:3px}}.box{{background:#fff7ed;border-left:4px solid var(--a);padding:10px 14px;border-radius:7px;margin:12px 0}}.box.neutral{{background:#f8fafc;border-left-color:#64748b}}.chip{{display:inline-block;font-size:.76rem;padding:2px 7px;border-radius:999px;border:1px solid #e2e8f0;background:#fff}}.st-reportado_sin_primaria,.st-reportado_cifras_prensa{{background:#fffbeb;border-color:#fcd34d}}.st-declaracion_publica{{background:#eff6ff;border-color:#93c5fd}}.role-primary{{background:#dcfce7;border-color:#86efac}}.role-oficial{{background:#e0f2fe;border-color:#7dd3fc}}.role-state{{background:#fef2f2;border-color:#fca5a5}}
.timeline{{list-style:none;padding:0;margin:0;border-left:2px solid #e2e8f0}}.timeline li{{position:relative;padding:0 0 14px 18px;margin:0}}.timeline li:before{{content:"";position:absolute;left:-6px;top:8px;width:10px;height:10px;border-radius:50%;background:var(--a)}}.timeline time{{display:block;font-size:.78rem;color:var(--m);font-weight:700}}
.actors{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:10px 0}}.actor{{background:#fff;border:1px solid #e2e8f0;border-top:4px solid var(--a);border-radius:9px;padding:12px}}.caveat{{font-size:.8rem;color:var(--m);border-top:1px solid #f1f5f9;padding-top:7px}}table{{width:100%;border-collapse:collapse;font-size:.88rem}}th,td{{border-bottom:1px solid #e2e8f0;padding:8px;text-align:left;vertical-align:top}}th{{background:#f8fafc;font-size:.78rem;text-transform:uppercase;letter-spacing:.04em;color:#475569}}ul{{padding-left:20px}}li{{margin:6px 0}}.two{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.two .box{{margin:0}}.foot{{display:grid;grid-template-columns:1.4fr 1fr 1.2fr;gap:20px;margin-top:40px;border-top:2px solid var(--l);padding-top:22px;color:#334155;font-size:.86rem}}.foot b{{display:block;color:var(--i);margin-bottom:6px}}.foot a{{display:block;text-decoration:none;margin:4px 0}}.foot p{{margin:0 0 8px;color:var(--m)}}@media(max-width:760px){{.actors,.two,.kpis,.charts,.foot{{grid-template-columns:1fr}}h1{{font-size:1.45rem}}table{{font-size:.82rem}}}}
</style></head><body><div class="wrap">
<div class="sitehead"><a class="brand" href="/observatorio/">Observatorio de lo publicado</a><nav><a href="/observatorio/">Inicio</a><a href="/observatorio/ceuta/">Frontera Sur</a><a href="/observatorio/juventud/">Protestas juveniles</a><a href="/observatorio/campana/">Elecciones generales</a><a href="/observatorio/infraestructuras/">Infraestructuras</a><a href="/observatorio/eventos/">Acontecimientos</a><a href="/observatorio/metodo/">Método</a><a href="/observatorio/fuentes/">Fuentes</a><a href="/observatorio/datos/">Datos</a></nav></div>
<div class="hero"><p class="muted">Ficha de situación · {e(sit["periodo"])}</p><h1>{e(sit["titulo"])}</h1><p class="lead">{e(sit["subtitulo"])}. Qué se publica, qué actores aparecen, qué evidencia existe y qué no se puede concluir.</p><p class="muted">Actualizada: {e(sit["actualizado"])} · No es un observatorio de hechos confirmados.</p></div>
{kpi_html}
<div class="box"><b>Qué es esto.</b> Una ficha de situación construida sobre las fichas ya publicadas. No añade hechos ni atribuye intenciones: ordena lo que se afirma, quién lo publica, qué respuesta oficial existe y qué falta para poder concluir.</div>
<h2>2. Qué está pasando</h2>{''.join(f'<p>{e(x)}</p>' for x in sit["resumen"])}
<div class="two"><div class="box neutral"><b>Qué ha cambiado</b><ul>{changes}</ul></div><div class="box neutral"><b>Cómo leer los actores</b><p>Los intereses son una lectura analítica, no una intención declarada ni una prueba de coordinación.</p></div></div>
{charts_html}
<h2>3. Cronología</h2><ol class="timeline">{timeline}</ol>
<h2>4. Actores</h2><div class="actors">{actors}</div>
<h2>5. Relaciones documentadas</h2><table><thead><tr><th>Relación</th><th>Tipo</th><th>Estado</th><th>Fichas</th></tr></thead><tbody>{relations}</tbody></table><p class="muted">Una relación documentada no equivale a una alianza, una orden ni una coordinación.</p>
<h2>6. Evidencia y vacíos</h2><table><thead><tr><th>Ficha</th><th>Qué se afirma</th><th>Estado</th><th>Qué falta</th></tr></thead><tbody>{evidence}</tbody></table>
<h2>7. Contradicciones</h2><ul>{contradictions}</ul>
<h2>8. Preguntas abiertas</h2><ul>{questions}</ul>
<h2>9. Qué no se puede concluir</h2><ul>{limits}</ul>
<div class="box"><b>Resumen honesto.</b> Hay cobertura periodística suficiente para describir un debate y varias hipótesis; no hay evidencia primaria suficiente para confirmar las afirmaciones, una intención hostil ni una operación de influencia.</div>
<h2>10. Fuentes y papel documental</h2><table><thead><tr><th>Dominio</th><th>Papel</th><th>Enlaces</th></tr></thead><tbody>{roles}</tbody></table><p class="muted">{len(all_urls)} enlaces únicos en {len(domains)} dominios · {primary_count} fuentes primarias · {official_count} fuentes oficiales enlazadas · {declared_count} declaración pública · {pending_count} pendientes de contraste. La clasificación describe el tipo de pieza, no su independencia editorial.</p>
<div class="box"><b>Qué no es esta ficha.</b> No es una verificación de los hechos, no identifica a los responsables de una campaña y no usa clústeres, bandas ni puntuaciones internas. Las fuentes primarias siguen pendientes.</div>
<p><a href="/observatorio/ceuta/situacion/cambios/"><b>Ver briefing de cambios →</b></a></p>
<p><a href="/observatorio/ceuta/"><b>← Volver al registro de Frontera Sur</b></a> · <a href="/observatorio/eventos/">Acontecimientos agrupados</a> · <a href="/observatorio/fuentes/">Fuentes</a> · <a href="/observatorio/metodo/">Método</a></p>
<footer class="foot"><div><b>Observatorio de lo publicado</b><p>Registro de afirmaciones, episodios y calendario oficial. No confirma hechos ni atribuye intenciones.</p><p>Ficha de situación · {e(sit["version"])}</p></div><div><b>Secciones</b><a href="/observatorio/">Inicio</a><a href="/observatorio/ceuta/">Frontera Sur</a><a href="/observatorio/juventud/">Protestas juveniles</a><a href="/observatorio/campana/">Elecciones generales</a><a href="/observatorio/infraestructuras/">Infraestructuras</a><a href="/observatorio/metodo/">Método</a></div><div><b>Contacto</b><a href="mailto:info-fimi@viajeinteligencia.com">info-fimi@viajeinteligencia.com</a><p>Prensa y correcciones: indica la URL y la fuente.</p><a href="/observatorio/privacidad/">Privacidad</a></div></footer>
</div></body></html>'''
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(doc, encoding="utf-8")
    print(f"{args.out} · {len(ordered)} fichas · {len(all_urls)} enlaces · {primary_count} primarias")


if __name__ == "__main__":
    main()
