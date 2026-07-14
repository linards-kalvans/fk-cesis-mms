# Registration date format design

Date: 2026-07-13

## Problem

The parent registration child birth date must use Latvian `DD.MM.GGGG`. Native `input type="date"` cannot be relied on for this: a Chromium probe with `html lang="lv"` and `input lang="lv"` still rendered `mm/dd/yyyy` and `02/01/2025`.

A text input fixes visible format, but the user still wants native date-picker assistance and native-like slash/dot insertion while typing.

## Goal

Show and accept the child birth date as `DD.MM.GGGG`, keep calendar picker assistance, and make typing forgiving by auto-inserting dots.

## Scope

In scope:
- The `member_birth_date` field only (`Bērna dzimšanas datums`).
- Parent registration create/edit workspace surfaces.
- Read-only display for that field.
- Form validation and tests for the visible format.
- Progressive-enhancement native picker assist.
- Lightweight input mask for dot insertion and paste normalization.

Out of scope:
- Other admin date fields.
- Billing, agreement, discontinuation, and Invoice Ninja date fields.
- External date-picker or masking libraries.
- Custom calendar UI.
- Database/model changes.

## Design

Use a plain text input for `member_birth_date` as the source of truth, formatted as `DD.MM.GGGG`. Add a hidden native `input type="date"` plus a calendar button as picker assist. Add a small input mask that normalizes typed/pasted values.

Why:
- Native date input display is controlled by browser/OS locale and cannot reliably be forced to `DD.MM.GGGG`, even with `lang="lv"` in Chromium.
- Text input gives exact visible format and placeholder behavior.
- Hidden native date input keeps browser calendar assistance without dependencies.
- Small mask improves typing without taking over server-side validation.
- If JavaScript is unavailable, the visible text field still works.

Field behavior:
- Label stays `Bērna dzimšanas datums`.
- Placeholder is `DD.MM.GGGG`.
- Help text is `Ievadiet datumu formātā DD.MM.GGGG`.
- Accepted server input format is `DD.MM.GGGG` via Django form parsing (`%d.%m.%Y`).
- Invalid dates show existing Latvian invalid-date error.
- Initial form values render as `DD.MM.GGGG`.
- Read-only display renders as `DD.MM.YYYY`.
- Calendar button opens native date picker where supported.
- Picking a date fills the visible text field as `DD.MM.GGGG`.
- Typing digits auto-inserts dots:
  - `01` -> `01.`
  - `0102` -> `01.02.`
  - `01022025` -> `01.02.2025`
- Manually typed separators do not duplicate dots.
- Paste normalization:
  - `01022025` -> `01.02.2025`
  - `01/02/2025` -> `01.02.2025`
  - `2025-02-01` -> `01.02.2025`

## Implementation boundary

- `RegistrationApplicationForm.member_birth_date` remains a Django `DateField` with `input_formats=["%d.%m.%Y"]` and a text-style `DateInput` widget.
- Visible input carries `data-date-format="lv-dot"`.
- The shared form field partial renders the picker assist for this one data hook.
- Existing `static/js/wizard.js` owns the progressive-enhancement behavior and input mask because it already runs on registration wizard pages.
- No new dependency is added.

## Test strategy

Add/update tests around existing contracts:
- Form accepts a valid `DD.MM.GGGG` value and returns a `date`.
- Form rejects invalid Latvian-format date.
- Rendered field contains placeholder and help text.
- Rendered field includes calendar button and hidden native date input assist.
- CSS contract keeps the field as one short visible control with hidden native input.
- JS source contract includes date-mask helpers and ISO paste conversion.
- Read-only date display uses dot-separated Latvian format.
- Existing form POST tests that submit through the parent UI use `DD.MM.GGGG`.

Do not test browser-native calendar internals; browsers own native picker UI.

## Acceptance criteria

- Parent sees one short visible date field with calendar button inside the field.
- Parent does not see a second `mm/dd/yyyy` native field.
- Parent sees placeholder `DD.MM.GGGG`.
- Parent sees hint `Ievadiet datumu formātā DD.MM.GGGG`.
- Parent can click calendar button to use native date picker assistance.
- Picking date through assist fills visible input as `DD.MM.GGGG`.
- Typing/pasting dates auto-normalizes dots as described above.
- `01.02.2025` is accepted and stored as the correct date.
- Invalid values are rejected with Latvian validation copy.
- Existing stored dates display as dot-separated dates in parent read-only surfaces.
- No model migration is created.
