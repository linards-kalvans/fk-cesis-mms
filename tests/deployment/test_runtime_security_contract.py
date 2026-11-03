"""Protect image scanning and the production-only dependency build contract."""

from pathlib import Path
import re

import yaml  # type: ignore[import-untyped]


ROOT = Path(__file__).resolve().parents[2]


def test_runtime_uses_the_same_digest_pinned_python_as_builder():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert re.search(r"ARG PYTHON_IMAGE=python:3\.14\.[^\s@]+@sha256:[a-f0-9]{64}", dockerfile)
    assert "FROM ${PYTHON_IMAGE} AS builder" in dockerfile
    assert "FROM ${PYTHON_IMAGE} AS runtime" in dockerfile


def test_collectstatic_cannot_implicitly_reinstall_dev_dependencies():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "RUN .venv/bin/python manage.py collectstatic" in dockerfile
    assert "RUN uv run python manage.py collectstatic" not in dockerfile
    assert 'CMD ["python", "-c", "import urllib.request;' in dockerfile
    assert "apt-get install" not in dockerfile


def test_ci_scans_before_registry_login_and_push_without_rebuilding():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    assert "packages" not in workflow["permissions"]
    job = workflow["jobs"]["build-and-push"]
    assert "github.event_name != 'pull_request'" in job["if"]
    assert job["permissions"]["packages"] == "write"
    steps = job["steps"]
    build = next(i for i, s in enumerate(steps) if "docker/build-push-action@" in s.get("uses", ""))
    scan = next(i for i, s in enumerate(steps) if "bash scripts/scan-runtime-image.sh" in s.get("run", ""))
    login = next(i for i, s in enumerate(steps) if "docker/login-action@" in s.get("uses", ""))
    push = next(i for i, s in enumerate(steps) if "docker push" in s.get("run", ""))
    assert build < scan < login < push
    assert steps[build]["with"]["load"] is True
    assert steps[build]["with"].get("push", False) is False
    assert "continue-on-error" not in steps[scan]
    assert "docker build" not in steps[push]["run"]


def test_scanner_is_pinned_and_reports_unfixed_without_a_docker_socket():
    script = (ROOT / "scripts/scan-runtime-image.sh").read_text()
    assert re.search(r"scanner=aquasec/trivy:0\.76\.1@sha256:[a-f0-9]{64}", script)
    assert "set -euo pipefail" in script
    assert "docker image save" in script
    assert "/var/run/docker.sock" not in script
    assert "--ignorefile ''" in script
    assert "--ignore-unfixed" not in script
    assert 'jq -e \'length == 0\'' in script
