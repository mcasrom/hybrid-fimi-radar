#!/usr/bin/env python3
"""Tests de detection/subtipo.py (rol narrativo del cluster).

Casos guiados por la propuesta de revisión: incidente, respuesta oficial, meta,
narrativa potencial y señal de coordinación, más la desambiguación por prioridad.
Función pura (sin I/O).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from detection.subtipo import clasificar_texto, dominante  # noqa: E402


def test_incident_report():
    t = "España sufre un ciberataque ruso contra una infraestructura crítica"
    assert clasificar_texto(t) == "incident_report"


def test_potential_narrative():
    t = "Una operación de influencia rusa difunde propaganda contra España"
    assert clasificar_texto(t) == "potential_narrative"


def test_official_response():
    t = "El Gobierno aprueba una estrategia contra la desinformación"
    assert clasificar_texto(t) == "official_response"


def test_meta_analysis():
    t = "Expertos analizan en un simposio qué es la guerra híbrida"
    assert clasificar_texto(t) == "meta_analysis"


def test_coordination_signal():
    t = "Una red de bots orquestó la amplificación coordinada del mensaje"
    assert clasificar_texto(t) == "coordination_signal"


def test_prioridad_meta_sobre_incidente():
    assert clasificar_texto("Expertos analizan el ciberataque") == "meta_analysis"


def test_prioridad_respuesta_sobre_incidente():
    assert clasificar_texto("El Ministerio investiga el ciberataque") == "official_response"


def test_sin_subtipo():
    assert clasificar_texto("El tiempo en Madrid este fin de semana") is None


def test_texto_vacio():
    assert clasificar_texto("") is None
    assert clasificar_texto(None) is None


def test_dominante_con_recuento():
    texts = [
        "El Gobierno condena el ciberataque ruso",
        "Expertos analizan el ciberataque",
        "Expertos publican un estudio sobre la amenaza híbrida",
    ]
    d = dominante(texts)
    assert d["dominant"] == "meta_analysis"
    assert d["counts"]["meta_analysis"] == 2
    assert d["counts"]["official_response"] == 1
    assert d["label"] == "Análisis / meta"


def test_dominante_sin_textos():
    d = dominante([])
    assert d["dominant"] == "" and d["counts"] == {}
