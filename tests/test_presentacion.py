"""Tests Sprint A: definición única de 'cluster publicado' y distribución."""
from detection.presentacion import (
    MIN_CUENTAS_PUBLICADO,
    bloque_distribucion_html,
    es_publicado,
    mil,
    partir_publicados,
    resumen_distribucion,
)


def test_umbral_publicado():
    assert MIN_CUENTAS_PUBLICADO == 3
    assert es_publicado(3) and es_publicado(91)
    assert not es_publicado(2) and not es_publicado(1) and not es_publicado(0)
    assert not es_publicado(None)


def test_partir_publicados():
    cls = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]
    pub, par = partir_publicados(cls, {1: 10, 2: 3, 3: 2})
    assert [c["id"] for c in pub] == [1, 2]
    assert [c["id"] for c in par] == [3, 4]  # 2 cuentas y sin dato van agregados
    pub2, par2 = partir_publicados(cls, {})
    assert [c["id"] for c in pub2] == [1, 2, 3, 4] and par2 == []  # fail-open


def test_resumen_distribucion_y_muro():
    d = resumen_distribucion([39.0, 39.0, 59.0, 61.0, 85.0, 10.0, None])
    assert d["total"] == 7
    assert (d["pin39"], d["pin59"]) == (2, 1)
    assert d["bandas"]["WATCH"] == 2  # los dos 39.0 (techo de WATCH)
    assert d["bandas"]["ANOMALOUS"] == 1  # 59.0
    assert d["bandas"]["HIGH"] == 1 and d["bandas"]["CRITICAL"] == 1
    assert d["bandas"]["NORMAL"] == 2  # 10.0 y None


def test_mil_formato_es():
    assert mil(241885) == "241.885"
    assert mil(0) == "0"


def test_bloque_muestra_muro_y_pares():
    h = bloque_distribucion_html(resumen_distribucion([39.0, 61.0]), n_par=1048)
    assert "39,0" in h and "59,0" in h and "+1048" in h and "scale_floor" in h
