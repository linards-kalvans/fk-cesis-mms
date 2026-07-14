"""Regression: async_upload.js must sync the review summary after upload.

Bug: wizard.js::updateReview() skips file inputs, so the review step
shows "—" for file fields after async upload until page reload.
Root cause: async_upload.js updates the document card but not the
[data-review-for] cell.
"""

from __future__ import annotations

from pathlib import Path

JS_PATH = Path(__file__).resolve().parents[2] / "static" / "js" / "async_upload.js"


def _source() -> str:
    return JS_PATH.read_text(encoding="utf-8")


def test_async_upload_syncs_review_summary_for_file_input():
    """async_upload.js must update [data-review-for] matched by input.id."""
    src = _source()
    assert "data-review-for" in src
    assert "input.id" in src


def test_review_sync_runs_after_mark_card_as_uploaded():
    """Review update must happen in the success path after markCardAsUploaded."""
    src = _source()
    mark_idx = src.find("markCardAsUploaded(input)")
    review_idx = src.find("data-review-for")
    assert mark_idx != -1
    assert review_idx != -1
    assert review_idx > mark_idx
