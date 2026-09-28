#!/usr/bin/env python3
"""Tests de detection/purgar_tema_keyword.py.

Verifican el criterio conservador: solo se desetiqueta lo que su único motivo
era una keyword retirada, y se conserva tanto lo que no coincide con las
retiradas como lo que además coincide con una vigente (ruta "por consulta").
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import detection.purgar_tema_keyword as ptk  # noqa: E402

import yaml  # noqa: E402


def _bdb(tmp_path, monkeypatch, textos, etiquetas=("elecciones",)):
    """BD mínima con eventos (id, text, timestamp) y sus etiquetas."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, text TEXT, "
                "title TEXT, timestamp INTEGER)")
    con.execute("CREATE TABLE event_temas (event_id INTEGER, tema_id TEXT)")
    ahora = 1_700_000_000
    for i, t in enumerate(textos, start=1):
        con.execute("INSERT INTO events (id, text, title, timestamp) "
                    "VALUES (?,?,?,?)", (i, t, "", ahora))
        con.execute("INSERT INTO event_temas (event_id, tema_id) VALUES (?,?)",
                    (i, etiquetas[0]))
    con.commit()
    return con


def _cfg(tmp_path, monkeypatch, kws, filtro):
    cfg = {"keywords": [{"palabra": k, "tema": "elecciones"} for k in kws],
           "temas": {"elecciones": {"filtro": filtro, "contexto": None}}}
    f = tmp_path / "config.yaml"
    f.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(ptk, "ROOT", tmp_path)


def test_solo_retirada_se_desetiqueta(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch, ["wahlen"], ["urne", "election"])
    con = _bdb(tmp_path, monkeypatch, [
        "US House funding bill ahead of the midterms",   # solo retirada
        "Bundestagswahl in Berlin",                     # vigente -> intacto
    ])
    a_quitar, d = ptk.clasificar(con, "elecciones", ["midterms"], 7300)
    assert a_quitar == [1]
    # el 2 no matchea la retirada: va a sin_motivo, no a intactos
    assert d["sin_motivo_retirado"] == 1
    assert d["etiquetados"] == 2


def test_no_matchea_retirada_no_se_toca(tmp_path, monkeypatch):
    """Ruta (b): un post etiquetado por consulta, sin la keyword retirada."""
    _cfg(tmp_path, monkeypatch, ["wahlen"], ["urne"])
    con = _bdb(tmp_path, monkeypatch, [
        "ein Kommentar zur Lage im Bundestag",  # no contiene 'midterms'
    ])
    a_quitar, d = ptk.clasificar(con, "elecciones", ["midterms"], 7300)
    assert a_quitar == []
    assert d["sin_motivo_retirado"] == 1


def test_retirada_mas_vigente_se_conserva(tmp_path, monkeypatch):
    """Coincide con la retirada Y con una vigente: tiene otro motivo."""
    # escenario real: la retirada ya no esta en config, y el evento ademas
    # matchea una vigente
    _cfg(tmp_path, monkeypatch, ["bundestagswahl"], ["urne"])
    con = _bdb(tmp_path, monkeypatch, [
        "midterms and the Bundestagswahl both matter",
    ])
    a_quitar, d = ptk.clasificar(con, "elecciones", ["midterms"], 7300)
    assert a_quitar == []
    assert d["intactos_otro_motivo"] == 1


def test_filtro_tambien_sostiene(tmp_path, monkeypatch):
    """La lista `filtro` también puede mantener la etiqueta aunque no sea keyword."""
    _cfg(tmp_path, monkeypatch, ["midterms"], ["wähler"])
    con = _bdb(tmp_path, monkeypatch, [
        "midterms und wähler",       # retirada + filtro -> intacto
        "midterms only",             # solo retirada -> fuera
    ])
    a_quitar, d = ptk.clasificar(con, "elecciones", ["midterms"], 7300)
    assert a_quitar == [2]
    assert d["intactos_otro_motivo"] == 1


def test_fuera_de_ventana_no_se_borra(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch, ["wahlen"], ["urne"])
    con = _bdb(tmp_path, monkeypatch, ["the midterms are coming"])
    con.execute("UPDATE events SET timestamp=timestamp-99999999 WHERE id=1")
    con.commit()
    a_quitar, d = ptk.clasificar(con, "elecciones", ["midterms"], 1)
    assert a_quitar == []
    assert d["fuera_ventana"] == 1


def test_retirada_ya_no_esta_en_filtro_no_cuenta_como_vigente(tmp_path, monkeypatch):
    """Si alguien dejó la retirada en `filtro`, se excluye al medir lo vigente."""
    _cfg(tmp_path, monkeypatch, ["wahlen"], ["midterms", "urne"])
    con = _bdb(tmp_path, monkeypatch, ["the midterms are coming"])
    _, d = ptk.clasificar(con, "elecciones", ["midterms"], 7300)
    assert d["filtro"] == 1  # 'midterms' excluida del filtro vigente
    assert d["a_desetiquetar"] == 1


def test_retirada_que_sigue_en_config_se_ignora_como_vigente(tmp_path, monkeypatch, capsys):
    """Pie de arma: si la retirada sigue en keywords, no puede actuar como
    'otro motivo' (si no, la herramienta no borraria nada y no avisaria)."""
    _cfg(tmp_path, monkeypatch, ["midterms", "wahlen"], ["urne"])
    con = _bdb(tmp_path, monkeypatch, ["the midterms are coming"])
    a_quitar, d = ptk.clasificar(con, "elecciones", ["midterms"], 7300)
    assert a_quitar == [1]
    assert d["keywords_vigentes"] == 1        # 'midterms' excluida
    assert "sigue" in capsys.readouterr().out  # y avisa


def test_tema_inexistente(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch, ["wahlen"], ["urne"])
    con = _bdb(tmp_path, monkeypatch, ["x"])
    try:
        ptk.clasificar(con, "no_existe", ["midterms"], 7300)
    except SystemExit as e:
        assert "no_existe" in str(e)
    else:
        raise AssertionError("debería lanzar SystemExit")
