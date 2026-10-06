"""Formal production-page JSDOM coverage for the VAN-20 AI workspace flow."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]


def test_van20_formal_production_dom_flow():
    env = os.environ.copy()
    env.setdefault("VAN16_DOM_DEPS", "/private/tmp/van13-jsdom-deps/node_modules")
    result = subprocess.run(
        ["node", "tests/van20_real_dom_behavior.js"],
        cwd=str(APP_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert "PASS VAN20 formal production DOM" in result.stdout
