"""Full production script regressions; browser layout is independently verified in IAB."""
import os
import subprocess
from pathlib import Path
import pytest

@pytest.mark.parametrize('scenario', ['visibility', 'visibility-empty', 'month-switch', 'cross-year', 'same-month', 'range-error', 'partial-error', 'all-error'])
def test_second_rework_full_page(scenario):
    result = subprocess.run(['node', 'tests/second_rework_behavior.js', scenario], cwd=Path(__file__).resolve().parents[1], env=os.environ.copy(), capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"PASS":true' in result.stdout
