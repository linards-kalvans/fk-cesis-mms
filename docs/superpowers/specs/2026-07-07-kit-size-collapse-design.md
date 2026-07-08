# Kit size collapse design

Date: 2026-07-07
Status: delivered (2026-07-07)

## Problem

The parent registration flow currently asks for separate shirt and shorts sizes. FK Cēsis now needs a single kit-size choice only: **Formas izmērs**.

## Goals

- Show one parent-facing kit-size field labelled **Formas izmērs**.
- Require only that one kit-size field before submission.
- Preserve existing application data by treating the old shirt-size value as the new single kit-size value.
- Order active kit-size choices naturally: numeric child sizes first (`116`, `122`, ..., `146`), then t-shirt sizes (`XS`, `S`, `M`, `L`, `XL`), with unknown labels after known labels.
- Keep the change small and compatible with existing registration flow tests and data.

## Non-goals

- No stock management or size chart.
- No parent UI redesign beyond replacing two kit-size selects with one.
- No admin kit-size cleanup; collapsing shirt/shorts into one admin-facing form-size control is deferred to P11 family hub.
- No member-model kit-size persistence changes unless required by existing code.
- No cleanup of unrelated registration fields.

## Chosen approach

Reuse the existing `RegistrationApplication.member_kit_size_shirt` field as the canonical single kit-size field. The old `member_kit_size_shorts` field becomes legacy-only and is no longer shown or required in the parent registration form.

Why: this is the smallest safe change. Existing rows already have shirt-size data, and the user selected shirt size as the migration/source rule. A full schema rename/drop can happen later if needed, but it is not required to solve the parent-flow problem.

## Data model and migration

- Keep `member_kit_size_shirt` as the stored canonical kit size for now.
- Keep `member_kit_size_shorts` in the database for backward compatibility, but stop writing it from current parent form submissions.
- `KitSizeOption.kind` remains for compatibility, but parent-flow choices should not expose separate shirt/shorts categories.
- Existing data needs no destructive migration: old shirt values are already in the canonical field.
- New or updated seed/admin-created options should use the shirt kind or a compatibility kind selected by implementation. The parent flow will read the canonical active option set once.

## Form behavior

- Replace form field `member_kit_size_shirt` label with **Formas izmērs**.
- Remove `member_kit_size_shorts` from section order, submit-required fields, wizard step-gating, and parent-visible UI.
- Populate the single field with active kit options in natural size order.
- Submitting without the field remains invalid.

## Service behavior

- `create_or_update_draft` reads only `member_kit_size_shirt` from cleaned data for current forms.
- It leaves `member_kit_size_shorts` unchanged or clears it only if necessary for existing service invariants. No caller should need to post shorts anymore.
- `submit_application` requires only `member_kit_size_shirt_id`.
- Error text should refer to a single kit size, not shirt/shorts.

## Sorting rule

Implement a small local sort helper for kit-size labels. Known order:

numeric labels first by numeric value, then `XXS`, `XS`, `S`, `M`, `L`, `XL`, `2XL`, `3XL`, `4XL`, `5XL`

Labels not in the known map sort after numeric and known t-shirt sizes, alphabetically case-insensitive. This avoids adding dependencies or a new ordering column for now.

## Tests

- Form contract: one kit-size field in the member section; old shorts field absent from parent form section/order.
- Submit validation: missing canonical kit size raises; shorts not required.
- Choice ordering: active options sort numeric sizes before t-shirt sizes (for example `116`, `122`, `XS`, `S`, `M`), with inactive options excluded.
- Draft save: canonical field persists selected option without requiring shorts.
- Existing compatibility tests updated to post only the canonical field where they exercise parent forms.

## Acceptance criteria

- Parent workspace renders **Formas izmērs** once and does not render **Krekla izmērs** or **Šortu izmērs**.
- Parent submit succeeds when all existing required fields plus single kit size are present.
- Parent submit fails when single kit size is absent.
- Kit choices show numeric sizes before t-shirt sizes, and `XS` before `S` before `M` within t-shirt sizes.
- Full verification passes: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy .`.
