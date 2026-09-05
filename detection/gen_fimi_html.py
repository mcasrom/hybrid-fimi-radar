#!/usr/bin/env python3
"""gen_fimi_html.py — Genera el dashboard HTML estático del radar FIMI.

Replica el patrón de nivel-embalses.html (HTML estático + SVG inline), leyendo
data/radar.db. Salida: /var/www/fimi/index.html (servido por nginx).
Sin RAM extra en runtime: lo genera el cron.
"""
import json
import re
import sqlite3
import sys
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/deploy/hybrid-fimi-radar")
DB = ROOT / "data" / "radar.db"
OUT = Path("/var/www/fimi/index.html")

BAND_COLORS = {
    "NORMAL": "#16a34a", "WATCH": "#0891b2", "ANOMALOUS": "#eab308",
    "HIGH": "#f97316", "CRITICAL": "#dc2626",
}

# Traducción de hipótesis H1-H6 (attribution.py) a español natural, para que
# quien no conoce el motor entienda la tarjeta sin códigos internos.
HYPOTHESIS_ES = {
    "H1": {"t": "Viralización orgánica", "d": "muchas cuentas distintas lo difunden sin pauta coordinada clara"},
    "H2": {"t": "Campaña coordinada doméstica", "d": "coordinación dentro del país, sin infraestructura externa compartida"},
    "H3": {"t": "Operación de influencia extranjera", "d": "coordinación + infraestructura común + narrativa que cruza países"},
    "H4": {"t": "Amplificación mediática", "d": "el eco lo dan medios establecidos, no cuentas anónimas coordinadas"},
    "H5": {"t": "Campaña política", "d": "coordinación en el marco electoral o partidista"},
    "H6": {"t": "Sin evidencia concluyente", "d": "no hay señal suficiente para distinguir entre las anteriores"},
}

# Componentes que muestra cada tarjeta: frase en lenguaje llano de qué mide.
# Todos se presentan en su escala real 0-100 (el máximo del componente es 100).
COMPONENT_ES = {
    "coordination_score": "Cuentas del grupo publican el mismo contenido o enlaces casi a la vez",
    "anomaly_score": "Cuánto se desvía el comportamiento de estas cuentas de lo normal",
    "infrastructure_score": "Comparten dominios, enlaces o la misma base técnica",
    "network_density": "Qué conectadas están entre sí las cuentas del cluster",
}


def band_of(score):
    if score >= 80: return "CRITICAL"
    if score >= 60: return "HIGH"
    if score >= 40: return "ANOMALOUS"
    if score >= 20: return "WATCH"
    return "NORMAL"


def kpi(label, value, sub, bg):
    return (f'<div style="flex:1 1 150px;background:{bg};border-radius:12px;padding:14px 16px;'
            f'box-shadow:0 1px 3px rgba(0,0,0,.06)">'
            f'<div style="font-size:.72rem;color:#475569;font-weight:600;text-transform:uppercase">{label}</div>'
            f'<div style="font-size:1.6rem;font-weight:800;color:#0f172a;line-height:1.2">{value}</div>'
            f'<div style="font-size:.78rem;color:#64748b">{sub}</div></div>')


def svg_score_bar(score, band):
    col = BAND_COLORS.get(band, "#94a3b8")
    w = int((score / 100) * 460)
    return (f'<div style="display:flex;align-items:center;gap:10px;margin:6px 0">'
            f'<div style="flex:1;height:14px;background:#f1f5f9;border-radius:7px;overflow:hidden">'
            f'<div style="width:{w}px;height:100%;background:{col};border-radius:7px"></div></div>'
            f'<b style="width:52px;text-align:right">{score:.0f}/100</b>'
            f'<span style="width:70px;color:{col};font-weight:700">{band}</span></div>')


def kpi_banda_alerta(clus):
    """KPI con la banda de alerta máxima de una lista de clusters."""
    max_o = max((c["overall_score"] or 0) for c in clus) if clus else 0
    b = band_of(max_o)
    col = BAND_COLORS[b]
    if not clus:
        return kpi("Banda de alerta", "—", "sin clusters", "#f8fafc")
    return (f'<div style="flex:1 1 150px;background:#f8fafc;border-radius:12px;padding:14px 16px;'
            f'box-shadow:0 1px 3px rgba(0,0,0,.06)">'
            f'<div style="font-size:.72rem;color:#475569;font-weight:600;text-transform:uppercase">Banda de alerta</div>'
            f'<div style="font-size:1.6rem;font-weight:800;color:{col};line-height:1.2">{b}</div>'
            f'<div style="font-size:.78rem;color:#64748b">máx {max_o:.0f}/100</div></div>')


def render_dial_svg(etiqueta, valor, color):
    """Velocímetro SVG simple (sin librería). valor 0-100, color de banda.

    Semicírculo base gris + aguja que apunta a la posición del valor.
    El color de la aguja y de la etiqueta indica el estado (banda).
    """
    import math as _m
    cx, cy, r = 100, 100, 72
    L = _m.pi * r  # longitud del semicírculo
    # punto del arco superior para un porcentaje (0% izquierda, 100% derecha)
    theta = _m.radians(180 - 180.0 * (min(100, max(0, valor)) / 100.0))
    px = cx + r * _m.cos(theta)
    py = cy - r * _m.sin(theta)
    # aguja más corta que el radio
    nx = cx + (r - 14) * _m.cos(theta)
    ny = cy - (r - 14) * _m.sin(theta)
    path_d = f"M {cx - r} {cy} A {r} {r} 0 0 1 {cx + r} {cy}"
    return (f'<svg viewBox="0 0 200 112" width="180" height="101" role="img" '
            f'aria-label="{etiqueta}: {valor:.0f}/100">'
            f'<path d="{path_d}" fill="none" stroke="#e2e8f0" stroke-width="11" '
            f'stroke-linecap="round" stroke-dasharray="{L:.1f} {L:.1f}"/>'
            f'<line x1="{cx}" y1="{cy}" x2="{nx:.1f}" y2="{ny:.1f}" '
            f'stroke="{color}" stroke-width="4" stroke-linecap="round"/>'
            f'<circle cx="{cx}" cy="{cy}" r="6" fill="{color}"/>'
            f'<text x="{cx - r - 4}" y="{cy + 8}" font-size="9" fill="#94a3b8">0</text>'
            f'<text x="{cx + r + 1}" y="{cy + 8}" font-size="9" fill="#94a3b8">100</text>'
            f'</svg>')


COMPONENT_LABELS = {
    "coordination_score": "Coordinación",
    "anomaly_score": "Anomalía",
    "infrastructure_score": "Infraestructura",
    "network_density": "Densidad de red",
}

EXPANDED_BANDS = ("CRITICAL", "HIGH")  # solo estas muestran detalle por defecto


def render_component_legend():
    """Leyenda única de los componentes (qué mide cada uno). Se muestra una
    sola vez, arriba del listado de clusters, no repetida en cada tarjeta."""
    rows = ""
    for key in ("coordination_score", "anomaly_score",
                "infrastructure_score", "network_density"):
        label = COMPONENT_LABELS[key]
        frase = COMPONENT_ES[key]
        rows += (f'<div style="display:flex;gap:10px;align-items:flex-start;min-width:170px;flex:1 1 40%">'
                 f'<b style="color:#334155;font-size:.82rem;min-width:110px">{label}</b>'
                 f'<span style="font-size:.76rem;color:#64748b;line-height:1.4">{frase}</span></div>')
    return (f'<div class="card" style="padding:14px 16px;background:#f8fafc">'
            f'<h3 style="font-size:.9rem;margin:0 0 8px">Cómo leer los componentes (0-100)</h3>'
            f'<div style="display:flex;flex-wrap:wrap;gap:8px 18px">{rows}</div>'
            f'<p class="caption" style="margin:8px 0 0">Las barras miden cada señal de 0 a 100. '
            f'El score global pondera estos 4 componentes + la amplificación del tema.</p></div>')


def _cluster_comps(c, a):
    """Componentes 0-100 de un cluster: preferir el assessment (ya normalizado,
    ej. coordination_score del assessment = synchronization=coord*12 cap 100);
    si no hay assessment, derivar con las mismas fórmulas que run_fimi."""
    if a:
        return {
            "coordination_score": a["coordination_score"] or 0,
            "anomaly_score": a["anomaly_score"] or 0,
            "infrastructure_score": a["infrastructure_score"] or 0,
            "network_density": a["network_density"] or 0,
        }
    coord = c["coordination_score"] or 0
    return {
        "coordination_score": min(100.0, coord * 12),
        "anomaly_score": c["anomaly_score"] or 0,
        "infrastructure_score": c["infrastructure_score"] or 0,
        "network_density": min(100.0, coord * 6),
    }


def _cluster_detail_html(c, a, comps, contenido=None):
    """Detalle completo de un cluster: contenido real (titulares) + barra
    overall + componentes con barra (X/100) + atribución + hipótesis (solo 2
    más probables). Sin frases por componente: están en la leyenda única."""
    import re as _re
    overall = c["overall_score"] or 0
    band = band_of(overall)
    col = BAND_COLORS[band]
    n_cuentas = None
    if a:
        m = _re.search(r"(\d+)\s+cuentas?", str(a["assessment"] or ""))
        if m:
            n_cuentas = int(m.group(1))
    cuentas_html = (f' · <span style="color:#475569">{n_cuentas} cuentas</span>'
                    if n_cuentas is not None else "")

    h = (f'<div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:4px">'
         f'<b style="font-size:1.02rem">{c["cluster_label"]}</b>'
         f'<span style="font-size:1.25rem;color:{col}">{overall:.0f}/100</span>'
         f'<span style="font-size:.8rem;color:{col};background:{col}18;border:1px solid {col};'
         f'border-radius:999px;padding:1px 10px;font-weight:700">{band}</span>'
         f'{cuentas_html}</div>')

    # GUARDIA DE INTERPRETACIÓN: evita que un lector no experto lea HIGH/CRITICAL
    # como "campaña extranjera confirmada". La banda es una señal conductual de
    # coordinación, NO una atribución de actor ni una prueba de orquestación.
    if band in ("HIGH", "CRITICAL"):
        h += (f'<div style="background:#fffbeb;border:1px solid #fde68a;color:#92400e;'
              f'border-radius:8px;padding:6px 12px;margin:4px 0 8px;font-size:.74rem;line-height:1.35">'
              f'<b>Interpreta con cautela:</b> {band} = señal de <b>comportamiento coordinado '
              f'anómalo</b> entre estas cuentas. <b>No</b> implica por sí solo un actor extranjero '
              f'ni una campaña orquestada: revisa el contenido, la atribución (a menudo '
              f'UNKNOWN/NO_ATTRIBUTION) y las hipótesis alternativas antes de concluir.</div>')

    # CONTENIDO REAL del cluster: de qué habla (titulares + enlaces). Se
    # muestran los 2-3 textos más repetidos del cluster, con su fuente.
    content_html = ""
    if contenido:
        import html as _html_esc
        list_items = ""
        for item in contenido[:3]:
            txt = _html_esc.escape(str(item.get("text", "")))[:180]
            url = _html_esc.escape(str(item.get("url", "")))
            freq = item.get("n", 1)
            url_html = (f' · <a href="{url}" target="_blank" rel="noopener noreferrer" '
                        f'style="color:#c2410c;font-size:.76rem">fuente</a>' if url else "")
            freq_html = (f' <span style="color:#94a3b8;font-size:.72rem">(x{freq})</span>'
                         if freq > 1 else "")
            list_items += (f'<div style="font-size:.84rem;color:#1e293b;line-height:1.4;'
                           f'padding:4px 0">{txt}{freq_html}{url_html}</div>')
        content_html = (f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;'
                        f'padding:8px 12px;margin:6px 0">'
                        f'<div style="font-size:.72rem;color:#64748b;font-weight:600;'
                        f'text-transform:uppercase;margin-bottom:2px">De qué habla este cluster</div>'
                        f'{list_items}</div>')

    # barras de componentes (X/100 junto a la barra)
    bars = ""
    for key in ("coordination_score", "anomaly_score",
                "infrastructure_score", "network_density"):
        val = comps.get(key, 0) or 0
        val = max(0.0, min(100.0, val))
        bcol = BAND_COLORS[band_of(val)]
        bars += (f'<div style="display:flex;align-items:center;gap:8px;margin:5px 0">'
                 f'<span style="font-size:.8rem;color:#475569;width:118px;min-width:118px">'
                 f'{COMPONENT_LABELS[key]}</span>'
                 f'<div style="flex:1;height:9px;background:#f1f5f9;border-radius:5px;overflow:hidden">'
                 f'<div style="width:{val:.0f}%;height:100%;background:{bcol};border-radius:5px"></div>'
                 f'</div>'
                 f'<b style="font-size:.8rem;color:#334155;width:46px;text-align:right">'
                 f'{val:.0f}/100</b></div>')

    # atribución
    attr = ""
    if a:
        attr = (f'<p style="font-size:.8rem;color:#475569;border-top:1px dashed #e2e8f0;'
                f'padding-top:6px;margin:8px 0 4px">'
                f'<b>Atribución:</b> {a["attribution"]} · confianza {a["attribution_confidence"]}'
                f' — {a["attribution_evidence"]}</p>')

    # hipótesis: solo las 2 más probables
    hyp_html = ""
    if a:
        try:
            hyp = json.loads(a["hypotheses_json"]) if a["hypotheses_json"] else []
            hyp = sorted(hyp, key=lambda x: -(x.get("score") or 0))
            if hyp:
                chips = ""
                for x in hyp[:2]:
                    code = x.get("hypothesis", "?")
                    es = HYPOTHESIS_ES.get(code, {"t": x.get("label", code), "d": ""})
                    pct = int(round((x.get("score") or 0) * 100))
                    chips += (f'<span style="display:inline-flex;align-items:center;gap:8px;'
                              f'background:#fff7ed;border:1px solid #fed7aa;color:#9a3412;'
                              f'border-radius:999px;padding:3px 12px;font-size:.78rem;margin:2px 6px 2px 0">'
                              f'<b>{es["t"]}</b><span style="color:#c2410c;font-weight:700">{pct}%</span>'
                              f'</span>')
                hyp_html = (f'<div style="margin-top:2px"><span style="font-size:.74rem;color:#94a3b8">'
                            f'Explicación más probable: </span>{chips}</div>')
        except Exception:
            pass

    return h + content_html + svg_score_bar(overall, band) + bars + attr + hyp_html


def render_cluster_cards(clus, asm, titulo_vacio="Sin clusters activos", contenido_map=None):
    """Renderiza los clusters de un tema.

    Escaneo rápido: solo los clusters HIGH/CRITICAL muestran su detalle por
    defecto. El resto (ANOMALOUS/WATCH) queda resumido en un bloque colapsado
    "ver los N restantes", y dentro de él cada uno puede expandirse.
    contenido_map: dict cluster_id -> [ {text,url,n}, ... ] titulares reales.
    """
    if not clus:
        return (f'<div class="card"><h3>{titulo_vacio}</h3>'
                '<p class="caption">Con la historia acumulada hasta ahora no hay señal de '
                'coordinación. La ausencia de señal es un resultado válido del radar.</p></div>')
    # índice assessments por cluster_id
    asm_by_cid = {a["cluster_id"]: a for a in asm} if asm else {}
    contenido_map = contenido_map or {}
    order = sorted(clus, key=lambda c: -(c["overall_score"] or 0))
    expandidos = [c for c in order if band_of(c["overall_score"] or 0) in EXPANDED_BANDS]
    resto = [c for c in order if band_of(c["overall_score"] or 0) not in EXPANDED_BANDS]

    out = ""
    # --- clusters HIGH/CRITICAL: detalle completo visible ---
    for c in expandidos:
        a = asm_by_cid.get(c["id"])
        comps = _cluster_comps(c, a)
        out += (f'<div class="card">{_cluster_detail_html(c, a, comps, contenido_map.get(c["id"]))}</div>')

    # --- resto (ANOMALOUS/WATCH/NORMAL): gráfico de barras clicable ---
    if resto:
        import re as _re2

        def _n_acc(c):
            """Nº de cuentas del cluster (desempate), del texto del assessment."""
            a_ = asm_by_cid.get(c["id"])
            if a_:
                m_ = _re2.search(r"(\d+)\s+cuentas?", str(a_["assessment"] or ""))
                if m_:
                    return int(m_.group(1))
            return 0

        # orden: score desc; empate -> más cuentas primero
        resto_sorted = sorted(resto, key=lambda c: (-(c["overall_score"] or 0), -_n_acc(c)))

        bars = ""
        pool = ""  # detalles pre-renderizados (uno por cluster), ocultos
        for c in resto_sorted:
            cid = c["id"]
            a_ = asm_by_cid.get(cid)
            comps_ = _cluster_comps(c, a_)
            overall_ = c["overall_score"] or 0
            band_ = band_of(overall_)
            nacc_ = _n_acc(c)
            # color por banda: ANOMALOUS ámbar, WATCH/NORMAL gris neutro
            barcol_ = "#f59e0b" if band_ == "ANOMALOUS" else "#94a3b8"
            pct_ = max(2.0, min(100.0, overall_))
            # contexto real (de qué habla) del cluster para verlo sin expandir
            ctx_ = ""
            try:
                import html as _he
                _topc = (contenido_map.get(cid) or [])
                if _topc:
                    ctx_ = (f"<div style='font-size:.72rem;color:#64748b;margin-top:2px;"
                            f"line-height:1.3'>“{_he.escape(_topc[0].get('text',''))[:78]}”</div>")
            except Exception:
                ctx_ = ""
            # fila-barra clicable (div, sin framework)
            bars += (
                f'<div class="fimi-bar" data-cid="{cid}" '
                f'onclick="fimiResto({cid})" '
                f'style="display:flex;align-items:center;gap:10px;padding:7px 8px;'
                f'border-radius:8px;cursor:pointer;user-select:none;'
                f'border:1px solid transparent">'
                f'<div style="min-width:120px"><b style="min-width:92px;font-size:.82rem;'
                f'color:#334155">{c["cluster_label"]}</b>{ctx_}</div>'
                f'<div style="flex:1;height:16px;background:#f1f5f9;border-radius:8px;overflow:hidden">'
                f'<div style="width:{pct_:.0f}%;height:100%;background:{barcol_};border-radius:8px"></div>'
                f'</div>'
                f'<span style="min-width:150px;text-align:right;font-size:.78rem;color:#475569;'
                f'font-weight:600">{overall_:.0f}/100 '
                f'<span style="color:{barcol_};font-weight:700">{band_}</span>'
                f' · {nacc_} cuentas</span></div>')
            # detalle completo pre-renderizado (lo mismo que HIGH/CRITICAL)
            pool += (f'<div class="fimi-resto-detail" data-cid="{cid}" hidden>'
                     f'{_cluster_detail_html(c, a_, comps_, contenido_map.get(cid))}</div>')

        plural = "clusters" if len(resto) != 1 else "cluster"
        out += (f'<div class="card" style="padding:12px 16px;background:#fafaf9">'
                f'<details><summary style="cursor:pointer;font-weight:600;color:#475569;font-size:.9rem">'
                f'Ver los {len(resto)} {plural} restantes '
                f'(WATCH/ANOMALOUS, sin nivel de alerta)</summary>'
                f'<p style="font-size:.74rem;color:#94a3b8;margin:8px 0 2px">Pulsa una barra para ver su detalle '
                f'(solo se muestra uno a la vez).</p>'
                f'{bars}'
                f'<div id="fimiRestoPane" style="display:none;margin-top:10px"></div>'
                f'{pool}'
                f'</details></div>')

    return out


def main():
    # cargar config para inventario de fuentes y keywords
    try:
        import yaml
        cfg = yaml.safe_load(open(ROOT / "config.yaml"))
        feeds = cfg.get("feeds", [])
        keywords = cfg.get("keywords", [])
        telegram = cfg.get("telegram_canales", [])
        subreddits = cfg.get("subreddits", [])
        temas_cfg = cfg.get("temas", {})
    except Exception:
        feeds, keywords, telegram, subreddits, temas_cfg = [], [], [], [], {}
    # temas activos (catálogo config.yaml); frontera_sur siempre existe
    temas = list(temas_cfg.keys()) or ["frontera_sur"]
    if "frontera_sur" not in temas:
        temas.insert(0, "frontera_sur")

    feeds_html = ""
    for f in feeds:
        pais = f.get("pais", "")
        feeds_html += (f"<li>{f.get('nombre','?')} "
                       f"<span style='color:#94a3b8;font-size:.8rem'>· {f.get('url','')}"
                       f"{' · ' + pais if pais else ''}</span></li>")
    kw_html = ""
    for k in keywords:
        kw_html += (f"<li><code>{k.get('palabra','?')}</code> → "
                    f"{', '.join(k.get('plataformas', []))}</li>")
    tg_html = " · ".join(f"<code>{c}</code>" for c in telegram) or "—"
    sr_html = " · ".join(f"<code>r/{s}</code>" for s in subreddits) or "—"

    if not DB.exists():
        html = f"<html><body><h1>Sin datos aún</h1><p>El radar capturará en el próximo ciclo (6h).</p></body></html>"
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(html, encoding="utf-8")
        print("sin datos, pagina placeholder generada")
        return

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row  # acceso por nombre de columna (robusto al orden)
    clusters = con.execute("SELECT * FROM clusters ORDER BY overall_score DESC").fetchall()
    assessments = con.execute("SELECT * FROM assessments").fetchall()
    # contenido real por cluster (cluster_events): cluster_id -> top titulares
    # agrupados por frecuencia, para mostrar DE QUÉ habla cada cluster.
    contenido_map = {}
    try:
        ce = con.execute(
            "SELECT ce.cluster_id, ce.text, ce.url, ce.ts FROM cluster_events ce"
            " ORDER BY ce.cluster_id, ce.ts").fetchall()
        from collections import OrderedDict
        _acc = OrderedDict()
        for r in ce:
            _t = (str(r["text"] or "")).strip()
            if not _t:
                continue
            _key = r["cluster_id"]
            bucket = _acc.setdefault(_key, {})
            entry = bucket.get(_t)
            if entry:
                entry["n"] += 1
            else:
                bucket[_t] = {"text": _t, "url": str(r["url"] or ""), "n": 1}
        for _cid, _bucket in _acc.items():
            contenido_map[_cid] = sorted(_bucket.values(),
                                         key=lambda x: -x["n"])[:4]
    except Exception:
        contenido_map = {}
    n_events = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    n_sources = con.execute("SELECT COUNT(DISTINCT source) FROM events").fetchone()[0]
    ev_df = pd.read_sql("SELECT timestamp, source, title, url, text FROM events", con)
    # agregación por tema (multi-tema): eventos/fuentes via event_temas, clusters via tema_id
    has_et = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='event_temas'").fetchone()
    por_tema = {}
    for _t in temas:
        if has_et:
            _ev = con.execute(
                "SELECT COUNT(*) FROM events e JOIN event_temas t ON t.event_id=e.id WHERE t.tema_id=?",
                (_t,)).fetchone()[0]
            _src = con.execute(
                "SELECT COUNT(DISTINCT e.source) FROM events e JOIN event_temas t ON t.event_id=e.id"
                " WHERE t.tema_id=?", (_t,)).fetchone()[0]
        else:
            _ev = con.execute("SELECT COUNT(*) FROM events WHERE tema_id=?", (_t,)).fetchone()[0]
            _src = con.execute("SELECT COUNT(DISTINCT source) FROM events WHERE tema_id=?", (_t,)).fetchone()[0]
        _cl = [c for c in clusters if c["tema_id"] == _t]
        por_tema[_t] = {"eventos": _ev, "fuentes": _src, "clusters": _cl}
    # historial persistido de hallazgos, agrupado por tipo (top recientes de cada uno)
    try:
        _top_n = 12
        findings = {
            "amplificacion_narrativa": con.execute(
                "SELECT id, fecha, tipo, titulo, detalle, n_sources, n_events, window_hours"
                " FROM findings WHERE tipo='amplificacion_narrativa'"
                " ORDER BY fecha DESC LIMIT ?", (_top_n,)).fetchall(),
            "cluster": con.execute(
                "SELECT id, fecha, tipo, titulo, detalle, n_sources, n_events, window_hours"
                " FROM findings WHERE tipo='cluster'"
                " ORDER BY fecha DESC LIMIT ?", (_top_n,)).fetchall(),
            "cascada": con.execute(
                "SELECT id, fecha, tipo, titulo, detalle, n_sources, n_events, window_hours"
                " FROM findings WHERE tipo='cascada'"
                " ORDER BY fecha DESC LIMIT ?", (_top_n,)).fetchall(),
        }
    except Exception:
        findings = {}
    # narrativas sostenidas (misma narrativa amplificada en >=3 dias = alerta)
    sostenidas = []
    try:
        import sys as _sys
        _sys.path.insert(0, str(ROOT))
        from detection.persistencia import detectar_sostenidas
        sostenidas = detectar_sostenidas(con, min_dias=3)
    except Exception:
        sostenidas = []

    # --- TENDENCIA POR TEMA (para la vista resumen de diales) ---
    # Métrica: nº de hallazgos del tema HOY vs hace 48h (2 días). Subiendo si
    # hoy > hace48, o hay cluster HIGH/CRITICAL nuevo hoy que no estaba hace 48h.
    # findings.tema_id ahora existe (migración); los anteriores son frontera_sur.
    import datetime as _dtc
    from datetime import timedelta as _td
    _hoy_d = datetime.now(timezone.utc).date()
    _hace48 = _hoy_d - _td(days=2)
    tendencias = {}
    try:
        for _t in temas:
            _hoy_n = con.execute(
                "SELECT COUNT(*) FROM findings WHERE tema_id=? AND date(fecha,'unixepoch')=?",
                (_t, _hoy_d.isoformat())).fetchone()[0]
            _h48_n = con.execute(
                "SELECT COUNT(*) FROM findings WHERE tema_id=? AND date(fecha,'unixepoch')=?",
                (_t, _hace48.isoformat())).fetchone()[0]
            # clusters HIGH/CRITICAL del tema HOY en vista activa
            _cl_tema = [c for c in clusters if c["tema_id"] == _t]
            _high_hoy = sum(1 for c in _cl_tema if (c["overall_score"] or 0) >= 60)
            # clusters HIGH/CRITICAL hace 48h (findings cluster de ese tema con >=60)
            _high_48 = con.execute(
                "SELECT COUNT(*) FROM findings WHERE tema_id=? AND tipo='cluster'"
                " AND date(fecha,'unixepoch')=? AND intensidad>=60",
                (_t, _hace48.isoformat())).fetchone()[0]
            # decidir tendencia
            if _hoy_n == 0 and _h48_n == 0 and _high_hoy == 0 and _high_48 == 0:
                estado = "recopilando"
            elif _high_hoy > _high_48:
                estado = "subiendo"
            elif _hoy_n > _h48_n:
                estado = "subiendo"
            elif _hoy_n < _h48_n:
                estado = "bajando"
            else:
                estado = "estable"
            tendencias[_t] = {
                "estado": estado,
                "hoy": _hoy_n, "hace48": _h48_n,
                "high_hoy": _high_hoy, "high_48": _high_48,
            }
    except Exception as _exc_t:
        for _t in temas:
            tendencias[_t] = {"estado": "estable", "hoy": 0, "hace48": 0,
                              "high_hoy": 0, "high_48": 0}
    con.close()

    # narrativas amplificadas (mismo titular en varias fuentes)
    narr_kpi = None  # se rellena en el bloque de narrativas amplificadas
    try:
        import sys as _sys
        _sys.path.insert(0, str(ROOT))
        from detection.fakenews import detect_narrative_amplification
        ev_df["ts"] = ev_df["timestamp"]  # la detección espera columna ts
        narr_html = ""
        narratives = detect_narrative_amplification(ev_df, {"thresholds": {"near_duplicate_threshold": 0.7, "min_amp_sources": 3}})
        if narratives:
            # KPI de narrativas amplificadas
            narr_kpi = kpi("Narrativas amplificadas", len(narratives),
                           f"top: {narratives[0]['seed'][:28]}...", "#fff7ed")
            # intensidad = eventos x fuentes / (ventana_horas + 1)
            top_n = narratives[:8]
            def _intensity(n):
                return n["n_events"] * n["n_sources"] / max(n["window_hours"] + 1, 0.5)
            max_i = max(_intensity(n) for n in top_n) or 1
            rows = ""
            for i, n in enumerate(top_n):
                pct = int((_intensity(n) / max_i) * 100)
                ratio = _intensity(n) / max_i
                if ratio >= 0.8:
                    col = "#dc2626"
                elif ratio >= 0.5:
                    col = "#f97316"
                elif ratio >= 0.3:
                    col = "#fbbf24"
                else:
                    col = "#22c55e"
                import html as _html
                title = _html.escape(n["seed"][:110])
                # eventos completos de esta narrativa (desplegable)
                eventos_html = ""
                for ev in n.get("eventos", []):
                    txt = _html.escape(str(ev.get("texto", ""))[:220])
                    src = _html.escape(str(ev.get("fuente", "")))
                    url = _html.escape(str(ev.get("url", "")))
                    dt = ""
                    try:
                        import datetime as _dt
                        dt = _dt.datetime.utcfromtimestamp(ev["ts"]).strftime("%d/%m %H:%M")
                    except Exception:
                        pass
                    url_html = f" · <a href='{url}' target='_blank' style='color:#c2410c'>enlace</a>" if url else ""
                    eventos_html += (
                        f"<div style='padding:6px 8px;border-top:1px solid #f1f5f9;font-size:.8rem;color:#334155'>"
                        f"<b style='color:#c2410c'>{dt}</b> [{src}]{url_html}<br>{txt}</div>")
                # fila de ancho COMPLETO (igual que el resto del dashboard): título,
                # métricas, barra de intensidad y desplegable del texto.
                rows += (
                    f"<div style='margin:10px 0;padding:12px 14px;border:1px solid #e2e8f0;"
                    f"border-radius:10px;background:#fff'>"
                    f"<div style='display:flex;justify-content:space-between;gap:10px;align-items:baseline'>"
                    f"<div style='font-size:.9rem;font-weight:600;color:#1e293b;line-height:1.35;flex:1'>{title}</div>"
                    f"<span style='font-size:.78rem;color:{col};font-weight:700;white-space:nowrap'>{pct}%</span></div>"
                    f"<div style='font-size:.78rem;color:#64748b;margin:2px 0 8px'>"
                    f"{n['n_events']} eventos · {n['n_sources']} fuentes · ventana {n['window_hours']}h</div>"
                    f"<div style='height:8px;background:#f1f5f9;border-radius:5px;overflow:hidden'>"
                    f"<div style='width:{pct}%;height:100%;background:{col};border-radius:5px'></div></div>"
                    f"<details style='margin-top:8px'><summary style='font-size:.8rem;color:#c2410c;cursor:pointer'>"
                    f"Ver texto completo ({n['n_events']} eventos)</summary>{eventos_html}</details>"
                    f"</div>")
            # bloque a ancho COMPLETO: h3 + caption + filas full-width, sin
            # KPI lateral que desplace el contenido a una columna estrecha.
            narr_block = (
                f"<div class='card'><h3 style='margin:0 0 2px'>Narrativas amplificadas "
                f"<span style='color:#c2410c;font-size:.9rem'>({len(top_n)})</span></h3>"
                f"<p class='caption'>Mismo titular compartido por varias fuentes en una ventana. "
                f"Indica amplificación de una noticia, no coordinación de cuentas. Sin atribución. "
                f"Intensidad = eventos × fuentes ÷ ventana en horas (menos tiempo = más amplificación).</p>"
                f"{rows}</div>")
        else:
            narr_kpi = kpi("Narrativas amplificadas", 0, "ninguna ≥3 fuentes", "#f8fafc")
            narr_block = (f"<div class='card'><div style='display:flex;gap:16px;align-items:center;flex-wrap:wrap'>"
                          f"{narr_kpi}"
                          f"<div style='flex:1;min-width:260px'><h3 style='margin:0'>Narrativas amplificadas</h3>"
                          f"<p class='caption'>Ninguna narrativa compartida por ≥3 fuentes distintas en la ventana actual.</p>"
                          f"</div></div></div>")
    except Exception as e:
        narr_block = ""
    # historial de hallazgos persistidos, agrupado por tipo
    import html as _html
    import datetime as _dt

    def _fmt_fecha(ts):
        try:
            return _dt.datetime.utcfromtimestamp(ts).strftime("%d/%m")
        except Exception:
            return ""

    _HIST_TYPES = [
        ("amplificacion_narrativa", "📣 Narrativas amplificadas", "#f97316",
         "Mismo titular propagado por varias fuentes (eco mediático, no coordinación)."),
        ("cluster", "🕸️ Clusters de coordinación", "#7c3aed",
         "Grupos de cuentas con comportamiento coordinado. Score del momento de detección."),
        ("cascada", "⚡ Cascadas", "#0891b2",
         "Ráfagas de publicaciones casi simultáneas de varias cuentas."),
    ]
    hist_blocks = ""
    for _tipo, _titulo, _color, _desc in _HIST_TYPES:
        rows_t = ""
        for f in findings.get(_tipo, []):
            hid, fecha, tipo, titulo, detalle, nsrc, nev, wh = f[:8]
            fecha_s = _fmt_fecha(fecha)
            det = str(detalle or "")
            # en clusters: chip de banda con color (score X/100 en el detalle)
            # + contexto real (de qué habla). Para findings NUEVOS el titular
            # dominante se persiste en el propio detalle (tras "|"); para los
            # antiguos se intenta el lookup por id en cluster_events.
            chip_banda = ""
            ctx_txt = ""
            if _tipo == "cluster":
                _ms = re.search(r"score\s+(\d+)/100", det)
                if _ms:
                    _sc = int(_ms.group(1))
                    _bd = band_of(_sc)
                    _bc = BAND_COLORS.get(_bd, "#94a3b8")
                    chip_banda = (f"<span style='display:inline-block;font-size:.68rem;font-weight:700;"
                                  f"color:{_bc};border:1px solid {_bc};border-radius:999px;"
                                  f"padding:0 6px;margin-left:6px'>{_bd}</span>")
                # contexto persistido (nuevo formato) o lookup por id (antiguo)
                if " | " in det:
                    _builtin = det.split(" | ", 1)[1]
                    ctx_txt = (f"<div style='font-size:.78rem;color:#334155;font-weight:600;"
                               f"margin-top:2px'>“{_html.escape(_builtin)[:90]}”</div>")
                    det = det.split(" | ", 1)[0]
                else:
                    try:
                        _cid = int(re.search(r"cluster_(\d+)", str(titulo)).group(1))
                        _top = (contenido_map.get(_cid) or [])
                        if _top:
                            _first = _top[0].get("text", "")
                            ctx_txt = (f"<div style='font-size:.78rem;color:#334155;font-weight:600;"
                                       f"margin-top:2px'>“{_html.escape(_first)[:90]}”</div>")
                    except Exception:
                        ctx_txt = ""
            rows_t += (f"<div style='display:flex;gap:10px;padding:6px 10px;border-left:3px solid {_color};"
                       f"background:#f8fafc;border-radius:6px;margin:4px 0;align-items:center'>"
                       f"<div style='flex:1'><div style='font-size:.84rem;color:#1e293b;font-weight:600'>"
                       f"{_html.escape(str(titulo)[:80])}</div>"
                       f"{ctx_txt}"
                       f"<div style='font-size:.74rem;color:#64748b'>{_html.escape(det)}"
                       f"{chip_banda} · {fecha_s}</div></div></div>")
        if not rows_t:
            continue
        _n = len(findings.get(_tipo, []))
        # cada tipo = <details> colapsado por defecto (evita scroll largo).
        hist_blocks += (
            f"<details style='margin:10px 0;border:1px solid #e2e8f0;border-radius:10px;"
            f"background:#fff;padding:4px 4px'>"
            f"<summary style='cursor:pointer;font-weight:700;color:{_color};font-size:.9rem;"
            f"padding:6px 8px;user-select:none'>{_titulo}"
            f" <span style='color:#94a3b8;font-weight:400'>({_n} recientes) · abrir</span></summary>"
            f"<div style='padding:2px 6px 8px'><p style='font-size:.74rem;color:#94a3b8;"
            f"margin:2px 0 6px'>{_desc}</p>{rows_t}</div></details>")
    hist_html = ""
    if hist_blocks:
        hist_html = (f"<div class='card'><h3>Historial de hallazgos</h3>"
                     f"<p class='caption'>Resultados positivos persistidos: no se pierden cuando el tema "
                     f"deja de ser noticia. Registro acumulado del radar, agrupado por tipo. "
                     f"Cada bloque se abre al pulsarlo para no ocupar todo el scroll.</p>"
                     f"{hist_blocks}</div>")

    # ALERTA: narrativas sostenidas (>=3 dias) — señal de campaña sostenida
    sost_html = ""
    if sostenidas:
        sost_rows = ""
        for s in sostenidas[:8]:
            fechas = ", ".join(s["fechas"][-5:])
            sost_rows += (f"<div style='display:flex;gap:10px;padding:10px 12px;border-left:4px solid #dc2626;"
                          f"background:#fef2f2;border-radius:8px;margin:8px 0;align-items:center'>"
                          f"<span style='font-size:1.2rem'>🚨</span>"
                          f"<div style='flex:1'><div style='font-size:.88rem;color:#7f1d1d;font-weight:700'>"
                          f"{_html.escape(s['titulo'][:70])}</div>"
                          f"<div style='font-size:.75rem;color:#991b1b'>{s['dias']} días distintos · "
                          f"últimos: {fechas}</div></div>"
                          f"<span style='background:#dc2626;color:#fff;border-radius:6px;padding:3px 8px;"
                          f"font-size:.75rem;font-weight:700'>SOSTENIDA</span></div>")
        sost_html = (f"<div class='card' style='border:2px solid #dc2626'>"
                     f"<h3 style='color:#b91c1c;margin-top:0'>🚨 Narrativas sostenidas ({len(sostenidas)})</h3>"
                     f"<p class='caption'>La misma narrativa se ha amplificado en ≥3 días distintos. "
                     f"Señal de campaña sostenida (no un titular suelto). Requiere investigación prioritaria.</p>"
                     f"{sost_rows}</div>")
    else:
        sost_html = ("<div class='card'><h3>Narrativas sostenidas</h3>"
                     "<p class='caption'>Ninguna narrativa amplificada en ≥3 días distintos todavía. "
                     "El radar sigue acumulando historial para detectarlas.</p></div>")

    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    # KPIs globales (resumen para SEO/share; el detalle por tema va en pestañas)
    n_crit = sum(1 for c in clusters if c["overall_score"] and c["overall_score"] >= 80) if clusters else 0
    n_high = sum(1 for c in clusters if c["overall_score"] and 60 <= c["overall_score"] < 80) if clusters else 0
    n_anom = sum(1 for c in clusters if c["overall_score"] and 40 <= c["overall_score"] < 60) if clusters else 0
    if narr_kpi is None:
        narr_kpi = kpi("Narrativas amplificadas", 0, "sin datos", "#f8fafc")

    # ---- PESTAÑAS POR TEMA (vista activa multi-tema) ----
    # Cada pestaña muestra: eventos, fuentes, clusters y banda de alerta del tema.
    tema_tabs = ""
    tema_panes = ""
    temas_stats = {}
    for i, _t in enumerate(temas):
        d = por_tema.get(_t, {"eventos": 0, "fuentes": 0, "clusters": []})
        _cl = d["clusters"]
        _meta = temas_cfg.get(_t, {}) if isinstance(temas_cfg, dict) else {}
        _nombre = _meta.get("nombre", _t)
        _estado = _meta.get("estado", "produccion")
        _discl = _meta.get("disclaimer", "")
        _tema_cl = [c for c in clusters if c["tema_id"] == _t]
        # Amplificación: señal GLOBAL del tema (un solo valor por run, no por
        # cluster). Se muestra una vez a nivel de pestaña con su escala y frase.
        _amp_tema = None
        for _cc in _tema_cl:
            _amp_tema = _cc["amplification_score"] or 0
            break
        _amp_kpi = ""
        if _amp_tema is not None:
            _amp_kpi = (f'<div style="flex:1 1 150px;background:#fff7ed;border-radius:12px;'
                        f'padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.06)">'
                        f'<div style="font-size:.72rem;color:#475569;font-weight:600;'
                        f'text-transform:uppercase">Amplificación del tema</div>'
                        f'<div style="font-size:1.6rem;font-weight:800;color:#c2410c;line-height:1.2">'
                        f'{_amp_tema:.0f}/100</div>'
                        f'<div style="font-size:.76rem;color:#78716c">señal global: cuántas cuentas '
                        f'distintas repiten el mismo contenido en el tema</div></div>')
        _cards_t = "".join([
            kpi("Eventos", d["eventos"], "del tema", "#eff6ff"),
            kpi("Fuentes", d["fuentes"], "del tema", "#f0fdf4"),
            kpi("Clusters", len(_tema_cl), "activos", "#fafaf9"),
            _amp_kpi,
            kpi_banda_alerta(_tema_cl),
        ])
        # stats por tema para el texto de compartir (se genera en el momento)
        _n_high_t = sum(1 for _cc in _tema_cl
                        if (_cc["overall_score"] or 0) >= 60)
        temas_stats[_t] = {
            "nombre": _nombre,
            "estado": _estado,
            "clusters": len(_tema_cl),
            "high": _n_high_t,
        }
        _cl_txt = ""
        if not _tema_cl:
            _cl_txt = render_cluster_cards([], assessments, titulo_vacio="Sin clusters activos en este tema")
        else:
            # leyenda de componentes UNA vez, arriba del listado; luego las tarjetas
            _cl_txt = render_component_legend() + render_cluster_cards(
                _tema_cl, assessments, contenido_map=contenido_map)
        _sel = " style='background:#c2410c;color:#fff;border-color:#c2410c'" if i == 0 else ""
        tema_tabs += (f"<button type='button' data-tema='{_t}' data-estado='{_estado}'"
                      f" onclick='fimiTab(\"{_t}\")'"
                      f" style='cursor:pointer;border:1px solid #e2e8f0;background:#fff;color:#334155;"
                      f"border-radius:999px;padding:7px 14px;font-weight:600;font-size:.82rem;"
                      f"font-family:inherit;{_sel if i == 0 else _sel}'>{_nombre}"
                      f"<span style='opacity:.75;font-weight:400'> · {_estado}</span></button>")
        tema_panes += (f"<div id='fimi-pane-{_t}' class='fimi-pane' data-tema='{_t}'"
                       f"{'' if i == 0 else ' hidden'}>"
                       f"<div class='kpis'>{_cards_t}</div>{_cl_txt}</div>")
    # Banner fijo de piloto: se muestra/oculta por JS segun la pestaña activa,
    # justo debajo del selector (imposible de no ver al entrar en un tema piloto).
    piloto_banner = (
        '<div id="pilotoBanner" class="piloto-banner" hidden>'
        '<div style="margin:10px 0;padding:12px 14px;background:#fef2f2;border:2px solid #fecaca;'
        'border-radius:10px;font-size:.85rem;color:#991b1b;line-height:1.5">'
        '<b>⚠️ Este radar está en fase de calibración</b> — el volumen de coordinación '
        'legítima en política es alto y el sistema aún está ajustando umbrales. '
        'Trata los scores de este tema con más cautela que los de frontera sur.</div></div>')
    tabs_ui = (f"<div style='display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 4px'>{tema_tabs}</div>"
               f"{piloto_banner}"
               f"<div style='font-size:.76rem;color:#94a3b8;margin:2px 0 8px'>"
               f"Cada pestaña muestra un dominio del catálogo. Las secciones de narrativas, historial y "
               f"metodología de abajo son el resumen global del radar.</div>"
               f"{tema_panes}")


    # nombres de temas para intro de página y popup (fuente única)
    _nombres_temas = []
    _nombres_intro = []
    for _t in temas:
        _m = temas_cfg.get(_t, {}) if isinstance(temas_cfg, dict) else {}
        _nn = _m.get("nombre", _t)
        if _m.get("estado") == "piloto":
            _nn += " (piloto)"
        _nombres_temas.append(_nn)
        _corto = re.sub(r"\s*\(.*\)\s*", "", _nn).strip().lower()
        _nombres_intro.append(_corto)
    tema_nombres_html = ", ".join(_nombres_temas) if _nombres_temas else "frontera sur"
    tema_lista_intro = ", ".join(_nombres_intro) if _nombres_intro else "frontera sur"

    # ============================================================
    # FUNNEL INTERPRETATIVO — guía visual para leer el radar
    # ============================================================
    n_clusters = len(clusters)
    n_crit, n_high, n_anom2 = (n_crit, n_high, n_anom)  # ya calculadas arriba
    # texto del estado actual para el CTA de compartir (CTR): se genera POR
    # TEMA ACTIVO (no agregado global), para no mezclar produccion con piloto.
    import urllib.parse as _up

    def _share_txt_for(tema_id, st):
        nm = (st.get("nombre") or tema_id).lower()
        # normalizar nombre para el texto (sin parentesis)
        nm = re.sub(r"\s*\(.*\)\s*", "", nm).strip()
        cl = st.get("clusters", 0)
        hi = st.get("high", 0)
        piloto = st.get("estado") == "piloto"
        base = (f"Radar FIMI — {nm.title()} ({now[:5]}): {cl} cluster{'s' if cl != 1 else ''}"
                f"{', ' + str(hi) + ' HIGH' if hi else ', 0 HIGH'}. "
                f"{'(piloto, en calibración) ' if piloto else ''}Agnóstico al actor, "
                f"sin atribución sin evidencia. https://fimi.viajeinteligencia.com")
        return base

    # por defecto: primer tema del catálogo
    default_tema = temas[0] if temas else "frontera_sur"
    default_stat = temas_stats.get(default_tema, {"nombre": default_tema, "estado": "produccion",
                                                  "clusters": 0, "high": 0})
    share_txt = _share_txt_for(default_tema, default_stat)
    share_url = "https://fimi.viajeinteligencia.com/"
    tw_url = "https://twitter.com/intent/tweet?text=" + _up.quote(share_txt)
    bsky_url = "https://bsky.app/intent/compose?text=" + _up.quote(share_txt)

    # mapa tema -> {txt, tw, bsky} para que el JS reescriba compartir al cambiar
    share_by_tema = {}
    for _t in temas:
        _st = temas_stats.get(_t, {"nombre": _t, "estado": "produccion",
                                   "clusters": 0, "high": 0})
        _txt = _share_txt_for(_t, _st)
        share_by_tema[_t] = {
            "txt": _txt,
            "tw": "https://twitter.com/intent/tweet?text=" + _up.quote(_txt),
            "bsky": "https://bsky.app/intent/compose?text=" + _up.quote(_txt),
        }
    import json as _json
    share_by_tema_js = _json.dumps(share_by_tema, ensure_ascii=False)
    steps = [
        ("01", "Captura", f"<b>{n_events}</b> eventos reales de <b>{n_sources}</b> fuentes: "
         "medios ES/FR/MA, RSS, Bluesky, Telegram y Reddit. Sin cuentas ni rastreo.",
         "Todo lo que el radar observa es <b>público</b>. La fuente más amplia del embudo.",
         "#eff6ff", "#1d4ed8"),
        ("02", "Amplificación", "Un <b>mismo titular se repite</b> en varias fuentes en pocas horas. "
         "Hecho observable: la noticia se propaga.", "Indica <b>eco</b> de una narrativa. "
         "Aún no es coordinación ni atribución.", "#e0f2fe", "#0369a1"),
        ("03", "Coordinación", "Cuentas de redes sociales distintas publican el <b>mismo enlace o texto "
         "casi idéntico</b> en una ventana corta (a diferencia del paso 02, donde es el <b>eco editorial</b> "
         "de los medios/RSS el que se repite: aquí es la pauta de las <b>cuentas</b> la que se iguala).",
         "Señal de posible <b>comportamiento coordinado</b>. El radar une esas cuentas en un cluster"
         " — puede ser una campaña de comunicación legítima (partido, ONG, institución) o amplificación "
         "artificial. El radar no distingue el motivo, solo la estructura.", "#fef3c7", "#b45309"),
        ("04", "Cluster y score", "El radar puntúa el grupo <b>0–100</b> y lo clasifica en banda "
         "NORMAL→WATCH→ANÓMALO→HIGH→CRITICAL.", "Cuanto más alto, más señales de actividad "
         "coordinada <b>observables</b>. Ver KPIs de arriba.", "#fed7aa", "#c2410c"),
        ("05", "Atribución", "¿Quién está detrás? Solo con <b>evidencia organizativa o financiera</b>.",
         "Sin prueba suficiente → <b>UNKNOWN</b>. Ese 'no sé quién' <b>es un resultado válido</b>, "
         "no un fallo.", "#fecaca", "#b91c1c"),
    ]
    funnel_cards = ""
    n_st = len(steps)
    for i, (num, title, what, means, bg, fg) in enumerate(steps):
        width = round(100 - (100 / n_st) * i * 0.8, 1)  # 100,84,68,52,36
        funnel_cards += f"""
      <div style="max-width:{width}%;margin:10px auto 0;background:{bg};border-left:5px solid {fg};
                  border-radius:10px;padding:12px 16px;box-shadow:0 1px 3px rgba(15,23,42,.08)">
        <div style="display:flex;gap:10px;align-items:flex-start">
          <span style="background:{fg};color:#fff;border-radius:999px;width:26px;height:26px;
                       min-width:26px;display:inline-flex;align-items:center;justify-content:center;
                       font-size:.8rem;font-weight:800">{num}</span>
          <div style="flex:1">
            <div style="font-weight:800;color:{fg};font-size:.95rem">{title}</div>
            <div style="font-size:.86rem;color:#0f172a;line-height:1.5">{what}</div>
            <div style="font-size:.78rem;color:#334155;margin-top:5px;line-height:1.45">
              <b style="color:{fg}">→ Significa:</b> {means}</div>
          </div>
        </div>
      </div>"""
    funnel_html = f"""
  <button id="btnComoLeer" type="button"
     onclick="funnelOpen()"
     style="margin:0 0 4px;cursor:pointer;border:1px solid #c2410c;background:#fff7ed;color:#c2410c;
            border-radius:999px;padding:7px 16px;font-weight:700;font-size:.82rem;font-family:inherit;
            display:inline-flex;align-items:center;gap:6px">🗺️ Cómo leer este radar</button>
  <div id="funnelOverlay" role="dialog" aria-modal="true" aria-labelledby="funnelTitle"
     style="position:fixed;inset:0;z-index:999;display:none;align-items:flex-start;justify-content:center;
            overflow-y:auto;background:rgba(15,23,42,.55);backdrop-filter:blur(2px);padding:24px 14px">
    <div style="background:#fff;max-width:640px;width:100%;border-radius:16px;padding:20px 20px 18px;
                box-shadow:0 20px 60px rgba(0,0,0,.3);max-height:92vh;overflow-y:auto;position:relative">
      <button type="button" onclick="funnelClose(false)"
        aria-label="Cerrar"
        style="position:sticky;top:0;float:right;cursor:pointer;border:none;background:#f1f5f9;color:#0f172a;
               border-radius:999px;width:30px;height:30px;font-size:1rem;font-weight:700;line-height:1">✕</button>
      <div style="text-align:center;margin-bottom:12px">
        <span style="display:inline-block;font-size:.7rem;font-weight:800;letter-spacing:.12em;
                     color:#c2410c;background:#fff7ed;border:1px solid #fed7aa;border-radius:999px;
                     padding:4px 12px">CÓMO LEER ESTE RADAR</span>
        <h2 id="funnelTitle" style="font-size:1.2rem;margin:.5rem 0 .2rem">Del ruido a la señal: el prisma analítico</h2>
        <p style="color:#475569;font-size:.84rem;margin:.4rem 0 0;line-height:1.5">Detección de coordinación
           y amplificación en el catálogo de temas monitorizados ({tema_lista_intro}).
           Agnóstico al actor: primero se observa la anomalía, después se evalúan hipótesis;
           la atribución nunca se presume.</p>
        <p style="color:#64748b;font-size:.86rem;margin:.5rem 0 0;line-height:1.5">Cada nivel filtra la información y se acerca al fondo.
           Solo el último escalón responde "¿quién?". Ninguno atribuye sin evidencia.</p>
      </div>
      {funnel_cards}
      <div style="margin-top:14px;padding:10px 14px;background:#fffbeb;border:1px solid #fde68a;
                  border-radius:8px;font-size:.78rem;color:#78350f;line-height:1.45">
        <b>Ajuste por tema:</b> el umbral de lo que se considera anómalo se calibra por tema — no todos
        los temas tienen el mismo volumen de conversación "normal".
      </div>
      <div style="text-align:center;margin-top:16px;padding-top:14px;border-top:1px dashed #e2e8f0">
        <p style="font-size:.86rem;color:#334155;margin:0 0 10px"><b>¿Has visto una señal que merezca difundirse?</b>
           Comparte este estado del radar (se actualiza cada 6 h):</p>
        <p id="sharePreview" style="font-size:.74rem;color:#94a3b8;background:#f8fafc;border:1px solid #e2e8f0;
           border-radius:8px;padding:6px 10px;margin:0 0 10px;line-height:1.4"></p>
        <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:center">
          <a id="linkShareX" href="{tw_url}" target="_blank" rel="noopener noreferrer"
             style="display:inline-flex;align-items:center;gap:6px;font-weight:700;font-size:.84rem;
                    color:#fff;background:#0f1419;border-radius:8px;padding:9px 15px;text-decoration:none">𝕏 Compartir en X</a>
          <a id="linkShareBsky" href="{bsky_url}" target="_blank" rel="noopener noreferrer"
             style="display:inline-flex;align-items:center;gap:6px;font-weight:700;font-size:.84rem;
                    color:#fff;background:#1185fe;border-radius:8px;padding:9px 15px;text-decoration:none">🦋 Compartir en Bluesky</a>
        <a href="https://t.me/Sieg_politica_bot" target="_blank" rel="noopener noreferrer"
           style="display:inline-flex;align-items:center;gap:6px;font-weight:700;font-size:.84rem;
                  color:#fff;background:#229ed9;border-radius:8px;padding:9px 15px;text-decoration:none">Recibir avisos en Telegram</a>
          <a href="https://ko-fi.com/m_castillo" target="_blank" rel="noopener noreferrer"
             style="display:inline-flex;align-items:center;gap:6px;font-weight:700;font-size:.84rem;
                    color:#fff;background:#13C3A5;border-radius:8px;padding:9px 15px;text-decoration:none">☕ Apoyar en Ko-fi</a>
        </div>
        <label style="display:inline-flex;align-items:center;gap:6px;margin-top:12px;cursor:pointer;
                      font-size:.78rem;color:#64748b">
          <input type="checkbox" id="funnelNoMostrar" style="accent-color:#c2410c"> No volver a mostrar esta guía
        </label>
      </div>
    </div>
  </div>
  <script>
  (function(){{
    var O=document.getElementById('funnelOverlay');
    var B=document.getElementById('btnComoLeer');
    var T=document.getElementById('funnelNoMostrar');
    var K='fimi_funnel_visto';
    function show(){{ O.style.display='flex'; }}
    function hide(dont){{ O.style.display='none'; if(dont&&T&&T.checked){{ try{{ localStorage.setItem(K,'1'); }}catch(e){{}} }} }}
    window.funnelOpen=function(){{ if(T){{ T.checked=false; }} show(); }};
    window.funnelClose=function(dont){{ hide(dont); }};
    if(O){{ O.addEventListener('click',function(e){{ if(e.target===O){{ hide(T?T.checked:false); }} }}); }}
    var visto='0'; try{{ visto=localStorage.getItem(K)||'0'; }}catch(e){{}}
    if(B){{ if(visto==='1'){{ B.style.display='none'; }} }}
    if(O&&visto!=='1'){{ show(); }}
  }})();
  </script>"""

    # ============================================================
    # VISTA RESUMEN (por defecto): diales por tema, nada más
    # ============================================================
    # color/valor del dial según tendencia + frase de contexto
    ESTADO_DIAL = {
        "subiendo":   {"txt": "Subiendo", "color": "#d97706", "valor": 75},
        "estable":    {"txt": "Estable",  "color": "#16a34a", "valor": 40},
        "bajando":    {"txt": "Bajando",  "color": "#64748b", "valor": 20},
        "recopilando":{"txt": "En recopilación", "color": "#94a3b8", "valor": 10},
    }
    dial_cards = ""
    for _t in temas:
        _m = temas_cfg.get(_t, {}) if isinstance(temas_cfg, dict) else {}
        _nombre = _m.get("nombre", _t)
        _estado_cfg = _m.get("estado", "produccion")
        _tr = tendencias.get(_t, {"estado": "estable", "hoy": 0, "hace48": 0,
                                  "high_hoy": 0, "high_48": 0})
        # contexto: piloto -> aviso; si no, frase de tendencia
        if _estado_cfg == "piloto":
            _frase = "piloto en calibración — lectura con cautela"
            _estado_dial = "recopilando"
            _estilo = ESTADO_DIAL["recopilando"]
        else:
            _estado_dial = _tr.get("estado", "estable")
            _estilo = ESTADO_DIAL.get(_estado_dial, ESTADO_DIAL["estable"])
            if _estado_dial == "recopilando":
                _frase = "sin datos suficientes aún (se está acumulando histórico)"
            elif _estado_dial == "subiendo":
                _frase = f"{_tr['hoy']} hallazgos hoy frente a {_tr['hace48']} hace 48h"
                if _tr["high_hoy"] > _tr["high_48"]:
                    _frase = f"{_tr['high_hoy']} clusters en alerta alta hoy, +{_tr['high_hoy'] - _tr['high_48']} vs hace 48h"
            elif _estado_dial == "bajando":
                _frase = f"{_tr['hoy']} hallazgos hoy frente a {_tr['hace48']} hace 48h"
            else:
                _frase = f"{_tr['hoy']} hallazgos hoy, sin cambio frente a hace 48h"
        dial_cards += (
            f"<div style='flex:1 1 260px;max-width:340px;background:#fff;border:1px solid #e2e8f0;"
            f"border-radius:16px;padding:18px 16px 14px;text-align:center;box-shadow:0 1px 3px rgba(15,23,42,.06)'>"
            f"<div style='font-size:.78rem;color:#475569;font-weight:700;text-transform:uppercase;"
            f"letter-spacing:.04em'>{_nombre}</div>"
            f"{render_dial_svg(_nombre, _estilo['valor'], _estilo['color'])}"
            f"<div style='font-size:1.5rem;font-weight:800;color:{_estilo['color']};line-height:1.1'>"
            f"{_estilo['txt']}</div>"
            f"<div style='font-size:.8rem;color:#64748b;margin:4px 0 10px;min-height:2.4em;line-height:1.35'>"
            f"{_frase}</div>"
            f"<button type='button' onclick='abrirDetalle(\"{_t}\")' "
            f"style='cursor:pointer;border:none;background:#c2410c;color:#fff;border-radius:999px;"
            f"padding:8px 18px;font-weight:700;font-size:.85rem;font-family:inherit'>"
            f"Ver detalle de este tema</button>"
            f"<div style='margin-top:12px;padding-top:10px;border-top:1px dashed #e2e8f0;text-align:center'>"
            f"<div style='font-size:.72rem;color:#94a3b8;margin-bottom:6px'>¿Te resulta útil este tema?</div>"
            f"<div style='display:flex;gap:6px;justify-content:center'>"
            f"<button type='button' data-voto='si' onclick='feedbackClick(\"{_t}\",\"si\",this)' "
            f"style='cursor:pointer;border:1px solid #d0d5dd;background:#fff;color:#334155;border-radius:8px;"
            f"padding:5px 12px;font-size:.78rem;font-weight:700;font-family:inherit'>Sí</button>"
            f"<button type='button' data-voto='no' onclick='feedbackClick(\"{_t}\",\"no\",this)' "
            f"style='cursor:pointer;border:1px solid #d0d5dd;background:#fff;color:#334155;border-radius:8px;"
            f"padding:5px 12px;font-size:.78rem;font-weight:700;font-family:inherit'>No</button>"
            f"<button type='button' data-voto='ns' onclick='feedbackClick(\"{_t}\",\"ns\",this)' "
            f"style='cursor:pointer;border:1px solid #d0d5dd;background:#fff;color:#334155;border-radius:8px;"
            f"padding:5px 12px;font-size:.78rem;font-weight:700;font-family:inherit'>No lo sé</button>"
            f"</div>"
            f"<div id='fbMsg_{_t}' style='font-size:.72rem;color:#16a34a;margin-top:6px;min-height:1em'></div>"
            f"</div></div>")
    # --- COMPARTIR AGREGADO (vista resumen): un solo texto con los 3 diales ---
    # Se construye desde los mismos datos que pintan los diales (tendencias +
    # catálogo config) para que el mensaje coincida con lo que se ve en pantalla.
    def _dial_palabra(_est):
        return {"subiendo": "Subiendo", "bajando": "Bajando",
                "estable": "Estable", "recopilando": "En recopilación"}.get(_est, _est)

    _partes_compartir = []
    for _t in temas:
        _m = temas_cfg.get(_t, {}) if isinstance(temas_cfg, dict) else {}
        _nom = re.sub(r"\s*\(.*\)\s*", "", _m.get("nombre", _t)).strip().title()
        _cfg_est = _m.get("estado", "produccion")
        _tend_est = tendencias.get(_t, {}).get("estado", "estable")
        _est_txt = _dial_palabra(_tend_est)
        if _cfg_est == "piloto":
            _est_txt += " (piloto)"
        _partes_compartir.append(f"{_nom}: {_est_txt}")
    _txt_agregado = ("Radar FIMI (" + now[:5] + ") — " +
                     " · ".join(_partes_compartir) +
                     ". Agnóstico al actor, sin atribución sin evidencia. https://fimi.viajeinteligencia.com")
    _tw_agregado = "https://twitter.com/intent/tweet?text=" + _up.quote(_txt_agregado)
    _bsky_agregado = "https://bsky.app/intent/compose?text=" + _up.quote(_txt_agregado)
    _share_resumen_buttons = (
        "<div style='display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:16px'>"
        f"<a href='{_tw_agregado}' target='_blank' rel='noopener noreferrer' "
        f"style='color:#fff;background:#0f1419;border-radius:8px;padding:9px 16px;text-decoration:none;"
        f"font-size:.85rem;font-weight:700'>𝕏 Compartir estado (X)</a>"
        f"<a href='{_bsky_agregado}' target='_blank' rel='noopener noreferrer' "
        f"style='color:#fff;background:#1185fe;border-radius:8px;padding:9px 16px;text-decoration:none;"
        f"font-size:.85rem;font-weight:700'>🦋 Compartir estado (Bluesky)</a>"
        f"<a href='https://t.me/Sieg_politica_bot' target='_blank' rel='noopener noreferrer' style='color:#fff;background:#229ed9;border-radius:8px;padding:9px 16px;text-decoration:none;font-size:.85rem;font-weight:700'>Recibir avisos en Telegram</a>"
        f"</div>")

    # --- FORMULARIO NEWSLETTER POR EMAIL (vista resumen) ---
    # checkboxes de tema + email + envío a /api/subscribe (doble opt-in).
    def _nombre_tema_clean(_t):
        _m = temas_cfg.get(_t, {}) if isinstance(temas_cfg, dict) else {}
        return re.sub(r"\s*\(.*\)\s*", "", _m.get("nombre", _t)).strip().title()

    _email_checks = []
    for _t in temas[:6]:
        _email_checks.append(
            f"<label style='display:inline-flex;align-items:center;gap:6px;"
            f"font-size:.82rem;color:#334155;margin:2px 12px 2px 0;cursor:pointer'>"
            f"<input type='checkbox' value='{_t}'> {_nombre_tema_clean(_t)}</label>")
    newsletter_form = (
        "<div id='newsletterBox' style='margin-top:20px;padding:18px 20px;border:1px solid #e2e8f0;"
        "border-radius:14px;background:#fff'>"
        "<div style='font-size:.95rem;font-weight:700;color:#1e293b;margin-bottom:2px'>"
        "📬 Newsletter por email</div>"
        "<div style='font-size:.78rem;color:#64748b;margin-bottom:10px'>Resumen semanal (cada lunes) "
        "con el estado de los diales de los temas que elijas. Doble opt-in: confirmarás por email "
        "antes de recibir nada. Baja en un clic desde cada correo.</div>"
        f"<div style='margin-bottom:8px'>{''.join(_email_checks)}</div>"
        "<div style='display:flex;gap:8px;flex-wrap:wrap;max-width:380px'>"
        "<input id='nlEmail' type='email' placeholder='tu@email.com' "
        "style='flex:1;min-width:200px;padding:9px 12px;border:1px solid #d0d5dd;border-radius:8px;"
        "font-size:.85rem;font-family:inherit'>"
        "<button id='nlBtn' type='button' onclick='newsletterClick()' "
        "style='cursor:pointer;border:none;background:#c2410c;color:#fff;border-radius:8px;"
        "padding:9px 16px;font-weight:700;font-size:.85rem;font-family:inherit'>Suscribirme</button>"
        "</div>"
        "<div id='nlMsg' style='font-size:.8rem;color:#16a34a;margin-top:8px;min-height:1.2em'></div>"
        "</div>")
    # --- SUGERIR TEMA (vista resumen): textarea + envío a /api/sugerir (rate-limit por IP) ---
    # Las sugerencias van a la tabla `sugerencias` (radar.db) y se reenvían al dueño
    # por Telegram. NO hay votación pública: son un canal privado dueño-usuario.
    sugerir_form = (
        "<div style='margin-top:14px;padding:18px 20px;border:1px solid #e2e8f0;"
        "border-radius:14px;background:#fff'>"
        "<div style='font-size:.95rem;font-weight:700;color:#1e293b;margin-bottom:2px'>"
        "💡 ¿Qué tema debería vigilar el radar?</div>"
        "<div style='font-size:.78rem;color:#64748b;margin-bottom:10px'>Sugerencias para ampliar el "
        "catálogo (frontera sur, UE-Marruecos, política nacional). Llegan directamente al autor.</div>"
        "<textarea id='sugerirTxt' maxlength='500' rows='2' placeholder='Ej.: desinformación sobre "
        "migración en Canarias…' "
        "style='width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #d0d5dd;"
        "border-radius:8px;font-size:.85rem;font-family:inherit;resize:vertical'></textarea>"
        "<div style='display:flex;align-items:center;gap:10px;margin-top:8px;flex-wrap:wrap'>"
        "<button id='sugerirBtn' type='button' onclick='sugerirClick()' "
        "style='cursor:pointer;border:none;background:#0f172a;color:#fff;border-radius:8px;"
        "padding:9px 16px;font-weight:700;font-size:.85rem;font-family:inherit'>Enviar sugerencia</button>"
        "<div id='sugerirMsg' style='font-size:.8rem;color:#16a34a;min-height:1.2em'></div>"
        "</div></div>")
    resumen_html = (
        f"<div id='vistaResumen'>"
        f"<p style='font-size:.9rem;color:#334155;margin:10px 0 4px'><b>¿Qué está pasando ahora?</b> "
        f"Estado de los temas monitorizados. Pulsa <b>ver detalle</b> si algo te interesa.</p>"
        f"<div style='display:flex;flex-wrap:wrap;gap:14px;justify-content:center;margin-top:8px'>"
        f"{dial_cards}</div>"
        f"{_share_resumen_buttons}"
        f"{newsletter_form}"
        f"{sugerir_form}"
        f"<div style='font-size:.72rem;color:#94a3b8;text-align:center;margin-top:10px'>"
        f"Tendencia: hallazgos de hoy frente a hace 48 h por tema. Actualizado cada 6 h.</div>"
        f"</div>")
    # el detalle completo queda oculto por defecto, detrás de "ver detalle"
    detalle_wrap_open = "<div id='vistaDetalle' hidden>"
    detalle_wrap_close = "</div>"
    resumen_html += (f"<button type='button' onclick='volverResumen()' id='btnVolver' hidden "
                     f"style='cursor:pointer;border:1px solid #c2410c;background:#fff;color:#c2410c;"
                     f"border-radius:999px;padding:7px 16px;font-weight:700;font-size:.84rem;"
                     f"font-family:inherit'>← Volver al resumen</button>")

    # cuerpo de clusters (por tema)
    # versión desplegada (git describe --tags; fallback a último commit corto)
    try:
        import subprocess as _sp
        _ver = (_sp.check_output(["git", "describe", "--tags", "--always"],
                                 cwd=str(ROOT), stderr=_sp.DEVNULL)
                .decode().strip())
    except Exception:
        _ver = "desarrollo"
    version_html = (f'<p style="font-size:.74rem;color:#999;margin:6px 0 0">'
                    f'<a href="https://github.com/mcasrom/hybrid-fimi-radar" target="_blank" '
                    f'rel="noopener noreferrer" style="color:#888">github.com/mcasrom/hybrid-fimi-radar</a>'
                    f' · <span title="{_ver}">{_ver}</span></p>')
    # --- Salud de las fuentes (health monitor) ---
    try:
        import importlib.util
        _spec = importlib.util.spec_from_file_location("health_fuentes", ROOT / "detection" / "health_fuentes.py")
        _hf = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_hf)
        _salud = _hf.analizar()
        salud_html = _hf._html(_salud)
    except Exception as _e:
        salud_html = (f"<div class='card'><h3>Salud de las fuentes</h3>"
                      f"<p class='caption'>No disponible: {_e}</p></div>")

    html = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>European Hybrid &amp; FIMI Radar · Multi-tema</title>
<meta name="description" content="Radar OSINT agnóstico al actor: detección de coordinación, amplificación y FIMI en el catálogo de temas monitorizados (frontera sur, geopolítica UE-Marruecos, política nacional). {n_events} eventos, {n_clusters} clusters. Actualizado cada 6h.">
<meta name="keywords" content="FIMI, hybrid threats, radar OSINT, desinformación, España, Marruecos, Ceuta, Melilla, UE-Marruecos, geopolítica, política nacional, coordinación de cuentas, amplificación de narrativas">
<link rel="canonical" href="https://fimi.viajeinteligencia.com/">
<meta property="og:type" content="website">
<meta property="og:title" content="FIMI Radar · {n_events} eventos, {n_clusters} clusters de coordinación">
<meta property="og:description" content="Radar OSINT agnóstico al actor en el catálogo de temas monitorizados (frontera sur, geopolítica UE-Marruecos, política nacional). {n_clusters} clusters señalados hoy ({n_high} HIGH). Sin atribución sin evidencia.">
<meta property="og:locale" content="es_ES">
<meta property="og:url" content="https://fimi.viajeinteligencia.com/">
<meta property="og:image" content="https://fimi.viajeinteligencia.com/og-preview.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:image" content="https://fimi.viajeinteligencia.com/og-preview.png">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="FIMI Radar · Multi-tema">
<meta name="twitter:description" content="{n_clusters} clusters de coordinación, {n_events} eventos de {n_sources} fuentes. Radar OSINT agnóstico al actor en varios temas.">
<meta name="robots" content="index, follow">
<meta name="theme-color" content="#c2410c">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" type="image/png" sizes="192x192" href="/icon-192.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="FIMI Radar">
<style>
:root{{color-scheme:light}}
body{{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#f8fafc;color:#0f172a}}
main{{max-width:960px;margin:0 auto;padding:20px 16px 56px}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:20px;margin:16px 0;box-shadow:0 1px 2px rgba(15,23,42,.04)}}
.card h3{{margin-top:0;font-size:1.02rem}}
.caption{{font-size:.84rem;color:#64748b;margin:.3rem 0}}
.kpis{{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}}
.fimi-pane[hidden], .fimi-pane.hidden{{display:none}}
a{{color:#c2410c}}
</style></head>
<body>
<main>
<p style="font-size:.82rem">
<a href="#metodologia" style="color:#c2410c">Metodología</a> · 
<a href="#fuentes" style="color:#c2410c">Fuentes y búsquedas</a> · 
<a href="https://github.com/mcasrom/hybrid-fimi-radar" target="_blank" rel="noopener noreferrer" style="color:#c2410c">GitHub</a>
</p>
<h1 style="font-size:1.5rem;margin:.2em 0">European Hybrid &amp; FIMI Radar</h1>
<p style="color:#475569">Detección de <strong>coordinación, amplificación y anomalías</strong> en el
catálogo de temas monitorizados: <strong>{tema_nombres_html}</strong>.
 <strong>Agnóstico al actor</strong>: primero se observa la anomalía, después se evalúan hipótesis;
la atribución nunca se presume.</p>

 {resumen_html}

 {funnel_html}

 {detalle_wrap_open}

<script>window.FIMI_SHARE = {share_by_tema_js};</script>

 {tabs_ui}

{narr_block}

{sost_html}

{hist_html}

{detalle_wrap_close}

<div class="card">
<h3 id="fuentes">Fuentes y búsquedas activas</h3>
<p class="caption">Inventario real de config.yaml: qué se vigila y con qué palabras. Para añadir o
quitar, edita <code>config.yaml</code> en el repo (docs/FUENTES.md lo documenta).</p>
<div style="display:flex;gap:24px;flex-wrap:wrap">
  <div style="flex:1;min-width:260px">
    <b style="font-size:.9rem">RSS / feeds ({len(feeds)})</b>
    <ul style="font-size:.82rem;color:#334155;padding-left:18px;line-height:1.7">{feeds_html}</ul>
  </div>
  <div style="flex:1;min-width:260px">
    <b style="font-size:.9rem">Palabras clave ({len(keywords)})</b>
    <ul style="font-size:.82rem;color:#334155;padding-left:18px;line-height:1.7">{kw_html}</ul>
    <b style="font-size:.9rem">Telegram</b>
    <p style="font-size:.82rem;color:#334155">{tg_html}</p>
    <b style="font-size:.9rem">Reddit</b>
    <p style="font-size:.82rem;color:#334155">{sr_html}</p>
  </div>
</div>
</div>

<div class="card">
<h3 id="metodologia">Metodología</h3>
<p class="caption">
- Fuentes: Bluesky (autenticado), Telegram público, Google News RSS, medios internacionales y RSS oficiales.<br>
- Bot de Telegram <b><a href="https://t.me/Sieg_politica_bot" target="_blank" rel="noopener noreferrer" style="color:#229ed9">@Sieg_politica_bot</a></b>: suscríbete para recibir avisos cuando cambie el estado de tus temas.
- Señales: sincronización temporal, contenido casi duplicado, amplificación, infraestructura compartida.<br>
- Scoring 0-100 con bandas NORMAL→CRITICAL. Cada cluster muestra sus componentes.<br>
- Atribución: módulo separado con taxonomía neutra y confianza NO/LOW/MEDIUM/HIGH.
  "No hay evidencia suficiente para atribuir" es un resultado válido.<br>
- Actualizado automáticamente cada 6h. Última actualización: {now}.
</p>
</div>

{salud_html}

<footer style="border-top:1px solid #e5e5e5;margin-top:28px;padding-top:18px;text-align:center">
  <div style="font-size:.85rem;color:#666;line-height:1.9">
    <b>Radar FIMI</b> · <a href="#metodologia" style="color:#c2410c">Metodología</a> · <a href="#fuentes" style="color:#c2410c">Fuentes y búsquedas</a> · <a href="https://github.com/mcasrom/hybrid-fimi-radar" target="_blank" rel="noopener noreferrer" style="color:#c2410c">GitHub</a> · <a href="https://www.viajeinteligencia.com" style="color:#c2410c">ViajeInteligencia</a>
  </div>
  <a href="https://ko-fi.com/m_castillo" target="_blank" rel="noopener noreferrer"
     style="display:inline-flex;align-items:center;gap:8px;font-weight:700;font-size:13.5px;color:#fff;background:#13C3A5;border-radius:7px;padding:11px 18px;margin-top:14px;text-decoration:none">☕ Invítame a un café</a>
  <p style="font-size:.78rem;color:#888;margin:10px 0 0">Proyecto personal, sin rastreo. Los servidores los paga su autor; el newsletter solo usa tu email para el envío y nada más.</p>
  {version_html}
</footer>
</main>
<script>
if ('serviceWorker' in navigator) {{
  navigator.serviceWorker.register('/sw.js').catch(function(e){{ console.warn('SW no registrado', e); }});
}}
</script>
<script>
(function(){{
  var shareMap = window.FIMI_SHARE || {{}};
  var estadoActivo = null;

  function updatePilotoBanner(t){{
    var btn=null, i, bs=document.querySelectorAll('[data-tema]');
    for(i=0;i<bs.length;i++){{ if(bs[i].getAttribute('data-tema')===t){{ btn=bs[i]; break; }} }}
    var estado = btn ? (btn.getAttribute('data-estado')||'produccion') : 'produccion';
    estadoActivo = estado;
    var bn=document.getElementById('pilotoBanner');
    if(bn){{ if(estado==='piloto'){{ bn.removeAttribute('hidden'); }} else {{ bn.setAttribute('hidden',''); }} }}
  }}

  function updateShare(t){{
    var s=shareMap[t];
    var x=document.getElementById('linkShareX');
    var bk=document.getElementById('linkShareBsky');
    var pv=document.getElementById('sharePreview');
    if(s){{
      if(x){{ x.href=s.tw; }}
      if(bk){{ bk.href=s.bsky; }}
      if(pv){{ pv.textContent=s.txt; }}
    }}
  }}

  function fimiTab(t){{
    var i, p, b;
    var btns=document.querySelectorAll('[data-tema]');
    for(i=0;i<btns.length;i++){{ b=btns[i];
      if(b.getAttribute('data-tema')===t){{
        b.style.background='#c2410c';b.style.color='#fff';b.style.borderColor='#c2410c';
      }}else{{
        b.style.background='#fff';b.style.color='#334155';b.style.borderColor='#e2e8f0';
      }}
    }}
    var panes=document.querySelectorAll('.fimi-pane');
    for(i=0;i<panes.length;i++){{ p=panes[i];
      if(p.getAttribute('data-tema')===t){{ p.classList.remove('hidden'); }}
      else {{ p.classList.add('hidden'); }}
    }}
    updatePilotoBanner(t);
    updateShare(t);
  }}
  window.fimiTab=fimiTab;

  // Detalle de los clusters WATCH/ANOMALOUS del gráfico de barras: al clicar
  // una barra, muestra su panel (uno solo a la vez) sin recargar la página.
  function fimiResto(cid){{
    var src=document.querySelector('.fimi-resto-detail[data-cid="'+cid+'"]');
    var pane=document.getElementById('fimiRestoPane');
    if(!src||!pane){{ return; }}
    pane.innerHTML = src.innerHTML;
    pane.style.display = 'block';
    var bs=document.querySelectorAll('.fimi-bar');
    for(var i=0;i<bs.length;i++){{
      var b=bs[i];
      var act = parseInt(b.getAttribute('data-cid'),10) === parseInt(cid,10);
      b.style.background = act ? '#f1f5f9' : 'transparent';
      b.style.borderColor = act ? '#c2410c' : 'transparent';
    }}
    pane.scrollIntoView({{behavior:'smooth', block:'nearest'}});
  }}
  window.fimiResto=fimiResto;

  // Navegación 2 vistas: resumen (diales) por defecto; detalle tras pulsar.
  function abrirDetalle(t){{
    var R=document.getElementById('vistaResumen');
    var D=document.getElementById('vistaDetalle');
    var B=document.getElementById('btnVolver');
    if(R){{ R.style.display='none'; }}
    if(D){{ D.removeAttribute('hidden'); }}
    if(B){{ B.removeAttribute('hidden'); }}
    fimiTab(t);
    window.scrollTo({{top:0, behavior:'smooth'}});
  }}
  function volverResumen(){{
    var R=document.getElementById('vistaResumen');
    var D=document.getElementById('vistaDetalle');
    var B=document.getElementById('btnVolver');
    if(R){{ R.style.display='block'; }}
    if(D){{ D.setAttribute('hidden',''); }}
    if(B){{ B.setAttribute('hidden',''); }}
    window.scrollTo({{top:0, behavior:'smooth'}});
  }}
  window.abrirDetalle=abrirDetalle;
  window.volverResumen=volverResumen;

  // Newsletter por email (vista resumen): POST /api/subscribe (doble opt-in).
  window.newsletterClick = function(){{
    var box=document.getElementById('newsletterBox');
    var email=(document.getElementById('nlEmail').value||'').trim().toLowerCase();
    var msg=document.getElementById('nlMsg');
    var btn=document.getElementById('nlBtn');
    if(!msg){{ return; }}
    msg.style.color='#16a34a';
    if(!email){{ msg.textContent='Escribe un email válido.'; msg.style.color='#dc2626'; return; }}
    var temas=[];
    var cbs=document.querySelectorAll('#newsletterBox input[type=checkbox]');
    for(var i=0;i<cbs.length;i++){{ if(cbs[i].checked){{ temas.push(cbs[i].value); }} }}
    if(temas.length===0){{ msg.textContent='Marca al menos un tema.'; msg.style.color='#dc2626'; return; }}
    btn.disabled=true; msg.textContent='Enviando…';
    fetch('/api/subscribe',{{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{email:email, temas:temas}})
    }}).then(function(r){{ return r.json(); }}).then(function(d){{
      btn.disabled=false;
      if(d && d.ok){{
        msg.textContent='✅ Revisa tu email y confirma la suscripción (doble opt-in).';
      }}else{{
        msg.textContent='No se pudo suscribir: '+(d&&d.error?d.error:'inténtalo más tarde.');
        msg.style.color='#dc2626';
      }}
    }}).catch(function(){{
      btn.disabled=false;
      msg.textContent='Error de red. Inténtalo de nuevo.'; msg.style.color='#dc2626';
    }});
  }};

  // Feedback ligero por tema (vista resumen): POST /api/feedback (rate-limit por IP).
  // Visible solo para el dueño; sin cómputo público de votos.
  window.feedbackClick = function(tema, voto, btn){{
    var msg=document.getElementById('fbMsg_'+tema);
    if(!msg){{ return; }}
    msg.style.color='#16a34a';
    msg.textContent='Enviando…';
    var btns=btn.parentNode.querySelectorAll('button');
    for(var i=0;i<btns.length;i++){{ btns[i].disabled=true; btns[i].opacity=0.6; }}
    fetch('/api/feedback',{{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{tema:tema, voto:voto}})
    }}).then(function(r){{ return r.json(); }}).then(function(d){{
      for(var i=0;i<btns.length;i++){{ btns[i].disabled=false; btns[i].opacity=1; }}
      if(d && d.ok){{
        msg.textContent='✅ Gracias por tu opinión.';
      }}else{{
        msg.textContent='No se guardó: '+(d&&d.error?d.error:'inténtalo más tarde.');
        msg.style.color='#dc2626';
      }}
    }}).catch(function(){{
      for(var i=0;i<btns.length;i++){{ btns[i].disabled=false; btns[i].opacity=1; }}
      msg.textContent='Error de red. Inténtalo de nuevo.'; msg.style.color='#dc2626';
    }});
  }};

  // Sugerir tema (vista resumen): POST /api/sugerir (rate-limit por IP).
  window.sugerirClick = function(){{
    var txt=(document.getElementById('sugerirTxt').value||'').trim();
    var msg=document.getElementById('sugerirMsg');
    var btn=document.getElementById('sugerirBtn');
    if(!msg){{ return; }}
    msg.style.color='#16a34a';
    if(!txt){{ msg.textContent='Escribe una sugerencia primero.'; msg.style.color='#dc2626'; return; }}
    btn.disabled=true; msg.textContent='Enviando…';
    fetch('/api/sugerir',{{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{texto:txt}})
    }}).then(function(r){{ return r.json(); }}).then(function(d){{
      btn.disabled=false;
      if(d && d.ok){{
        msg.textContent='✅ Sugerencia enviada al autor. ¡Gracias!';
        document.getElementById('sugerirTxt').value='';
      }}else{{
        msg.textContent='No se envió: '+(d&&d.error?d.error:'inténtalo más tarde.');
        msg.style.color='#dc2626';
      }}
    }}).catch(function(){{
      btn.disabled=false;
      msg.textContent='Error de red. Inténtalo de nuevo.'; msg.style.color='#dc2626';
    }});
  }};

  // Mensaje al volver de confirmar/baja (query param de email_api).
  var q=(location.search||'').replace('?','').split('&');
  for(var i=0;i<q.length;i++){{
    if(q[i]==='confirmado=1'){{ alert('✅ Suscripción confirmada. Cada lunes recibirás el resumen.'); }}
    else if(q[i]==='baja=1'){{ alert('Te has dado de baja del newsletter del radar.'); }}
  }}

  var hash=(location.hash||'').replace('#','');
  // deep-link #tema abre directamente el detalle de ese tema
  if(hash && document.querySelector('.fimi-pane[data-tema="'+hash+'"]')){{ abrirDetalle(hash); }}
}})();
</script>
</body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"OK: {OUT} — {n_events} eventos, {n_sources} fuentes, {len(clusters)} clusters")


if __name__ == "__main__":
    main()
