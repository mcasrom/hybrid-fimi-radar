import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIT_PATH = HERE / "situacion_frontera_sur.json"


class TestBriefing(unittest.TestCase):
    def setUp(self):
        self.sit = json.loads(SIT_PATH.read_text(encoding="utf-8"))

    def test_snapshot_is_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "snap"
            out = Path(tmp) / "out.html"
            cmd = [sys.executable, str(HERE / "gen_briefing.py"), "--snapshots", str(snap), "--out", str(out), "--date", "2026-11-01"]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            first = json.loads((snap / "2026-11-01.json").read_text())
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            second = json.loads((snap / "2026-11-01.json").read_text())
            self.assertEqual(first, second)
            self.assertIn("Primera edición", out.read_text(encoding="utf-8"))

    def test_status_change_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "snap"
            out = Path(tmp) / "out.html"
            changed = json.loads(json.dumps(self.sit))
            changed["episode_status"]["CUR-2026-002"] = "declaracion_publica"
            changed_path = Path(tmp) / "situacion.json"
            changed_path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")

            base = [sys.executable, str(HERE / "gen_briefing.py"), "--snapshots", str(snap), "--out", str(out)]
            subprocess.run(base + ["--date", "2026-11-01"], check=True, capture_output=True, text=True)
            second = subprocess.run(base + ["--date", "2026-11-08", "--situacion", str(changed_path)], check=True, capture_output=True, text=True)
            page = out.read_text(encoding="utf-8")
            self.assertIn("1 cambio(s)", second.stdout)
            self.assertIn("CUR-2026-002", page)
            self.assertIn("Sin documento público localizado", page)
            self.assertIn("Declaración pública", page)

    def test_no_primary_source_is_claimed(self):
        roles = [x["role"] for x in self.sit["source_roles"].values()]
        self.assertNotIn("primaria", roles)
        for key in self.sit["episode_order"]:
            self.assertIn(key, self.sit["episode_status"])


if __name__ == "__main__":
    unittest.main()
