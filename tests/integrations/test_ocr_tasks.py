"""Background-job runner smoke tests.

P3.5 Phase 0: prove django-q2 enqueues and executes jobs end-to-end
before we put real OCR work on it.
"""

from __future__ import annotations

import pytest
from django_q.tasks import async_task, result

pytestmark = pytest.mark.django_db


def _smoke_multiply(value: int, factor: int) -> int:
    """Test target — used as the job body by the smoke test."""
    return value * factor


def test_django_q_runs_a_noop_job() -> None:
    task_id = async_task(
        "tests.integrations.test_ocr_tasks._smoke_multiply",
        7,
        6,
        sync=True,
    )
    assert result(task_id) == 42
