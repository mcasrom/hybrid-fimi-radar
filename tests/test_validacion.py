#!/usr/bin/env python3
"""Tests de la validación externa EUvsDisinfo (tests/validacion_externa.py).

Cubren el filtro por idioma del ground truth y el mapeo de fuentes a dominios
documentados (incluido el bug corregido: "Niger Report" se mapeaba a
actualidad.rt.com por el match de subcadena `"rt" in s`).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from validacion_externa import (  # noqa: E402
    _fuentes_documentadas, load_documented_domains, netloc,
)

CABECERA = ("debunk_id,keywords,article_id,article_publisher,article_domain,"
            "article_url,article_language,debunk_date,class")


def _csv(tmp_path: Path) -> Path:
    filas = [
        "d1,ukraine,a1,sputnik,mundo.sputniknews.com,https://mundo.sputniknews.com/x,Spanish,01-01-2022,disinformation",
        "d2,ukraine,a2,elpais,elpais.com,https://elpais.com/y,Spanish,01-01-2022,trustworthy",
        "d3,nato,a3,rt,actualidad.rt.com,https://actualidad.rt.com/z,English,01-01-2022,disinformation",
        "d4,nato,a4,rt,actualidad.rt.com,https://actualidad.rt.com/w,English,01-01-2022,disinformation",
    ]
    p = tmp_path / "euvsdisinfo.csv"
    p.write_text(CABECERA + "\n" + "\n".join(filas) + "\n", encoding="utf-8")
    return p


def test_load_sin_filtro(tmp_path):
    domains, _kw, cases, idiomas = load_documented_domains(_csv(tmp_path))
    assert cases == 3  # las 2 inglesas + 1 española (la trustworthy se excluye)
    assert domains == {"mundo.sputniknews.com", "actualidad.rt.com"}
    assert idiomas["spanish"] == 2 and idiomas["english"] == 2


def test_load_filtro_idioma_spanish(tmp_path):
    domains, _kw, cases, idiomas = load_documented_domains(_csv(tmp_path), lang="spanish")
    assert cases == 1  # solo la española de desinformación
    assert domains == {"mundo.sputniknews.com"}
    # el Counter de idiomas sigue reflejando TODAS las filas (para el informe)
    assert idiomas["english"] == 2


def test_netloc():
    assert netloc("https://www.eldiario.es/politica/x") == "eldiario.es"
    assert netloc("") is None


def test_fuentes_documentadas_no_mapea_niger_report():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE events(source TEXT, url TEXT)")
    con.executemany(
        "INSERT INTO events VALUES (?,?)",
        [
            ("rss:RT en Español", "https://actualidad.rt.com/actualidad/x"),
            ("rss:Niger Report", "https://nigerreport.com/a"),
            ("rss:RT en Español", ""),  # feed sin dominio en la url -> fallback
        ],
    )
    res = _fuentes_documentadas(con, {"actualidad.rt.com"})
    assert res.get("rss:RT en Español") == "actualidad.rt.com"
    # bug corregido: "repoRT" no debe mapear a actualidad.rt.com
    assert "rss:Niger Report" not in res
