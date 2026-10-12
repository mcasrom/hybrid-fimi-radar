"""Tests de la cola de revisión de relevancia (S2, 12-oct)."""
import importlib.util
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "revisar_relevancia", os.path.join(BASE, "detection", "revisar_relevancia.py"))
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)


def test_band():
    assert rr.band(85) == "CRITICAL"
    assert rr.band(61) == "HIGH"
    assert rr.band(45) == "ANOMALOUS"
    assert rr.band(25) == "WATCH"
    assert rr.band(0) == "NORMAL"
    assert rr.band(None) == "NORMAL"


def test_norm():
    n = rr.norm("Ceuta, ¡frontera!")
    assert "ceuta" in n and "frontera" in n
    assert "," not in n and "!" not in n
    assert rr.norm("") == ""


def test_kw_terms_frontera_sur_incluye_legado():
    # Las keywords sin tema (legado) pertenecen a frontera_sur.
    terms = rr.kw_terms("frontera_sur")
    assert "ceuta" in terms and "melilla" in terms


def test_kw_terms_otro_tema_no_cuela_legado():
    terms = rr.kw_terms("energia")
    assert "ceuta" not in terms
