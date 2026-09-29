"""Regresión de la card de validación (detection/validacion_card.py).

Fallos que este test fija, todos vistos en producción (29/Sep/2026):
  1. `n = len(bandas) * 8` suponía 8 clusters por banda: con la muestra real de
     53 HIGH la card publicaba «sobre 8 clusters etiquetados a mano». El n sale
     ahora de la fila del historial.
  2. La card decía «se actualizan solas en cada ciclo»: la capa curada es
     mensual y la externa semanal. Solo el render es por ciclo.
  3. La card no anclaba cada cifra a su fecha de medición, y presenta precisión
     curada junto a cifras post-banding. Ahora cada fila lleva su fecha y un
     aviso de no comparabilidad.
  4. `_curada()` y la fila externa compartían el nombre `fecha`: usarlo en la
     fila antes de definirlo era un NameError latente en el próximo ciclo.
"""
import csv
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def card(tmp_path, monkeypatch):
    """Card apuntando a un data/validacion temporal (no toca los reales)."""
    val = tmp_path / "validacion"
    val.mkdir()
    import detection.validacion_card as v
    importlib.reload(v)
    # el reload re-ejecuta `VAL = ROOT / "data" / "validacion"`: hay que
    # reapuntarlo DESPUÉS, o el test lee los ficheros reales de producción.
    v.VAL = val
    return v, val


def _historial(val, filas):
    with open(val / "historial.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["muestra", "banda", "n", "coord", "no", "dud", "precision"])
        w.writerows(filas)


def test_n_real_de_la_ultima_muestra(card):
    """Regresión 1: el n sale del historial, no de len(bandas) * 8."""
    v, val = card
    _historial(val, [
        ["muestra_20260917_1740.csv", "HIGH", 8, 1, 6, 1, 50.0],
        ["muestra_high_20260921_1351.csv", "HIGH", 53, 36, 15, 2, 94.7],
    ])
    html = v.render_validacion_html()
    assert "53 clusters etiquetados" in html
    assert "8 clusters etiquetados" not in html
    assert "n=53" in html


def test_suma_el_n_de_todas_las_bandas_de_la_muestra(card):
    v, val = card
    _historial(val, [
        ["muestra_x_20260921_1351.csv", "HIGH", 53, 36, 15, 2, 94.7],
        ["muestra_x_20260921_1351.csv", "ANOMALOUS", 20, 8, 9, 3, 40.0],
    ])
    html = v.render_validacion_html()
    assert "73 clusters etiquetados" in html  # 53 + 20, no 2 bandas * 8


def test_no_anuncia_ciclo_diario(card):
    """Regresión 2: la cadencia real es CI / semanal / mensual."""
    v, val = card
    _historial(val, [["muestra_20260921_1351.csv", "HIGH", 53, 36, 15, 2, 94.7]])
    html = v.render_validacion_html()
    assert "Se actualizan solas en cada ciclo" not in html
    assert "Cada capa se mide con su propia cadencia" in html
    for esperado in ("CI", "lunes", "cada mes"):
        assert esperado in html


def test_ancla_cifra_curada_a_su_fecha(card):
    """Regresión 3: fecha de medición visible y aviso de no comparabilidad."""
    v, val = card
    _historial(val, [["muestra_high_20260921_1351.csv", "HIGH", 53, 36, 15, 2, 94.7]])
    html = v.render_validacion_html()
    assert "21/09/2026" in html
    assert "no es comparable" in html


def test_el_aviso_de_banding_se_invierte_en_muestras_posteriores(card):
    """La muestra del 29/Sep es POSTERIOR al gate: el aviso debe decirlo al revés.

    Con el texto fijo, la card afirmaba que toda cifra curada era previa al
    banding vigente, lo cual dejó de ser cierto en cuanto entró la muestra
    post-gate.
    """
    v, val = card
    _historial(val, [["muestra_high_blind_20260929_postgate.csv", "HIGH", 40, 3, 33, 4, 8.3]])
    html = v.render_validacion_html()
    assert "29/09/2026" in html
    assert "banding vigente" in html
    assert "no es comparable" not in html
    assert "#166534" in html            # verde = comparable


def test_fecha_iso_extrae_la_primera_fecha_de_8_digitos(card):
    v, _ = card
    assert v._fecha_iso("muestra_high_blind_20260929_postgate.csv") == "2026-09-29"
    assert v._fecha_iso("muestra_20260917_1805.csv") == "2026-09-17"
    assert v._fecha_iso("sin_fecha.csv") == ""


def test_no_afirma_orden_de_bandas_con_una_sola_banda(card):
    """La muestra post-gate es HIGH-only: no puede sostener 'sube con la banda'."""
    v, val = card
    _historial(val, [["muestra_high_blind_20260929_postgate.csv", "HIGH", 40, 3, 33, 4, 8.3]])
    html = v.render_validacion_html()
    assert "no permite afirmar" in html
    assert "sube con la banda</b>" not in html
    assert "8.3%" in html          # sin redondear a 8 %


def test_sigue_afirmando_el_orden_cuando_hay_varias_bandas(card):
    v, val = card
    _historial(val, [
        ["muestra_x_20260921_1351.csv", "HIGH", 53, 36, 15, 2, 94.7],
        ["muestra_x_20260921_1351.csv", "WATCH", 8, 0, 8, 0, 0.0],
    ])
    html = v.render_validacion_html()
    assert "La precisión sube con la banda" in html


def test_regresion_4_no_nameerror_en_la_fila_externa(card):
    """La fila externa usa `fecha`: debe existir antes de construir las filas."""
    v, val = card
    _historial(val, [["muestra_high_20260921_1351.csv", "HIGH", 53, 36, 15, 2, 94.7]])
    (val / "auto_ultimo.json").write_text(json.dumps({
        "fecha": "2026-09-28T07:15:47+00:00",
        "dataset_refrescado": False,
        "dataset_edad_dias": 19.7,
        "resultados": {
            "global": {"precision": 0.156, "recall": 0.0, "n_senales": 109,
                       "n_senales_doc": 17, "dominios_doc_amplificados": 14,
                       "fuentes_doc_con_senal": 0},
            "spanish": {"precision": 0.0642, "recall": 0.0, "n_senales": 109,
                        "n_senales_doc": 7, "dominios_doc_amplificados": 3,
                        "fuentes_doc_con_senal": 0},
        },
    }), encoding="utf-8")
    html = v.render_validacion_html()
    assert "2026-09-28 07:15" in html
    assert "19.7 días" in html
    assert "15.6%" in html          # precisión real, no la vieja 8.5
    assert "8.5%" not in html


def test_no_rompe_sin_ficheros(card):
    v, _ = card
    html = v.render_validacion_html()          # ni historial ni auto
    assert "Validación del modelo" in html
    assert "Aún sin muestras etiquetadas" in html


def test_no_rompe_con_historial_vacio_o_corrupto(card):
    v, val = card
    (val / "historial.csv").write_text("muestra,banda,n,coord,no,dud,precision\n",
                                       encoding="utf-8")
    html = v.render_validacion_html()
    assert "Validación del modelo" in html


def test_fecha_muestra_descompuesta(card):
    v, _ = card
    assert v._fecha_muestra("muestra_high_20260921_1351.csv") == "21/09/2026"
    assert v._fecha_muestra("muestra_20260917_1805.csv") == "17/09/2026"
    assert v._fecha_muestra("algo_raro.csv") == "algo_raro.csv"


def test_avisa_cuando_una_banda_alta_sale_baja(card):
    """Regresión 5 (29-Sep): una banda alta con precisión baja NO es coordinación.

    La card debe decirlo explícitamente, no solo mostrar el 8,3 % en una chip.
    """
    v, val = card
    _historial(val, [
        ["muestra_high_blind_20260929_postgate.csv", "HIGH", 40, 3, 33, 4, 8.3],
    ])
    html = v.render_validacion_html()
    assert "Aviso: 8.3 %" in html
    assert "NO equivale a coordinación" in html


def test_no_traga_excepcion_si_la_precision_no_es_numero(card, capsys):
    """El valor del historial llega como STRING ('8.3'): formatearlo con :.1f
    reventaba con ValueError y un `except: pass` lo hacia invisible."""
    v, val = card
    (val / "historial.csv").write_text(
        "muestra,banda,n,coord,no,dud,precision\n"
        "muestra_x_20260929_postgate.csv,HIGH,40,3,33,4,no-es-un-numero\n",
        encoding="utf-8")
    html = v.render_validacion_html()          # no debe romperse
    assert "Validación del modelo" in html
    assert "no se pudo evaluar la precisión" in capsys.readouterr().err


def test_nota_de_capa_ciega_refleja_el_estado_real(card):
    v, val = card
    _historial(val, [
        ["muestra_high_blind_20260929_postgate.csv", "HIGH", 40, 3, 33, 4, 8.3],
    ])
    html = v.render_validacion_html()
    assert "está ejecutada" in html
    assert "sin κ" in html
    assert "sin ejecutar" not in html
