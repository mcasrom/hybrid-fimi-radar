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
