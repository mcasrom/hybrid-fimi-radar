"""Render de KPI y gráficos SVG compartidos por las fichas de situación."""
import html
import math


def e(value):
    return html.escape(str(value or ""))


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


def kpi_strip(kpis, fallback=None):
    act = kpis["activity"]
    src = kpis["sources"]
    ev = kpis.get("evidence") or (fallback or {})
    lang = (kpis.get("languages", {}).get("top") or [{}])[0]
    delta = act.get("delta_pct")
    delta_abs = act.get("delta_abs", 0)
    delta_txt = "sin base" if delta is None else f"{delta:+.1f} %".replace(".", ",")
    delta_txt = f"{delta_txt} ({delta_abs:+d})" if delta is not None else delta_txt
    if act["previous7_complete"]["n"] < 50:
        delta_txt += " · base baja"
    label = ev.get("label", "fuentes primarias")
    if label == "fuentes oficiales":
        detail = f'{ev.get("documented_relations", 0)} relaciones · no confirman incidencias'
    else:
        detail = f'{ev.get("reported_pending", 0)} fichas pendientes'
    return f'''<div class="kpis">
<div class="kpi"><b>{fmt_num(act["total"])}</b><span>publicaciones · {kpis["period"]["days"]} d</span><small>{act["days_with_data"]} días con datos</small></div>
<div class="kpi"><b>{fmt_num(src["distinct"])}</b><span>fuentes distintas</span><small>top-3: {fmt_pct(src.get("top3_share"))}</small></div>
<div class="kpi"><b>{e(lang.get("lang", "s/d"))}</b><span>idioma principal</span><small>{fmt_num(lang.get("n", 0))} publicaciones</small></div>
<div class="kpi"><b>{fmt_num(ev.get("primary_sources", 0))}</b><span>{e(label)}</span><small>{e(detail)}</small></div>
</div>'''


def charts_block(kpis, number="1"):
    act = kpis["activity"]
    src = kpis["sources"]
    delta = act.get("delta_pct")
    delta_abs = act.get("delta_abs", 0)
    delta_txt = "sin base" if delta is None else f"{delta:+.1f} %".replace(".", ",")
    delta_txt = f"{delta_txt} ({delta_abs:+d})" if delta is not None else delta_txt
    if act["previous7_complete"]["n"] < 50:
        delta_txt += " · base baja"
    return f'''<h2>{e(number)}. Indicadores de situación</h2>
<p class="muted">Serie de publicaciones capturadas, no de hechos confirmados. Periodo: {e(kpis["period"]["from"])} → {e(kpis["period"]["to"])}; hoy es un día parcial.</p>
<section class="charts">
<article class="chart"><h3>Actividad diaria</h3><p class="muted">Barras: publicaciones. Línea: media móvil de 7 días. Últimos 7 días completos: <b>{fmt_num(act["last7_complete"]["n"])}</b> frente a <b>{fmt_num(act["previous7_complete"]["n"])}</b> ({e(delta_txt)}).</p>{svg_activity(act)}<div class="legend"><span><i class="swatch bar"></i> publicaciones</span><span><i class="swatch line"></i> media 7 d</span></div></article>
<article class="chart"><h3>Fuentes con más publicaciones</h3><p class="muted">{fmt_num(src["distinct"])} fuentes distintas; la primera concentra el {fmt_pct(src.get("top1_share"))} y las tres primeras el {fmt_pct(src.get("top3_share"))}. Etiqueta de captura, no independencia editorial.</p>{svg_sources(src)}</article>
</section>
<div class="box neutral"><b>Cómo leer estos indicadores.</b> Miden actividad y procedencia, no coordinación, intención ni gravedad. Un pico puede ser un acontecimiento real, una decisión editorial o una consulta que captura más. El denominador y los días sin datos quedan visibles.</div>'''
