#!/usr/bin/env python3
"""Contrato mínimo de las cifras publicadas en la ficha de protestas."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from detection.protestas import validar_senal  # noqa: E402


def _ok() -> dict:
    return {
        "eventos": 100,
        "cuentas": 20,
        "cuentas_cluster": 10,
        "clusters": 2,
        "signal_clusters": 2,
        "small_clusters": 0,
        "bandas": {"CRITICAL": 0, "HIGH": 1, "ANOMALOUS": 1, "WATCH": 0, "NORMAL": 0},
        "bandas_signal": {"CRITICAL": 0, "HIGH": 1, "ANOMALOUS": 1, "WATCH": 0, "NORMAL": 0},
        "tie59_all": 1,
        "tie59_signal": 1,
        "top_signal": [
            {"label": "a", "score": 79.0, "cuentas": 5, "eventos": 11},
            {"label": "b", "score": 59.0, "cuentas": 5, "eventos": 20},
        ],
    }


def test_senal_consistente():
    assert validar_senal(_ok()) == []


def test_senal_detecta_bandas_que_no_cuadran():
    s = _ok()
    s["bandas"]["WATCH"] = 1
    assert any("bandas" in e for e in validar_senal(s))


def test_senal_detecta_signal_y_pequenos():
    s = _ok()
    s["small_clusters"] = 1
    assert any("señal + pequeños" in e for e in validar_senal(s))


def test_senal_detecta_tabla_con_dos_cuentas():
    s = _ok()
    s["top_signal"][0]["cuentas"] = 2
    assert any("<3 cuentas" in e for e in validar_senal(s))


def test_senal_detecta_empate_59_mal_calculado():
    s = _ok()
    s["tie59_signal"] = 2
    assert any("tie59_signal" in e for e in validar_senal(s))
