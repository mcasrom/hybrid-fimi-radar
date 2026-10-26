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
    assert len(kws) == 12
    assert any(k["palabra"] == "blocus" for k in kws)
    assert all("protestas" not in k["palabra"] or " " in k["palabra"] for k in kws)


def test_registro_curado():
    eps = _eps()
    assert len(eps) == 5
    ids = [e["id"] for e in eps]
    assert len(ids) == len(set(ids))
    for e in eps:
        for k in ("id", "pais", "ciudad", "fecha", "nombre", "estado", "detonante",
                  "convocantes", "demandas", "llamada", "alcance", "fuentes"):
            assert k in e, (e.get("id"), k)
        assert isinstance(e["demandas"], list)
        assert e["fuentes"], e["id"]
        assert e["fuente_primaria"] is None, e["id"]
