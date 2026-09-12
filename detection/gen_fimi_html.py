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
import time
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


def render_dial_svg(etiqueta, valor, color, ancho=180, banda=None, umbral=None):
    """Velocímetro SVG simple (sin librería). valor 0-100, color de banda.

    Semicírculo base gris + aguja que apunta a la posición del valor.
    El color de la aguja y de la etiqueta indica el estado (banda).
    ``ancho`` permite usarlo pequeño en cabeceras de pestaña sin que el
    viewBox se recorte (el alto se escala proporcional al viewBox 200x112).

    Opcionales para anclar el dial a la línea base del tema:
      ``banda`` = (p25, p75): dibuja la zona "normal" del tema (rango p25-p75
                  de los picos diarios recientes) como un arco sombreado + dos
                  marcas verticales en los extremos. La aguja fuera de esa
                  zona comunica más que el número.
      ``umbral`` = valor 0-100 donde empieza la banda de alerta del tema
                   (p.ej. 60 = HIGH); se dibuja una muesca roja.
    """
    import math as _m
    alto = int(ancho * 112 / 200)
    cx, cy, r = 100, 100, 72
    L = _m.pi * r  # longitud del semicírculo

    def _pt(v):
        # punto sobre el semicírculo superior para un valor 0-100 (0 izq, 100 der)
        v = min(100, max(0, v))
        th = _m.radians(180 - 180.0 * (v / 100.0))
        return (cx + r * _m.cos(th), cy - r * _m.sin(th))

    theta = _m.radians(180 - 180.0 * (min(100, max(0, valor)) / 100.0))
    px = cx + r * _m.cos(theta)
    py = cy - r * _m.sin(theta)
    # aguja más corta que el radio
    nx = cx + (r - 14) * _m.cos(theta)
    ny = cy - (r - 14) * _m.sin(theta)
    path_d = f"M {cx - r} {cy} A {r} {r} 0 0 1 {cx + r} {cy}"

    out = [f'<svg viewBox="0 0 200 112" width="{ancho}" height="{alto}" role="img" '
           f'aria-label="{etiqueta}: {valor:.0f}/100">']

    # zona "normal" del tema (rango p25-p75) sobre el arco base
    if banda and banda[0] is not None and banda[1] is not None:
        x1, y1 = _pt(banda[0])
        x2, y2 = _pt(banda[1])
        out.append(f'<path d="M {x1:.1f} {y1:.1f} A {r} {r} 0 0 1 {x2:.1f} {y2:.1f}" '
                   f'fill="none" stroke="#86efac" stroke-width="11" stroke-opacity="0.5" '
                   f'stroke-linecap="round"/>')
        # marcas + etiquetas p25/p75 (arriba si el valor es >50, abajo si no)
        for vv, lab in ((banda[0], "p25"), (banda[1], "p75")):
            xx, yy = _pt(vv)
            out.append(f'<line x1="{xx:.1f}" y1="{yy - 15:.1f}" x2="{xx:.1f}" y2="{yy + 13:.1f}" '
                       f'stroke="#16a34a" stroke-width="1.6" stroke-dasharray="2.5 2.5"/>')
            ty = yy + 22 if vv < 50 else yy - 13
            out.append(f'<text x="{xx:.1f}" y="{ty:.1f}" font-size="6.5" fill="#16a34a" '
                       f'text-anchor="middle" font-weight="700">{lab}</text>')

    # muesca del umbral de alerta (donde empieza HIGH, p.ej. 60)
    if umbral is not None:
        ux, uy = _pt(umbral)
        out.append(f'<line x1="{ux:.1f}" y1="{uy - 24:.1f}" x2="{ux:.1f}" y2="{uy + 6:.1f}" '
                   f'stroke="#dc2626" stroke-width="2"/>')

    out.append(f'<path d="{path_d}" fill="none" stroke="#e2e8f0" stroke-width="11" '
               f'stroke-linecap="round" stroke-dasharray="{L:.1f} {L:.1f}"/>')
    out.append(f'<line x1="{cx}" y1="{cy}" x2="{nx:.1f}" y2="{ny:.1f}" '
               f'stroke="{color}" stroke-width="4" stroke-linecap="round"/>')
    out.append(f'<circle cx="{cx}" cy="{cy}" r="6" fill="{color}"/>')
    out.append(f'<text x="{cx - r - 4}" y="{cy + 8}" font-size="9" fill="#94a3b8">0</text>')
    out.append(f'<text x="{cx + r + 1}" y="{cy + 8}" font-size="9" fill="#94a3b8">100</text>')
    out.append('</svg>')
    return "".join(out)


def render_sparkline(serie, color, ancho=180):
    """Mini tendencia SVG (sin librería) de hallazgos por día.

    ``serie`` = lista de (fecha_iso, count). Línea + área rellena de encima
    del último valor, sin etiquetas dentro (la cabecera con las fechas va
    fuera, en HTML). Diseño consistente con render_dial_svg.
    """
    if not serie:
        return ""
    n = len(serie)
    vals = [v for _, v in serie]
    vmax = max(vals) or 1
    W, H = 180, 42
    pad_l, pad_r, pad_t, pad_b = 3, 3, 5, 6
    coords = []
    for i, (d, v) in enumerate(serie):
        x = pad_l + (W - pad_l - pad_r) * i / (n - 1) if n > 1 else W / 2
        y = H - pad_b - (H - pad_t - pad_b) * (v / vmax)
        coords.append((x, y))
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area = (f"{coords[0][0]:.1f},{H - pad_b} {pts} {coords[-1][0]:.1f},{H - pad_b}")
    lx, ly = coords[-1]
    return (f'<svg viewBox="0 0 {W} {H}" width="{ancho}" height="{int(ancho * H / W)}" '
            f'role="img" aria-label="Tendencia de hallazgos últimos {n} días">'
            f'<polygon points="{area}" fill="{color}" opacity="0.12"/>'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.8" fill="{color}"/>'
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
    return (f'<details class="card" style="padding:12px 16px;background:#f8fafc">'
            f'<summary style="cursor:pointer;font-size:.88rem;font-weight:700;color:#475569">'
            f'Cómo leer los componentes (0-100)</summary>'
            f'<div style="display:flex;flex-wrap:wrap;gap:8px 18px;margin-top:8px">{rows}</div>'
            f'<p class="caption" style="margin:8px 0 0">Las barras miden cada señal de 0 a 100. '
            f'El score global pondera estos 4 componentes + la amplificación del tema.</p></details>')


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


def _sostenido_chip(diver):
    """Clasifica un cluster como 'eco puntual de 1 pieza' vs 'coordinación
    sostenida' según la diversidad de URLs y la ventana temporal (opción 3).

    diver: dict con {n_ev, n_urls, horas} o None. Criterios (solo lectura):
      - n_urls<=1 y n_ev>=2 -> eco puntual: varias cuentas comparten la MISMA
        pieza. No es patrón de larga duración.
      - n_ev>=10 y horas>=24 y n_urls>=3 -> coordinación sostenida: una misma
        red vertiendo muchas piezas a lo largo del tiempo.
    Devuelve el HTML del chip o "" si no aplica. NO toca el scoring: es contexto
    de interpretación para que el analista no lea el eco de una pieza como una
    campaña de larga duración (responde a 'no hay trayectoria, solo snapshot')."""
    if not diver:
        return ""
    n_ev = diver.get("n_ev", 0) or 0
    n_urls = diver.get("n_urls", 0) or 0
    horas = diver.get("horas", 0) or 0
    if n_urls <= 1 and n_ev >= 2:
        return ('<span style="display:inline-block;font-size:.72rem;color:#7c3aed;'
                'border:1px dashed #a78bfa;border-radius:999px;padding:1px 10px;'
                'font-weight:600;background:#f5f3ff">ecos de 1 pieza</span>')
    if n_ev >= 10 and horas >= 24 and n_urls >= 3:
        return ('<span style="display:inline-block;font-size:.72rem;color:#b45309;'
                'border:1px solid #f59e0b;border-radius:999px;padding:1px 10px;'
                'font-weight:600;background:#fffbeb">coordinación sostenida</span>')
    return ""


# S3 — propagación orgánica: el radar también sabe NO acusar. Según la matriz
# del modelo (sección 5 del análisis), una combinación de ALTA COORDINACIÓN con
# BAJA ANOMALÍA y SIN infraestructura común apunta a propagación orgánica (una
# oleada real de gente compartiendo el mismo hecho), no a una red inorgánica.
# El chip lo deja dicho en la tarjeta para que no se lea como señal de campaña
# lo que probablemente es eco de interés humano. Solo lectura: no toca scoring.
def _organico_chip(coordination_score=None, anomaly_score=None, infrastructure_score=None):
    try:
        coord = float(coordination_score or 0)
        anom = float(anomaly_score or 0)
        infra = float(infrastructure_score or 0)
    except (TypeError, ValueError):
        return ""
    if coord >= 70 and anom <= 20 and infra <= 30:
        return ('<span style="display:inline-block;font-size:.72rem;color:#0e7490;'
                'border:1px dashed #22d3ee;border-radius:999px;padding:1px 10px;'
                'font-weight:600;background:#ecfeff" title="Alta coordinación + '
                'baja anomalía + sin infraestructura común: probablemente '
                'propagación orgánica, no red inorgánica">☁️ posible propagación orgánica</span>')
    return ""


# S5 — matriz de evidencia del cluster: las dimensiones del modelo (sección 5
# del análisis) resumidas en una sola tabla para que el lector vea de un vistazo
# qué dimensiones soportan señal y cuáles están en "no concluyente". Es lectura
# de los componentes ya calculados (am/coord/anomalia/infra/densidad) + la
# atribución (actor) + la conclusión FIMI. NO calcula nada nuevo ni acusa: la
# inautenticidad se reporta honestamente como NO MEDIBLE (el radar no verifica
# identidades), y el actor sale de attribution (habitualmente UNKNOWN).
def _matriz_evidencia_html(comps, a, band, amp_global=None):
    def _qual(v):
        v = float(v or 0)
        if v >= 80:
            return "Muy alta"
        if v >= 60:
            return "Alta"
        if v >= 40:
            return "Media"
        if v >= 20:
            return "Baja"
        return "Muy baja"

    def _row(dim, lect, col="#334155"):
        return (
            f'<div style="display:flex;justify-content:space-between;gap:10px;'
            f'padding:3px 0;border-top:1px dashed #e2e8f0;font-size:.74rem">'
            f'<span style="color:#64748b;min-width:120px">{dim}</span>'
            f'<span style="text-align:right;color:{col};font-weight:600">{lect}</span></div>')

    coord = comps.get("coordination_score", 0) or 0
    anom = comps.get("anomaly_score", 0) or 0
    infra = comps.get("infrastructure_score", 0) or 0
    dens = comps.get("network_density", 0) or 0
    amp = amp_global if amp_global is not None else None

    actor = "UNKNOWN"
    actor_col = "#94a3b8"
    concluyente = "No concluyente"
    fimi_col = "#94a3b8"
    if a:
        try:
            _atr = str(a["attribution"] or "")
        except (KeyError, IndexError):
            _atr = ""
        try:
            _conf = str(a["attribution_confidence"] or "")
        except (KeyError, IndexError):
            _conf = ""
        if _atr and _atr.upper() not in ("", "UNKNOWN", "NO_ATTRIBUTION"):
            actor = _atr
            actor_col = "#b45309"
        if _conf.upper() == "HIGH":
            concluyente = "Concluyente (confianza HIGH)"
            fimi_col = "#9a3412"

    _amp_row = (_row("Amplificación", _qual(amp) + f" · {amp:.0f}/100 (global del tema)")
                if amp is not None else "")
    rows = (
        _amp_row +
        _row("Coordinación", _qual(coord) + f" · {coord:.0f}/100") +
        _row("Anomalía", _qual(anom) + f" · {anom:.0f}/100") +
        _row("Infraestructura", _qual(infra) + f" · {infra:.0f}/100") +
        _row("Densidad de red", _qual(dens) + f" · {dens:.0f}/100") +
        _row("Inautenticidad", "No medible (observaría cuentas, no identidades)",
             "#94a3b8") +
        _row("Actor extranjero", actor, actor_col) +
        _row("Evaluación FIMI", concluyente, fimi_col))

    return (
        f'<div style="background:#fff;border:1px solid #e2e8f0;border-radius:8px;'
        f'padding:8px 12px;margin:6px 0">'
        f'<div style="font-size:.72rem;color:#64748b;font-weight:600;'
        f'text-transform:uppercase;margin-bottom:2px">Matriz de evidencia '
        f'(5 dimensiones)</div>'
        f'{rows}'
        f'<div style="color:#94a3b8;font-size:.68rem;margin-top:4px">Lectura de '
        f'los componentes del cluster y su atribución. El sistema observa '
        f'comportamiento; la identidad no se presume.</div></div>')


def _cluster_detail_html(c, a, comps, contenido=None, diver=None, dominios=None, evidencia=None, amp_global=None):
    """Detalle completo de un cluster: contenido real (titulares) + barra
    overall + componentes con barra (X/100) + atribución + hipótesis (solo 2
    más probables) + chip de trayectoria (eco puntual vs coordinación
    sostenida). Sin frases por componente: están en la leyenda única.
    evidencia: lista opcional de eventos miembro {ts, source, author, title,
    text, url} para la cadena de evidencia colapsable (S2)."""
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

    ruido = False
    if a is not None:
        try:
            _asm_txt = a["assessment"] if isinstance(a, (dict, sqlite3.Row)) else getattr(a, "assessment", "")
            ruido = "Posible ruido de bajo volumen" in str(_asm_txt or "")
        except Exception:
            ruido = False
    ruido_html = (f'<span style="display:inline-block;font-size:.72rem;color:#6b7280;border:1px dashed #9ca3af;'
                  f'border-radius:999px;padding:1px 10px;font-weight:600;background:#f9fafb">'
                  f'Posible ruido de bajo volumen</span>' if ruido else "")

    h = (f'<div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:4px">'
         f'<b style="font-size:1.02rem">{c["cluster_label"]}</b>'
         f'<span style="font-size:1.25rem;color:{col}">{overall:.0f}/100</span>'
         f'<span style="font-size:.8rem;color:{col};background:{col}18;border:1px solid {col};'
         f'border-radius:999px;padding:1px 10px;font-weight:700">{band}</span>'
         f'{ruido_html}'
         f'{cuentas_html}'
         f'{_sostenido_chip(diver)}'
         f'{_organico_chip(comps.get("coordination_score"), comps.get("anomaly_score"), comps.get("infrastructure_score"))}'
         f'</div>')

    # S1 — SEÑAL, NO ATRIBUCIÓN: cabecera fija que aclara cómo leer el cluster
    # ANTES de ver peso/bandas. Cuando la atribución es UNKNOWN/NO_ATTRIBUTION
    # (lo habitual: el radar observa comportamiento, no identifica actores), se
    # muestra un banner explícito: la señal es real, la identidad NO está probada.
    _senal_html = ""
    if a:
        _atr_s = str(a["attribution"] or "").upper()
        _conf_s = str(a["attribution_confidence"] or "").upper()
        if ("UNKNOWN" in _atr_s) or ("NO_ATTRIBUTION" in _atr_s):
            _senal_html = (
                f'<div style="display:flex;align-items:center;justify-content:space-between;'
                f'gap:10px;flex-wrap:wrap;background:#f8fafc;border:1px solid #cbd5e1;'
                f'border-left:4px solid #64748b;border-radius:8px;padding:8px 12px;margin:6px 0 2px">'
                f'<span style="font-size:.78rem;font-weight:800;color:#0f172a">⚖️ SEÑAL, '
                f'NO ATRIBUCIÓN</span>'
                f'<span style="font-size:.72rem;color:#475569">Actor: <b>UNKNOWN</b> · evidencia '
                f'FIMI no concluyente — el radar detecta comportamiento coordinado, '
                f'no acusa a ningún actor sin pruebas.</span></div>')
        elif _conf_s != "HIGH":
            # Atribución como HIPÓTESIS (confianza baja/media), no concluyente:
            # se mantiene el banner para que no se lea como identidad probada.
            _senal_html = (
                f'<div style="display:flex;align-items:center;justify-content:space-between;'
                f'gap:10px;flex-wrap:wrap;background:#f8fafc;border:1px solid #cbd5e1;'
                f'border-left:4px solid #64748b;border-radius:8px;padding:8px 12px;margin:6px 0 2px">'
                f'<span style="font-size:.78rem;font-weight:800;color:#0f172a">⚖️ SEÑAL, '
                f'NO ATRIBUCIÓN</span>'
                f'<span style="font-size:.72rem;color:#475569">Actor: <b>{a["attribution"]}</b> '
                f'· hipótesis con confianza {a["attribution_confidence"]} — evidencia FIMI '
                f'NO concluyente; el radar no acusa a ningún actor sin pruebas.</span></div>')
    elif band in ("HIGH", "CRITICAL"):
        # sin assessment pero banda alta: al menos dejar claro que no hay atribución
        _senal_html = (
            f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;'
            f'background:#f8fafc;border:1px solid #cbd5e1;border-left:4px solid #64748b;'
            f'border-radius:8px;padding:8px 12px;margin:6px 0 2px">'
            f'<span style="font-size:.78rem;font-weight:800;color:#0f172a">⚖️ SEÑAL, NO '
            f'ATRIBUCIÓN</span>'
            f'<span style="font-size:.72rem;color:#475569">Sin datos de atribución: no se '
            f'acusa a ningún actor.</span></div>')

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
    # dominios amplificados (punto 5): cuántas cuentas comparten cada dominio,
    # para distinguir "eco del mismo medio" de una red que amplifica muchos.
    _dom_html = ""
    if dominios:
        import html as _dom_esc
        _dom_chips = "".join(
            f'<span style="display:inline-block;background:#fff;border:1px solid #e2e8f0;'
            f'border-radius:999px;padding:1px 8px;font-size:.72rem;color:#475569;margin:1px 4px 1px 0">'
            f'{_dom_esc.escape(x["dominio"])} <b style="color:#c2410c">· {x["n_cuentas"]} cuentas</b></span>'
            for x in dominios[:3])
        if _dom_chips:
            _dom_html = (f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;'
                         f'padding:8px 12px;margin:6px 0">'
                         f'<div style="font-size:.72rem;color:#64748b;font-weight:600;'
                         f'text-transform:uppercase;margin-bottom:2px">Dominios que amplifican '
                         f'({len(dominios)})</div>'
                         f'{_dom_chips}'
                         f'<div style="color:#94a3b8;font-size:.68rem;margin-top:4px">Cuentas del cluster '
                         f'compartiendo enlaces del mismo dominio — útil para distinguir eco de un medio '
                         f'de una red que amplifica fuentes variadas.</div></div>')
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
                         f'{list_items}'
                         f'<div style="font-size:.72rem;color:#64748b;margin-top:6px;border-top:1px dashed #e2e8f0;'
                         f'padding-top:5px">'
                         f'<a href="/api/export?cluster={c["cluster_label"]}&fmt=csv" '
                         f'style="color:#c2410c;text-decoration:none">📥 Exportar evidencia (CSV)</a>'
                         f' · <a href="/api/export?cluster={c["cluster_label"]}&fmt=json" '
                         f'style="color:#c2410c;text-decoration:none">JSON</a>'
                         f'</div></div>')

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

    # S2 — CADENA DE EVIDENCIA: <details> colapsable que sigue el hilo de cómo
    # se formó el cluster (eventos miembro en orden cronológico: cuándo, desde
    # qué fuente, qué cuenta, qué titular/enlace). Lectura interpretable sin
    # exportar; la lista completa está en /api/export. Aditivo, no toca scoring.
    _ev_html = ""
    if evidencia:
        import html as _ev_esc
        total = int(evidencia.get("total", 0)) or 0
        rows = evidencia.get("muestra") or []
        if rows:
            _items = ""
            for r in rows:
                _t_utc = time.strftime("%d %b %H:%M UTC", time.gmtime(r.get("ts") or 0))
                _src = _ev_esc.escape(str(r.get("source") or "?"))
                _auth = _ev_esc.escape(str(r.get("author") or ""))
                _title = _ev_esc.escape(str(r.get("title") or r.get("text") or ""))[:110]
                _url = _ev_esc.escape(str(r.get("url") or ""))
                _l = (f' <a href="{_url}" target="_blank" rel="noopener noreferrer" '
                      f'style="color:#c2410c;font-size:.7rem">↗</a>' if _url else "")
                _items += (
                    f'<div style="font-size:.73rem;color:#475569;line-height:1.35;'
                    f'padding:2px 0;display:flex;gap:8px;align-items:baseline">'
                    f'<span style="color:#94a3b8;white-space:nowrap;font-variant-numeric:'
                    f'tabular-nums">{_t_utc}</span>'
                    f'<span style="min-width:0;flex:1">“{_title}”{_l}'
                    f'<span style="color:#94a3b8"> · {_src}'
                    f'{" · " + _auth if _auth else ""}</span></span></div>')
            _extra = (f'<span style="color:#94a3b8;font-size:.7rem">… y {total - len(rows)} más '
                      f'(¡descarga el export para verlos todos):</span>'
                      if total and total > len(rows) else "")
            _ev_html = (
                f'<details style="background:#fff;border:1px solid #e2e8f0;border-radius:8px;'
                f'padding:4px 10px 8px;margin:6px 0">'
                f'<summary style="cursor:pointer;font-size:.72rem;color:#64748b;font-weight:600;'
                f'text-transform:uppercase;padding:4px 0">🔗 Cadena de evidencia '
                f'({total} eventos)</summary>'
                f'<div style="border-top:1px dashed #e2e8f0;margin-top:4px;padding-top:6px">'
                f'<div style="font-size:.7rem;color:#94a3b8;margin-bottom:4px">Eventos que '
                f'forman este cluster, en orden cronológico (primera → última aparición):</div>'
                f'{_items}'
                f'{_extra}'
                f'</div></details>')

    return (h + _senal_html + content_html + _dom_html + _ev_html
            + svg_score_bar(overall, band) + bars + _matriz_evidencia_html(comps, a, band, amp_global)
            + attr + hyp_html)


def render_cluster_cards(clus, asm, titulo_vacio="Sin clusters activos", contenido_map=None, diversidad_map=None, domains_map=None, evidencia_map=None, amp_global=None):
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
    diversidad_map = diversidad_map or {}
    evidencia_map = evidencia_map or {}
    # Progressive disclosure: solo los N clusters más altos se muestran
    # expandidos; el resto (incluidos los HIGH/CRITICAL que no entran en el top N)
    # va al bloque colapsado con el gráfico de barras. Evita panes de decenas de
    # miles de px cuando un tema tiene muchas señales en alerta (p.ej. frontera_sur
    # con ~68 HIGH/CRITICAL = ~60k px si se expanden todos).
    MAX_EXPAND = 6
    order = sorted(clus, key=lambda c: -(c["overall_score"] or 0))
    _cands = [c for c in order if band_of(c["overall_score"] or 0) in EXPANDED_BANDS]
    expandidos = _cands[:MAX_EXPAND]
    _exp_ids = {c["id"] for c in expandidos}
    resto = [c for c in order if c["id"] not in _exp_ids]

    out = ""
    # --- clusters HIGH/CRITICAL: detalle completo visible ---
    for c in expandidos:
        a = asm_by_cid.get(c["id"])
        comps = _cluster_comps(c, a)
        _bcol_out = BAND_COLORS[band_of(c["overall_score"] or 0)]
        out += (f'<div class="card" style="border-left:5px solid {_bcol_out}">{_cluster_detail_html(c, a, comps, contenido_map.get(c["id"]), diversidad_map.get(c["id"]), (domains_map or {}).get(c["id"]), evidencia_map.get(c["id"]), amp_global)}</div>')


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
            # color por banda (ahora el bloque "resto" incluye también HIGH/CRITICAL
            # que no entran en el top-N expandido)
            barcol_ = BAND_COLORS.get(band_, "#94a3b8")
            pct_ = max(2.0, min(100.0, overall_))
            # recorte por piso de masa: el assessment lo marca como ruido de
            # bajo volumen. Añadir anotación para que los "39/100" repetidos no
            # parezcan el mismo hallazgo clonado (es un techo de escala, no el
            # valor real de la señal).
            _rui = ""
            try:
                _asm_s = a_["assessment"] if isinstance(a_, (dict, sqlite3.Row)) else getattr(a_, "assessment", "")
                if "Posible ruido de bajo volumen" in str(_asm_s or ""):
                    _rui = ('<span title="Recortado por el piso de masa (<3 cuentas sin '
                            'volumen o infraestructura suficiente): el score crudo sería '
                            'más alto, pero la escala lo limita a banda WATCH para no '
                            'alarmar con señales de bajo volumen." style="display:inline-block;'
                            'font-size:.66rem;color:#9ca3af;border:1px dashed #d1d5db;'
                            'border-radius:999px;padding:0 6px;font-weight:600;margin-left:4px">'
                            'recortado por escala</span>')
            except Exception:
                _rui = ""
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
                f' · {nacc_} cuentas{_rui}</span></div>')
            # detalle completo pre-renderizado (lo mismo que HIGH/CRITICAL)
            _bcol_pool = BAND_COLORS[band_]
            pool += (f'<div class="fimi-resto-detail" data-cid="{cid}" hidden>'
                     f'<div style="border-left:5px solid {_bcol_pool}">{_cluster_detail_html(c, a_, comps_, contenido_map.get(cid), diversidad_map.get(cid), (domains_map or {}).get(cid), evidencia_map.get(cid), amp_global)}</div></div>')

        plural = "clusters" if len(resto) != 1 else "cluster"
        out += (f'<div class="card" style="padding:12px 16px;background:#fafaf9">'
                f'<details><summary style="cursor:pointer;font-weight:600;color:#475569;font-size:.9rem">'
                f'Ver los {len(resto)} {plural} restantes '
                f'(resto del listado, ordenado por score)</summary>'
                f'<p style="font-size:.74rem;color:#94a3b8;margin:8px 0 2px">Pulsa una barra para ver su detalle '
                f'(solo se muestra uno a la vez).</p>'
                f'{bars}'
                f'<div id="fimiRestoPane" style="display:none;margin-top:10px"></div>'
                f'{pool}'
                f'</details></div>')

    return out


RESEARCH_OUT = Path("/var/www/fimi/research.html")


def render_research_html(cfg, feeds, keywords, temas_cfg, temas):
    """Página /research: FIMI Radar Research (pregunta, datos, método,
    evidencia, incertidumbre, limitaciones, reproducción, dataset).

    Todo el contenido está anclado a artefactos reales del repo (docs/*.md,
    tests/, /api/export) y a la BD (cifras vivas del último ciclo). Es una
    página independiente generada en el mismo run que el dashboard para que
    los números no se anticuen entre ciclos."""
    import yaml
    _scr = (cfg or {}).get("scoring", {}) or {}
    _w_global = _scr.get("weights", {}) or {}
    _w_names = {
        "synchronization": "Sincronización",
        "content_similarity": "Contenido similar",
        "amplification": "Amplificación",
        "infrastructure": "Infraestructura",
        "network_density": "Densidad de red",
        "anomaly": "Anomalía",
    }
    _w_default = {
        "synchronization": 0.25, "content_similarity": 0.20,
        "amplification": 0.20, "infrastructure": 0.15,
        "network_density": 0.10, "anomaly": 0.10,
    }
    n_events = n_sources = n_clusters = n_ecos = n_sost = n_rss_ev = n_redes_ev = 0
    n_src_feeds = n_src_plt = n_src_tg = n_src_reddit = 0
    n_band = {}
    _gen = "—"
    _top_label = ""
    try:
        rc = sqlite3.connect(DB)
        rc.row_factory = sqlite3.Row
        n_events = rc.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        n_sources = rc.execute("SELECT COUNT(DISTINCT source) FROM events").fetchone()[0]
        n_src_feeds = rc.execute(
            "SELECT COUNT(DISTINCT source) FROM events WHERE source LIKE 'rss:%'").fetchone()[0]
        n_src_tg = rc.execute(
            "SELECT COUNT(DISTINCT source) FROM events WHERE source LIKE 'telegram:%'").fetchone()[0]
        n_src_reddit = rc.execute(
            "SELECT COUNT(DISTINCT source) FROM events WHERE source LIKE 'reddit:%'").fetchone()[0]
        n_src_plt = n_sources - n_src_feeds - n_src_tg - n_src_reddit
        n_rss_ev = rc.execute("SELECT COUNT(*) FROM events WHERE source LIKE 'rss:%'").fetchone()[0]
        n_redes_ev = n_events - n_rss_ev
        try:
            _ts = rc.execute("SELECT MAX(timestamp) FROM events").fetchone()[0]
            _gen = datetime.fromtimestamp(_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if _ts else "—"
        except Exception:
            _gen = "—"
        _rows = rc.execute("SELECT cluster_label, overall_score, tema_id FROM clusters").fetchall()
        n_clusters = len(_rows)
        for _c in _rows:
            s = _c["overall_score"] or 0
            b = "CRITICAL" if s >= 80 else "HIGH" if s >= 60 else "ANOMALOUS" if s >= 40 \
                else "WATCH" if s >= 20 else "NORMAL"
            n_band[b] = n_band.get(b, 0) + 1
        top = rc.execute("SELECT cluster_label, overall_score, tema_id FROM clusters"
                         " ORDER BY overall_score DESC LIMIT 1").fetchone()
        if top and top["cluster_label"]:
            _top_label = top["cluster_label"]
        n_ecos = n_sost = 0
        try:
            for r in rc.execute(
                    "SELECT ce.cluster_id AS id, COUNT(*) n_ev, COUNT(DISTINCT ce.url) n_urls,"
                    " MIN(ce.ts) mn, MAX(ce.ts) mx FROM cluster_events ce GROUP BY ce.cluster_id"):
                if (r["n_urls"] or 0) <= 1 and (r["n_ev"] or 0) >= 2:
                    n_ecos += 1
                if (r["n_ev"] or 0) >= 10 and (((r["mx"] or 0) - (r["mn"] or 0)) >= 86400) and (r["n_urls"] or 0) >= 3:
                    n_sost += 1
        except Exception:
            pass
        rc.close()
    except Exception as e:
        print(f"research: {e}")
    # --- método: pesos / bandas / escala (mismo criterio que la card Metodología) ---
    _w_rows = "".join(
        f"<tr><td>{_w_names.get(k, k)}</td>"
        f"<td style='text-align:right'>{int(round((_w_global.get(k, _w_default.get(k, 0)))) * 100)}%</td></tr>"
        for k in ["synchronization", "content_similarity", "amplification",
                  "infrastructure", "network_density", "anomaly"])
    _w_tabla = ("<table style='border-collapse:collapse;font-size:.78rem;width:100%;max-width:420px'>"
                "<tr style='border-bottom:1px solid #e2e8f0;background:#f8fafc'>"
                "<th style='text-align:left;padding:4px 8px'>Componente</th>"
                "<th style='text-align:right;padding:4px 8px'>Peso global</th></tr>"
                + _w_rows + "</table>")
    _bandas = _scr.get("bands", {}) or {
        "NORMAL": [0, 19], "WATCH": [20, 39], "ANOMALOUS": [40, 59],
        "HIGH": [60, 79], "CRITICAL": [80, 100]}
    _b_html = "".join(
        f"<span style='display:inline-block;margin:2px;padding:2px 8px;"
        f"border:1px solid #e2e8f0;border-radius:12px'>{b} {lo}–{hi}</span>"
        for b, (lo, hi) in _bandas.items())
    _sma = _scr.get("scale_min_accounts", {}) or {}
    _s_f = _scr.get("scale_floor", {}) or {}
    _s_b = _scr.get("scale_bonus", {}) or {}
    _s_o = _scr.get("origen_unico", {}) or {}
    _escala = (
        f"Cuentas mínimas para banda alta: {_sma.get('HIGH', '2')} (HIGH) y "
        f"{_sma.get('CRITICAL', '10')} (CRITICAL). Piso de masa: &lt;{_s_f.get('min_accounts', 3)} "
        f"cuentas = banda máx WATCH (&quot;posible ruido de bajo volumen&quot;), salvo "
        f"≥{_s_f.get('except_events', 10)} eventos sostenidos o infra ≥{_s_f.get('except_infra', 80)} "
        f"(entonces hasta HIGH, nunca CRITICAL). Bonus de masa +{_s_b.get('per_account', 0.08)}×cuentas "
        f"(tope {_s_b.get('cap', 3.5)} pts). Tope &quot;origen único&quot;: ≤{_s_o.get('max_urls', 1)} "
        f"URL y ≥{_s_o.get('min_events', 2)} eventos = eco de 1 pieza, máx "
        f"{_s_o.get('cap_band', 'ANOMALOUS')}."
    )
    _t_over = []
    for _t in temas:
        _ts = (temas_cfg.get(_t, {}) or {}).get("scoring", {}) or {}
        if not _ts:
            continue
        _tw = _ts.get("weights", {}) or {}
        _partes = []
        if _tw:
            _partes.append("pesos " + ", ".join(
                f"{_w_names.get(k, k)} {int(round(v * 100))}%" for k, v in _tw.items()))
        if _ts.get("scale_min_accounts"):
            _partes.append("mín. cuentas " + ", ".join(
                f"{k} {v}" for k, v in _ts["scale_min_accounts"].items()))
        if _ts.get("scale_floor"):
            _sf = _ts["scale_floor"]
            _partes.append(f"piso &lt;{_sf.get('min_accounts', 3)} cuentas, except. ev {_sf.get('except_events', 10)}")
        if _partes:
            _t_over.append(f"<li><b>{_t}</b>: {' · '.join(_partes)}</li>")
    _over_html = ("<ul style='margin:6px 0 0 18px;padding:0'>" + "".join(_t_over) + "</ul>" if _t_over
                  else "<p style='color:#94a3b8'>Ningún tema define calibración propia (todos usan los globales).</p>")

    _fuentes_txt = (f"<b>{n_sources}</b> fuentes de captura con eventos recientes"
                    f" ({n_src_feeds} feeds RSS · {n_src_plt} plataformas · {n_src_tg} Telegram · "
                    f"{n_src_reddit} subreddits). De los <b>{n_events}</b> eventos en ventana, "
                    f"{n_rss_ev} vienen de feeds (lectura ancilar de prensa) y {n_redes_ev} de redes/plataformas "
                    f"(cuentas sociales = el grafo de coordinación).")
    _evidencia_txt = (f"En el ciclo actual el radar mantiene <b>{n_clusters}</b> cluster(s) de coordinación: "
                      f"{n_band.get('CRITICAL', 0)} CRITICAL · {n_band.get('HIGH', 0)} HIGH · "
                      f"{n_band.get('ANOMALOUS', 0)} ANOMALOUS · {n_band.get('WATCH', 0)} WATCH · "
                      f"{n_band.get('NORMAL', 0)} NORMAL. De ellos, {n_ecos} son &quot;ecos de 1 pieza&quot; "
                      f"(varias cuentas compartiendo la misma URL) y {n_sost} muestran &quot;coordinación "
                      f"sostenida&quot; (la misma red vertiendo varias piezas a lo largo de &gt;1 día).")
    _tabs_temas = " · ".join(f"<a href='/#{t}'>#{t}</a>" for t in temas) or "/"
    _dataset_link = (f"/api/export?cluster={_top_label}&fmt=csv" if _top_label
                     else "/api/export?fmt=csv")
    _top_link = f"/#{(top and top['tema_id']) or 'frontera_sur'}" if (top and top["cluster_label"]) else "/"

    page = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FIMI Radar · Research — pregunta, datos, método, evidencia e incertidumbre</title>
<meta name="description" content="Nota de investigación del radar FIMI: qué detecta, qué datos observa, cómo lo mide, qué ha encontrado, qué no se sabe, qué puede fallar, cómo reproducirlo y qué se puede descargar.">
<meta name="robots" content="index, follow">
<meta name="theme-color" content="#c2410c">
<link rel="icon" type="image/png" sizes="192x192" href="/icon-192.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta property="og:title" content="FIMI Radar · Research">
<meta property="og:description" content="De la pregunta a la incertidumbre: cómo detecta el radar FIMI coordinación y amplificación, qué puede equivocarse y cómo repetirlo.">
<meta property="og:image" content="/og-preview.png">
<meta name="twitter:card" content="summary_large_image">
<style>
:root{{color-scheme:light}}
body{{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#f8fafc;color:#0f172a}}
main{{max-width:900px;margin:0 auto;padding:20px 16px 56px}}
a{{color:#c2410c}}
.card{{background:#fff;border:1.5px solid #cbd5e1;border-radius:14px;padding:20px;margin:16px 0;box-shadow:0 1px 3px rgba(15,23,42,.06)}}
.card h2{{margin-top:0;font-size:1.05rem}}
.card h2 .num{{color:#c2410c}}
.caption{{font-size:.84rem;color:#64748b;margin:.3rem 0}}
li{{margin:3px 0}}
code{{background:#f1f5f9;border:1px solid #e2e8f0;border-radius:5px;padding:0 4px;font-size:.85em}}
.fimi-brandbar{{position:sticky;top:0;z-index:100;display:flex;flex-wrap:wrap;align-items:center;gap:9px 14px;background:#fff;border-bottom:1px solid #e2e8f0;box-shadow:0 1px 3px rgba(15,23,42,.06);padding:11px 16px;font-size:.86rem}}
.fimi-brandbar .brand{{display:inline-flex;align-items:center;gap:8px;font-weight:800;font-size:1.08rem;color:#0f172a;text-decoration:none}}
.fimi-brandbar .logo{{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:8px;background:linear-gradient(135deg,#c2410c,#9a3412);color:#fff;font-size:.95rem;box-shadow:0 1px 2px rgba(0,0,0,.15)}}
.fimi-brandbar .nav{{display:inline-flex;flex-wrap:wrap;gap:6px}}
.fimi-brandbar a.nlink{{color:#475569;font-weight:700;font-size:.9rem;text-decoration:none;padding:7px 12px;border-radius:9px;border:1px solid transparent}}
.fimi-brandbar a.nlink:hover{{color:#c2410c;background:#fff7ed}}
.fimi-brandbar a.nlink.active{{color:#c2410c;background:#fff7ed;border-color:#fdba74}}
.fimi-brandbar .chips{{display:inline-flex;flex-wrap:wrap;gap:6px;margin-left:auto}}
.fimi-brandbar .chip{{display:inline-flex;align-items:center;gap:6px;font-size:.78rem;font-weight:700;color:#334155;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:999px;padding:4px 11px}}
.fimi-brandbar .chip .dot{{width:7px;height:7px;border-radius:50%;background:#16a34a}}
@media(max-width:560px){{.fimi-brandbar .chips{{margin-left:0;width:100%}}}}
.hero{{margin:26px 0 8px}}
.hero h1{{margin:0 0 6px;font-size:1.6rem}}
.hero .sub{{color:#475569;font-size:.95rem;max-width:100%}}
.footer{{border-top:1px solid #e2e8f0;margin-top:34px;padding:18px 0 0;font-size:.82rem;color:#64748b}}
.footer a{{color:#c2410c;text-decoration:none}}
</style>
</head>
<body>
<header>
  <div class="fimi-brandbar">
    <a class="brand" href="/"><span class="logo">📡</span> Radar FIMI</a>
    <div class="nav">
      <a class="nlink" href="/">Radar</a>
      <a class="nlink" href="/#transparencia">Transparencia</a>
      <a class="nlink active" href="/research.html">Research</a>
    </div>
    <div class="chips"><span class="chip"><span class="dot"></span> En producción</span></div>
  </div>
</header>
<main>
  <div class="hero">
    <h1>FIMI Radar · Research</h1>
    <p class="sub">Notas de investigación del radar de manipulación informativa:
      lo que queremos detectar, los datos que observamos, cómo lo medimos, qué hemos
      encontrado, qué no sabemos, qué puede equivocarse, cómo repetirlo y qué se
      puede descargar. Herramienta OSINT <b>agnóstica al actor</b>: nunca atribuimos
      sin evidencia. Cifras del último ciclo — generado <b>{_gen}</b>.</p>
  </div>

  <div class="card">
    <h2><span class="num">01 —</span> Pregunta: ¿qué queremos detectar?</h2>
    <p>Comportamiento <b>coordinado e inorgánico</b> en cuentas abiertas en español que sugiere
      una campaña de manipulación o interferencia informativa (FIMI): amplificación artificial,
      sincronía de publicación, repetición de las mismas piezas y patrones de red anómalos.</p>
    <ul>
      <li>¿Cuándo una discusión es orgánica y cuándo parece orquestada?</li>
      <li>¿Qué cuentas amplifican qué piezas, con qué timing y qué estructura de red?</li>
      <li>¿La señal es un <b>eco de una sola pieza</b> o una <b>coordinación sostenida</b>?</li>
    </ul>
    <p class="caption">Regla de oro: OBSERVACIÓN → ANOMALÍA → COORDINACIÓN → CLUSTER → CAMPAÑA
      → HIPÓTESIS DE ACTOR → ATRIBUCIÓN CON NIVEL DE CONFIANZA. Nunca al revés. Ver
      <a href="/#que-es-fimi">qué es FIMI</a> y
      <a href="https://github.com/mcasrom/hybrid-fimi-radar">el README del proyecto</a>.</p>
  </div>

  <div class="card">
    <h2><span class="num">02 —</span> Datos: ¿qué observamos?</h2>
    <p>{_fuentes_txt}</p>
    <ul>
      <li><b>Temas monitorizados:</b> {_tabs_temas} (catálogo curado en
        <code>config.yaml</code>: feeds + keywords, no todo el ruido de internet).</li>
      <li><b>Ventana de captura:</b> 90 días (alineada con la retención); cada ciclo (6&nbsp;h)
        añade nuevos eventos y regenera el análisis.</li>
      <li><b>Idiomas:</b> mayoritariamente español, francés e inglés, con 1 fuente en árabe
        (decisión editorial del alcance; ver <a href="/#fuentes">fuentes y búsquedas activas</a>).</li>
      <li>Catálogo completo con sesgo/fiabilidad/transparencia por fuente en
        <a href="https://github.com/mcasrom/hybrid-fimi-radar/blob/main/docs/FUENTES.md">docs/FUENTES.md</a>.</li>
    </ul>
    <p class="caption">La captura regenera los eventos cada ciclo; la retención es de 90&nbsp;días
      para <code>events</code> y hallazgos (política documentada en el repo).</p>
  </div>

  <div class="card">
    <h2><span class="num">03 —</span> Método: ¿cómo lo medimos?</h2>
    <ol>
      <li><b>Captura</b> de fuentes abiertas (feeds RSS + Bluesky + Google News + Telegram + Reddit).</li>
      <li><b>Limpieza y dedupe</b> (los RSS no entran al grafo de coordinación: son lectura ancilar; el
        grafo se construye solo con cuentas sociales).</li>
      <li><b>Etiquetado multi-tema</b> por contenido (un evento puede pertenecer a varios temas).</li>
      <li><b>Análisis de coordinación:</b> centroides TF-IDF (sparse) por cuenta → grafo → clustering
        → puntuación por componentes.</li>
      <li><b>Decisión editorial, no automática:</b> el sistema sugiere; el dueño decide
        (alta/cierre/promoción vía <code>temas_cli.py</code> y bitácora).</li>
    </ol>
    <p>Pesos de la puntuación (globales; cada tema puede calibrar su override en
      <code>config.yaml</code>):</p>
    {_w_tabla}
    <p style="margin-top:8px">Bandas: {_b_html}</p>
    <p class="caption">{_escala}</p>
    <p>Calibración por tema:{_over_html}</p>
    <p class="caption">Detalle y fórmula completa (con el antes/después de cada ajuste de escala):
      <a href="https://github.com/mcasrom/hybrid-fimi-radar/blob/main/docs/SCORING.md">docs/SCORING.md</a>.</p>
  </div>

  <div class="card">
    <h2><span class="num">04 —</span> Evidencia: ¿qué encontramos?</h2>
    <p>{_evidencia_txt}</p>
    <ul>
      <li><b>Clusters activos por tema:</b> {_tabs_temas}, ordenados por score en el
        <a href="{_top_link}">dashboard</a>.</li>
      <li><b>Ejemplos documentados de tipos de hallazgo:</b> el detector separa el
        <b>eco de una pieza</b> (misma URL repetida por varias cuentas) de la
        <b>coordinación sostenida</b> (una red que vierte piezas durante días); ambos casos se
        han producido sobre temas reales (p. ej. narrativas de frontera sur y pares de cuentas
        con volumen sostenido de una sola pieza, que la escala de masa deja en su banda correcta).</li>
      <li><b>Validación sintética:</b> <code>tests/generate_synthetic.py</code> mide que el pipeline
        recupera las campañas inyectadas sin falsos positivos (ARI 1.000 sobre el conjunto de prueba).</li>
      <li><b>Validación externa:</b> cruce contra el corpus EUvsDisinfo en
        <code>tests/validacion_externa.py</code>; la interpretación (incluido por qué el cruce da
        0% por diseño) está documentada en el propio test y abajo en Incertidumbre.</li>
    </ul>
  </div>

  <div class="card">
    <h2><span class="num">05 —</span> Incertidumbre: ¿qué no sabemos?</h2>
    <ul>
      <li><b>Atribución:</b> la salida <code>UNKNOWN</code> es un resultado válido. No inferimos
        actores; RDAP aporta señales de registro/transferencia/privacidad de dominios, nunca
        identidades. Ver
        <a href="https://github.com/mcasrom/hybrid-fimi-radar/blob/main/docs/ATRIBUCION-LIMITACIONES.md">docs/ATRIBUCION-LIMITACIONES.md</a>.</li>
      <li><b>Validación externa limitada:</b> el benchmark contra EUvsDisinfo (catálogo 2015-23,
        Ucrania/Rusia) arroja precisión y recall 0% sobre la vista activa; parte es explicable por
        diseño (los RSS no entran al grafo y el catálogo no cubre los temas vivos del radar:
        Ceuta/Marruecos/España/EEUU/Oriente Medio). Es un hueco de validación, no una prueba de
        ausencia de campañas.</li>
      <li><b>Identificadores inestables:</b> los <code>cluster_label</code> se regeneran en cada
        ciclo → el delta de un cluster individual no es trazable entre ciclos; solo hay línea base
        a nivel de tema (percentiles p25-p75, media 14&nbsp;días).</li>
      <li><b>Sesgo de cobertura:</b> solo vemos lo que las fuentes del catálogo ven. Una campaña que
        no toque esas fuentes no produce señal (ausencia de dato ≠ ausencia de campaña).</li>
    </ul>
  </div>

  <div class="card">
    <h2><span class="num">06 —</span> Limitaciones: ¿qué puede equivocarse?</h2>
    <ul>
      <li><b>Ceguera de plataformas:</b> sin TikTok, X, Instagram ni WhatsApp; solo Bluesky, Google
        News, Telegram (canales públicos) y Reddit.</li>
      <li><b>RSS fuera del grafo:</b> veinte medios republicando una pieza <b>no</b> forman un
        cluster (por diseño); el radar mide coordinación de cuentas, no eco de prensa.</li>
      <li><b>Solo texto:</b> sin análisis de imagen, vídeo ni deepfakes (no viable en un server de
        3,7&nbsp;GB sin GPU).</li>
      <li><b>Escala convive con señal:</b> clusters de &lt;3 cuentas se recortan a WATCH salvo
        excepción por volumen/infraestructura — puede dejar fuera redes pequeñas pero reales.</li>
      <li><b>Retención 90&nbsp;días:</b> lo anterior a 90 días no forma parte del análisis.</li>
      <li><b>Indicación de lectura:</b> los diales y bandas son señales de un sistema en calibración
        continua; los temas en piloto se marcan como tal en el dashboard.</li>
    </ul>
  </div>

  <div class="card">
    <h2><span class="num">07 —</span> Reproducción: ¿cómo repetirlo?</h2>
    <ol>
      <li>Clonar <code>github.com/mcasrom/hybrid-fimi-radar</code> y crear el venv de Python con
        dependencias.</li>
      <li>Configurar el entorno (<code>FIMI_ADMIN_SECRET</code> y tokens en <code>.env</code>;
        el catálogo de fuentes/keywords/temas vive en <code>config.yaml</code>).</li>
      <li>Lanzar <code>scripts/cron_every_6h.sh</code> (captura → análisis → dashboard) o por tema:
        <code>detection/run_fimi.py --tema &lt;slug&gt;</code>.</li>
      <li>Regenerar páginas con <code>detection/gen_fimi_html.py</code> (dashboard + esta página).</li>
      <li>Gestión de temas vía <code>detection/temas_cli.py</code> (alta/cierre/estado) con bitácora
        metodológica.</li>
    </ol>
    <p class="caption">Reproducibilidad acotada por los datos: la retención de 90&nbsp;días limita
      cuánto atrás puede repetirse un análisis completo; el pipeline en sí es repetible idéntico
      sobre los mismos datos.</p>
  </div>

  <div class="card">
    <h2><span class="num">08 —</span> Dataset: ¿qué podemos descargar?</h2>
    <ul>
      <li><b>Evidencia por cluster</b> (los eventos, fuentes, autores y URLs que forman cada cluster):
        botón «Exportar evidencia» en cada tarjeta del dashboard, o por API:
        <code><a href="{_dataset_link}">/api/export?cluster=&lt;label&gt;&amp;fmt=csv|json</a></code>
        (ejemplo vivo: <a href="{_dataset_link}">CSV del cluster top actual</a>,
        {_top_label or 'sin cluster top en este ciclo'}).</li>
      <li><b>Export a auditores:</b> <code>detection/export_evidencia.py --list/--cluster/--out</code>
        (registro en <code>data/export/</code>).</li>
      <li><b>Export de cierre de tema:</b> <code>temas_cli.py cerrar</code> empaqueta hallazgos,
        clusters, bitácora y estadísticas en JSON permanente.</li>
    </ul>
    <p class="caption">No publicamos un volcado masivo de la BD por decisión metodológica
      (contiene metadatos de posts públicos y la ventana es móvil); el dataset accionable es el de
      evidencia por cluster, descargable en cada ciclo.</p>
  </div>

  <div class="footer">
    Radar FIMI · <a href="/research.html">Research</a> · <a href="/#transparencia">Transparencia</a> ·
    <a href="https://github.com/mcasrom/hybrid-fimi-radar">GitHub ↗</a> ·
    <a href="https://viajeinteligencia.com">viajeinteligencia.com</a>
  </div>
</main>
</body></html>"""
    RESEARCH_OUT.parent.mkdir(parents=True, exist_ok=True)
    RESEARCH_OUT.write_text(page, encoding="utf-8")
    print(f"OK: {RESEARCH_OUT} — {n_events} eventos, {n_clusters} clusters, ecos {n_ecos}, sostenidas {n_sost}")


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

    ax_col = {"alta": "#065f46", "media": "#92400e", "baja": "#475569"}
    rel_col = {"high": "#065f46", "mostly-factual": "#166534", "mixed": "#92400e",
               "low": "#b91c1c", "state": "#334155"}
    def _ax_chip(f, key, labels, colors):
        v = f.get(key, "")
        if not v:
            return ""
        lab = labels.get(v, v)
        col = colors.get(v, "#475569")
        return (f"<span style='border:1px solid {col};color:{col};border-radius:999px;"
                f"padding:0 7px;font-size:.72rem;line-height:1.6'>{lab}</span>")
    bias_lab = {"least-biased": "LEAST BIASED", "center": "CENTER", "center-left": "CENTER-LEFT",
                "center-right": "CENTER-RIGHT", "left": "LEFT", "right": "RIGHT", "state": "STATE"}
    rel_lab = {"high": "high", "mostly-factual": "mostly-factual", "mixed": "mixed",
               "low": "low", "state": "state"}
    ax_lab = {"alta": "relevancia analítica alta", "media": "relevancia analítica media",
              "baja": "relevancia analítica baja"}
    feeds_html = ""
    for f in feeds:
        pais = f.get("pais", "")
        url = f.get("url", "")
        _ch = (_ax_chip(f, "bias", bias_lab, {"least-biased": "#0e7490", "center": "#475569",
                "center-left": "#1d4ed8", "center-right": "#b45309", "left": "#7c3aed",
                "right": "#b91c1c", "state": "#334155"}) +
               _ax_chip(f, "reliability", rel_lab, rel_col) +
               _ax_chip(f, "analytical_relevance", ax_lab, ax_col))
        feeds_html += (f"<li>{f.get('nombre','?')} "
                       f"<span style='color:#94a3b8;font-size:.8rem'>· {url}"
                       f"{' · ' + pais if pais else ''}</span>"
                       f"{'<br>' + _ch if _ch else ''}</li>")
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
    # S2 — cadena de evidencia por cluster: los eventos miembro (ts, fuente,
    # autor, titular, URL) en orden cronológico, para que el analista pueda
    # seguir el hilo de CÓMO se formó el cluster. Solo lectura; se limita a
    # pocos eventos por cluster en la tarjeta (el export tiene la lista completa).
    evidencia_map = {}
    try:
        _cev = con.execute(
            "SELECT cluster_id, ts, source, author, title, text, url"
            " FROM cluster_events ORDER BY cluster_id, ts").fetchall()
        from collections import defaultdict
        _ev_acc = defaultdict(list)
        for r in _cev:
            _ev_acc[r["cluster_id"]].append(r)
        for _cid, _rows in _ev_acc.items():
            evidencia_map[_cid] = {
                "total": len(_rows),
                "muestra": [dict(x) for x in _rows[:7]],
            }
    except Exception:
        evidencia_map = {}
    # diversidad de piezas por cluster (opción 3): nº de URLs distintas vs nº
    # de eventos y ventana temporal (min->max ts). Distingue un "eco puntual de
    # una pieza" (varias cuentas comparten la MISMA url) de una "coordinación
    # sostenida" (misma red, muchas piezas, ventana larga). Solo lectura, no
    # toca scoring; da contexto de interpretación al analista.
    diversidad_map = {}
    try:
        _div = con.execute(
            "SELECT cluster_id, COUNT(*) n_ev, COUNT(DISTINCT url) n_urls,"
            " MIN(ts) min_ts, MAX(ts) max_ts FROM cluster_events"
            " GROUP BY cluster_id").fetchall()
        for r in _div:
            horas = (r["max_ts"] - r["min_ts"]) / 3600.0
            diversidad_map[r["cluster_id"]] = {
                "n_ev": r["n_ev"], "n_urls": r["n_urls"], "horas": horas,
            }
    except Exception:
        diversidad_map = {}
    # dominios amplificados por cluster (punto 5, 08/Sep): extraer el dominio
    # (netloc) de cada URL en cluster_events y agrupar cuántas CUENTAS distintas
    # comparten cada dominio. Distingue visualmente "eco de un mismo medio"
    # (2 cuentas compartiendo el enlace de un único dominio) de una red que
    # amplifica muchos dominios. Solo lectura: contexto de interpretación.
    domains_map = {}
    try:
        import urllib.parse as _up
        _dom = con.execute(
            "SELECT cluster_id, url, author FROM cluster_events"
            " WHERE url IS NOT NULL AND url != ''").fetchall()
        _dacc = {}
        for r in _dom:
            try:
                host = (_up.urlparse(str(r["url"])).netloc or "").lower()
            except Exception:
                host = ""
            host = host[4:] if host.startswith("www.") else host
            if not host:
                continue
            key = r["cluster_id"]
            d = _dacc.setdefault(key, {})
            e = d.setdefault(host, {"dominio": host, "autores": set()})
            e["autores"].add(str(r["author"] or ""))
        for _cid, _dominos in _dacc.items():
            domains_map[_cid] = sorted(
                [{"dominio": x["dominio"], "n_cuentas": len(x["autores"])}
                 for x in _dominos.values()],
                key=lambda x: -x["n_cuentas"])[:4]
    except Exception:
        domains_map = {}
    # firma de cuentas por cluster (A2, 05/Sep): conjunto de autores distintos
    # en cluster_events -> permite deduplicar el MISMO conjunto de cuentas que
    # forma clusters en varios temas (solape frontera_sur/geopolitica: la pareja
    # carlos1951+saharaenelcorazon salía como geopolitica_001 Y frontera_sur_012).
    firma_cluster = {}
    try:
        _firmas = con.execute(
            "SELECT ce.cluster_id, ce.author FROM cluster_events ce JOIN clusters cl"
            " ON cl.id=ce.cluster_id WHERE ce.author!=''").fetchall()
        for _f in _firmas:
            firma_cluster.setdefault(_f["cluster_id"], set()).add(_f["author"])
    except Exception:
        firma_cluster = {}
    n_events = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    # Última ingesta real: momento de la captura más reciente (events.timestamp).
    # Se muestra en la vista resumen bajo "¿Qué está pasando ahora?".
    try:
        _last_ts = con.execute("SELECT MAX(timestamp) FROM events").fetchone()[0]
    except Exception:
        _last_ts = None
    # Fuentes de captura: total real en events + desglose por clase.
    # `n_sources` cuenta feeds RSS + plataformas (bluesky/google-news) + canales
    # Telegram + subreddits — NO solo "feeds". El inventario de config.yaml
    # (card "Fuentes y búsquedas activas") muestra los bloques y coincide.
    n_sources = con.execute("SELECT COUNT(DISTINCT source) FROM events").fetchone()[0]
    n_src_feeds = con.execute(
        "SELECT COUNT(DISTINCT source) FROM events WHERE source LIKE 'rss:%'").fetchone()[0]
    n_src_tg = con.execute(
        "SELECT COUNT(DISTINCT source) FROM events WHERE source LIKE 'telegram:%'").fetchone()[0]
    n_src_reddit = con.execute(
        "SELECT COUNT(DISTINCT source) FROM events WHERE source LIKE 'reddit:%'").fetchone()[0]
    n_src_plt = n_sources - n_src_feeds - n_src_tg - n_src_reddit
    # inventario de plataformas con eventos (bluesky, google-news, ...)
    _plt_sources = [r[0] for r in con.execute(
        "SELECT DISTINCT source FROM events WHERE source NOT LIKE 'rss:%'"
        " AND source NOT LIKE 'telegram:%' AND source NOT LIKE 'reddit:%'"
        " ORDER BY source").fetchall()]
    plt_html = " · ".join(f"<code>{_s}</code>" for _s in _plt_sources) or "—"
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
    # Sparkline (trayectoria 14 días por tema): serie diaria de hallazgos para
    # la vista resumen, para ver si un tema lleva subiendo o es un pico de hoy.
    SPARK_DAYS = 14
    spark_data = {}
    try:
        _t0 = int((datetime.now(timezone.utc) - _td(days=SPARK_DAYS - 1)).timestamp())
        for _t in temas:
            _rows = con.execute(
                "SELECT date(fecha,'unixepoch') d, COUNT(*) n FROM findings"
                " WHERE tema_id=? AND fecha>=? GROUP BY d",
                (_t, _t0)).fetchall()
            _map = {r[0]: int(r[1]) for r in _rows}
            _serie = []
            for _i in range(SPARK_DAYS):
                _dd = _hoy_d - _td(days=SPARK_DAYS - 1 - _i)
                _serie.append((_dd.isoformat(), _map.get(_dd.isoformat(), 0)))
            spark_data[_t] = _serie
    except Exception:
        spark_data = {_t: [] for _t in temas}
    # --- LÍNEA BASE POR TEMA (anclar la señal a su propio histórico) ---
    # Métrica continua por tema: pico diario = MAX(intensidad) de los findings
    # tipo cluster de ese día (el cluster más señalado de cada ciclo). Sobre esa
    # serie se calculan percentiles (banda "normal" p25-p75), la media 14d y el
    # máximo 30d, para responder "¿es esto mucho PARA ESTE TEMA?". El histórico
    # es corto en temas jóvenes: los percentiles se calculan con los días
    # disponibles y se muestra "N días de base" cuando hay menos de 14.
    _LB_DAYS = 30
    linea_base = {}
    try:
        _lb_desde = int((datetime.now(timezone.utc) - _td(days=_LB_DAYS)).timestamp())
        for _t in temas:
            _rows = con.execute(
                "SELECT date(fecha,'unixepoch') d, MAX(intensidad) mx FROM findings"
                " WHERE tema_id=? AND tipo='cluster' AND fecha>=? AND intensidad>0"
                " GROUP BY d", (_t, _lb_desde)).fetchall()
            _picos = [float(r[1]) for r in _rows]
            _dias = len(_picos)
            def _pct(vals, q):
                if not vals:
                    return None
                s = sorted(vals)
                k = (len(s) - 1) * q
                f = int(k)
                c = min(f + 1, len(s) - 1)
                return s[f] + (s[c] - s[f]) * (k - f)
            # media de los últimos 14 días (o los disponibles si son menos)
            _p14 = _picos if _dias <= 14 else _picos[-14:]
            _media14 = sum(_p14) / len(_p14) if _p14 else None
            # pico del día hace 48h (para el delta "hoy vs hace 48h" del tema)
            _d48 = (_hoy_d - _td(days=2)).isoformat()
            _p48r = con.execute(
                "SELECT MAX(intensidad) FROM findings"
                " WHERE tema_id=? AND tipo='cluster' AND intensidad>0"
                " AND date(fecha,'unixepoch')=?", (_t, _d48)).fetchone()[0]
            linea_base[_t] = {
                "dias": _dias,
                "p25": _pct(_picos, 0.25),
                "p75": _pct(_picos, 0.75),
                "media14": _media14,
                "max30": max(_picos) if _picos else None,
                "hoy": _picos[-1] if _picos else None,   # pico de hoy (findings)
                "pico48": float(_p48r) if _p48r else None,
            }
    except Exception:
        for _t in temas:
            linea_base[_t] = {"dias": 0, "p25": None, "p75": None,
                              "media14": None, "max30": None, "hoy": None,
                              "pico48": None}
    # Narrativas alineadas (cluster-of-clusters, 05/Sep): une clusters de la
    # vista activa que hablan de la misma narrativa (TF-IDF + coseno sobre el
    # texto real de cluster_events). Capa transversal, agnóstica al actor.
    # Se computa AQUÍ (antes de con.close()) y se renderiza más abajo.
    _grupos_na = []
    _na_mod = None
    try:
        import importlib.util
        _spec_na = importlib.util.spec_from_file_location(
            "narrativas_alineadas", ROOT / "detection" / "narrativas_alineadas.py")
        _na_mod = importlib.util.module_from_spec(_spec_na)
        _spec_na.loader.exec_module(_na_mod)
        _grupos_na = _na_mod.detectar(con)
    except Exception:
        _grupos_na = []
        _na_mod = None
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
                        dt = _dt.datetime.fromtimestamp(ev["ts"], tz=_dt.timezone.utc).strftime("%d/%m %H:%M")
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
    # Narrativas alineadas: render a partir de los grupos ya calculados antes
    # de cerrar la conexión (arriba, junto al bloque de tendencias).
    narr_align_block = ""
    if _na_mod is not None:
        try:
            narr_align_block = _na_mod._html(_grupos_na)
        except Exception:
            narr_align_block = ""
    # historial de hallazgos persistidos, agrupado por tipo
    import html as _html
    import datetime as _dt

    def _fmt_fecha(ts):
        try:
            return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime("%d/%m")
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

    # --- Narrativas: cabecera combinada sostenidas + amplificadas ---
    def _strip_outer_card(h):
        """Extrae el contenido interno de un <div class='card'>...</div>."""
        i = h.find('>')
        if i >= 0:
            h = h[i+1:]
        j = h.rfind('</div>')
        if j >= 0:
            h = h[:j]
        return h.strip()

    _has_sost = bool(sostenidas)
    _has_amp = narr_block and "Ninguna narrativa" not in narr_block
    _nh = []
    if _has_sost:
        _nh.append(f"🚨 {len(sostenidas)} sostenida{'s' if len(sostenidas)!=1 else ''} (≥3 días)")
    if _has_amp:
        _nh.append("📣 eco mediático en ventana actual")
    if _has_sost or _has_amp:
        _sost_inner = _strip_outer_card(sost_html) if _has_sost else ""
        _amp_inner = _strip_outer_card(narr_block) if _has_amp else ""
        narrativas_combined = (
            f"<div class='card'>"
            f"<h3 style='margin:0 0 2px'>Narrativas</h3>"
            f"<p class='caption'>{' · '.join(_nh)}.</p>"
            f"{_sost_inner}"
            f"{_amp_inner}"
            f"</div>")
    else:
        narrativas_combined = ("<div class='card'><h3>Narrativas</h3>"
                               "<p class='caption'>Ninguna narrativa detectada en la ventana actual.</p></div>")

    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    # KPIs globales (resumen para SEO/share; el detalle por tema va en pestañas)
    n_crit = sum(1 for c in clusters if c["overall_score"] and c["overall_score"] >= 80) if clusters else 0
    n_high = sum(1 for c in clusters if c["overall_score"] and 60 <= c["overall_score"] < 80) if clusters else 0
    n_anom = sum(1 for c in clusters if c["overall_score"] and 40 <= c["overall_score"] < 60) if clusters else 0
    if narr_kpi is None:
        narr_kpi = kpi("Narrativas amplificadas", 0, "sin datos", "#f8fafc")

    # Estado resumido por tema para diales/cabeceras: tendencia, color y frase.
    ESTADO_DIAL = {
        "subiendo":   {"txt": "Subiendo", "color": "#d97706", "valor": 75},
        "estable":    {"txt": "Estable",  "color": "#16a34a", "valor": 40},
        "bajando":    {"txt": "Bajando",  "color": "#64748b", "valor": 20},
        "recopilando":{"txt": "En recopilación", "color": "#94a3b8", "valor": 10},
    }

    def _estado_tema(_t):
        """Devuelve (estado_dial, estilo, frase) para el tema _t."""
        _m = temas_cfg.get(_t, {}) if isinstance(temas_cfg, dict) else {}
        _estado_cfg = _m.get("estado", "produccion")
        _tr = tendencias.get(_t, {"estado": "estable", "hoy": 0, "hace48": 0,
                                  "high_hoy": 0, "high_48": 0})
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
        return _estado_dial, _estilo, _frase

    # ---- PESTAÑAS POR TEMA (vista activa multi-tema) ----
    # Cada pestaña muestra: eventos, fuentes, clusters y banda de alerta del tema.
    # A2: dedupe entre temas. El mismo conjunto de cuentas coordinadas puede
    # formar clusters en varios temas (solape geográfico/temático frontera_sur↔
    # geopolitica_ue_marruecos: 168/168 eventos compartidos). Para no inflar la
    # sensación de alerta, cada firma (set de autores) se muestra UNA vez, en el
    # primer tema del catálogo que la reclama; en los demás se marca como
    # "duplicado de <tema origen>" y se oculta de la lista de tarjetas.
    _firma_duenho = {}       # frozenset(auth) -> cluster_label del 1er tema
    _duplicados = {}         # cluster_label -> cluster_label origen
    for _t_ord in temas:
        for _c_ord in clusters:
            if _c_ord["tema_id"] != _t_ord:
                continue
            _sig = frozenset(firma_cluster.get(_c_ord["id"], ()))
            if not _sig:
                continue
            _dueno = _firma_duenho.get(_sig)
            if _dueno is None:
                _firma_duenho[_sig] = _c_ord["cluster_label"]
            else:
                _duplicados[_c_ord["cluster_label"]] = _dueno

    tema_tabs = ""
    tema_panes = ""
    temas_stats = {}
    # --- RESÚMENES DE SÍNTESIS POR TEMA (FASE 3) ---
    # Caja de 4-6 líneas en la parte superior de cada pestaña, combinando datos
    # YA calculados: salud, cluster de mayor alerta + componentes, narrativas
    # sostenidas del tema, narrativas alineadas cross-topic y bitácora.
    # Se computa aquí (con conexión propia a BD) porque `con` se cerró arriba.
    _resumen_tema_html = {}
    try:
        import sqlite3 as _r_sql
        import sys as _r_sys
        _r_sys.path.insert(0, str(ROOT))
        from detection.persistencia import detectar_sostenidas as _ds_sost
        import importlib.util as _ilu_r
        _spec_st_r = _ilu_r.spec_from_file_location(
            "salud_tema", ROOT / "detection" / "salud_tema.py")
        _st_mod_r = _ilu_r.module_from_spec(_spec_st_r)
        _spec_st_r.loader.exec_module(_st_mod_r)
        _salud_r = _st_mod_r.salud_por_tema() or {}
        _spec_rt = _ilu_r.spec_from_file_location(
            "resumen_tema", ROOT / "detection" / "resumen_tema.py")
        _rt_mod = _ilu_r.module_from_spec(_spec_rt)
        _spec_rt.loader.exec_module(_rt_mod)
        _rcon = _r_sql.connect(DB)
        _rcon.row_factory = _r_sql.Row
        # cuentas por cluster desde assessments (mismo patrón que el loop)
        _asm_by_cid_r = {a["cluster_id"]: a for a in assessments} if assessments else {}
        for _t_r in temas:
            _m_r = temas_cfg.get(_t_r, {}) if isinstance(temas_cfg, dict) else {}
            _nm_r = _m_r.get("nombre", _t_r)
            _cl_r = [c for c in clusters if c["tema_id"] == _t_r]
            # cluster de mayor score con componentes + cuentas + banda
            _top_r = None
            if _cl_r:
                _cc_r = max(_cl_r, key=lambda x: x["overall_score"] or 0)
                _aa_r = _asm_by_cid_r.get(_cc_r["id"])
                _mm_r = re.search(r"(\d+)\s+cuentas?", str(_aa_r["assessment"] or "")
                                  if _aa_r is not None else "")
                _top_r = dict(_cc_r)
                _top_r["cuentas"] = int(_mm_r.group(1)) if _mm_r else 0
                _top_r["banda"] = band_of(_cc_r["overall_score"] or 0)
            # filas de bitácora del tema
            _brows_r = [dict(x) for x in _rcon.execute(
                "SELECT fecha, tipo, motivo FROM bitacora WHERE tema=?"
                " ORDER BY fecha ASC", (_t_r,))]
            _lineas_r = _rt_mod.generar_resumen_tema(
                _t_r, _nm_r,
                salud=_salud_r.get(_t_r),
                cluster_top=_top_r,
                sostenidas_tema=_ds_sost(_rcon, min_dias=3, tema=_t_r),
                grupos_na=_grupos_na,
                bitacora_filas=_brows_r,
            )
            # render de la caja destacada (resumen visualmente distinguido)
            import re as _re_r
            _conv = lambda _s: _re_r.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _s)
            _items = "".join(
                f"<div style='margin:5px 0 5px;line-height:1.5'>{_conv(li)}</div>"
                for li in _lineas_r)
            _resumen_tema_html[_t_r] = (
                "<div class='fimi-resumen' style='background:#fffbeb;border:1px solid #fcd34d;"
                "border-left:4px solid #c2410c;border-radius:10px;padding:10px 14px;margin:0 0 12px'>"
                "<div style='font-size:.72rem;color:#b45309;font-weight:700;text-transform:uppercase;"
                "letter-spacing:.05em;margin-bottom:2px'>Resumen del tema</div>"
                f"{_items}</div>")
        _rcon.close()
    except Exception as _e_r:
        # si falla el resumen, no romper el dashboard: pestañas normales
        _resumen_tema_html = {}
    for i, _t in enumerate(temas):
        d = por_tema.get(_t, {"eventos": 0, "fuentes": 0, "clusters": []})
        _cl = d["clusters"]
        _meta = temas_cfg.get(_t, {}) if isinstance(temas_cfg, dict) else {}
        _nombre = _meta.get("nombre", _t)
        _estado = _meta.get("estado", "produccion")
        _discl = _meta.get("disclaimer", "")
        _blog_cta = {
            "frontera_sur": {
                "title": "Análisis: la frontera sur como crisis diplomática",
                "desc": "Lectura en @pruebapublica sobre Ceuta y la migración como arma.",
                "url": "https://analisis.pruebapublica.com/posts/ceuta-melilla-2026-crisis-migratoria-arma-diplomatica",
            },
            "geopolitica_ue_marruecos": {
                "title": "Análisis: el tablero del Magreb antes de la tormenta",
                "desc": "Objetivos de cada actor en el Magreb occidental (UE-Marruecos).",
                "url": "https://analisis.pruebapublica.com/posts/el-tablero-antes-de-la-tormenta",
            },
            "politica_nacional": {
                "title": "Análisis: lealtad y bunkerización en Moncloa",
                "desc": "Ensayo de opinión sobre dereliction of duty y la decisión política.",
                "url": "https://analisis.pruebapublica.com/posts/dereliction-of-duty-lealtad-bunkeriza-moncloa",
            },
            "eeuu_politica": [
                {
                    "title": "Análisis: Donroe, la nueva Doctrina Monroe",
                    "desc": "Lectura geopolítica de la política exterior estadounidense.",
                    "url": "https://analisis.pruebapublica.com/posts/donroe-la-nueva-version-de-la-doctrina-monroe",
                },
                {
                    "title": "Análisis: neocolonialismo del siglo XXI y el Corolario Trump-Monroe",
                    "desc": "Cronología de la injerencia hemisférica hasta la operación de Venezuela (2026).",
                    "url": "https://analisis.pruebapublica.com/posts/neocolonialismo-siglo-xxi-corolario-trump-monroe",
                },
            ],
        }.get(_t)
        if _blog_cta:
            _items = _blog_cta if isinstance(_blog_cta, list) else [_blog_cta]
            _blog_html = (
                f"<div style='border:1px dashed #c2410c;border-radius:10px;padding:10px 14px;"
                f"margin:0 0 12px;background:#fffaf5;font-size:.82rem;line-height:1.5'>"
                + "".join(
                    f"<div style='margin:2px 0'><b>📚 {_c['title']}</b><br>"
                    f"<span style='color:#94a3b8;font-size:.75rem'>{_c['desc']}</span><br>"
                    f"<a href='{_c['url']}' target='_blank' rel='noopener noreferrer' "
                    f"style='color:#c2410c;font-weight:600'>Leer el análisis en el blog →</a></div>"
                    for _c in _items
                )
                + "</div>")
        else:
            _blog_html = ""
        _tema_cl_raw = [c for c in clusters if c["tema_id"] == _t]
        # A2: quitar de este tema los clusters cuyo conjunto de cuentas ya se
        # muestra en un tema anterior del catálogo (no duplicar hallazgos).
        _dup_aqui = [c for c in _tema_cl_raw if c["cluster_label"] in _duplicados]
        _tema_cl = [c for c in _tema_cl_raw if c["cluster_label"] not in _duplicados]
        _dup_note = ""
        if _dup_aqui:
            # nombres legibles de los temas origen + qué cuentas son
            _origenes = {}
            _detalles = []
            for _c in _dup_aqui:
                _o = _duplicados[_c["cluster_label"]]
                _otema = _o.split("_cluster_")[0]
                _origenes.setdefault(_otema, []).append(_c["cluster_label"])
                _aut = firma_cluster.get(_c["id"], ())
                _quien = ", ".join(sorted(str(a).split(":")[-1] for a in _aut)) if _aut else ""
                _sc = _c["overall_score"] or 0
                _detalles.append(f"{_c['cluster_label'].split('_cluster_')[-1]} · {_sc:.0f}/100"
                                 + (f" ({_quien})" if _quien else ""))
            _od = " · ".join(f"{k} ({len(v)} duplicado{'s' if len(v)>1 else ''})"
                             for k, v in _origenes.items())
            # mapa tema->nombre del catálogo para legibilidad
            _cat_nombre = {}
            for _t2, _m2 in (temas_cfg.items() if isinstance(temas_cfg, dict) else {}):
                _cat_nombre[_t2] = _m2.get("nombre", _t2)
            _od_legible = " · ".join(
                f"<b>{_cat_nombre.get(k, k)}</b> ({len(v)} duplicado{'s' if len(v)>1 else ''})"
                for k, v in _origenes.items())
            _dup_note = (f'<div style="background:#fffbeb;border:1.5px solid #fcd34d;border-left:5px solid #d97706;'
                         f'border-radius:8px;padding:10px 14px;margin:10px 0;font-size:.8rem;'
                         f'color:#78350f;line-height:1.55">'
                         f'<b>🔁 Señal ya contada en otro tema ({len(_dup_aqui)} cluster'
                         f'{"s" if len(_dup_aqui)>1 else ""})</b><br>'
                         f'Los clusters de este tema que ves en 0 arriba son <b>el mismo conjunto de '
                         f'cuentas</b> que el radar ya muestra en {_od_legible} ({" · ".join(_detalles)}). '
                         f'Para no inflar la alerta con la misma señal dos veces, se listan una sola vez '
                         f'en el radar (solape temático entre dominios).</div>')
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
        # Agregados de las tarjetas para el KPI de cabecera: nº de clusters en
        # alerta alta, anomalía alta, cuentas implicadas y score máximo, todos
        # derivados de los datos que se muestran en cada tarjeta.
        _asm_by_cid_t = {a["cluster_id"]: a for a in assessments} if assessments else {}
        _tot_cuentas = 0
        _anom_list_t = []
        _score_list_t = []
        for _cc_t in _tema_cl:
            _aa_t = _asm_by_cid_t.get(_cc_t["id"])
            if _aa_t:
                _mm_t = re.search(r"(\d+)\s+cuentas?", str(_aa_t["assessment"] or ""))
                if _mm_t:
                    _tot_cuentas += int(_mm_t.group(1))
            _anom_list_t.append(_cc_t["anomaly_score"] or 0)
            _score_list_t.append(_cc_t["overall_score"] or 0)
        _n_alerta = sum(1 for _v in _score_list_t if _v >= 60)
        _max_score = max(_score_list_t) if _score_list_t else 0
        _max_banda = band_of(_max_score)
        _max_color = BAND_COLORS[_max_banda]
        _anom_max = round(max(_anom_list_t)) if _anom_list_t else 0
        _anom_color = "#dc2626" if _anom_max >= 60 else ("#f59e0b" if _anom_max >= 40 else "#94a3b8")
        _pct_alerta = round(100.0 * _n_alerta / len(_tema_cl)) if _tema_cl else 0
        _amp_val = int(round(_amp_tema or 0))
        _n_tot = len(_tema_cl)
        def _mini_dial(label, valor, color, sub):
            return (f'<div style="flex:0 1 165px;min-width:150px;width:165px;background:#fff;'
                    f'border:1px solid #e2e8f0;border-radius:16px;padding:12px 8px 8px;'
                    f'text-align:center;box-shadow:0 1px 3px rgba(15,23,42,.06)">'
                    f'<div style="font-size:.72rem;color:#475569;font-weight:700;'
                    f'text-transform:uppercase;letter-spacing:.03em">{label}</div>'
                    f'{render_dial_svg(label, max(0, min(100, valor)), color, ancho=112)}'
                    f'<div style="font-size:1.4rem;font-weight:800;color:{color};line-height:1.05">'
                    f'{valor:.0f}</div>'
                    f'<div style="font-size:.74rem;color:#64748b;line-height:1.3">{sub}</div></div>')
        # Delta del score top del tema vs su pico de hace 48h (trazable por
        # findings.intensidad; los cluster_label no son estables entre ciclos).
        _p48_t = (linea_base.get(_t) or {}).get("pico48")
        if _max_score and _p48_t:
            _delta = _max_score - _p48_t
            _delta_txt = (f"▲ +{_delta:.0f}" if _delta > 0.5
                          else (f"▼ {_delta:.0f}" if _delta < -0.5 else "▬"))
            _delta_color = "#dc2626" if _delta > 0.5 else ("#16a34a" if _delta < -0.5 else "#64748b")
        else:
            _delta_txt, _delta_color = "—", "#94a3b8"
        _gauges_t = "".join([
            _mini_dial("Score top", _max_score, _max_color,
                       f"{_max_banda} · <span style='color:{_delta_color};font-weight:700'>{_delta_txt}</span> vs hace 48h"),
            _mini_dial("En alerta", _n_alerta, "#dc2626" if _n_alerta else "#94a3b8",
                       f"{_pct_alerta}% · {_n_alerta} de {_n_tot} clusters ≥60"),
            _mini_dial("Anomalía máx", _anom_max, _anom_color,
                       "desviación más alta de un cluster"),
            _mini_dial("Amplificación", _amp_val, "#c2410c",
                       "señal global del tema"),
        ])
        _cards_t = (f'<div class="fimi-gauges" '
                    f'style="display:flex;flex-wrap:wrap;gap:12px;margin:0 auto 10px;width:100%;justify-content:center">'
                    f'{_gauges_t}</div>'
                    f'<div style="display:flex;flex-wrap:wrap;gap:10px;width:100%">' + "".join([
                        kpi("Eventos", d["eventos"], "del tema", "#eff6ff"),
                        kpi("Fuentes", d["fuentes"], "del tema", "#f0fdf4"),
                        kpi("Clusters", len(_tema_cl), "activos", "#fafaf9"),
                        kpi("Cuentas", _tot_cuentas, "implicadas en clusters", "#f1f5f9"),
                        kpi_banda_alerta(_tema_cl),
                    ]) + '</div>')
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
            if _dup_aqui:
                _cl_txt = ("<p style='font-size:.82rem;color:#64748b;font-style:italic'>"
                           "Todo lo activo en este tema ya se muestra en otro tema "
                           "(mismas cuentas coordinadas). Sin hallazgos exclusivos ahora.</p>")
            else:
                _cl_txt = render_cluster_cards([], assessments, titulo_vacio="Sin clusters activos en este tema")
        else:
            # leyenda de componentes UNA vez, arriba del listado; luego las tarjetas
            _cl_txt = render_component_legend() + render_cluster_cards(
                _tema_cl, assessments, contenido_map=contenido_map, diversidad_map=diversidad_map,
                domains_map=domains_map, evidencia_map=evidencia_map, amp_global=_amp_tema)
        # Color de acento por tema: cada dominio del catálogo tiene identidad
        # visual propia en su pestaña (no todas monótonas en gris/naranja).
        # Frontera Sur = naranja (identidad del radar), UE-Marruecos = azul
        # diplomacia, Política nacional = violeta institucional.
        _accent = {"frontera_sur": "#c2410c",
                   "geopolitica_ue_marruecos": "#0ea5e9",
                   "politica_nacional": "#7c3aed"}.get(_t, "#c2410c")
        if i == 0:
            # pestaña activa: fondo con su color de acento, texto NEGRO
            _tab_style = (f"border-color:{_accent};background:{_accent};color:#000;"
                          f"box-shadow:0 1px 3px rgba(15,23,42,.15)")
            _dot = ""
        else:
            # inactivas: punto de color + nombre negro, borde suave del acento
            _tab_style = (f"border-color:{_accent}55;background:#fff;color:#000;"
                          f"border-left:3px solid {_accent}")
            _dot = (f"<span style='display:inline-block;width:8px;height:8px;"
                    f"border-radius:50%;background:{_accent};margin-right:6px'></span>")
        _estado_label = {"produccion": "Producción",
                         "piloto": "Piloto",
                         "candidato_a_cierre": "Candidato a cierre",
                         "cerrado": "Cerrado"}.get(_estado, _estado)
        if _estado == "piloto":
            _badge_est = (f"<span class='fimi-tab-badge' style='font-weight:800;font-size:.66rem;"
                          f"color:#7c2d12;background:#ffedd5;border:1px solid #fdba74;border-radius:999px;"
                          f"padding:1px 8px;margin-left:6px'>{_estado_label}</span>")
        elif _estado == "produccion":
            _badge_est = (f"<span class='fimi-tab-badge' style='font-weight:700;font-size:.66rem;"
                          f"color:#166534;background:#dcfce7;border:1px solid #86efac;border-radius:999px;"
                          f"padding:1px 8px;margin-left:6px'>{_estado_label}</span>")
        else:
            _badge_est = (f"<span class='fimi-tab-badge' style='font-weight:600;font-size:.66rem;"
                          f"color:#334155;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:999px;"
                          f"padding:1px 8px;margin-left:6px'>{_estado_label}</span>")
        tema_tabs += (f"<button type='button' data-tema='{_t}' data-estado='{_estado}'"
                      f" data-accent='{_accent}' onclick='fimiTab(\"{_t}\")'"
                      f" style='cursor:pointer;border:1px solid #e2e8f0;border-radius:999px;"
                      f"padding:7px 14px;font-weight:600;font-size:.82rem;font-family:inherit;"
                      f"{_tab_style}'>{_dot}<span style='color:#000'>{_nombre}</span>"
                      f"{_badge_est}</button>")

        _bias_note = ""
        if _estado == "piloto":
            # C1: riesgo de sesgo visible en el propio panel (no solo "piloto en
            # calibración"): en politica_nacional la coordinación partidista
            # legítima y la opinión editorial se mezclan con señal de campaña.
            _bias_note = (f'<div style="background:#fef2f2;border:2px solid #fecaca;border-radius:8px;'
                          f'padding:8px 12px;margin:0 0 8px;font-size:.78rem;color:#7f1d1d;line-height:1.45">'
                          f'<b>Riesgo de falso positivo por sesgo:</b> en este tema la coordinación '
                          f'partidista legítima y la opinión editorial de cuentas activas se mezclan '
                          f'con señal de campaña. El sistema da mucho peso a la anomalía para no '
                          f'marcarlas como red inorgánica, pero sigue en calibración: interpreta '
                          f'cualquier alerta como hipótesis, no como veredicto.</div>')
        tema_panes += (f"<div id='fimi-pane-{_t}' class='fimi-pane' data-tema='{_t}'"
                       f"{'' if i == 0 else ' hidden'}>"
                       f"{_resumen_tema_html.get(_t, '')}"
                       f"{_blog_html}"
                       f"{_bias_note}{_dup_note}<div class='kpis'>{_cards_t}</div>{_cl_txt}</div>")
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
      <div class="funnel-card" style="max-width:{width}%;margin:10px auto 0;background:{bg};border-left:5px solid {fg};
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
    <div style="background:#fff;max-width:640px;width:100%;border-radius:16px;padding:20px 20px 30px;
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
      <img src="/fimi-overview.webp" alt="Vista general del Radar FIMI: del ruido a la señal"
           width="1200" height="800" loading="lazy"
           style="display:block;width:100%;height:auto;border-radius:10px;border:1px solid #e2e8f0;margin:2px 0 14px">
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
    # Salud de los temas (score 0-100, mismo criterio que check_cierre).
    # Se computa aquí (antes de los diales) para poder pintar un chip en cada
    # tarjeta de la vista resumen; la card completa del detalle reutiliza el
    # mismo dict más abajo (no se recalcula).
    _salud_temas = {}
    try:
        import importlib.util as _ilu0
        _spec_st = _ilu0.spec_from_file_location("salud_tema", ROOT / "detection" / "salud_tema.py")
        _st_mod = _ilu0.module_from_spec(_spec_st)
        _spec_st.loader.exec_module(_st_mod)
        _salud_temas = _st_mod.salud_por_tema() or {}
    except Exception as _e_st0:
        _salud_temas = {}
    _SALUD_COLOR = {"alta": "#16a34a", "media": "#d97706", "baja": "#dc2626"}


    # color/valor y frase del dial se calculan en _estado_tema(_t) para que la
    # vista resumen y las cabeceras de pestaña nunca diverjan.
    def _resumen_ejecutivo(_t):
        """B1: 2-3 líneas en texto plano de QUÉ está pasando en el tema hoy.
        Construido de los clusters EXCLUSIVOS (sin los duplicados entre temas)
        y de su contenido real (cluster_events). Ideal para el lector que solo
        quiere "qué pasó hoy" y para compartir en redes."""
        _cli_t = [c for c in clusters
                  if c["tema_id"] == _t and c["cluster_label"] not in _duplicados]
        if not _cli_t:
            return "Sin clusters exclusivos ahora (lo activo ya se muestra en otro tema)."
        _n_al = sum(1 for c in _cli_t if (c["overall_score"] or 0) >= 60)
        _top = max(_cli_t, key=lambda c: c["overall_score"] or 0)
        _band_top = band_of(_top["overall_score"] or 0)
        _top_txt = ""
        _topc = contenido_map.get(_top["id"]) or []
        if _topc:
            _tt = re.sub(r"\s+", " ", str(_topc[0].get("text", ""))).strip()
            if _tt:
                _top_txt = f' El cluster de mayor alerta habla de: "{_tt[:90]}{"…" if len(_tt) > 90 else ""}".'
        _dims = f"{len(_cli_t)} clusters exclusivos"
        if _n_al:
            _dims += f", {_n_al} en alerta alta (≥60)"
        return _dims + f". Top: {_top['cluster_label'].split('_cluster_')[-1] if '_cluster_' in (_top['cluster_label'] or '') else _top['cluster_label']} {_top['overall_score']:.0f}/100 {_band_top}." + _top_txt

    dial_cards = ""
    _board_rows = ""
    _ALERTA_UMBRAL = 60  # donde empieza HIGH (≥60 = "en alerta", banda alta)
    # Señales de gobernanza (promoción/cierre) para el badge de gestión. Opción C:
    # la tarjeta comunica el estado; la acción se ejecuta en el panel admin
    # autenticado (el sistema nunca decide solo).
    def _gov_json(_p):
        try:
            return json.loads(Path(_p).read_text(encoding="utf-8"))
        except Exception:
            return {}
    _gov_map = {}
    for _t in temas:
        _prom = _gov_json(ROOT / "data" / f"promocion_{_t}.json")
        _cierre = _gov_json(ROOT / "data" / f"cierre_{_t}.json")
        _gov_map[_t] = {"ready": bool(_prom.get("ready")), "cierre": bool(_cierre.get("candidato"))}
    for _t in temas:
        _m = temas_cfg.get(_t, {}) if isinstance(temas_cfg, dict) else {}
        _nombre = _m.get("nombre", _t)
        _es_piloto = _m.get("estado", "produccion") == "piloto"
        _estado_dial, _estilo, _frase = _estado_tema(_t)
        _st_t = _salud_temas.get(_t) or {}
        _st_nivel = _st_t.get('nivel') or '—'
        _st_score = _st_t.get('score') or 0
        _st_color = _SALUD_COLOR.get(_st_nivel, '#94a3b8')

        # ---- Anclaje a la línea base del tema (opción elegida por el dueño) ----
        # La aguja apunta a una métrica CONTINUA real: el score top del tema hoy
        # (clusters activos exclusivos). La zona verde sombreada = rango p25-p75
        # de los picos diarios (findings.intensidad); la muesca roja = umbral de
        # alerta (60). El número grande muestra el score de hoy y su banda.
        _lb_t = linea_base.get(_t) or {}
        # Signal del tema = max de TODOS sus clusters (el dedupe A2 evita
        # duplicar tarjetas entre temas en el LISTADO, pero el dial de un tema
        # debe reflejar su propia señal: si ese tema tiene un cluster 39/100 hoy,
        # su dial muestra 39, aunque el mismo conjunto de cuentas ya figure en
        # frontera_sur con nota "duplicado". Si no, un tema joven parecería en 0
        # pese a tener señal, como pasó con oriente_medio tras su calibración.
        _cli_t = [c for c in clusters if c["tema_id"] == _t]
        _hoy_top = max((c["overall_score"] or 0) for c in _cli_t) if _cli_t else 0
        _lb_dias = _lb_t.get("dias", 0)
        _p25, _p75 = _lb_t.get("p25"), _lb_t.get("p75")
        _media14, _max30 = _lb_t.get("media14"), _lb_t.get("max30")
        # banda p25-p75 solo con base mínima (≥3 días) para no dibujar ruido
        _banda = None
        if _lb_dias >= 3 and _p25 is not None and _p75 is not None:
            _banda = (round(_p25), round(_p75))
        _hoy_val = _hoy_top if _hoy_top > 0 else 0
        if _hoy_top > 0:
            _dial_color = BAND_COLORS[band_of(_hoy_top)]
            _num_txt = f"{_hoy_top:.0f}"
            _num_band = band_of(_hoy_top)
        else:
            _dial_color = _estilo['color']
            _num_txt = "—"
            _num_band = "sin cluster"
        # línea de contexto: Hoy X · media 14d · máx 30d (destaca si bate máx)
        _ctx_bits = []
        if _hoy_top > 0:
            _ctx_bits.append(f"Hoy <b>{_hoy_top:.0f}</b>")
        if _media14 is not None:
            _ctx_bits.append(f"media 14d: <b>{_media14:.0f}</b>")
        if _max30 is not None:
            _ctx_bits.append(f"máx 30d: <b>{_max30:.0f}</b>")
        if _lb_dias and _lb_dias < 14:
            _ctx_bits.append(f"base {_lb_dias}d")
        _ctx_html = " · ".join(_ctx_bits)
        # Robustez de la línea base: "nuevo máximo" solo con historia suficiente
        # (≥14 días). Con menos, se etiqueta como máximo de la ventana observada,
        # no como récord del tema (evita sobre-interpretar bases de 3-9 días).
        _MIN_DIAS_MAX = 14
        _ctx_extra = ""
        if _lb_dias < 3:
            _ctx_extra = ("<span style='color:#94a3b8'> · línea base en "
                          f"acumulación ({_lb_dias or 0} días)</span>")
        elif _hoy_top > 0 and _max30 and _hoy_top >= _max30 - 0.5:
            if _lb_dias >= _MIN_DIAS_MAX:
                _ctx_extra = ("<span style='color:#dc2626;font-weight:700'> 🏁 nuevo "
                              "máximo del tema</span>")
            else:
                _ctx_extra = ("<span style='color:#94a3b8'> · máximo de la ventana "
                              f"observada ({_lb_dias}d); base corta para declararlo récord</span>")
        elif _banda and _hoy_top > _p75:
            _ctx_extra = ("<span style='color:#d97706;font-weight:700'> ⚠ fuera "
                          "de la banda normal (p75)</span>")
        # estado direccional pasa a chip (la aguja ya no lo representa)
        _chip_estado = (f"<span style='display:inline-block;font-size:.68rem;"
                        f"font-weight:700;color:{_estilo['color']};background:#f8fafc;"
                        f"border:1px solid #e2e8f0;border-radius:999px;padding:2px 10px;"
                        f"margin:6px 0 2px'>{_estilo['txt']}</span>")
        # Distinción clara piloto vs producción: borde, badge y frase destacada.
        _card_border = "#d97706" if _es_piloto else _estilo['color']
        _badge_tema = ("<span class='pilot-badge'>● PILOTO · en calibración</span>"
                       if _es_piloto else "<span class='prod-badge'>● Producción</span>")
        _frase_html = (f"<div class='pilot-frase'>{_frase}</div>" if _es_piloto else _frase)
        _gov = _gov_map.get(_t, {})
        if _es_piloto and _gov.get("ready"):
            _gestion = ("<a href='/admin.html' style='display:inline-block;font-size:.7rem;font-weight:700;"
                        "color:#166534;background:#dcfce7;border:1px solid #86efac;border-radius:999px;"
                        "padding:3px 10px;margin:2px 0 0;text-decoration:none'>✅ Lista para producción · gestionar</a>")
        elif _gov.get("cierre"):
            _gestion = ("<a href='/admin.html' style='display:inline-block;font-size:.7rem;font-weight:700;"
                        "color:#7c2d12;background:#ffedd5;border:1px solid #fdba74;border-radius:999px;"
                        "padding:3px 10px;margin:2px 0 0;text-decoration:none'>🗂 Candidata a cierre · gestionar</a>")
        else:
            _gestion = ""
        # Panel de situación (aditivo): fila compacta por tema para el "de un
        # vistazo". NO sustituye el dial; es un board de densidad comparable.
        _trend_glyph = {"subiendo": "▲", "bajando": "▼", "estable": "▬", "recopilando": "…"}
        _trend_col = {"subiendo": "#d97706", "bajando": "#16a34a",
                      "estable": "#64748b", "recopilando": "#94a3b8"}
        _board_rows += (
            f"<div class='sit-row'>"
            f"<span class='sit-dot' style='background:{_dial_color}'></span>"
            f"<span class='sit-name'>{_nombre}"
            f"{' <span class=&quot;sit-pil&quot;>piloto</span>' if _es_piloto else ''}</span>"
            f"<span class='sit-bar'><span style='display:block;width:{min(100, _hoy_val):.0f}%;height:100%;background:{_dial_color}'></span></span>"
            f"<span class='sit-score' style='color:{_dial_color}'>{_num_txt}/100 {_num_band}</span>"
            f"<span class='sit-trend' style='color:{_trend_col.get(_estado_dial, '#64748b')}'>{_trend_glyph.get(_estado_dial, '')}</span>"
            f"<span class='sit-cl'>{len(_cli_t)} cl</span>"
            f"</div>")
        dial_cards += (
            f"<div style='flex:1 1 260px;max-width:340px;background:#fff;border:1px solid #e2e8f0;border-left:5px solid {_card_border};"
            f"border-radius:16px;padding:18px 16px 14px;text-align:center;box-shadow:0 1px 3px rgba(15,23,42,.06)'>"
            f"<div style='font-size:.78rem;color:#475569;font-weight:700;text-transform:uppercase;"
            f"letter-spacing:.04em'>{_nombre}</div>"
            f"<div style='margin:4px 0 0'>{_badge_tema}</div>"
            f"{_gestion}"
            f"{render_dial_svg(_nombre, _hoy_val, _dial_color, banda=_banda, umbral=_ALERTA_UMBRAL)}"
            f"<div style='font-size:1.5rem;font-weight:800;color:{_dial_color};line-height:1.1'>"
            f"{_num_txt}<span style='font-size:.7rem;color:#64748b;font-weight:700'>/100</span></div>"
            f"<div style='font-size:.7rem;color:{_dial_color};font-weight:700;"
            f"text-transform:uppercase;letter-spacing:.05em'>{_num_band}</div>"
            f"{_chip_estado}"
            f"<div style='font-size:.78rem;color:#64748b;margin:6px 0 8px;min-height:2.2em;line-height:1.35'>"
            f"{_frase_html}</div>"
            f"<div style='font-size:.76rem;color:#475569;background:#f0fdf4;border:1px solid #bbf7d0;"
            f"border-radius:8px;padding:6px 10px;margin:0 0 8px;text-align:left;line-height:1.5'>"
            f"<span style='font-weight:700'>📈 {_ctx_html}</span>{_ctx_extra}</div>"
            f"<div style='font-size:.72rem;color:#94a3b8;text-align:left;margin:0 0 8px;line-height:1.4'>"
            f"Zona verde = rango normal del tema (p25-p75 de los picos diarios) · "
            f"muesca roja = umbral de alerta (≥{_ALERTA_UMBRAL}). La aguja señala el score top de hoy "
            f"sobre su propia línea base.</div>"
            f"<div style='font-size:.78rem;color:#334155;background:#f8fafc;border:1px solid #e2e8f0;"
            f"border-radius:8px;padding:8px 10px;margin:0 0 10px;text-align:left;line-height:1.45'>"
            f"{_resumen_ejecutivo(_t)}</div>"
            f"<div style='margin:0 0 10px;font-size:.74rem;color:#475569;display:flex;justify-content:center;"
            f"align-items:center;gap:6px'>"
            f"<span style='color:#94a3b8'>Salud del tema</span>"
            f"<b style='color:{_st_color}'>{_st_score:.0f}/100 · {_st_nivel}</b>"
            f"</div>"
            f"<div style='margin:0 0 10px;padding:8px 10px 4px;background:#fff;border:1px dashed #e2e8f0;"
            f"border-radius:8px;text-align:left'>"
            f"<div style='font-size:.68rem;color:#94a3b8;letter-spacing:.03em;margin-bottom:2px'>"
            f"Hallazgos por día · últimos {SPARK_DAYS} días</div>"
            f"{render_sparkline(spark_data.get(_t, []), _estilo['color'])}"
            f"</div>"
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
    # Línea de última ingesta bajo "¿Qué está pasando ahora?" (vista resumen).
    # = momento de la captura más reciente (events.timestamp), no del build HTML.
    # Se colorea según frescura para que sirva de indicador de salud del pipeline:
    #   verde  < 7h  -> ciclo normal (cron cada 6h).
    #   ámbar  7-13h -> tardando: casi se salta un ciclo.
    #   rojo   > 13h -> se ha saltado >=1 ciclo: el cron/captura ha fallado.
    if _last_ts:
        _lt_s = datetime.fromtimestamp(_last_ts, tz=timezone.utc)
        _lt_txt = _lt_s.strftime("%d/%m/%Y %H:%M UTC")
        _min = int((time.time() - _last_ts) / 60)
        if _min < 60:
            _lt_rel = f"hace {max(_min, 1)} min"
        elif _min < 1440:
            _lt_rel = f"hace {_min // 60} h {_min % 60:02d} min"
        else:
            _lt_rel = f"hace {_min // 1440} d"
        if _min < 420:  # < 7h
            _lt_color, _lt_icon, _lt_estado = "#16a34a", "🟢", "al día"
        elif _min < 780:  # 7-13h
            _lt_color, _lt_icon, _lt_estado = "#d97706", "🟠", "tardando"
        else:  # > 13h: se saltó al menos un ciclo de 6h
            _lt_color, _lt_icon, _lt_estado = "#dc2626", "🔴", "cron saltado"
        _ingesta_line = (f"<p id='fimiIngesta' style='font-size:.74rem;color:{_lt_color};margin:2px 0 2px' "
                         f"data-ts='{int(_last_ts)}' data-txt='{_lt_txt}'>"
                         f"🕒 Última ingesta: <b>{_lt_txt}</b> (<span id='fimiRel'>{_lt_rel}</span>) · "
                         f"<b id='fimiEstado'>{_lt_icon} {_lt_estado}</b>"
                         f"<span style='color:#94a3b8'> · datos de captura, centinela cada 6 h.</span></p>")
    else:
        # sin ingesta todavía: valores por defecto para el hero y la línea
        _lt_txt, _lt_rel, _lt_color, _lt_icon, _lt_estado = "—", "sin datos", "#dc2626", "🔴", "sin datos"
        _ingesta_line = ""
    # --- Explicación de scoring: pesos y umbrales por tema (opción 2 del
    #     próximo sprint FIMI). Exponemos lo que hoy solo vive en config.yaml
    #     para que el lector sepa qué pesa y cuántas cuentas exige cada banda
    #     (transparencia: cada tema puede calibrar en config->temas-><tema>
    #     sobre los valores globales de config->scoring).
    _scr = (cfg or {}).get("scoring", {}) or {}
    _w_global = _scr.get("weights", {}) or {}
    _w_names = {
        "synchronization": "Sincronización",
        "content_similarity": "Contenido similar",
        "amplification": "Amplificación",
        "infrastructure": "Infraestructura",
        "network_density": "Densidad de red",
        "anomaly": "Anomalía",
    }
    _w_default = {
        "synchronization": 0.25, "content_similarity": 0.20,
        "amplification": 0.20, "infrastructure": 0.15,
        "network_density": 0.10, "anomaly": 0.10,
    }
    _bandas = _scr.get("bands", {}) or {
        "NORMAL": [0, 19], "WATCH": [20, 39], "ANOMALOUS": [40, 59],
        "HIGH": [60, 79], "CRITICAL": [80, 100],
    }
    _band_order = ["NORMAL", "WATCH", "ANOMALOUS", "HIGH", "CRITICAL"]
    _w_rows = []
    for k in ["synchronization", "content_similarity", "amplification",
              "infrastructure", "network_density", "anomaly"]:
        pct = int(round((_w_global.get(k, _w_default.get(k, 0))) * 100))
        _w_rows.append(f"<tr><td>{_w_names.get(k,k)}</td><td>{pct}%</td></tr>")
    _w_tabla = ("<table style='border-collapse:collapse;font-size:.72rem;width:100%'>"
                "<tr style='border-bottom:1px solid #e2e8f0;background:#f8fafc'>"
                "<th style='text-align:left;padding:4px 8px'>Componente</th>"
                "<th style='text-align:right;padding:4px 8px'>Peso global</th></tr>"
                + "".join(_w_rows) + "</table>")
    # bandas
    _b_chips = []
    for b in _band_order:
        lo, hi = _bandas.get(b, [0, 0])
        _b_chips.append(f"<span style='display:inline-block;margin:2px;padding:2px 8px;"
                        f"border:1px solid #e2e8f0;border-radius:12px'>{b} {lo}–{hi}</span>")
    _b_html = "".join(_b_chips)
    # escala global
    _sma = _scr.get("scale_min_accounts", {}) or {}
    _s_f = _scr.get("scale_floor", {}) or {}
    _s_b = _scr.get("scale_bonus", {}) or {}
    _s_o = _scr.get("origen_unico", {}) or {}
    _escala_global = (
        f"· Masa mínima para banda alta: "
        f"{_sma.get('HIGH','2')} cuentas en HIGH, "
        f"{_sma.get('CRITICAL','10')} en CRITICAL.<br>"
        f"· Piso de masa: &lt;{_s_f.get('min_accounts',3)} cuentas = banda máx WATCH "
        f"(&quot;posible ruido de bajo volumen&quot;), salvo ≥<b>{_s_f.get('except_events',10)}</b> eventos "
        f"sostenidos o infraestructura ≥<b>{_s_f.get('except_infra',80)}</b>: entonces hasta HIGH, nunca CRITICAL.<br>"
        f"· Bonus de masa: +{_s_b.get('per_account',0.08)}×cuentas (tope "
        f"{_s_b.get('cap',3.5)} pts) a igualdad de componentes.<br>"
        f"· Origen único: cluster de ≤<b>{_s_o.get('max_urls',1)}</b> URL(s) y ≥<b>{_s_o.get('min_events',2)}</b> "
        f"eventos = &quot;eco de 1 pieza&quot; (mismo artículo repetido), tope "
        f"<b>{_s_o.get('cap_band','ANOMALOUS')}</b> para que el eco de una sola fuente no entre en banda alta."
    )
    # overrides por tema (scoring propio)
    _t_over = []
    for _t in temas:
        _ts = (temas_cfg.get(_t, {}) or {}).get("scoring", {}) or {}
        if not _ts:
            continue
        _tw = _ts.get("weights", {}) or {}
        _partes = []
        if _tw:
            _tw_pct = ", ".join(f"{_w_names.get(k,k)} {int(round(v*100))}%" for k, v in _tw.items())
            _partes.append("pesos: " + _tw_pct)
        if _ts.get("scale_min_accounts"):
            _partes.append("mín. cuentas: " +
                           ", ".join(f"{k} {v}" for k, v in (_ts["scale_min_accounts"]).items()))
        if _ts.get("scale_floor"):
            _sf = _ts["scale_floor"]
            _partes.append("piso: &lt;" + str(_sf.get("min_accounts", 3)) + " cuentas, except. ev "
                           + str(_sf.get("except_events", 10)))
        if _partes:
            _t_over.append(f"<li><b>{_t}</b>: {' · '.join(_partes)}</li>")
    _t_over_html = ("<ul style='margin:4px 0 0 18px;padding:0'>" + "".join(_t_over) + "</ul>" if _t_over
                    else "<span style='color:#94a3b8'>Ningún tema define calibración propia (todos usan valores globales).</span>")
    _scoring_html = (
        f"<div style='margin-top:8px;padding:10px 12px;background:#f8fafc;border:1px solid #e2e8f0;"
        f"border-radius:8px;font-size:.72rem;line-height:1.6'>"
        f"<b style='font-size:.76rem'>Cómo se puntúa (transparencia del modelo)</b><br>"
        f"<span style='display:inline-block;min-width:150px;vertical-align:top;margin-right:14px'>{_w_tabla}</span>"
        f"<span style='display:inline-block;vertical-align:top;max-width:520px'>"
        f"Bandas: {_b_html}<br>{_escala_global}</span>"
        f"<div style='margin-top:6px;border-top:1px solid #e2e8f0;padding-top:6px'>"
        f"Calibración por tema (config.yaml → temas): {_t_over_html}</div>"
        f"</div>"
    )
    # S1 — banner ejecutivo nivel 1 (vista resumen): una lectura de TODO el radar
    # antes de entrar a los temas. Datos reales de la vista activa (sin inventar):
    # nº de clusters activos, nº en alerta (score>=60) y nº con atribución
    # CONCLUYENTE = distinta de UNKNOWN/NO_ATTRIBUTION Y con confianza HIGH
    # (una atribución de confianza baja/media es hipótesis, no conclusión).
    _n_clusters = len(clusters)
    _n_alerta = sum(1 for c in clusters if (c["overall_score"] or 0) >= 60)
    _atr_map_b = {}
    for _a in assessments or []:
        _atr_map_b[_a["cluster_id"]] = (
            str(_a["attribution"] or "").upper(),
            str(_a["attribution_confidence"] or "").upper(),
        )
    _n_atrib = sum(1 for c in clusters
                   if (_atr_map_b.get(c["id"], ("", ""))[0]
                       not in ("", "UNKNOWN", "NO_ATTRIBUTION")
                       and _atr_map_b[c["id"]][1] == "HIGH"))
    _banner_html = (
        f"<div style='background:linear-gradient(180deg,#fff7ed,#ffedd5);border:1px solid #fdba74;"
        f"border-radius:14px;padding:14px 16px;margin:0 0 16px'>"
        f"<div style='font-size:.8rem;font-weight:800;color:#9a3412;text-transform:uppercase;"
        f"letter-spacing:.05em;margin-bottom:8px'>¿Qué está cambiando hoy?</div>"
        f"<div style='display:flex;flex-wrap:wrap;gap:8px'>"
        f"<span style='display:inline-block;padding:4px 12px;border-radius:999px;"
        f"background:#fff0e6;border:1px solid #fdba74;font-size:.78rem;font-weight:700;color:#7c2d12'>"
        f"🚨 {_n_alerta} señales en alerta (≥60)</span>"
        f"<span style='display:inline-block;padding:4px 12px;border-radius:999px;"
        f"background:#fff;border:1px solid #fcd34d;font-size:.78rem;font-weight:700;color:#78350f'>"
        f"📊 {_n_clusters} clusters activos</span>"
        f"<span style='display:inline-block;padding:4px 12px;border-radius:999px;"
        f"background:#fff;border:1px solid #e2e8f0;font-size:.78rem;font-weight:700;color:#475569'>"
        f"⚖️ {_n_atrib}/{_n_clusters} con atribución concluyente</span>"
        f"</div>"
        f"<div style='font-size:.74rem;color:#7c2d12;margin-top:10px;line-height:1.5'>"
        f"El radar marca <b>señales de comportamiento</b> (coordinación, amplificación, anomalía), "
        f"no identidades: sin evidencia concluyente, <b>no se acusa a ningún actor</b>. "
        f"Pulsa <b>ver detalle</b> en un tema para leer la evidencia y sus límites.</div>"
        f"</div>"
    )
    # Panel de situación (aditivo, S-preview): tiles KPI + distribución por banda
    # + tira por tema. Reutiliza lo ya calculado; no altera nada existente.
    _counts_band = {}
    for _c in clusters:
        _bb = band_of(_c["overall_score"] or 0)
        _counts_band[_bb] = _counts_band.get(_bb, 0) + 1
    _tot_band = sum(_counts_band.values()) or 1
    _seg = ""
    _leg = ""
    for _b in ("NORMAL", "WATCH", "ANOMALOUS", "HIGH", "CRITICAL"):
        _nb = _counts_band.get(_b, 0)
        if _nb:
            _seg += (f"<span style='display:block;width:{100 * _nb / _tot_band:.1f}%;height:100%;"
                     f"background:{BAND_COLORS[_b]}'></span>")
            _leg += (f"<span style='display:inline-flex;align-items:center;gap:5px'>"
                     f"<span style='width:9px;height:9px;border-radius:50%;background:{BAND_COLORS[_b]}'></span>"
                     f"{_nb} {_b}</span>")
    _band_dist = (
        f"<div style='margin-top:12px'>"
        f"<div style='font-size:.72rem;color:#64748b;font-weight:600;margin-bottom:4px'>"
        f"Distribución de clusters por banda</div>"
        f"<div style='display:flex;height:14px;border-radius:7px;overflow:hidden;background:#f1f5f9'>{_seg}</div>"
        f"<div style='display:flex;flex-wrap:wrap;gap:12px;margin-top:6px;font-size:.72rem;color:#475569'>{_leg}</div></div>")
    _panel_html = (
        f"<div id='situacion' style='background:linear-gradient(180deg,#ffffff,#fffaf5);border:1.5px solid #fed7aa;"
        f"border-radius:16px;padding:16px 18px;margin:0 0 18px'>"
        f"<div style='font-size:.74rem;font-weight:800;color:#9a3412;text-transform:uppercase;"
        f"letter-spacing:.05em;margin-bottom:10px'>Panel de situación · de un vistazo</div>"
        f"<div style='display:flex;flex-wrap:wrap;gap:10px'>"
        f"{kpi('Eventos', n_events, 'ventana 90 días', '#f8fafc')}"
        f"{kpi('Fuentes', n_sources, 'captura activa', '#f8fafc')}"
        f"{kpi('Clusters', _n_clusters, 'activos ahora', '#f8fafc')}"
        f"{kpi('En alerta', _n_alerta, 'score ≥60', '#fff7ed')}"
        f"{kpi('Temas', len(temas), 'monitorizados', '#f8fafc')}"
        f"</div>"
        f"{_band_dist}"
        f"<div style='margin-top:12px'>{_board_rows}</div>"
        f"<div style='font-size:.72rem;color:#94a3b8;margin-top:10px'>Resumen aditivo — el detalle "
        f"sigue en los diales y tarjetas de abajo. Señal, no atribución.</div>"
        f"</div>"
    )
    resumen_html = (
        f"<div id='vistaResumen'>"
        f"{_banner_html}"
        f"{_panel_html}"
        f"<div style='border-bottom:1px solid #e2e8f0;padding-bottom:16px;margin:0 0 26px'>"
        f"<p style='font-size:.9rem;color:#334155;margin:10px 0 2px'><b>¿Qué está pasando ahora?</b> "
        f"Estado de los temas monitorizados. Pulsa <b>ver detalle</b> si algo te interesa.</p>"
        f"{_ingesta_line}"
        f"</div>"
         f"<div id='estado' style='display:flex;flex-wrap:wrap;gap:16px;justify-content:center;margin-top:6px'>"
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
    try:
        _fecha = (_sp.check_output(["git", "log", "-1", "--format=%ci"],
                                   cwd=str(ROOT), stderr=_sp.DEVNULL).decode().strip())
        _fecha = _fecha[:16].replace(" ", " ")  # YYYY-MM-DD HH:MM
    except Exception:
        _fecha = ""
    _fecha_sufijo = f" · {_fecha}" if _fecha else ""
    # Marca de generación verificable en el HTML servido (05/Sep): permite
    # confirmar que el archivo servido es reciente (diagnóstico de cachés viejas
    # vistas por revisores externos) y distingue "fecha del último commit" de
    # "cuándo se generó este HTML". La muestra el footer y también se expone en
    # una etiqueta meta machine-readable.
    _gen_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    _gen_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    version_html = (f'<p style="font-size:.74rem;color:#999;margin:6px 0 0">'
                    f'<a href="https://github.com/mcasrom/hybrid-fimi-radar" target="_blank" '
                    f'rel="noopener noreferrer" style="color:#888">github.com/mcasrom/hybrid-fimi-radar</a>'
                    f' · <span title="{_ver}">{_ver}</span>{_fecha_sufijo}'
                    f' · <span title="fecha de generación de este HTML">generado {_gen_utc}</span></p>')
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

    # --- Salud de keywords por tema (¿captura cada tema su ruido real?) ---
    # Detector del patrón "tema ciego": keywords de registro metodológico (FIMI)
    # que los titulares reales no usan -> el tema apenas ve eventos de su ámbito
    # pese a que el corpus sí los tiene (caso oriente_medio 09/Sep). Solo informa.
    try:
        import importlib.util as _ilu_kw
        _spec_kw = _ilu_kw.spec_from_file_location(
            "salud_keywords", ROOT / "detection" / "salud_keywords.py")
        _kwm = _ilu_kw.module_from_spec(_spec_kw)
        _spec_kw.loader.exec_module(_kwm)
        _salud_kw = _kwm.analizar(14)
        salud_kw_html = _kwm.to_html(_salud_kw)
    except Exception as _e_kw:
        salud_kw_html = (f"<div class='card' id='salud-keywords'><h3>Salud de keywords</h3>"
                         f"<p class='caption'>No disponible: {_e_kw}</p></div>")

    # --- Salud del sistema (check médico integral) ---
    # Auto-chequeo estructural del pipeline: frescura de captura, snapshots por
    # tema, integridad BD y coherencia config. Complementa a los checkers
    # individuales; aquí solo se muestra la card (el aviso Telegram es del cron).
    try:
        import importlib.util as _ilu_sis
        _spec_sis = _ilu_sis.spec_from_file_location(
            "check_sistema", ROOT / "detection" / "check_sistema.py")
        _sim = _ilu_sis.module_from_spec(_spec_sis)
        _spec_sis.loader.exec_module(_sim)
        _sistema_res = _sim.chequea()
        sistema_html = _sim.to_html(_sistema_res)
    except Exception as _e_sis:
        sistema_html = (f"<div class='card' id='sistema'><h3>Salud del sistema</h3>"
                        f"<p class='caption'>No disponible: {_e_sis}</p></div>")

    # --- Salud de los temas (score continuo, mismo criterio que check_cierre) ---
    # 0-100 por tema: volumen de hallazgos/día, narrativas sostenidas, señal del
    # último cluster y madurez/calibración. Solo informativo; el cierre lo decide
    # el dueño (bitacora.py). Ya computado arriba (_salud_temas, en la vista
    # resumen) para pintar el chip de cada dial; aquí se construye la card.
    try:
        if not _salud_temas:
            raise ValueError("sin datos de salud (¿módulo salud_tema no disponible?)")
        _salud_temas_html = ("<div class='card' id='salud-temas'><h3>Salud de los temas</h3>"
                             "<p class='caption'>Score continuo 0-100 por tema (volumen de hallazgos/día, "
                             "narrativas sostenidas, señal del último cluster y madurez). Mismo criterio que el "
                             "check de cierre, sin decidir nada: orienta la revisión de mantenimiento del dueño.</p>"
                             "<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;"
                             "font-size:.82rem'>"
                             "<tr><th style='text-align:left;padding:5px 8px;border-bottom:1px solid #e2e8f0'>Tema</th>"
                             "<th style='text-align:left;padding:5px 8px;border-bottom:1px solid #e2e8f0'>Salud</th>"
                             "<th style='text-align:left;padding:5px 8px;border-bottom:1px solid #e2e8f0'>Nivel</th>"
                             "<th style='text-align:left;padding:5px 8px;border-bottom:1px solid #e2e8f0'>Volumen</th>"
                             "<th style='text-align:left;padding:5px 8px;border-bottom:1px solid #e2e8f0'>Sostenidas</th>"
                             "<th style='text-align:left;padding:5px 8px;border-bottom:1px solid #e2e8f0'>Señal</th>"
                             "<th style='text-align:left;padding:5px 8px;border-bottom:1px solid #e2e8f0'>Op.</th></tr>")
        for _st_k in sorted(_salud_temas.values(), key=lambda x: x.get("score", 0)):
            _nm = _st_k.get("nombre", _st_k.get("tema", "?"))
            _cod = _st_k.get("tema", "")
            _sc = _st_k.get("score", 0)
            _lv = _st_k.get("nivel", "—")
            _col = "#16a34a" if _lv == "alta" else ("#d97706" if _lv == "media" else "#dc2626")
            _vol = f"{_st_k.get('volumen_por_dia') or 0:.1f}/d"
            _sost = _st_k.get("sostenidas", 0)
            _ucs = _st_k.get("ultimo_cluster")
            _senal = f"{_ucs:.0f} {_st_k.get('banda', '')}" if _ucs is not None else "—"
            _dop = f"{_st_k.get('dias_operacion') or 0:.0f}d"
            _salud_temas_html += (f"<tr><td style='padding:5px 8px;border-bottom:1px solid #f1f5f9'>{_nm} "
                                  f"<code style='color:#94a3b8;font-size:.72rem'>{_cod}</code></td>"
                                  f"<td style='padding:5px 8px;border-bottom:1px solid #f1f5f9'><b>{_sc:.0f}/100</b></td>"
                                  f"<td style='padding:5px 8px;border-bottom:1px solid #f1f5f9;color:{_col};font-weight:700'>{_lv}</td>"
                                  f"<td style='padding:5px 8px;border-bottom:1px solid #f1f5f9'>{_vol}</td>"
                                  f"<td style='padding:5px 8px;border-bottom:1px solid #f1f5f9'>{_sost}</td>"
                                  f"<td style='padding:5px 8px;border-bottom:1px solid #f1f5f9'>{_senal}</td>"
                                  f"<td style='padding:5px 8px;border-bottom:1px solid #f1f5f9'>{_dop}</td></tr>")
        _salud_temas_html += "</table><p class='caption' style='margin-top:8px'>Lectura: "
        _salud_temas_html += "<b style='color:#16a34a'>alta</b> = tema vivo con señal; "
        _salud_temas_html += "<b style='color:#d97706'>media</b> = funciona con reservas (piloto/volumen justo/joven); "
        _salud_temas_html += "<b style='color:#dc2626'>baja</b> = señal débil sostenida, candidato a revisión de cierre "
        _salud_temas_html += "(el sistema nunca decide; ver Bitácora).</p></div></div>"
    except Exception as _e_st:
        _salud_temas_html = ("<div class='card' id='salud-temas'><h3>Salud de los temas</h3>"
                             f"<p class='caption'>No disponible: {_e_st}</p></div>")

    # --- Volumen fuera de catálogo (posible tema emergente, pieza #4) ---
    # Eventos que solo llevan el default frontera_sur y cuyo texto NO matchea
    # ninguna keyword del catálogo: ese volumen no lo cubre ningún tema. Se
    # agrupa por términos recurrentes como CANDIDATOS a revisar (el dueño
    # decide si añade keyword/tema). detection/temas_emergentes.py.
    try:
        import importlib.util as _ilu_em
        _spec_em = _ilu_em.spec_from_file_location(
            "temas_emergentes", ROOT / "detection" / "temas_emergentes.py")
        _tem = _ilu_em.module_from_spec(_spec_em)
        _spec_em.loader.exec_module(_tem)
        _emer_res = _tem.detectar(dias=14, min_eventos=10)
        _emer_html = _tem._html(_emer_res)
    except Exception as _e_em:
        _emer_html = (f"<div class='card'><h3>Volumen fuera del catálogo</h3>"
                      f"<p class='caption'>No disponible: {_e_em}</p></div>")

    # --- Bitácora de temas (transparencia metodológica) ---
    # Ciclo de vida por tema: inicio de ingesta (derivado de BD), estado vigente
    # (config.yaml = fuente de verdad), cambios de estado y sugerencias del
    # sistema (check_cierre, origen='sistema', sin decidir nada).
    # Los motivos se escriben en lenguaje metodológico (volumen/señal/calibración),
    # nunca como atribución a actores — principio agnóstico al actor.
    _ESTADOS_COLOR = {
        "produccion": ("#16a34a", "Producción"),
        "piloto": ("#d97706", "Piloto (calibración)"),
        "candidato_a_cierre": ("#ea580c", "Candidato a cierre"),
        "cerrado": ("#64748b", "Cerrado"),
    }
    _fmt_d = lambda _u: (datetime.fromtimestamp(_u, tz=timezone.utc).strftime("%d/%m/%Y")
                         if _u else "—")
    bitacora_rows = []
    _bit_by_tema = {}
    _inicio_findings = {}
    # `con` ya está cerrado a esta altura (main() lo cierra tras el historial):
    # abrimos conexión propia de solo lectura para la bitácora.
    try:
        _bcon = sqlite3.connect(DB)
        _bcon.row_factory = sqlite3.Row
        bitacora_rows = _bcon.execute(
            "SELECT tema, tipo, fecha, estado_anterior, estado_nuevo, motivo, origen"
            " FROM bitacora ORDER BY tema, fecha").fetchall()
        for _t in temas:
            _v = _bcon.execute(
                "SELECT MIN(fecha) FROM findings WHERE tema_id=?", (_t,)).fetchone()
            _inicio_findings[_t] = _v[0] if _v and _v[0] else None
        _bcon.close()
    except Exception:
        bitacora_rows = []
    for _br in bitacora_rows:
        _bit_by_tema.setdefault(_br["tema"], []).append(_br)
    bitacora_cards = ""
    for _t in temas:
        _tcfg = temas_cfg.get(_t, {}) or {}
        _estado = _tcfg.get("estado", "produccion")
        _nombre = _tcfg.get("nombre", _t)
        _cerr = [e for e in _bit_by_tema.get(_t, []) if e["tipo"] == "cierre"]
        _fecha_cierre = _motivo_cierre = None
        if _cerr:
            _estado = "cerrado"
            _fecha_cierre = _cerr[-1]["fecha"]
            _motivo_cierre = _cerr[-1]["motivo"]
        _color, _label = _ESTADOS_COLOR.get(_estado, ("#334155", _estado))
        _inicio = None
        for _e in _bit_by_tema.get(_t, []):
            if _e["tipo"] == "inicio" and _e["fecha"]:
                _inicio = _e["fecha"]
                break
        if _inicio is None:
            _inicio = _inicio_findings.get(_t)
        _card_sug = ""
        _sugs = [e for e in _bit_by_tema.get(_t, []) if e["tipo"] == "sugerencia"]
        if _sugs:
            _cand = _sugs[-1]
            _card_sug = (f"<div style='margin-top:8px;padding:8px 10px;border:1px solid #fed7aa;"
                         f"background:#fff7ed;border-radius:8px;font-size:.8rem;color:#9a3412'>"
                         f"<b>🗓 Sugerencia del sistema</b> ({_fmt_d(_cand['fecha'])}): "
                         f"{_cand['motivo'] or ''}<br>"
                         f"<span style='color:#64748b'>La decisión la toma el dueño "
                         f"(<code>detection/bitacora.py --nuevo-estado cerrado</code>).</span></div>")
        _tl = ""
        for _e in _bit_by_tema.get(_t, []):
            if _e["tipo"] == "inicio":
                continue
            _fecha = _fmt_d(_e["fecha"])
            _origen = "" if _e["origen"] == "manual" else \
                " <span style='color:#94a3b8'>(sistema)</span>"
            if _e["tipo"] == "cierre":
                _accion = "→ cerrado"
            elif _e["tipo"] == "cambio_estado":
                _accion = f"→ {_e['estado_nuevo']}"
            else:
                _accion = f"[{_e['tipo']}]"
            _tl += (f"<li style='margin:4px 0;font-size:.82rem'>"
                    f"<span style='color:#94a3b8'>{_fecha}</span> {_accion}{_origen}"
                    f"{(' — ' + (_e['motivo'] or '')) if _e['motivo'] else ''}</li>")
        if not _tl:
            _tl = ("<li style='font-size:.82rem;color:#94a3b8'>"
                   "Sin cambios registrados aún.</li>")
        _cierre_txt = ""
        if _fecha_cierre:
            _cierre_txt = (f"<p class='caption'>Cerrado el <b>{_fmt_d(_fecha_cierre)}</b>"
                           f" — {_motivo_cierre or ''}</p>")
        bitacora_cards += (f"<div style='margin:14px 0;padding:14px 16px;"
                           f"border:1px solid #e2e8f0;border-radius:12px'>"
                           f"<div style='display:flex;justify-content:space-between;"
                           f"gap:10px;align-items:baseline;flex-wrap:wrap'>"
                           f"<b style='font-size:.95rem'>{_nombre}</b>"
                           f"<span style='font-size:.78rem;font-weight:700;color:{_color};"
                           f"border:1px solid {_color};border-radius:999px;"
                           f"padding:2px 10px'>{_label}</span></div>"
                           f"<p class='caption'>Ingesta desde <b>{_fmt_d(_inicio)}</b>"
                           f" · código: <code>{_t}</code></p>"
                           f"{_cierre_txt}{_card_sug}"
                           f"<ul style='margin:8px 0 0;padding-left:18px'>{_tl}</ul></div>")
    bitacora_html = (f"<div class='card' id='bitacora'><h3>Bitácora de temas</h3>"
                     f"<p class='caption'>Ciclo de vida de cada tema monitorizado: inicio de "
                     f"ingesta, estados y motivos. El estado vigente vive en "
                     f"<code>config.yaml</code>; esta bitácora registra el historial y las "
                     f"sugerencias del sistema (que nunca deciden, solo avisan).</p>"
                     f"{bitacora_cards}"
                     f"<p class='caption' style='margin-top:10px'>Los motivos se describen en "
                     f"términos metodológicos (volumen, señal, redundancia, calibración) — "
                     f"nunca como atribución a actores, en línea con el principio agnóstico "
                     f"al actor del proyecto.</p></div>")

    # Fecha de la última ingesta en ISO (para el JSON-LD Dataset). El html es un
    # f-string: hay que definirla como variable antes del bloque.
    _fecha_snapshot_iso = datetime.fromtimestamp(_last_ts, tz=timezone.utc).strftime("%Y-%m-%d") if _last_ts else ""
    _jsonld_html = (
        '<script type="application/ld+json">'
        '{"@context": "https://schema.org", "@graph": ['
        '{"@type": "WebSite", "@id": "https://fimi.viajeinteligencia.com/#website", '
        '"url": "https://fimi.viajeinteligencia.com/", "name": "FIMI Radar", "inLanguage": "es", '
        '"description": "Centro de situación de desinformación: radar OSINT agnóstico al actor que observa '
        'coordinación, amplificación y anomalías en temas en español."},'
        '{"@type": "Dataset", "@id": "https://fimi.viajeinteligencia.com/#dataset", '
        '"url": "https://fimi.viajeinteligencia.com/", "name": "FIMI Radar — eventos y clusters de coordinación", '
        f'"description": "{n_events} eventos y {n_clusters} clusters de coordinación del ciclo actual (6h) del radar FIMI.", '
        '"isAccessibleForFree": true, "inLanguage": "es", '
        f'"temporalCoverage": "{_fecha_snapshot_iso}T00:00:00Z/..", '
        '"creator": {"@type": "Organization", "name": "ViajeInteligencia / FIMI Radar"}}'
        "]}</script>"
    )

    html = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FIMI Radar · Centro de situación de desinformación</title>
 <meta name="description" content="Radar OSINT agnóstico al actor: coordinación, amplificación y FIMI en español. {n_events} eventos y {n_clusters} clusters señalados hoy. Sin atribución sin evidencia.">
<meta name="keywords" content="FIMI, hybrid threats, radar OSINT, desinformación, España, Marruecos, Ceuta, Melilla, UE-Marruecos, geopolítica, política nacional, coordinación de cuentas, amplificación de narrativas">
 <link rel="canonical" href="https://fimi.viajeinteligencia.com/">
 {_jsonld_html}
 <meta property="og:type" content="website">
 <meta property="og:title" content="FIMI Radar · Centro de situación de desinformación ({n_events} eventos, {n_clusters} clusters)">
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
main{{max-width:1200px;margin:0 auto;padding:20px 16px 56px}}
.card{{background:#fff;border:1.5px solid #cbd5e1;border-radius:14px;padding:20px;margin:16px 0;box-shadow:0 1px 3px rgba(15,23,42,.06)}}
.card h3{{margin-top:0;font-size:1.02rem}}
.caption{{font-size:.84rem;color:#64748b;margin:.3rem 0;max-width:82ch}}
.kpis{{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}}
.sit-row{{display:flex;align-items:center;gap:10px;padding:5px 0;border-top:1px dashed #e2e8f0}}
.sit-dot{{width:10px;height:10px;border-radius:50%;flex:0 0 auto}}
.sit-name{{min-width:150px;font-weight:700;font-size:.82rem;color:#0f172a}}
.sit-pil{{font-size:.62rem;color:#b45309}}
.sit-bar{{flex:1;height:10px;background:#f1f5f9;border-radius:5px;overflow:hidden;min-width:60px}}
.sit-score{{min-width:104px;text-align:right;font-size:.78rem;font-weight:700}}
.sit-trend{{min-width:22px;text-align:right;font-size:.82rem;font-weight:800}}
.sit-cl{{min-width:52px;text-align:right;font-size:.76rem;color:#94a3b8}}
@media(max-width:560px){{
  .sit-row{{flex-wrap:wrap;row-gap:4px}}
  .sit-name{{flex:1 1 auto;min-width:0}}
  .sit-bar{{flex:1 1 100%;order:9}}
  .sit-score{{min-width:0;margin-left:auto}}
  .sit-trend{{min-width:0}}
  .sit-cl{{min-width:0}}
}}
.fimi-pane[hidden], .fimi-pane.hidden{{display:none}}
a{{color:#c2410c}}

.tab-panel{{display:none}}.tab-panel.active{{display:block}}

/* ---- BARRA MARCA/BADGES (opción A: 1ª línea, identidad + estado + Transparencia) ---- */
.fimi-brandbar{{position:sticky;top:0;z-index:100;display:flex;flex-wrap:wrap;align-items:center;gap:9px 14px;background:#fff;border-bottom:1px solid #e2e8f0;box-shadow:0 1px 3px rgba(15,23,42,.06);padding:11px 16px;font-size:.86rem}}
.fimi-brandbar .brand{{display:inline-flex;align-items:center;gap:8px;font-weight:800;font-size:1.08rem;color:#0f172a;text-decoration:none}}
.fimi-brandbar .logo{{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:8px;background:linear-gradient(135deg,#c2410c,#9a3412);color:#fff;font-size:.95rem;box-shadow:0 1px 2px rgba(0,0,0,.15)}}
.fimi-brandbar .transp{{color:#475569;font-weight:700;font-size:.92rem;text-decoration:none;padding:7px 12px;border-radius:9px;border:1px solid #e2e8f0;background:#f8fafc;transition:all .15s}}
.fimi-brandbar .transp:hover{{color:#c2410c;background:#fff7ed;border-color:#fdba74}}
.fimi-brandbar .transp.active{{color:#c2410c;background:#fff7ed;border-color:#fdba74}}
.fimi-brandbar .chips{{display:inline-flex;flex-wrap:wrap;gap:6px;margin-left:auto}}
.fimi-brandbar .chip{{display:inline-flex;align-items:center;gap:6px;font-size:.78rem;font-weight:700;color:#334155;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:999px;padding:4px 11px}}
.fimi-brandbar .chip .dot{{width:7px;height:7px;border-radius:50%}}
.fimi-brandbar .chip.prod{{color:#166534;background:#f0fdf4;border-color:#bbf7d0}}
.fimi-brandbar .chip.prod .dot{{background:#16a34a}}
.fimi-brandbar a.gh-link{{color:#c2410c;font-weight:700;text-decoration:none;font-size:.9rem;display:inline-flex;align-items:center;gap:5px;padding:7px 12px;border-radius:9px;border:1px solid #fdba74;background:#fff7ed;transition:all .15s}}
.fimi-brandbar a.gh-link:hover{{color:#9a3412;background:#ffedd5;border-color:#fb923c}}
@media(max-width:560px){{.fimi-brandbar .chips{{margin-left:0;width:100%}}}}

/* ---- HERO "centro de situación" (claro cálido, coherente con la página) ---- */
.fimi-hero{{background:linear-gradient(180deg,#fff 0%,#fff7ed 78%,#ffedd5 100%);color:#1e293b;border:1px solid #fed7aa;border-radius:18px;padding:24px 26px 22px;margin:6px 0 20px;box-shadow:0 2px 8px rgba(194,65,12,.08);position:relative;overflow:hidden}}
.fimi-hero::after{{content:"";position:absolute;right:-70px;top:-70px;width:260px;height:260px;border-radius:50%;background:radial-gradient(circle,rgba(194,65,12,.10),transparent 70%)}}
.fimi-hero-eyebrow{{display:flex;flex-wrap:wrap;align-items:center;gap:8px;font-size:.72rem;color:#c2410c;font-weight:700;margin-bottom:10px}}
.fimi-hero-eyebrow a{{color:#c2410c;text-decoration:none}}
.fimi-hero-eyebrow a:hover{{text-decoration:underline}}
.fimi-hero-eyebrow .sep{{color:#fdba74;font-weight:400}}
.fimi-hero-eyebrow .dot{{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px}}
.fimi-hero h1{{margin:0 0 6px;font-size:1.55rem;line-height:1.25;color:#0f172a;font-weight:800;letter-spacing:-.01em}}
.fimi-hero .sub{{margin:0 0 18px;font-size:.95rem;color:#475569;line-height:1.6;max-width:100%}}
.fimi-hero .chain{{display:flex;flex-wrap:wrap;align-items:stretch;gap:8px;margin:0 0 20px}}
.fimi-hero .step{{background:#fff;border:1px solid #fde68a;border-radius:12px;padding:12px 14px;flex:1 1 150px;min-width:150px;cursor:default;transition:border-color .15s,box-shadow .15s}}
.fimi-hero .step:hover{{border-color:#fdba74;box-shadow:0 2px 6px rgba(194,65,12,.10)}}
.fimi-hero .step b{{display:block;font-size:.95rem;color:#1e293b;font-weight:800;margin-bottom:4px}}
.fimi-hero .step .ic{{color:#c2410c}}
.fimi-hero .step span{{font-size:.74rem;color:#64748b;line-height:1.4;display:block}}
.fimi-hero .arrow{{align-self:center;color:#c2410c;font-size:1.1rem;font-weight:700}}
.fimi-hero .cta{{display:flex;flex-wrap:wrap;align-items:center;gap:12px}}
.fimi-hero .cta a{{text-decoration:none;font-weight:700;border-radius:10px;padding:11px 20px;font-size:.9rem;display:inline-flex;align-items:center;gap:7px}}
.fimi-hero .cta .primary{{background:#c2410c;color:#fff;transition:background .15s}}
.fimi-hero .cta .primary:hover{{background:#9a3412}}
.fimi-hero .cta .ghost{{background:#fff;color:#c2410c;border:1px solid #fdba74}}
.fimi-hero .cta .ghost:hover{{border-color:#c2410c;background:#fff7ed}}
.fimi-hero .live{{display:inline-flex;align-items:center;gap:6px;font-size:.74rem;color:#7c4a12;background:#ffedd5;border:1px solid #fdba74;border-radius:999px;padding:4px 10px;margin-left:auto;font-weight:600}}
@media(max-width:640px){{.fimi-hero .live{{margin-left:0}} .fimi-hero .arrow{{transform:rotate(90deg)}} .fimi-hero h1{{font-size:1.3rem}}}}
/* Funnel modal: en móvil la escalera de anchos (max-width inline) queda muy
   estrecha y corta el texto (tarjetas 04/05). Se fuerza ancho completo. */
@media(max-width:560px){{.funnel-card{{max-width:100% !important;width:100% !important}}}}
@media(min-width:561px){{.funnel-card{{min-width:290px}}}}

/* ---- PILOTO vs PRODUCCIÓN (distinción clara en tarjetas y pestañas) ---- */
.prod-badge{{display:inline-block;font-size:.66rem;font-weight:700;letter-spacing:.04em;
  color:#166534;background:#dcfce7;border:1px solid #86efac;border-radius:999px;
  padding:2px 9px;margin-bottom:6px}}
.pilot-badge{{display:inline-block;font-size:.66rem;font-weight:800;letter-spacing:.04em;
  color:#7c2d12;background:#ffedd5;border:1px solid #fdba74;border-radius:999px;
  padding:2px 9px;margin-bottom:6px;animation:pilotPulse 2s ease-in-out infinite}}
.pilot-frase{{background:#fff7ed;border:1.5px solid #fdba74;border-radius:8px;
  padding:6px 10px;color:#9a3412;font-weight:700;animation:pilotPulse 2s ease-in-out infinite}}
@keyframes pilotPulse{{0%,100%{{box-shadow:0 0 0 0 rgba(217,119,6,.40)}}50%{{box-shadow:0 0 0 6px rgba(217,119,6,0)}}}}
@media(prefers-reduced-motion:reduce){{.pilot-badge,.pilot-frase{{animation:none}}}}
</style></head>
<body>
<header>
<div class="fimi-brandbar">
  <a class="brand" href="/" title="Radar FIMI · Centro de observación de desinformación en español">
    <span class="logo">📡</span> Radar FIMI
  </a>
  <a class="transp" href="/research.html" title="Investigación y validación del modelo">Research</a>
  <a class="transp" href="/api.html" title="API pública (datos en JSON)">API</a>
  <a class="transp" href="/operativa.html" title="Manual de operación (uso y administración)">Operativa</a>
  <a class="transp" href="#transparencia" data-panel="tabTransparencia" onclick="fimiPanel('tabTransparencia');return false">Transparencia</a>
  <div class="chips">
    <span class="chip"><span class="dot" style="background:#64748b"></span>Proyecto independiente</span>
    <span class="chip"><span class="dot" style="background:#0284c7"></span>Open Source</span>
    <span class="chip prod"><span class="dot"></span>En producción</span>
  </div>
  <a class="gh-link" href="https://github.com/mcasrom/hybrid-fimi-radar" target="_blank" rel="noopener noreferrer">GitHub ↗</a>
</div>
</header>
<main>
<div id="tabRadar" class="tab-panel active">
<section class="fimi-hero">
  <div class="fimi-hero-eyebrow">
    <span><span class="dot" style="background:#c2410c"></span>Radar FIMI · Centro de observación en español</span>
    <span class="live" id="fimiHeroLive">{_lt_icon}&nbsp;{_lt_estado} · última ingesta {_lt_rel}</span>
  </div>
  <h1>Radar FIMI · Centro de situación de desinformación</h1>
  <p class="sub">Monitorizamos <strong>{n_sources} fuentes</strong> y <strong>{n_events} eventos</strong> en {tema_nombres_html}
  para detectar <strong>coordinación, amplificación y anomalías</strong> — la maquinaria de la
  manipulación de información (FIMI). Observamos el comportamiento en red; nunca atribuimos a un actor sin evidencia.</p>
  <div class="chain">
    <div class="step"><b><span class="ic">👁</span> OBSERVAR</b><span>captura de {n_sources} fuentes abiertas en {len(temas)} temas, sin prejuicio de actor.</span></div>
    <div class="arrow">→</div>
    <div class="step"><b><span class="ic">📡</span> DETECTAR</b><span>señal de coordinación, amplificación y anomalías sobre {n_clusters} clusters activos.</span></div>
    <div class="arrow">→</div>
    <div class="step"><b><span class="ic">⚖️</span> CONTRASTAR</b><span>las hipótesis se contrastan contra la evidencia. Una señal no es una atribución.</span></div>
  </div>
  <div class="cta">
    <a href="#estado" class="primary" onclick="document.getElementById('estado').scrollIntoView({{behavior:'smooth'}});return false">Ver estado por tema →</a>
  </div>
</section>

 {resumen_html}

 {funnel_html}

 {detalle_wrap_open}

<script>window.FIMI_SHARE = {share_by_tema_js};</script>

 {tabs_ui}

<details style="margin:26px 0 4px">
<summary style="cursor:pointer;border-top:2px solid #e2e8f0;padding-top:12px;font-size:.84rem;color:#c2410c;font-weight:700">
Resumen global del radar (narrativas · historial) — no pertenece a la pestaña activa; pulsa para abrir
</summary>
<div style="font-size:.78rem;color:#94a3b8;margin:8px 0 12px">
<b>Resumen global del radar</b> — las secciones de abajo (Narrativas, Historial) NO pertenecen
a la pestaña activa: son el estado de TODO el catálogo (todos los temas juntos). Usa la pestaña
de arriba para ver solo un tema; estas secciones son la vista de conjunto.
</div>

 {narrativas_combined}

{narr_align_block}

{hist_html}
</details>

{detalle_wrap_close}
</div><!-- /tabRadar -->
<div id="tabTransparencia" class="tab-panel">

<div class="card" id="que-es-fimi">
<h3 style="margin-bottom:6px">Qué es FIMI Radar</h3>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
<b>FIMI</b> — <i>Foreign Information Manipulation and Interference</i> (Manipulación e
Interferencia de Información Extranjera) — es el término que usan la UE y sus servicios de
inteligencia para describir operaciones híbridas: campañas que amplifican, coordinan o
distorsionan narrativas para influir en la opinión pública desde fuera de la frontera de un país.
</p>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
Este radar es una herramienta <b>OSINT</b> (<i>open-source intelligence</i>) que observa, en
tiempo casi real, tres fenómenos concretos sobre información pública:
</p>
<ul style="font-size:.84rem;color:#334155;padding-left:18px;line-height:1.7;margin:6px 0">
  <li><b>Amplificación</b> — cuándo un mismo titular o narrativa se repite en múltiples fuentes en una ventana de tiempo corta.</li>
  <li><b>Coordinación</b> — cuándo cuentas de redes sociales distintas publican el mismo contenido casi de forma simultánea, más allá de lo que explicaría el interés orgánico.</li>
  <li><b>Anomalías</b> — comportamientos que se desvían de lo que es habitual para un tema o cuenta dado.</li>
</ul>
<h3 style="font-size:.9rem;margin:14px 0 4px">Qué NO hace</h3>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
El radar <b>no atribuye</b>. Detectar coordinación no significa identificar quién está detrás ni
por qué. Puede ser una campaña de comunicación legítima (un partido, una ONG, una institución
movilizando a sus seguidores), un eco periodístico normal, o efectivamente una operación de
interferencia — el radar mide la estructura del fenómeno, no el motivo. Cuando no hay evidencia
suficiente para ir más allá, la conclusión es <b>UNKNOWN</b> — y eso se considera un resultado
válido, no un fallo del sistema.
</p>
<h3 style="font-size:.9rem;margin:14px 0 4px">Objetivo</h3>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
Dar a periodistas, investigadores y cualquier persona interesada una vista pública y verificable
de cómo se mueve la información en torno a temas concretos, sin necesidad de acceso a herramientas
de pago ni a datos privados de plataformas. Todo lo que el radar observa es público: RSS de medios,
Bluesky, Telegram público, Reddit y Google News.
</p>
<h3 style="font-size:.9rem;margin:14px 0 4px">Temas monitorizados hoy</h3>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
El catálogo es dinámico y se amplía cuando hay señal real que lo justifique: actualmente cubre
Frontera Sur (España-Marruecos), Geopolítica UE-Marruecos y Política nacional.
</p>
<h3 style="font-size:.9rem;margin:14px 0 4px">Cómo se decide qué vigilar</h3>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
El propio radar analiza el volumen de eventos que no encajan en ningún tema activo y señala patrones
recurrentes que podrían justificar ampliar el catálogo — pero la decisión de añadir, mantener o
cerrar un tema es siempre humana. El sistema avisa; no decide.
</p>
<h3 style="font-size:.9rem;margin:14px 0 4px">Transparencia</h3>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
El código es abierto (GitHub), las fuentes y su fiabilidad están documentadas y auditables en tiempo
real, y el proyecto no hace seguimiento de sus visitantes. Es un proyecto personal, sin financiación
externa ni afiliación institucional.
</p>
</div>

<div class="card">
<h3 id="fuentes">Fuentes y búsquedas activas</h3>
<p class="caption">Inventario real de config.yaml: qué se vigila y con qué palabras.
<b>{n_sources} fuentes de captura en total</b> ({n_src_feeds} feeds RSS · {n_src_plt} plataformas
· {n_src_tg} canales Telegram · {n_src_reddit} subreddits). Para añadir o quitar,
edita <code>config.yaml</code> en el repo (docs/FUENTES.md lo documenta).</p>
<div style="display:flex;gap:24px;flex-wrap:wrap">
  <div style="flex:1;min-width:260px">
    <b style="font-size:.9rem">RSS / feeds ({len(feeds)})</b>
    <ul style="font-size:.82rem;color:#334155;padding-left:18px;line-height:1.7">{feeds_html}</ul>
    <p style="font-size:.72rem;color:#94a3b8;margin:4px 0 8px">Cada feed muestra: orientación
    editorial · fiabilidad · relevancia analítica (alta/media/baja, valoración editorial del equipo).</p>
    <b style="font-size:.9rem">Plataformas de búsqueda ({n_src_plt})</b>
    <ul style="font-size:.82rem;color:#334155;padding-left:18px;line-height:1.7">{plt_html}</ul>
  </div>
  <div style="flex:1;min-width:260px">
    <b style="font-size:.9rem">Palabras clave ({len(keywords)})</b>
    <ul style="font-size:.82rem;color:#334155;padding-left:18px;line-height:1.7">{kw_html}</ul>
    <b style="font-size:.9rem">Telegram ({n_src_tg})</b>
    <p style="font-size:.82rem;color:#334155">{tg_html}</p>
    <b style="font-size:.9rem">Reddit ({n_src_reddit})</b>
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
{_scoring_html}
</div>

<div class="card" id="seguridad">
<h3>Seguridad del despliegue</h3>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
Cabeceras HTTP servidas por nginx (detrás de Cloudflare): <code>X-Frame-Options: DENY</code>,
<code>X-Content-Type-Options: nosniff</code>, <code>Referrer-Policy: strict-origin-when-cross-origin</code>,
<code>Strict-Transport-Security: max-age=31536000; includeSubDomains</code> (HSTS) y
<code>Permissions-Policy</code> restringida (cámara/micrófono/geolocalización bloqueadas).
</p>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
La <b>Content-Security-Policy</b> usa <code>script-src 'self' 'unsafe-inline'</code> porque este
dashboard es un único HTML autocontenido (CSS+JS inline que genera <code>gen_fimi_html.py</code> cada 6 h).
El inline lo produce el propio pipeline, no input de usuario, por lo que no supone un vector explotable
en la práctica.
</p>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
Estado real — <a href="https://developer.mozilla.org/en-US/observatory/analyze?host=fimi.viajeinteligencia.com"
target="_blank" rel="noopener noreferrer" style="color:#c2410c">Mozilla Observatory</a> (escaneo 2026-09-07):
<b>B+ 80/100, 11/12 tests</b>. Único fallo: CSP (−20 por <code>unsafe-inline</code>, el diseño autocontenido
mencionado). La nota mide el despliegue técnico, no la calidad del modelo. Otros controles:
rate-limit en <code>/api/*</code> (429), <code>.env</code> y <code>data/radar.db</code> con permisos 600,
validación de <code>cluster_label</code> en el export (anti path-traversal/SQLi) y endpoints de admin con
<code>x-admin-secret</code>.
</p>
</div>

<div class="card" id="gobernanza">
<h3>Gobernanza de datos y salvaguardas</h3>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
<b>Qué se almacena.</b> Solo información <b>pública</b>: identificadores de cuenta de redes sociales
(Bluesky, Telegram, Reddit, Mastodon), el texto de sus publicaciones, las URLs compartidas y sus marcas
de tiempo. No se accede a contenido privado, mensajes directos ni datos personales sensibles, y no se
elabora ningún perfil de personas.
</p>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
<b>Qué NO entra en el análisis.</b> Los feeds RSS de medios no participan en el grafo de coordinación
(son fuentes legítimas que cubren los temas por periodismo, no cuentas coordinadas). No se monitorizan
cuentas privadas ni se rastrean individuos: el objeto del análisis es el <b>comportamiento de
coordinación</b>, no la identidad de quien lo emite.
</p>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
<b>Criterios de inclusión/exclusión.</b> Se incluyen cuentas públicas que publican sobre los temas del
catálogo. Se excluyen bots declarados, escáneres y fuentes sin texto analizable. Añadir o retirar temas
y cuentas es una decisión humana y queda registrada en la bitácora.
</p>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
<b>Retención.</b> Eventos y hallazgos se conservan <b>90 días</b>; los clusters se reemplazan en cada
ciclo (snapshot); la bitácora de cambios de estado es permanente. Los datos de suscripción (email/Telegram)
se guardan solo con consentimiento (doble opt-in) y se pueden dar de baja en cualquier momento.
</p>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
<b>Salvaguardas.</b> El radar <b>no atribuye</b> a actores concretos sin evidencia y trata «UNKNOWN»
como resultado válido. Para rectificaciones o consultas:
<a href="mailto:info-fimi@viajeinteligencia.com" style="color:#c2410c">info-fimi@viajeinteligencia.com</a>.
</p>
</div>

<div class="card" id="ciclo-vida">
<h3>Ciclo de vida de un tema y gobernanza</h3>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
<b>El sistema nunca decide.</b> Observa, sugiere y avisa; toda transición de estado la toma una
persona y queda registrada en la <a href="#bitacora" style="color:#c2410c">Bitácora</a>.
</p>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
<b>Alta → piloto.</b> Un tema nuevo nace en <b>piloto</b> (en calibración), con un aviso visible de
"lectura con cautela". Se observa sin prometer señal.
</p>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
<b>Promoción (piloto → producción).</b> Solo cuando supera una <b>ventana de validación</b>:
≥<b>72 h</b> de observación y ≥<b>8 ciclos</b> de snapshot sin errores de pipeline. Al cumplirse, el
radar avisa por Telegram y el tema muestra <b>«✅ lista para producción»</b>; la promoción se ejecuta
desde el panel de administración (o por CLI). Un error nuevo <b>reinicia</b> la ventana.
</p>
<p class="caption" style="font-size:.85rem;color:#334155;line-height:1.6">
<b>Cierre (sugerencia, no decisión).</b> El radar marca un tema como <b>candidato a cierre</b> si,
en una ventana de 21 días, acumula <b>&lt;2 hallazgos/día</b> (tras ≥14 días de operación) o si un
piloto lleva <b>&gt;90 días</b> sin promocionar — salvo que haya señal clara (último cluster ≥60).
Cerrar <b>exporta la evidencia</b>, detiene el pipeline del tema y lo registra en la Bitácora; se
puede <b>reabrir</b> en cualquier momento.
</p>
<p class="caption" style="font-size:.8rem;color:#94a3b8">
Detalle completo (umbrales y variables configurables):
<a href="https://github.com/mcasrom/hybrid-fimi-radar/blob/main/docs/GOBERNANZA.md" style="color:#c2410c">docs/GOBERNANZA.md</a>.
</p>
</div>

{salud_html}

{salud_kw_html}

{sistema_html}

{_salud_temas_html}

{bitacora_html}

{_emer_html}
</div><!-- /tabTransparencia -->

<footer style="border-top:1px solid #e5e5e5;margin-top:28px;padding-top:18px;text-align:center">
  <div style="font-size:.85rem;color:#666;line-height:1.9">
    <b>Radar FIMI</b> · <a href="/research.html" style="color:#c2410c">Research</a> · <a href="/api.html" style="color:#c2410c">API</a> · <a href="/operativa.html" style="color:#c2410c">Operativa</a> · <a href="#que-es-fimi" style="color:#c2410c">Qué es FIMI</a> · <a href="#metodologia" style="color:#c2410c">Metodología</a> · <a href="#fuentes" style="color:#c2410c">Fuentes y búsquedas</a> · <a href="#salud-keywords" style="color:#c2410c">Salud de keywords</a> · <a href="#sistema" style="color:#c2410c">Salud del sistema</a> · <a href="#salud-temas" style="color:#c2410c">Salud de los temas</a> · <a href="#seguridad" style="color:#c2410c">Seguridad</a> · <a href="#gobernanza" style="color:#c2410c">Gobernanza</a> · <a href="#ciclo-vida" style="color:#c2410c">Ciclo de vida</a> · <a href="#bitacora" style="color:#c2410c">Bitácora</a> · <a href="https://github.com/mcasrom/hybrid-fimi-radar" target="_blank" rel="noopener noreferrer" style="color:#c2410c">GitHub</a> · <a href="https://www.viajeinteligencia.com" style="color:#c2410c">ViajeInteligencia</a> · <a href="mailto:info-fimi@viajeinteligencia.com" style="color:#c2410c">Contacto</a> · <a href="/admin.html" style="color:#94a3b8">🔒 Panel de administración</a>
  </div>
  <a href="https://ko-fi.com/m_castillo" target="_blank" rel="noopener noreferrer"
     style="display:inline-flex;align-items:center;gap:8px;font-weight:700;font-size:13.5px;color:#fff;background:#13C3A5;border-radius:7px;padding:11px 18px;margin-top:14px;text-decoration:none">☕ Invítame a un café</a>
  <p style="font-size:.78rem;color:#888;margin:10px 0 0">Proyecto personal, sin rastreo. Los servidores los paga su autor; el newsletter solo usa tu email para el envío y nada más. Contacto: <a href="mailto:info-fimi@viajeinteligencia.com" style="color:#c2410c">info-fimi@viajeinteligencia.com</a></p>
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
      var ac=(b.getAttribute('data-accent')||'#c2410c');
      var bg=b.querySelector('.fimi-tab-badge');
      if(b.getAttribute('data-tema')===t){{
        b.style.background=ac;b.style.color='#000';b.style.borderColor=ac;
        b.style.boxShadow='0 1px 3px rgba(15,23,42,.15)';
      }}else{{
        b.style.background='#fff';b.style.color='#000';
        b.style.borderColor=ac+'55';b.style.boxShadow='none';
      }}
    }}
    var panes=document.querySelectorAll('.fimi-pane');
    for(i=0;i<panes.length;i++){{ p=panes[i];
      if(p.getAttribute('data-tema')===t){{ p.removeAttribute('hidden'); }}
      else {{ p.setAttribute('hidden',''); }}
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

  // Frescura de la última ingesta en TIEMPO REAL (JS): recalcula cada 30s el
  // "hace X" y el color a partir del timestamp absoluto (data-ts), en vez de
  // dejar congelado el "hace X" que se escribió al generar el HTML (que quedaba
  // viejo entre ciclos de 6h y confundía: parecía fresco cuando llevaba horas).
  function actualizarFrescura(){{
    var p=document.getElementById('fimiIngesta');
    if(!p) return;
    var ts=parseInt(p.getAttribute('data-ts')||'0',10);
    if(!ts) return;
    var ahora=Math.floor(Date.now()/1000);
    var min=Math.max(0, Math.floor((ahora-ts)/60));
    var rel;
    if(min<60) rel='hace '+Math.max(min,1)+' min';
    else if(min<1440) rel='hace '+Math.floor(min/60)+' h '+String(min%60).padStart(2,'0')+' min';
    else rel='hace '+Math.floor(min/1440)+' d';
    var color, icono, estado;
    if(min<420){{ color='#16a34a'; icono='🟢'; estado='al día'; }}
    else if(min<780){{ color='#d97706'; icono='🟠'; estado='tardando'; }}
    else {{ color='#dc2626'; icono='🔴'; estado='cron saltado'; }}
    var relEl=document.getElementById('fimiRel');
    var estEl=document.getElementById('fimiEstado');
    if(relEl) relEl.textContent=rel;
    if(estEl) estEl.textContent=icono+' '+estado;
    p.style.color=color;
    var heroEl=document.getElementById('fimiHeroLive');
    if(heroEl) heroEl.textContent=icono+' '+estado+' · última ingesta '+rel;
  }}
  setInterval(actualizarFrescura, 30000);
  window.actualizarFrescura = actualizarFrescura;
  actualizarFrescura();

  // Pre-cargar el formulario de sugerencia con un término emergente (AJUSTE 4).
  // Vuelve a la vista resumen (el formulario vive ahí), rellena el textarea y
  // hace scroll + foco para que el dueño solo tenga que pulsar enviar.
  window.precargarSugerencia = function(termino){{
    var R=document.getElementById('vistaResumen');
    var D=document.getElementById('vistaDetalle');
    var B=document.getElementById('btnVolver');
    if(R){{ R.style.display='block'; }}
    if(D){{ D.setAttribute('hidden',''); }}
    if(B){{ B.setAttribute('hidden',''); }}
    var txt=document.getElementById('sugerirTxt');
    if(txt){{
      var prop='Sugiero vigilar como posible tema emergente: ' + termino +
               ' (volumen fuera del catálogo detectado en el radar).';
      txt.value=prop;
      txt.focus();
      txt.scrollIntoView({{behavior:'smooth', block:'center'}});
    }}
  }};

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

  
  // Tab switching: Radar | Transparencia
  window.fimiPanel = function(id){{
    var panels=document.querySelectorAll('.tab-panel');
    var links=document.querySelectorAll('.fimi-brandbar a[data-panel]');
    for(var i=0;i<panels.length;i++){{
      if(panels[i].id===id){{ panels[i].classList.add('active'); }}
      else {{ panels[i].classList.remove('active'); }}
    }}
    for(var i=0;i<links.length;i++){{
      if(links[i].getAttribute('data-panel')===id){{ links[i].classList.add('active'); }}
      else {{ links[i].classList.remove('active'); }}
    }}
    window.scrollTo({{top:0,behavior:'smooth'}});
  }};

  // Footer anchors that point to Transparencia content: open that tab
  var _transAnchors=['que-es-fimi','metodologia','fuentes','salud-fuentes','salud-keywords','sistema','salud-temas','bitacora','seguridad','gobernanza','ciclo-vida','transparencia'];
  document.querySelectorAll('a[href^="#"]').forEach(function(a){{
    var h=a.getAttribute('href').replace('#','');
    if(_transAnchors.indexOf(h)!==-1){{
      a.addEventListener('click',function(ev){{
        ev.preventDefault();
        if(window.fimiPanel){{ window.fimiPanel('tabTransparencia'); }}
        setTimeout(function(){{ var t=document.getElementById(h); if(t){{ t.scrollIntoView({{behavior:'smooth',block:'start'}}); }} }},50);
      }});
    }}
  }});

  var hash=(location.hash||'').replace('#','');
  // deep-link #tema abre directamente el detalle de ese tema
  if(hash && document.querySelector('.fimi-pane[data-tema="'+hash+'"]')){{ abrirDetalle(hash); }}
}})();
</script>
</body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"OK: {OUT} — {n_events} eventos, {n_sources} fuentes, {len(clusters)} clusters")
    # Página /research (independiente, misma run para que los números no se anticuen).
    # Envuelta: si falla, el dashboard (página principal) sigue intacto.
    try:
        render_research_html(cfg, feeds, keywords, temas_cfg, temas)
    except Exception as e:
        print(f"research html fallo (no bloquea el dashboard): {e}")


if __name__ == "__main__":
    main()
