import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIT = json.loads((HERE / "situacion_temas.json").read_text(encoding="utf-8"))


class TestSituacionTemas(unittest.TestCase):
    def test_all_topics_have_context(self):
        for key in ("juventud", "campana", "infraestructuras"):
            self.assertIn(key, SIT["topics"])
            self.assertTrue(SIT["topics"][key]["titulo"])
            self.assertTrue(SIT["topics"][key]["limites"])

    def test_youth_has_no_primary_source(self):
        roles = [x["role"] for x in SIT["topics"]["juventud"]["source_roles"].values()]
        self.assertNotIn("primaria", roles)
        self.assertEqual(len(roles), 10)

    def test_pages_are_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            subprocess.run(
                [sys.executable, str(HERE / "gen_situacion_temas.py"), "--out", str(out)],
                check=True,
                capture_output=True,
                text=True,
            )
            youth = (out / "juventud/situacion/index.html").read_text(encoding="utf-8")
            campana = (out / "campana/situacion/index.html").read_text(encoding="utf-8")
            infra = (out / "infraestructuras/situacion/index.html").read_text(encoding="utf-8")
            self.assertIn("Protestas juveniles: situación", youth)
            self.assertIn("6</b><span>episodios", youth)
            self.assertIn("0</b><span>fuentes primarias", youth)
            self.assertIn("No hay relaciones documentadas", youth)
            self.assertIn("Elecciones generales: situación", campana)
            self.assertIn("5</b><span>hitos oficiales", campana)
            self.assertIn("BOE", campana)
            self.assertIn("Infraestructuras: cobertura y fuentes", infra)
            self.assertIn("8</b><span>fuentes oficiales", infra)
            self.assertIn("No hay relaciones documentadas", infra)


if __name__ == "__main__":
    unittest.main()
