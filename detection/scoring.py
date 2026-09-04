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
