import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SIT = json.loads((HERE / "situacion_frontera_sur.json").read_text(encoding="utf-8"))
EPS = json.loads((ROOT / "data/caso_frontera_sur_hibridos/episodios_curados.json").read_text(encoding="utf-8"))["episodios"]


def domains():
    out = set()
    for ep in EPS:
        for raw in ep.get("fuente", []):
            for token in raw.split():
                if token.startswith("http"):
                    out.add((urlsplit(token).hostname or "").lower().removeprefix("www."))
    return out


class TestSituacion(unittest.TestCase):
    def test_order_contains_all_episodes(self):
        ids = [x["id"] for x in EPS]
        self.assertEqual(sorted(SIT["episode_order"]), sorted(ids))
        self.assertEqual(len(SIT["episode_order"]), len(set(SIT["episode_order"])))

    def test_every_episode_has_status_and_missing(self):
        for ep in EPS:
            self.assertIn(ep["id"], SIT["episode_status"])
            self.assertIn(ep["id"], SIT["episode_missing"])
            self.assertIn(SIT["episode_status"][ep["id"]], SIT["status_labels"])

    def test_all_sources_are_classified(self):
        self.assertEqual(domains() - set(SIT["source_roles"]), set())

    def test_no_primary_source_is_claimed(self):
        roles = [x["role"] for x in SIT["source_roles"].values()]
        self.assertNotIn("primaria", roles)

    def test_kpis_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "situacion_kpis.json"
            subprocess.run(
                [
                    sys.executable,
                    str(HERE / "gen_kpis.py"),
                    "--today",
                    "2026-11-02",
                    "--out",
                    str(out),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["topic"], "frontera_sur")
            self.assertEqual(len(data["activity"]["daily"]), 45)
            self.assertGreater(data["activity"]["total"], 0)
            self.assertEqual(data["evidence"]["total"], 6)
            self.assertEqual(data["evidence"]["primary_sources"], 0)
            self.assertEqual(data["evidence"]["documented_relations"], 2)
            self.assertGreater(data["sources"]["distinct"], 0)
            self.assertGreaterEqual(data["quality"]["raw_publications"], data["quality"]["dedup_publications"])
            self.assertEqual(
                data["quality"]["dedup_publications"] + data["quality"]["duplicates_removed"] + data["quality"]["empty_titles"],
                data["quality"]["raw_publications"],
            )

    def test_page_is_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            kpis = Path(tmp) / "situacion_kpis.json"
            out = Path(tmp) / "index.html"
            subprocess.run(
                [sys.executable, str(HERE / "gen_kpis.py"), "--today", "2026-11-02", "--out", str(kpis)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [sys.executable, str(HERE / "gen_situacion.py"), "--kpis", str(kpis), "--out", str(out)],
                check=True,
                capture_output=True,
                text=True,
            )
            html = out.read_text(encoding="utf-8")
            self.assertIn("Frontera Sur: situación", html)
            self.assertIn("0</b><span>fuentes primarias", html)
            self.assertIn("Indicadores de situación", html)
            self.assertIn("Actividad diaria", html)
            self.assertIn("Fuentes con más publicaciones", html)
            self.assertIn("Qué no se puede concluir", html)
            self.assertNotIn('class="role-primary"', html)


if __name__ == "__main__":
    unittest.main()
