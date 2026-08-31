"""Señales estadísticas de comportamiento automatizado / inorgánico.

NUNCA concluye "es un bot" ni "es una granja": produce señales graduadas
(0..1) consistentes con automatización, y deja la interpretación al humano.

Señales (todas explicables):
  - regularidad: CV bajo del intervalo + pocos intervalos extremos
  - uniformidad horaria: publica en TODAS las horas del día (las 24h) — inusual
    en humanos
  - sincronización: alta fracción de intervalos muy cortos (<60s) repetidos
  - ratio share alto (amplificación sin creación)
  - baja diversidad de hashtags / dominios (monotema)
  - alta concentración temporal (ráfagas)
  - near-dup alto (texto reutilizado)
"""
import numpy as np


def bot_signal_score(feat, weights=None):
    """Combina características en un score de automatización 0..1, con el
    detalle de cada señal para explicabilidad."""
    if feat is None:
        return 0.0, {}

    # penalizar muestra pequeña: con pocos eventos el score no es confiable.
    # 0 eventos -> 0; 2 eventos -> se reduce a la mitad; >=10 -> pleno.
    n = feat.get("n_events", 0)
    confianza = min(1.0, n / 10.0)

    signals = {}

    # regularidad: humanos tienen CV de intervalo alto (publican a horas variables)
    cv = feat.get("cv_interval", 0.0)
    signals["regularidad_alta"] = float(np.clip(1.0 - cv, 0, 1))

    # sincronización: muchos intervalos < 60 s
    signals["sincronizacion"] = float(np.clip(feat.get("frac_short_int", 0.0) * 5, 0, 1))

    # uniformidad horaria: cuántas horas distintas publica
    signals["actividad_ininterrumpida"] = float(feat.get("hour_uniformity", 0.0))

    # amplificación: ratio share alto y pocos textos propios
    signals["amplificacion_sin_creacion"] = float(np.clip(feat.get("share_ratio", 0.0) * 2, 0, 1))

    # monotonía de contenido
    hd = feat.get("hashtag_diversity", 0.0)
    signals["monotonia_hashtags"] = float(np.clip(1.0 - hd * 3, 0, 1))
    dd = feat.get("domain_diversity", 0.0)
    signals["monotonia_dominios"] = float(np.clip(1.0 - dd * 3, 0, 1))

    # ráfagas / concentración
    signals["rafagas"] = float(np.clip(feat.get("max_concentration_1h", 0.0) * 2, 0, 1))

    # reutilización de texto
    signals["texto_reutilizado"] = float(np.clip(feat.get("near_dup_ratio", 0.0), 0, 1))

    if weights is None:
        weights = {
            "regularidad_alta": 1.0, "sincronizacion": 1.0,
            "actividad_ininterrumpida": 1.0, "amplificacion_sin_creacion": 1.0,
            "monotonia_hashtags": 1.0, "monotonia_dominios": 1.0,
            "rafagas": 1.0, "texto_reutilizado": 1.0,
        }

    score = sum(signals[k] * weights.get(k, 1.0) for k in signals) / sum(weights.values())
    score = float(np.clip(score, 0, 1)) * confianza
    return score, signals
