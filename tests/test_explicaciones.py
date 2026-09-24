#!/usr/bin/env python3
"""Tests de detection/explicaciones.py (explicaciones alternativas por cluster).

Cubren los criterios de aceptación acordados: eco mainstream, eco de una sola URL,
viralidad orgánica, sincronización sin operador y artefacto del grafo, además del
estado `unresolved` cuando nada encaja. La función es pura (sin I/O).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from detection.explicaciones import CODES, para_cluster, principal, resumen  # noqa: E402

_VALID = {"supported", "plausible", "ruled_out"}


def _by_code(items):
    return {it["code"]: it for it in items}


def _base(**kw):
    args = {
        "accounts": 5, "n_events": 5, "n_urls": 5, "synchronization": 30.0,
        "content_similarity": 30.0, "amplification": 20.0, "infrastructure": 60.0,
        "anomaly": 50.0, "kcore": 0, "kcore_size": 0, "mainstream_frac": 0.1,
        "mainstream_cap_applied": False, "single_piece_cap": False,
        "boilerplate_frac": 0.0, "top_hypothesis": "", "hypotheses": None,
    }
    args.update(kw)
    return args


def test_salida_estructurada_y_estados_validos():
    items = para_cluster(**_base())
    assert [it["code"] for it in items] == [c for c, _ in CODES]
    assert all(it["status"] in _VALID for it in items)
    assert all("evidence" in it for it in items)


def test_eco_mainstream_soportado():
    items = _by_code(para_cluster(**_base(mainstream_frac=0.86)))
    assert items["mainstream_echo"]["status"] == "supported"
    assert items["mainstream_echo"]["evidence"]["mainstream_domain_fraction"] == 0.86


def test_eco_mainstream_por_cap_aplicado():
    items = _by_code(para_cluster(**_base(mainstream_frac=0.6,
                                          mainstream_cap_applied=True)))
    assert items["mainstream_echo"]["status"] == "supported"


def test_eco_una_sola_url_soportado():
    items = _by_code(para_cluster(**_base(n_urls=1, n_events=4, single_piece_cap=True)))
    assert items["single_piece_echo"]["status"] == "supported"
    assert items["single_piece_echo"]["evidence"]["distinct_urls"] == 1


def test_viralidad_organica_soportada():
    items = _by_code(para_cluster(**_base(synchronization=72, anomaly=8,
                                          infrastructure=10)))
    assert items["organic_viral"]["status"] == "supported"


def test_sincronizacion_sin_operador_por_h2b():
    items = _by_code(para_cluster(**_base(top_hypothesis="H2b")))
    assert items["synchronized_without_operator"]["status"] == "supported"


def test_artefacto_de_grafo_soportado():
    items = _by_code(para_cluster(**_base(accounts=40, kcore_size=1, infrastructure=10)))
    assert items["graph_artifact"]["status"] == "supported"


def test_movilizacion_legitima_plausible():
    items = _by_code(para_cluster(**_base(synchronization=65, anomaly=20,
                                          content_similarity=55)))
    assert items["legitimate_mobilization"]["status"] == "plausible"


def test_unresolved_cuando_nada_encaja():
    items = _by_code(para_cluster(**_base()))
    assert items["unresolved"]["status"] == "supported"
    assert not any(it["status"] == "supported" for it in items.values()
                   if it["code"] != "unresolved")


def test_unresolved_ruled_out_cuando_hay_explicacion():
    items = _by_code(para_cluster(**_base(mainstream_frac=0.9)))
    assert items["unresolved"]["status"] == "ruled_out"


def test_principal_y_resumen():
    items = para_cluster(**_base(mainstream_frac=0.9))
    assert principal(items) == "mainstream_echo"
    r = resumen(items)
    assert r["principal"] == "mainstream_echo"
    assert "mainstream_echo" in r["supported"]
