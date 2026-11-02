import csv
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class TestNarrativas(unittest.TestCase):
    def test_codebook_and_sample(self):
        codebook = json.loads((HERE / "codigo.json").read_text(encoding="utf-8"))
        with (HERE / "muestra.csv").open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 60)
        self.assertEqual({r["topic"] for r in rows}, set(codebook["topics"]))
        self.assertTrue(all(not (r.get("narrativa") or "").strip() for r in rows))
        for row in rows:
            codes = {f["code"] for f in codebook["topics"][row["topic"]]["frames"]}
            self.assertIn(row["narrativa"].strip(), codes | {""})

    def test_page_has_codebook(self):
        html = (HERE / "index.html").read_text(encoding="utf-8")
        self.assertIn("Narrativas: código y muestra", html)
        self.assertIn("sin codificar", html)
        self.assertIn("Muestra: 60 publicaciones", html)
        self.assertIn("muestra.csv", html)


if __name__ == "__main__":
    unittest.main()
