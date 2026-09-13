#!/usr/bin/env python3
"""Tests unitarios de las piezas críticas del detector FIMI.

Cubren la lógica que más se ha tocado y donde un cambio silencioso rompería el
sistema sin que la validación sintética lo notara:

  - detection/scoring.py      : bandas, pesos (con override por tema) y la escala
                                (bonus por masa, piso híbrido, cap por masa, eco de 1 pieza).
  - normalizer/clasificar.py  : match por límite de palabra (evita "mali" dentro de
                                "normalizing") y asignación multi-tema por contenido.
  - clustering/clustering.py  : prefijo de label por tema y componentes conexas.

Se ejecutan con pytest (ver .github/workflows/ci.yml):
    pytest -q tests/
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from detection.scoring import (  # noqa: E402
    band_for, compute_scores, load_bands, origen_unico_cap, scale_bonus,
    scale_cap, scale_floor, solve_scale,
)
from normalizer.clasificar import _matches, _tokens, temas_por_contenido  # noqa: E402
from clustering.clustering import _label_prefix, cluster_by_components  # noqa: E402


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def _cfg():
    return {
        "scoring": {
            "bands": {"NORMAL": [0, 19], "WATCH": [20, 39], "ANOMALOUS": [40, 59],
                      "HIGH": [60, 79], "CRITICAL": [80, 100]},
            "weights": {"synchronization": 0.25, "content_similarity": 0.20,
                        "amplification": 0.20, "infrastructure": 0.15,
                        "network_density": 0.10, "anomaly": 0.10},
            "scale_min_accounts": {"HIGH": 2, "CRITICAL": 10},
            "scale_bonus": {"cap": 3.5, "per_account": 0.08},
            "scale_floor": {"min_accounts": 3, "except_events": 10, "except_infra": 80},
            "origen_unico": {"max_urls": 1, "min_events": 2, "cap_band": "ANOMALOUS"},
        }
    }


@pytest.mark.parametrize("score,banda", [
    (0, "NORMAL"), (19, "NORMAL"), (20, "WATCH"), (39, "WATCH"),
    (40, "ANOMALOUS"), (59, "ANOMALOUS"), (60, "HIGH"), (79, "HIGH"),
    (80, "CRITICAL"), (100, "CRITICAL"),
])
def test_band_for(score, banda):
    assert band_for(score, load_bands(_cfg())) == banda


def test_compute_scores_global_y_override_por_tema():
    cfg = _cfg()
    comp = {"synchronization": 0, "content_similarity": 0, "amplification": 0,
            "infrastructure": 0, "network_density": 0, "anomaly": 100}
    # global: anomaly pesa 0.10 -> 10.0
    overall, _ = compute_scores(comp, cfg)
    assert overall == 10.0
    # override por tema: anomaly 0.40 -> 40.0
    cfg["temas"] = {"politica_nacional": {"scoring": {"weights": {"anomaly": 0.40}}}}
    overall_t, _ = compute_scores(comp, cfg, tema="politica_nacional")
    assert overall_t == 40.0


def test_scale_bonus():
    assert scale_bonus(50, 0, _cfg()) == 50.0
    assert scale_bonus(50, 10, _cfg()) == pytest.approx(50.8)
    # el bonus está acotado por el cap
    assert scale_bonus(50, 1000, _cfg()) == pytest.approx(53.5)


def test_scale_floor_piso_hibrido():
    cfg = _cfg()
    # <3 cuentas sin excepción -> tope WATCH (39)
    assert scale_floor(90, 2, events=1, infra=0, config=cfg) == 39.0
    # <3 cuentas con volumen sostenido -> excepción, máx HIGH (79)
    assert scale_floor(90, 2, events=15, infra=0, config=cfg) == 79.0
    # <3 cuentas con infraestructura compartida -> excepción
    assert scale_floor(90, 2, events=1, infra=90, config=cfg) == 79.0
    # >=3 cuentas -> sin piso
    assert scale_floor(90, 5, events=1, infra=0, config=cfg) == 90.0


def test_scale_cap_por_masa():
    cfg = _cfg()
    # 2 cuentas: CRITICAL exige 10 -> recorta a HIGH (79)
    assert scale_cap(90, 2, cfg) == 79.0
    # 10 cuentas: CRITICAL permitido
    assert scale_cap(90, 10, cfg) == 90.0
    # por debajo de HIGH (2) -> recorta a la banda permitida (ANOMALOUS, 59)
    assert scale_cap(90, 1, cfg) == 59.0


def test_origen_unico_cap():
    cfg = _cfg()
    # 1 sola URL y >=2 eventos -> eco de 1 pieza, tope ANOMALOUS (59)
    overall, eco = origen_unico_cap(90, n_urls=1, n_events=5, config=cfg)
    assert eco is True and overall == 59.0
    # 2 URLs -> no es eco
    overall2, eco2 = origen_unico_cap(90, n_urls=2, n_events=5, config=cfg)
    assert eco2 is False and overall2 == 90.0


def test_solve_scale_orden_completo():
    cfg = _cfg()
    # 2 cuentas efímeras con 1 URL y 2 eventos: piso -> 39, cap -> 39, eco -> 39
    overall, floored, eco = solve_scale(90, accounts=2, events=2, infra=0,
                                        config=cfg, n_urls=1)
    assert overall == 39.0 and floored is True and eco is True
    # cluster grande y sano: se mantiene
    overall2, floored2, eco2 = solve_scale(70, accounts=20, events=50, infra=50,
                                           config=cfg, n_urls=8)
    assert overall2 == pytest.approx(70 + min(3.5, 20 * 0.08))
    assert floored2 is False and eco2 is False


# --------------------------------------------------------------------------- #
# normalizer/clasificar
# --------------------------------------------------------------------------- #
def test_matches_limite_de_palabra_no_subcadena():
    # "mali" NO debe matchear dentro de "normalizing" (bug corregido 11/Sep)
    assert _matches("mali", _tokens("Mali"), "normalizing the data",
                    ["normalizing", "the", "data"]) is False
    assert _matches("mali", _tokens("Mali"), "la situacion en mali",
                    ["la", "situacion", "en", "mali"]) is True


def test_temas_por_contenido_multitermino():
    kws = [
        {"palabra": "Mali", "tema": "sahel"},
        {"palabra": "relaciones España Marruecos", "tema": "geopolitica_ue_marruecos"},
    ]
    # "Mali" -> sahel
    assert "sahel" in temas_por_contenido("La crisis en Mali se agrava", kws)
    # "normalizing" NO debe activar sahel por subcadena
    assert "sahel" not in temas_por_contenido("normalizing the dataset", kws)
    # dos términos de la keyword de 3 (60%) presentes -> geopolitica
    assert "geopolitica_ue_marruecos" in temas_por_contenido(
        "Las relaciones entre España y Marruecos mejoran", kws)


# --------------------------------------------------------------------------- #
# clustering
# --------------------------------------------------------------------------- #
def test_label_prefix():
    assert _label_prefix("sahel") == "sahel_"
    assert _label_prefix(None) == ""


def test_cluster_by_components_aisla_componente_y_prefija():
    feat = pd.DataFrame(
        {"anomaly_score": [0.1, 0.2, 0.3]},
        index=["bsky:a", "bsky:b", "bsky:c"],
    )
    edges = pd.DataFrame(
        [{"source": "bsky:a", "target": "bsky:b", "weight": 1.0, "evidence": "texto"}]
    )
    cfg = {"thresholds": {"min_cluster_size": 2}}
    out = cluster_by_components(feat, edges, cfg, tema="t")
    assert out.at["bsky:a", "cluster_label"] == "t_cluster_000"
    assert out.at["bsky:b", "cluster_label"] == "t_cluster_000"
    # la cuenta aislada no recibe cluster
    assert pd.isna(out.at["bsky:c", "cluster_label"])
