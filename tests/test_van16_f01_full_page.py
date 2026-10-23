"""F01 gate using the complete production inline page script."""
from __future__ import annotations

from node_test_support import NODE

import os
import subprocess
from pathlib import Path

import pytest


APP_DIR = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = APP_DIR / ".tmp" / "van16-evidence"


def test_f01_full_inline_page_uses_real_hydrate_and_production_retry_click():
    """Run index.html with runScripts=dangerously and assert real DOM transitions."""
    result = subprocess.run(
        [NODE, "tests/f01_real_dom_behavior.js"],
        capture_output=True,
        text=True,
        cwd=APP_DIR,
        timeout=60,
        env=os.environ.copy(),
    )
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "f01-full-inline-dom.json").write_text(result.stdout or result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert '"PASS":true' in result.stdout
