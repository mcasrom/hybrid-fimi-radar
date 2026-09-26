"""Tests del linaje: `first_band_ts` (antigüedad de la alerta hacia delante)."""
from detection import lineage


def test_assign_fija_first_band_ts_al_entrar_en_alerta():
    rows = lineage.assign({}, {}, {"c1": {"a:x"}}, cycle_ts=1000, alert_labels={"c1"})
    assert rows["c1"][4] == 1000
    assert rows["c1"][2] == 1


def test_assign_sin_alerta_no_fija_first_band_ts():
    rows = lineage.assign({}, {}, {"c1": {"a:x"}}, cycle_ts=1000, alert_labels=set())
    assert rows["c1"][4] is None


def test_assign_hereda_first_band_ts_del_ciclo_previo():
    prev_members = {"c0": {"a:x"}}
    prev_lineage = {"c0": ("L1", 500, 3, 900)}
    rows = lineage.assign(prev_members, prev_lineage, {"c1": {"a:x"}},
                          cycle_ts=1000, alert_labels=set())
    assert rows["c1"][0] == "L1"
    assert rows["c1"][4] == 900  # no se resetea aunque ya no esté en alerta


def test_assign_fija_first_band_ts_si_faltaba_en_previo():
    prev_members = {"c0": {"a:x"}}
    prev_lineage = {"c0": ("L1", 500, 3, None)}
    rows = lineage.assign(prev_members, prev_lineage, {"c1": {"a:x"}},
                          cycle_ts=1000, alert_labels={"c1"})
    assert rows["c1"][4] == 1000


def test_assign_tolera_prev_lineage_de_3_campos():
    prev_members = {"c0": {"a:x"}}
    prev_lineage = {"c0": ("L1", 500, 3)}
    rows = lineage.assign(prev_members, prev_lineage, {"c1": {"a:x"}},
                          cycle_ts=1000, alert_labels={"c1"})
    assert rows["c1"][0] == "L1" and rows["c1"][4] == 1000
