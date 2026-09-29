#!/usr/bin/env python3
"""Tests de los KPIs del dashboard: solo los temas activos cuentan.

29/Sep/2026: la portada decia «1052 clusters activos» cuando 15 de esos
clusters eran de temas CERRADOS (el pipeline deja de correr para ellos, pero
sus clusters siguen en la tabla `clusters` porque la Bitácora los conserva).
El feed de alertas tenia el mismo fallo: publicaba temas ya cerrados.

Se prueba el helper `_filtro_temas_activos` y el SQL que genera, con una BD
temporal: es lo unico que se puede comprobar sin regen (6 min).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detection.gen_fimi_html import _filtro_temas_activos  # noqa: E402

CFG = {
    "temas": {
        "frontera_sur": {"estado": "produccion"},
        "elecciones": {"estado": "piloto"},
        "politica_nacional": {"estado": "cerrado"},
        "espana_amenazas_hibridas": {"estado": "cerrado"},
    }
}


def _bd(tmp_path):
    con = sqlite3.connect(tmp_path / "t.db")
    con.execute("CREATE TABLE clusters (cluster_label TEXT, tema_id TEXT, overall_score REAL)")
    con.executemany(
        "INSERT INTO clusters VALUES (?,?,?)",
        [("a_cluster_000", "frontera_sur", 70.0),
         ("b_cluster_000", "elecciones", 65.0),
         ("c_cluster_000", "politica_nacional", 80.0),
         ("d_cluster_000", "espana_amenazas_hibridas", 55.0)])
    con.commit()
    return con


def test_filtro_excluye_temas_cerrados():
    where, args = _filtro_temas_activos(CFG)
    assert "tema_id IN" in where
    assert sorted(args) == ["elecciones", "frontera_sur"]


def test_kpi_cuenta_solo_activos(tmp_path):
    con = _bd(tmp_path)
    where, args = _filtro_temas_activos(CFG)
    rows = con.execute("SELECT cluster_label, overall_score, tema_id FROM clusters"
                       + where, args).fetchall()
    assert len(rows) == 2
    assert {r[2] for r in rows} == {"frontera_sur", "elecciones"}
    con.close()


def test_top_cluster_no_es_de_tema_cerrado(tmp_path):
    """El cerrado tiene el score mas alto (80): sin filtro se publicaria como
    «el cluster mas alto del radar» aunque el tema este cerrado."""
    con = _bd(tmp_path)
    where, args = _filtro_temas_activos(CFG)
    top = con.execute("SELECT cluster_label, overall_score FROM clusters"
                      + where + " ORDER BY overall_score DESC LIMIT 1", args).fetchone()
    assert top[1] == 70.0
    con.close()


def test_acepta_el_config_entero_y_no_filtra_por_un_tema_llamado_temas():
    """Si le pasan config.yaml entero en vez de la seccion temas, el filtro
    naive seria `tema_id IN ('temas')` -> KPIs a cero, en silencio."""
    for entrada in (CFG, CFG["temas"]):
        where, args = _filtro_temas_activos(entrada)
        assert sorted(args) == ["elecciones", "frontera_sur"], entrada
        assert "tema_id IN" in where


def test_catalogo_vacio_no_deja_la_pagina_sin_datos():
    """Si config.yaml falla al leerse, preferimos mostrar de mas a no renderizar."""
    for vacio in ({}, {"temas": {}}, None, {"temas": {"x": None}},
                  {"temas": {"x": {"estado": "cerrado"}}}):
        where, args = _filtro_temas_activos(vacio)
        assert where == "" and args == []


def test_columna_qualificada_para_el_join_del_rss():
    """El feed de alertas hace JOIN, asi que la columna va cualificada."""
    where, _ = _filtro_temas_activos(CFG, col="c.tema_id")
    assert "c.tema_id IN" in where
