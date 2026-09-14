# Member ID Back Guidance Copy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clarify in parent-facing text that a child ID-card back image is optional but expected for an ID card, not for a passport or birth certificate.

**Architecture:** This is one parent-form label and its exact-copy contract. No server validation changes: the platform cannot reliably determine whether the front upload is an ID card, passport, or birth certificate.

**Tech Stack:** Django forms, pytest/pytest-django.

---

## File map

| File | Change |
|---|---|
| `apps/registrations/forms.py` | Replace only the `member_identity_back_document` label. |
| `tests/registrations/test_registration_form_contract.py` | Pin exact new label and preserve optional/no-gate contract. |
| `docs/superpowers/specs/2026-09-11-member-id-back-upload-design.md` | Already updated with approved guidance-only rule. |

## Test strategy

Test exact form label, `required=False`, omission from `submit_required_fields`, and absence of `data-step-required`. Do not test document-type enforcement because none must exist.

### Task 1: Update label contract and implementation

**Files:**
- Modify: `tests/registrations/test_registration_form_contract.py`
- Modify: `apps/registrations/forms.py:100-107`

- [ ] **Step 1: Write failing exact-copy test.**

```python
assert form.fields["member_identity_back_document"].label == (
    "Bērna ID kartes aizmugure (nav obligāta, bet nepieciešama, ja "
    "augšupielādēta bērna ID karte; nav vajadzīga pasei vai dzimšanas apliecībai)"
)
assert form.fields["member_identity_back_document"].required is False
assert "member_identity_back_document" not in form.submit_required_fields
assert "data-step-required" not in form.fields["member_identity_back_document"].widget.attrs
```

- [ ] **Step 2: Verify red phase.**

Run: `uv run pytest -q tests/registrations/test_registration_form_contract.py`

Expected: one exact-label assertion fails; existing optional/no-gate assertions pass.

- [ ] **Step 3: Replace only form label.**

```python
member_identity_back_document = forms.FileField(
    required=False,
    label=(
        "Bērna ID kartes aizmugure (nav obligāta, bet nepieciešama, ja "
        "augšupielādēta bērna ID karte; nav vajadzīga pasei vai dzimšanas apliecībai)"
    ),
)
```

Do not change any validation, form field ordering, async attribute, upload, OCR, document, or Admin Hub code.

- [ ] **Step 4: Verify green plus repository gates.**

Run: `uv run pytest -q tests/registrations/test_registration_form_contract.py && uv run pytest -q && uv run ruff check . && uv run mypy .`

Expected: every command exits 0.

## Acceptance criteria

1. Parent form has exact approved guidance copy.
2. Back upload remains technically optional and has no client/server conditional detection or validation.
3. No behavior outside label/test contract changes.
