"""Source-level contract checks for static/js/wizard.js (P4 Slice C Task 6).

Mirrors the substring-sniff pattern in
``tests/registrations/test_async_document_upload.py::TestAsyncUploadJsContract``.
There is no JS test runner; assertions on the source are the simplest stable
signal that the wizard controller exposes the documented hooks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

JS_PATH = Path(__file__).resolve().parents[2] / "static" / "js" / "wizard.js"


def _source() -> str:
    return JS_PATH.read_text(encoding="utf-8")


class TestWizardJsContract:
    def test_debounce_500ms_constant(self):
        src = _source()
        assert "500" in src
        # The constant is named or the helper is named — at least one of these
        # substrings must exist.
        assert "DEBOUNCE" in src or "debounce" in src

    def test_uses_xhr_header_xrequestedwith(self):
        src = _source()
        assert "X-Requested-With" in src
        assert "XMLHttpRequest" in src

    def test_uses_csrf_token_header(self):
        src = _source()
        assert "X-CSRFToken" in src

    def test_reads_data_step_required(self):
        src = _source()
        assert "data-step-required" in src

    def test_reads_data_personal_data_consent(self):
        src = _source()
        assert "data-personal-data-consent" in src

    def test_toggles_data_wizard_next_disabled(self):
        src = _source()
        assert "data-wizard-next" in src
        assert "disabled" in src
        assert ".disabled =" in src

    def test_retry_once_semantics(self):
        src = _source()
        # The retry path must be present — either as a named identifier or as
        # the 2000 ms delay constant.
        assert "retry" in src.lower() or "2000" in src

    def test_window_fk_wizard_exposed(self):
        src = _source()
        assert "__fkWizard" in src
        assert "validateStep" in src
        assert "scheduleAutoSave" in src
        assert "getSaveState" in src

    def test_handles_visibility_or_blur_or_input_triggers(self):
        src = _source()
        triggers = ["blur", "input", "change"]
        present = [t for t in triggers if t in src]
        assert len(present) >= 3, (
            f"Wizard must wire at least three of {triggers!r}; found {present!r}"
        )

    def test_waiver_logic_for_same_address(self):
        src = _source()
        assert (
            "member_same_address_as_guardian" in src
            or "data-same-address-waiver" in src
        )

    def test_save_indicator_state_transitions(self):
        src = _source()
        assert "data-save-state" in src
        for state in ("saving", "saved", "error"):
            assert state in src, f"Save indicator state {state!r} must appear in source"

    def test_date_mask_contract_for_latvian_birth_date(self):
        src = _source()
        # The mask helper must be defined in wizard.js.
        assert "formatLvDotDateInput" in src
        # The visible date field carries a stable hook the mask binds to.
        assert "data-date-format" in src
        # ISO paste conversion: source must recognise YYYY-MM-DD (either as a
        # literal example or as a digit-group regex).
        assert "2025-02-01" in src or r"(\d{4})-(\d{2})-(\d{2})" in src
        # Non-digit stripping + 8-digit cap.
        assert r"replace(/\D/g" in src or r"replace(/[^\d]/g" in src
        assert "slice(0, 8)" in src
        # Dot-format output: explicit example OR a join with the dot separator.
        assert "01.02.2025" in src or "parts.join('.')" in src


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
