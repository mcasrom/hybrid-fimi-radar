"""Tests del módulo central de reglas de tema (detection/tema_reglas.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detection import tema_reglas as tr  # noqa: E402


ACTIVOS_ESPERADOS = {
    "frontera_sur", "oriente_medio", "elecciones", "inteligencia_artificial",
    "eeuu_politica", "sahel", "energia", "defensa_espana", "espana_amenazas_hibridas",
}


def test_temas_activos_y_cerrados_disjuntos():
    activos, cerrados = set(tr.temas_activos()), set(tr.temas_cerrados())
    assert not (activos & cerrados), "un tema no puede ser activo y cerrado a la vez"
    assert ACTIVOS_ESPERADOS <= activos
    # Regresión: los temas cerrados NO deben colarse como activos.
    assert "politica_nacional" in cerrados
    assert "geopolitica_ue_marruecos" in cerrados


def test_reglas_por_tema_shape():
    por_tema, filtros, contextos, cerrados = tr.reglas_por_tema()
    assert "politica_nacional" in cerrados
    assert por_tema.get("frontera_sur"), "frontera_sur debe tener keywords"
    assert isinstance(filtros, dict) and isinstance(contextos, dict)


def test_matcher_plural_tolerante():
    # singular->plural (+s): "houthi" debe matchear "houthis"
    from detection.tema_reglas import normalizar, _tokens, _matches
    nt = normalizar("los houthis atacan el corredor")
    toks = [t for t in nt.split() if len(t) > 2]
    assert _matches(normalizar("houthi"), _tokens("houthi"), nt, toks)


def test_temas_activos_ignora_estado_desconocido():
    cfg = {"temas": {"a": {"estado": "produccion"}, "b": {"estado": "cerrado"},
                     "c": {"estado": "candidato_a_cierre"}, "d": {}}}
    # estado ausente = produccion (fiel a capture/recompute); candidato/cerrado NO activos
    assert tr.temas_activos(cfg) == ["a", "d"]
    assert set(tr.temas_cerrados(cfg)) == {"b", "c"}
