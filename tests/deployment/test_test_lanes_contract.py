"""Contract tests for pytest marker config and Woodpecker lane selection.

These verify the test-lane contract from:
  docs/superpowers/plans/2026-07-02-test-suite-consolidation-fast-lane.md

All tests use plain pathlib reads + string assertions. No YAML/TOML parser.
No pytest-django database requirement.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_pytest_markers_are_documented():
    pyproject = (ROOT / "pyproject.toml").read_text()

    assert "[tool.pytest.ini_options]" in pyproject
    assert "slow:" in pyproject
    assert "admin_view:" in pyproject
    assert "external_contract:" in pyproject


def test_woodpecker_pr_uses_fast_test_lane():
    ci_config = (ROOT / ".woodpecker.yml").read_text()

    assert 'CI_PIPELINE_EVENT" = "pull_request"' in ci_config
    assert 'uv run pytest -q -m "not slow"' in ci_config


def test_woodpecker_pushes_keep_full_test_suite():
    ci_config = (ROOT / ".woodpecker.yml").read_text()

    assert "else" in ci_config
    assert "uv run pytest -q" in ci_config
