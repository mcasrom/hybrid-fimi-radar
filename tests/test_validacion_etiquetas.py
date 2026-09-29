"""Normalizador de etiquetas de coordinación (validacion_curada_auto._label_coord).

Dos formatos conviven en data/validacion/ y antes de esto el nuevo se
descartaba en silencio (la muestra entera contaba como "sin etiquetar",
0 filas en el historial, sin ningún aviso):

  - antiguo (export_validacion.py):        `label`            = coordinado|no_coordinado|dudoso
  - nuevo  (auditoria_high --formato blind): `label_coordinacion` = si|no|dudoso
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from detection.validacion_curada_auto import (
    _completa,
    _label_coord,
    _metricas,
)


@pytest.mark.parametrize("viejo,esperado", [
    ("coordinado", "coordinado"),
    ("no_coordinado", "no_coordinado"),
    ("dudoso", "dudoso"),
    ("  coordinado  ", "coordinado"),
    ("COORDINADO", "coordinado"),
])
def test_formato_antiguo_se_respeta(viejo, esperado):
    assert _label_coord({"label": viejo}) == esperado


@pytest.mark.parametrize("nuevo,esperado", [
    ("si", "coordinado"),
    ("no", "no_coordinado"),
    ("dudoso", "dudoso"),
    (" SI ", "coordinado"),
])
def test_formato_uevo_se_traduce(nuevo, esperado):
    assert _label_coord({"label_coordinacion": nuevo}) == esperado


def test_si_esta_el_viejo_manda_este():
    """Con ambas columnas, manda `label` (formato de mayor antigüedad)."""
    assert _label_coord({"label": "no_coordinado", "label_coordinacion": "si"}) == "no_coordinado"


@pytest.mark.parametrize("fila", [
    {},
    {"label": ""},
    {"label_coordinacion": ""},
    {"label": "tal vez", "label_coordinacion": "quiza"},
])
def test_sin_etiqueta_devuelve_vacio(fila):
    assert _label_coord(fila) == ""


def test_completa_acepta_el_formato_nuevo():
    rows = [{"banda": "HIGH", "label_coordinacion": v} for v in ("si", "no", "dudoso")]
    assert _completa(rows) is True


def test_completa_rechaza_una_fila_sin_etiqueta():
    rows = [{"banda": "HIGH", "label_coordinacion": "si"},
            {"banda": "HIGH", "label_coordinacion": ""}]
    assert _completa(rows) is False


def test_metricas_con_formato_nuevo():
    """La cifra medida el 29/Sep/2026: 3 si, 33 no, 4 dudoso -> 8,3 % / 7,5 %."""
    rows = ([{"banda": "HIGH", "label_coordinacion": "si"}] * 3
            + [{"banda": "HIGH", "label_coordinacion": "no"}] * 33
            + [{"banda": "HIGH", "label_coordinacion": "dudoso"}] * 4)
    m = _metricas(rows)["HIGH"]
    assert (m["n"], m["coord"], m["no"], m["dud"]) == (40, 3, 33, 4)
    assert m["precision"] == 8.3          # excluye dudoso
    assert _completa(rows) is True
