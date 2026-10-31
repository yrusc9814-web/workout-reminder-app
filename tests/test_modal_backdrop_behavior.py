"""Full-page JSDOM regression gate for API modal backdrop pointer interactions."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from node_test_support import NODE

APP_DIR = Path(__file__).resolve().parents[1]


def test_modal_backdrop_behavior():
    result = subprocess.run(
        [NODE, "tests/modal_backdrop_behavior.js"],
        cwd=APP_DIR,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert "PASS modal backdrop behavior" in result.stdout
