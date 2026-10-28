"""Contrato del piloto `protestas_juveniles`: registro curado y configuración."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _cfg():
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def _eps():
    return yaml.safe_load((ROOT / "data" / "protestas.yaml").read_text(encoding="utf-8"))


def test_tema_piloto_acotado():
    t = _cfg()["temas"]["protestas_juveniles"]
    assert t["estado"] == "piloto"
    assert t["ventana_dias"] == 14
    assert t["scoring"]["weights"]["anomaly"] == 0.4444


def test_keywords_del_tema():
    cfg = _cfg()
    kws = [k for k in cfg["keywords"] if (k.get("tema") or "frontera_sur") == "protestas_juveniles"]
    assert len(kws) == 20
    assert any(k["palabra"] == "blocus" for k in kws)
    assert any(k["palabra"] == "student protest" for k in kws)
    assert any(k["palabra"] == "protesti studenti" for k in kws)
    assert all("protestas" not in k["palabra"] or " " in k["palabra"] for k in kws)


def test_registro_curado():
    eps = _eps()
    assert len(eps) == 6
    ids = [e["id"] for e in eps]
    assert len(ids) == len(set(ids))
    for e in eps:
        for k in ("id", "pais", "ciudad", "fecha", "nombre", "estado", "detonante",
                  "convocantes", "demandas", "llamada", "alcance", "fuentes"):
            assert k in e, (e.get("id"), k)
        assert isinstance(e["demandas"], list)
        assert e["fuentes"], e["id"]
        assert e["fuente_primaria"] is None, e["id"]
    by_id = {e["id"]: e for e in eps}
    assert str(by_id["FRA-2026-10-17"]["fecha"]) == "2026-10-17"
    assert str(by_id["ALB-2026-10-13"]["fecha"]) == "2026-10-13"


def test_informe_sin_senal_no_revienta():
    from detection.gen_informe_visual_tema import render
    kpi = {
        "n_ev": 10, "n_au_cl": 0, "n_au": 5, "n_fuentes": 2,
        "tmin": 1793000000, "tmax": 1793003600, "inicio": 1793003600,
        "theme_daily": {},
    }
    h = render("protestas_juveniles", "Protestas juveniles", [], kpi, None, [], 14)
    assert "Sin clústeres con señal" in h
    assert "ventana 14 d" in h
    assert "No significa que no haya protestas" in h
