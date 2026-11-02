import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class TestEvidencia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.html = base / "index.html"
        cls.js = base / "evidencia.json"
        subprocess.run(
            [sys.executable, str(HERE / "gen_evidencia.py"), "--out", str(cls.html), "--json", str(cls.js)],
            check=True,
            capture_output=True,
            text=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_counts_and_labels(self):
        data = json.loads(self.js.read_text(encoding="utf-8"))
        t = data["topics"]
        self.assertEqual(t["frontera_sur"]["n"], 6)
        self.assertEqual(t["frontera_sur"]["primary"], 0)
        self.assertEqual(t["juventud"]["n"], 6)
        self.assertEqual(t["juventud"]["primary"], 0)
        self.assertEqual(t["campana"]["n"], 5)
        self.assertEqual(t["campana"]["primary"], 1)
        self.assertEqual(t["infraestructuras"]["n"], 8)
        self.assertIn("no confirma", t["infraestructuras"]["note"])

    def test_page_has_evidence_sections(self):
        html = self.html.read_text(encoding="utf-8")
        self.assertIn("Evidencia documental", html)
        self.assertIn("Frontera Sur · fichas", html)
        self.assertIn("Protestas juveniles · episodios", html)
        self.assertIn("Elecciones generales · hitos", html)
        self.assertIn("Infraestructuras · fuentes oficiales", html)


if __name__ == "__main__":
    unittest.main()
