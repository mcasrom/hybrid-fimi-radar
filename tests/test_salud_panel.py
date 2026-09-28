#!/usr/bin/env python3
"""Tests de detection/salud_panel.py (panel de salud multi-tema del admin).

Cubren las funciones puras (dependencia y avisos). El calculo completo hace E/S
contra radar.db y no se ejercita aqui.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import detection.salud_panel as sp  # noqa: E402


def test_dependencia():
    assert sp._dependencia({"a": 90, "b": 10}) == (90, "a")
    assert sp._dependencia({"a": 50, "b": 50}) == (50, "a")
    assert sp._dependencia({}) == (0, "—")


def test_avisos(monkeypatch, tmp_path):
    est = tmp_path / "kw.json"
    est.write_text(json.dumps({"elecciones": {"alerta": True, "sin_etiquetar": 106}}), encoding="utf-8")
    monkeypatch.setattr(sp, "ESTADO_KEYWORDS", est)

    temas = [{
        "tema": "elecciones", "eventos": 1000, "dependencia_pct": 90,
        "fuente_top": "bluesky", "sync": 0, "pot_narrativas": 0,
    }]
    cl = {"elecciones": {"clusters": 10, "feed": 9}}
    avisos = sp._avisos(temas, cl)
    tipos = {a["tipo"] for a in avisos}
    assert "tema_ciego" in tipos
    assert "dependencia" in tipos
    assert "senal_baja" in tipos
    assert "sin_senal" in tipos
    # ordenados por nivel (alto antes que medio/bajo)
    assert avisos[0]["nivel"] == "alto"


def test_avisos_tema_sin_volumen_no_avisa(monkeypatch, tmp_path):
    est = tmp_path / "kw.json"
    est.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sp, "ESTADO_KEYWORDS", est)
    temas = [{"tema": "x", "eventos": 10, "dependencia_pct": 99,
              "fuente_top": "bluesky", "sync": 0, "pot_narrativas": 0}]
    assert sp._avisos(temas, {}) == []
