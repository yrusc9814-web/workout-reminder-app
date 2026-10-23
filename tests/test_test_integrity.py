"""Checks that a green regression run measures the code actually served."""
import ast
import os
from pathlib import Path
import subprocess

import pytest

from node_test_support import NODE

APP_DIR = Path(__file__).resolve().parents[1]


def test_test_definitions_cannot_silently_shadow_each_other():
    def check_scope(nodes, location):
        seen = {}
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                assert node.name not in seen, f"{location}:{node.lineno} shadows {node.name} at line {seen.get(node.name)}"
                seen[node.name] = node.lineno
                if isinstance(node, ast.ClassDef):
                    check_scope(node.body, f"{location}:{node.name}")
    for path in sorted((APP_DIR / "tests").glob("test_*.py")):
        check_scope(ast.parse(path.read_text(encoding="utf-8")).body, path.name)


def test_root_serves_the_current_page(client):
    result = client.get("/")
    assert result.status_code == 200
    assert result.text == (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")
    assert 'src="/static/app.js"' not in result.text


def test_obsolete_app_js_resource_has_no_checkout_copy():
    """The inline current page must not leave the retired app.js implementation behind."""
    assert not (APP_DIR / "static" / "app.js").exists()


def test_dom_gate_detects_a_broken_production_skip_handler(tmp_path):
    source = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")
    target = "          skipTodayTraining();"
    assert target in source
    broken_page = tmp_path / "broken-index.html"
    broken_page.write_text(source.replace(target, "          /* disabled only in negative-control fixture */", 1), encoding="utf-8")
    result = subprocess.run(
        [NODE, "tests/van25_current_page_behavior.js", "skip-failure"],
        cwd=APP_DIR, env={**os.environ, "VAN16_TEST_SOURCE": str(broken_page)},
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode != 0, "DOM gate passed with a disabled production skip button"
    assert "timed out waiting for failed skip payload" in result.stderr


def test_missing_jsdom_is_an_explicit_failure(tmp_path):
    result = subprocess.run(
        [NODE, "-e", "require('./tests/dom_dependencies')"],
        cwd=APP_DIR, env={**os.environ, "WORKOUT_NODE_MODULES": str(tmp_path / "missing-node-modules")},
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode != 0
    assert "jsdom is required" in result.stderr
    assert "Tests do not install dependencies" in result.stderr


@pytest.mark.parametrize("replacement,diagnostic", [
    ("templateId: null", "preserve explicit backend binding"),
    ("templateId: '8'", "explicit null must remain unbound"),
])
def test_template_gate_detects_broken_production_binding(tmp_path, replacement, diagnostic):
    source = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")
    original = "templateId: plan.template_id != null ? String(plan.template_id) : null"
    assert source.count(original) == 1
    broken_page = tmp_path / "broken-template-index.html"
    broken_page.write_text(source.replace(original, replacement, 1), encoding="utf-8")
    result = subprocess.run(
        [NODE, "tests/van25_current_page_behavior.js", "template-binding"],
        cwd=APP_DIR, env={**os.environ, "VAN16_TEST_SOURCE": str(broken_page)},
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode != 0, "Template gate passed with broken production binding"
    assert diagnostic in result.stderr
