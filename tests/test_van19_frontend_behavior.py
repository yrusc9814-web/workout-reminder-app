"""Formal production-page JSDOM coverage for the VAN-19 settings flow."""
from __future__ import annotations

from node_test_support import NODE

import os
import subprocess
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]


def test_van19_formal_production_dom_flow():
    env = os.environ.copy()
    result = subprocess.run(
        [NODE, "tests/van19_real_dom_behavior.js"],
        cwd=str(APP_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert "PASS VAN19 formal production DOM" in result.stdout
