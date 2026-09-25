#!/usr/bin/env python3
"""Guardas del pipeline: input inexistente, CSV avisado, y generador sintético
que escribe donde se le indique (no en data/raw de producción).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_run_fimi_input_inexistente_aborta():
    r = subprocess.run(
        [sys.executable, str(ROOT / "detection" / "run_fimi.py"),
         "--input", "/no/existe/de-verdad.db", "--tema", "frontera_sur"],
        capture_output=True, text=True)
    assert r.returncode == 2
    assert "no existe" in (r.stderr + r.stdout)


def test_generate_synthetic_respeta_out_dir(tmp_path):
    env = {**os.environ, "GEN_SYNTHETIC_OUT": str(tmp_path)}
    r = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "generate_synthetic.py")],
        capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "events.csv").exists()
    assert (tmp_path / "ground_truth.csv").exists()
