#!/usr/bin/env python3
"""Scoring configurable 0-100 con componentes y bandas.

Bandas (configurables en config.yaml):
  0-19 NORMAL · 20-39 WATCH · 40-59 ANOMALOUS · 60-79 HIGH · 80-100 CRITICAL

Cada score muestra sus componentes (coordination, synchronization, content
similarity, amplification, infrastructure, network density).
"""
import yaml
from pathlib import Path


def load_bands(config):
    """Carga las bandas de severidad desde config.yaml."""
    bands = (config or {}).get("scoring", {}).get("bands", {})
    return {
        "NORMAL": (0, 19),
        "WATCH": (20, 39),
        "ANOMALOUS": (40, 59),
        "HIGH": (60, 79),
        "CRITICAL": (80, 100),
    }


def band_for(score, bands):
    """Devuelve la etiqueta de banda para un score 0-100."""
    for label, (lo, hi) in bands.items():
        if lo <= score <= hi:
            return label
    return "NORMAL"


def _tema_weights(config, tema):
    """Pesos específicos del tema (config->temas-><tema>->scoring->weights).

    Permite calibrar por tema: p.ej. politica_nacional (piloto) da mucho más
    peso a la anomalía para no marcar como ANOMALOUS la coordinación humana
    partidista legítima (sync+contenido altos pero anomalía ~0).
    """
    if not tema:
        return {}
    return (config or {}).get("temas", {}).get(tema, {}).get("scoring", {}).get("weights", {}) or {}


def compute_scores(components, config, tema=None):
    """Combina componentes en overall_score ponderado.

    components: dict con synchronization, content_similarity, amplification,
    infrastructure, network_density (0-100) y anomaly (0-100).
    weights: configurables en config.yaml->scoring->weights, con override por
    tema en config.yaml->temas-><tema>->scoring->weights (merge sobre global).
    """
    w = (config or {}).get("scoring", {}).get("weights", {})
    default_w = {
        "synchronization": 0.25, "content_similarity": 0.20,
        "amplification": 0.20, "infrastructure": 0.15,
        "network_density": 0.10, "anomaly": 0.10,
    }
    for k, v in default_w.items():
        w.setdefault(k, v)
    w.update(_tema_weights(config, tema))

    overall = sum(components.get(k, 0) * w.get(k, 0) for k in default_w)
    overall = round(min(100.0, max(0.0, overall)), 1)
    return overall, w


def _scale_min_accounts(config, tema=None):
    """Mínimo de cuentas exigido por banda (config->scoring->scale_min_accounts).

    Merge sobre los globales con el override por tema
    (config->temas-><tema>->scoring->scale_min_accounts), igual que los pesos.
    """
    sma = (config or {}).get("scoring", {}).get("scale_min_accounts", {}) or {}
    if tema:
        t = (config or {}).get("temas", {}).get(tema, {}).get("scoring", {})
        sma = {**sma, **((t or {}).get("scale_min_accounts", {}) or {})}
    return sma


def scale_cap(overall, n_accounts, config, tema=None):
    """Límite de banda según la masa del cluster (nº de cuentas).

    La señal de coordinación a gran escala debe alarmar más que 2-3 cuentas
    sincronizadas (p.ej. una pareja de activistas no debe leerse como red
    orquestada). Si el cluster no llega al mínimo de cuentas de su banda, el
    overall se recorta al tope de la banda inmediatamente inferior permitida.

    Config: scoring.scale_min_accounts = {HIGH: n, CRITICAL: n} (nº mínimo de
    cuentas para poder estar en esa banda). Sin config no aplica límite.
    """
    sma = _scale_min_accounts(config, tema)
    if not sma:
        sma = {"CRITICAL": 10}  # defensivo: por defecto CRITICAL exige masa
    bands = load_bands(config)
    order = ["NORMAL", "WATCH", "ANOMALOUS", "HIGH", "CRITICAL"]
    cur = band_for(overall, bands)
    # banda máxima alcanzable con las cuentas actuales
    allowed = "NORMAL"
    for b in order:
        need = sma.get(b)
        if need is None or n_accounts >= need:
            allowed = b
        else:
            break
    if order.index(cur) > order.index(allowed):
        return float(bands[allowed][1])  # tope de la banda permitida
    return overall


def _tema_scale(config, tema, section, default):
    """Parámetros de escala: globales config->scoring-><section>, con override
    por tema (config->temas-><tema>->scoring-><section>). Igual que los pesos."""
    merged = dict(default)
    if config:
        merged.update((config.get("scoring", {}) or {}).get(section, {}) or {})
    if tema and config:
        t = (config.get("temas", {}) or {}).get(tema, {}).get("scoring", {})
        merged.update((t or {}).get(section, {}) or {})
    return merged


def scale_bonus(overall, accounts, config=None, tema=None):
    """Bonus por escala (Tarea 1 del análisis 05/Sep): a igualdad de
    componentes, más cuentas puntúan más. Corrige el orden invertido en la
    vista activa (un cluster de 2 cuentas puntuaba igual o más que uno de 49).
    bonus = min(cap, cuentas * per_account); acotado para no desbordar el
    score natural. Config: scoring.scale_bonus = {cap, per_account}."""
    p = _tema_scale(config, tema, "scale_bonus", {"cap": 3.5, "per_account": 0.08})
    bonus = min(float(p.get("cap", 3.5)), accounts * float(p.get("per_account", 0.08)))
    return min(100.0, float(overall) + bonus)


def scale_floor(overall, accounts, events, infra, config=None, tema=None):
    """Piso híbrido de masa (05/Sep): un cluster con pocas cuentas solo puede
    llegar a WATCH salvo evidencia adicional.

    Regla: cuentas < min_accounts (3) => banda máx WATCH y se etiqueta
    "posible ruido de bajo volumen", EXCEPTO si tiene >= except_events eventos
    sostenidos o infraestructura compartida >= except_infra: en ese caso puede
    alcanzar HIGH (79), pero NUNCA CRITICAL (eso lo fija scale_cap con
    scale_min_accounts.CRITICAL=10).

    Conserva como señal las parejas de 2 cuentas con volumen (cluster_012=22
    eventos, cluster_006=31) y tumba a WATCH las parejas efímeras (2-3
    eventos) que saturaban el top con banda alta.
    Config: scoring.scale_floor = {min_accounts, except_events, except_infra}."""
    p = _tema_scale(config, tema, "scale_floor",
                    {"min_accounts": 3, "except_events": 10, "except_infra": 80})
    bands = load_bands(config)
    if accounts < p["min_accounts"]:
        excepcion = (events >= p["except_events"]) or (infra >= p["except_infra"])
        if not excepcion:
            return float(bands["WATCH"][1])  # 39 — posible ruido de bajo volumen
        return min(float(overall), float(bands["HIGH"][1]))  # 79 máx, nunca CRITICAL
    return overall


def solve_scale(overall, accounts, events, infra, config=None, tema=None):
    """Aplica la escala completa del cluster (orden correcto):
    1) bonus por masa; 2) piso híbrido; 3) cap CRITICAL/HIGH por masa mínima.

    Devuelve (overall_final, floored):
      floored=True => cae en "posible ruido de bajo volumen" (para marcarlo
      en el assessment, la tarjeta y el informe)."""
    overall = scale_bonus(overall, accounts, config, tema)
    floored = False
    p = _tema_scale(config, tema, "scale_floor",
                    {"min_accounts": 3, "except_events": 10, "except_infra": 80})
    bands = load_bands(config)
    if accounts < p["min_accounts"]:
        excepcion = (events >= p["except_events"]) or (infra >= p["except_infra"])
        if not excepcion:
            overall = float(bands["WATCH"][1])
            floored = True
        else:
            overall = min(float(overall), float(bands["HIGH"][1]))
    overall = scale_cap(overall, accounts, config, tema)
    return overall, floored
