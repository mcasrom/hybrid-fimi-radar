import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


class TestSituacionTemas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name)
        cls.sit = HERE / "situacion_temas.json"
        for topic, key, name in (
            ("protestas_juveniles", "juventud", "situacion_kpis_juventud.json"),
            ("infraestructuras_espana", "infraestructuras", "situacion_kpis_infraestructuras.json"),
        ):
            subprocess.run(
                [
                    sys.executable,
                    str(HERE / "gen_kpis.py"),
                    "--today",
                    "2026-11-02",
                    "--topic",
                    topic,
                    "--curated",
                    str(cls.sit),
                    "--curated-key",
                    key,
                    "--out",
                    str(cls.base / name),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        subprocess.run(
            [
                sys.executable,
                str(HERE / "gen_situacion_temas.py"),
                "--situacion",
                str(cls.sit),
                "--protestas",
                str(ROOT / "data/protestas.yaml"),
                "--calendario",
                str(HERE.parent / "calendario/calendario_oficial.json"),
                "--feeds",
                str(ROOT.parent / "observatorio/feeds.json"),
                "--kpis-dir",
                str(cls.base),
                "--out",
                str(cls.base / "pages"),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_youth_page_has_kpi_and_charts(self):
        html = (self.base / "pages/juventud/situacion/index.html").read_text(encoding="utf-8")
        self.assertIn("Indicadores de situación", html)
        self.assertIn("Actividad diaria", html)
        self.assertIn("fuentes primarias", html)
        self.assertIn("Episodios", html)

    def test_infra_page_has_official_sources_not_evidence(self):
        html = (self.base / "pages/infraestructuras/situacion/index.html").read_text(encoding="utf-8")
        self.assertIn("Indicadores de situación", html)
        self.assertIn("fuentes oficiales", html)
        self.assertIn("no confirman incidencias", html)
        self.assertIn("Fuentes primarias institucionales", html)

    def test_kpi_evidence_labels(self):
        youth = json.loads((self.base / "situacion_kpis_juventud.json").read_text(encoding="utf-8"))
        infra = json.loads((self.base / "situacion_kpis_infraestructuras.json").read_text(encoding="utf-8"))
        self.assertEqual(youth["evidence"]["primary_sources"], 0)
        self.assertEqual(youth["evidence"]["label"], "fuentes primarias")
        self.assertEqual(infra["evidence"]["label"], "fuentes oficiales")
        self.assertEqual(infra["evidence"]["documented_relations"], 0)


if __name__ == "__main__":
    unittest.main()
