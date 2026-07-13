# Registration date format design

Date: 2026-07-13

## Problem

The parent registration form shows the child birth date with the browser-native date control. On some browsers/locales this appears as `MM/DD/YYYY`, which is not the Latvian format expected by parents.

## Goal

Show and accept the child birth date as `DD.MM.GGGG` in the parent registration form.

## Scope

In scope:
- The `member_birth_date` field only (`Bērna dzimšanas datums`).
- Parent registration create/edit workspace surfaces.
- Review/read-only display for that field.
- Form validation and tests for the visible format.

Out of scope:
- Other admin date fields.
- Billing, agreement, discontinuation, and Invoice Ninja date fields.
- JavaScript date masking or custom date picker.
- Database/model changes.

## Design

Use a plain text input for `member_birth_date` instead of the native HTML `type="date"` input.

Why:
- Native date input display is controlled by browser/OS locale and cannot reliably be forced to `DD.MM.GGGG`.
- A text input gives exact visible format and reliable placeholder behavior.
- Django can still parse into a real Python `date`, so stored data stays unchanged.

Field behavior:
- Label stays `Bērna dzimšanas datums`.
- Placeholder is `DD.MM.GGGG`.
- Help text is `Ievadiet datumu formātā DD.MM.GGGG`.
- Accepted input format is `DD.MM.GGGG` via Django form parsing (`%d.%m.%Y`).
- Invalid dates show the existing Latvian invalid-date error.
- Initial form values render as `DD.MM.GGGG`.
- Review/read-only display renders as `DD.MM.YYYY`.

## Test strategy

Add/update tests around the existing registration form/template contracts:
- Form accepts a valid `DD.MM.GGGG` value and returns a `date`.
- Form rejects an invalid Latvian-format date.
- Rendered registration field contains the placeholder and help text.
- Read-only/review date display uses dot-separated Latvian format.

Do not add tests for browser-native date picker behavior, because the design removes that dependency.

## Acceptance criteria

- Parent sees `Bērna dzimšanas datums` with placeholder `DD.MM.GGGG`.
- Parent sees hint `Ievadiet datumu formātā DD.MM.GGGG`.
- `01.02.2025` is accepted and stored as the correct date.
- Invalid values are rejected with Latvian validation copy.
- Existing stored dates display as dot-separated dates in parent review/read-only surfaces.
- No model migration is created.
