"""Test del calculador de kappa (detection/validacion_kappa.py)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_kappa_perfecto():
    from detection.validacion_kappa import kappa
    po, pe, k = kappa([("si", "si"), ("no", "no"), ("si", "si")])
    assert po == 1.0 and k == 1.0


def test_kappa_desacuerdo_total():
    from detection.validacion_kappa import kappa
    po, pe, k = kappa([("si", "no"), ("no", "si")])
    assert po == 0.0
    assert k <= 0.0


def test_kappa_parcial():
    from detection.validacion_kappa import kappa
    # 3 de 4 coinciden -> po=0.75
    po, pe, k = kappa([("si", "si"), ("si", "si"), ("no", "no"), ("si", "no")])
    assert abs(po - 0.75) < 1e-9
    assert 0.0 < k < 1.0


def test_precision_excluye_dudoso():
    from detection.validacion_kappa import precision
    rows = {
        "a": {"label_coordinacion": "si"},
        "b": {"label_coordinacion": "si"},
        "c": {"label_coordinacion": "no"},
        "d": {"label_coordinacion": "dudoso"},
    }
    yes, no, dud, prec = precision(rows, "label_coordinacion")
    assert (yes, no, dud) == (2, 1, 1)
    assert abs(prec - 66.666) < 0.1
