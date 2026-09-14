# Member ID Back Card Helper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show approved guidance below only child-ID-back document-card title.

**Architecture:** Pass a dedicated parent-workspace copy value from presentation context into existing generic `document_card.html`; render it only when loop kind is `member_identity_back`. No form field, validation, upload, storage, Admin, or Hub change.

**Tech Stack:** Django templates, pytest/pytest-django.

---

### Task 1: Add card-only helper text

**Files:**
- Modify: `tests/registrations/test_document_state_presentation.py`
- Modify: `apps/registrations/presentation.py`
- Modify: `apps/registrations/views.py`
- Modify: `templates/parent_ui/includes/document_card.html`

- [ ] **Step 1: Write failing rendered-DOM test.**

```python
assert "Bērna ID kartes aizmugure" in back_card
assert (
    "Nav obligāta, bet nepieciešama, ja augšupielādēta bērna ID karte; "
    "nav vajadzīga pasei vai dzimšanas apliecībai."
) in back_card
assert helper_text not in non_back_cards
```

- [ ] **Step 2: Verify red phase.**

Run: `uv run pytest -q tests/registrations/test_document_state_presentation.py`

Expected: helper-text assertion fails; unrelated document-card tests pass.

- [ ] **Step 3: Add minimal presentation copy and template conditional.**

```python
MEMBER_IDENTITY_BACK_HELPER_TEXT = (
    "Nav obligāta, bet nepieciešama, ja augšupielādēta bērna ID karte; "
    "nav vajadzīga pasei vai dzimšanas apliecībai."
)
```

Pass it from both workspace render contexts as `member_identity_back_helper_text`. In `document_card.html`, render a `<p class="fk-document-card__hint">` only for `kind == "member_identity_back"`. Keep title mapping short.

- [ ] **Step 4: Verify.**

Run: `uv run pytest -q tests/registrations/test_document_state_presentation.py && uv run pytest -q && uv run ruff check . && uv run mypy .`

Expected: all commands exit 0.

## Acceptance criteria

1. Back card shows short title plus exact helper text below title.
2. No other document card shows helper text.
3. No validation, detection, upload, storage, Admin, or Hub behavior changes.
