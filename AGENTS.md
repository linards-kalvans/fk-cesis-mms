# AGENTS.md — FK Cēsis MMS

*Authoritative project guide. Keep this file updated after major changes.*

## Project Purpose
Django MVP for FK Cēsis youth football club: parent registration, admin approval, secure identity-document handling, and Invoice Ninja billing orchestration.

## Stack
- **Python 3.12+**, **Django 5.x**, **PostgreSQL** (psycopg)
- **uv** for dependency management and script execution
- **pytest** + **pytest-django**, **ruff**, **mypy**
- Private file/object storage, background job runner (Celery / Django-Q)
- Server-rendered templates (parent + admin), minimal JS

## Architecture
Target Django monolith with domain apps:
- `apps/core` — shared base models, enums, audit helpers
- `apps/accounts` — ParentAccount, magic-link auth
- `apps/registrations` — RegistrationApplication workflow, OCR intake
- `apps/members` — Member, Guardian, TrainingGroup
- `apps/billing` — MembershipPlan, sibling discount, Invoice Ninja sync
- `apps/documents` — private Document model, audited access views
- `apps/integrations` — Invoice Ninja / OCR clients, retry state
- `apps/admin_ops` — admin dashboards, CSV export *(planned, not yet implemented)*

## Current Status
**Tasks 1–6 complete in current worktree, P1 + P2 are complete, and P3 is signed off (live validation evidence in `docs/p3_tiny_idp_validation.md`).** Registration workflow is usable for LAN acceptance testing; admin review queue, member creation baseline, guardian-email-first verified registration gate, and OCR-backed parent/admin review flow are operational.
- Django project scaffold exists and boots.
- `apps/` package exists with app configs for `core`, `accounts`, `registrations`, `members`, `billing`, `documents`, `integrations`.
- `apps/core/models.py` includes abstract `TimeStampedModel`.
- `apps/accounts/models.py` implements `ParentAccount`, `MagicLinkToken`, and `EmailVerificationCode`.
- `apps/accounts/services.py` implements `issue_magic_link`, `send_magic_link`, `consume_magic_link`, plus one-time email code issue/send/verify helpers.
- `apps/accounts/views.py` implements request, verify, logout, and one-time code verification views.
- `apps/accounts/management/commands/ensure_admin_user.py` for env-driven admin creation.
- `apps/registrations/models.py` implements `RegistrationApplication` with finalized P1 guardian/member/application fields, draft/submitted states, and fix/reject/approve workflow.
- `apps/registrations/services.py` implements application lifecycle: create, save draft, submit, chooser/prefill support, same-address handling, link to parent account, admin review actions (request_fix, reject, approve), OCR-triggered identity upload processing, guardian-doc reuse, and OCR-derived prefill/field-source mapping. `fix_requested` save preserves status (Task 3).
- `apps/registrations/views.py` provides guardian email entry, verified registration create/edit, chooser portal, admin review queue/detail views, canonical application workspace routing, parent OCR summary rendering, and admin OCR review context.
- `apps/registrations/presentation.py` implements grouped form rendering contract and workspace mode logic (Task 3).
- `apps/registrations/forms.py` implements the unified registration form with grouped sections (Task 3).
- `apps/registrations/templatetags/reg_filters.py` provides template filters for the form contract (Task 3).
- `apps/members/models.py` implements `Member`, `Guardian`, `TrainingGroup`, and `KitSizeOption` models; approval creates `Member` + `Guardian` with `training_group` left empty.
- `apps/documents/models.py` implements `Document` model with private storage (`PRIVATE_DOCUMENTS_ROOT`), OCR process state fields, and `DocumentExtraction` for encrypted OCR payload/summary persistence.
- `apps/documents` uses a dedicated private storage root (`private-uploads/`), Fernet-encrypted OCR payload/summary helpers in `apps/documents/ocr.py`, and admin-only protected preview/download endpoints (`/admin/documents/<id>/preview/`, `/admin/documents/<id>/download/`). Anonymous users are redirected to admin login; non-admin authenticated users receive `404`.
- `.env` autoload works for local commands and app startup.
- Current acceptance testing runs on LAN URL `http://192.168.3.245:8000`.

### P1 delivered registration workflow UX
- `/register/` is guardian email entry for one-time code verification.
- `/register/verify/` completes verified parent access before continuation.
- `/portal/` acts as chooser/dashboard for verified guardians.
- `/applications/new/` starts a new verified registration with guardian-only prefill.
- `/applications/<id>/` is the canonical parent application workspace (Task 3); legacy parent routes redirect here.
- Anonymous same-browser draft continuation was removed; edit/submit now require verified parent ownership.
- Edit page uses a single form with two actions: **save draft** and **submit application**.
- Member address supports live **Adrese tāda pati kā vecāka** sync and restore behavior.
- Grouped form rendering contract in place (Task 3): guardian, child/player, and document sections rendered via shared template primitives (`form_field.html`, `source_badge.html`).
- Application workspace supports read-only (submitted/approved/rejected) and editable (draft/fix_requested) modes; `fix_requested` save preserves status (Task 3).

### Task 4 delivered — document state, OCR source cues, error summary
- `templates/parent_ui/includes/document_card.html` — reusable document card partial showing filename, kind label, active/not-uploaded state, and replace/upload links for parent workspace.
- `templates/parent_ui/includes/error_summary.html` — updated to render field label, validation message, and anchor link to invalid field via `items` parameter.
- `templates/registrations/application_workspace.html` — includes document card section in both editable and read-only modes; replace/upload links only shown in editable mode; passes source labels to all form fields.
- Source badges render for `manual_only`, `derived_system_filled`, and OCR markers (`ocr_guardian_identity`, `ocr_member_identity`) using `SOURCE_LABEL_MAP` in `presentation.py`.
- Invalid-submit error summary shows heading, field label, validation message, and anchor target (`id-guardian_email` pattern).
- No schema changes, no business rule changes, no admin redesign.

### P2 delivered — visual system refinements, document-state/review-cue presentation
- Typography refined for readability (desktop and mobile).
- Active uploaded-document state and replace guidance clarified via document card partial.
- Review/correction cues completed at presentation layer without real OCR dependency: source badges, error summary with anchor links, invalid-submit error summary.
- No schema changes, no business rule changes, no admin redesign.

### P3 delivered — OCR integration + secure extracted metadata baseline
- `apps/integrations/ocr.py` provides OCR provider boundary with deterministic stub mode and tiny-IDP hook point.
- Identity uploads for `guardian_identity` and `member_identity` now run synchronous OCR in draft flow; `member_portrait` stays outside OCR scope.
- OCR success persists encrypted payload and encrypted summary in `DocumentExtraction`; OCR failure stays non-blocking and records failed state.
- `/applications/new/` reuses active guardian identity document by default for returning verified guardians and merges prior OCR extraction into new-app prefill.
- Parent workspace shows OCR-derived source labels and decrypted OCR summaries for uploaded identity documents.
- Admin review detail shows separate guardian/member document preview sections, decrypted OCR summaries, and confidence values when provider returns them.
- Test-client file upload workaround in `tests/conftest.py` supports Django 6 multipart posts with `files=`.
- Full repo verification after P3 landing: `uv run pytest -q` → `584 passed`, `uv run ruff check .` → passed, `uv run mypy .` → passed.
- Classified exception mapping in `safe_extract_document_data`: `_classify_exception()` maps typed OCR errors (`provider_misconfigured`, `auth_failed`, `rate_limited`, `request_timeout`, `provider_unavailable`, `invalid_response`) to `Document.ocr_error_code` for admin review. Unknown exceptions fall back to `provider_unavailable`.
- Real tiny-IDP runtime is landed; `TINY_IDP_API_URL` and `TINY_IDP_API_KEY` are the canonical config names. `OCR_ENCRYPTION_KEY` is required for OCR payload/summary encryption.
- Live sample-document validation evidence captured in `docs/p3_tiny_idp_validation.md` (run via `uv run python -m scripts.validate_tiny_idp`). P3 signed off 2026-05-22.
- Live validation surfaced and fixed three integration bugs against the real `api.tiny-idp.com` generic-id-document API: (1) auth header is `x-api-key`, not `Authorization: Bearer`; (2) multipart field name is `files`, not `file`; (3) response is `{success, data: {...}, balance, cost}` — adapter and tests had been built against a fictional `{entities, document, confidence}` shape. Normalizer now maps `data.given_names`→`first_name`, `data.first_surname`→`last_name`, `data.personal_number`→`personal_id`, `data.issuing_authority`→`issuer`, `data.issuing_date`→`issuance_date`, `data.date_of_birth`→`date_of_birth`, and derives `confidence` from `*_verified` booleans. Auth failure with malformed key returns HTTP 200 + `{"code": "API_KEY_REQUIRED"}` body, which `post_document` now classifies as `AuthError`.

### P4 Slice A delivered — foundations (2026-05-23)
- `apps/integrations/name_normalization.py` — pure Latvian title-case helper applied at OCR consumption boundaries only: the `encrypted_summary` builder in `apps/integrations/tasks.py` and the `_merge_ocr_extractions` prefill reads in `apps/registrations/services.py`. The encrypted OCR payload at rest stays raw (audit posture preserved). Handles hyphenated compounds, nobiliary particles (lowercase unless sole token), and Latvian diacritics; defensive against non-string input. Covered by 18 parametrized cases in `tests/integrations/test_name_normalization.py`.
- `RegistrationApplication.personal_data_consent_at` + `personal_data_consent_version` fields (migration `0007_personal_data_consent`, both nullable). Current consent version constant: `apps.registrations.models.PERSONAL_DATA_CONSENT_VERSION = "v1-2026-05"`. Both fields are listed in `RegistrationApplicationAdmin.readonly_fields` so admin staff cannot stamp or unstamp consent directly. Gate UX, T&C partial, and consent persistence on submit land in P4 Slice C.
- Cross-cutting parent-UI primitives in `templates/parent_ui/includes/`: `spinner.html` (`data-spinner`, `role="status"`), `toast.html` (`data-toast`, `data-toast-tone`; `warning` tone uses `role="alert"` + `aria-live="assertive"`), `empty_state.html` (`data-empty-state`), `error_state.html` (`data-error-state`, `role="alert"`). All follow the existing `fk-*` BEM-style class prefix. Consumers (visibility-aware polling, OCR-done toast, entry/portal empty + error states) land in P4 Slices B–E.

### P4 Slice B delivered — P3.5 polish leftovers (OCR UX) (2026-05-23)
- `apps/integrations/ocr_messages.py` — centralized Latvian error-code → message map plus generic fallback (`get_ocr_error_message`). Six known codes covered (`provider_misconfigured`, `auth_failed`, `rate_limited`, `request_timeout`, `provider_unavailable`, `invalid_response`); unknown / missing codes fall back to a generic "fill manually" message. No English fallback anywhere in the parent flow.
- Status polling endpoint (`/applications/<id>/documents/<doc_id>/status/`) now emits `ocr_error_message` on FAILED responses alongside the existing `ocr_error_code`. Running / completed payloads do not carry it.
- `static/js/async_upload.js` no longer renders raw text status. Running state uses the `fk-spinner` markup; completed state uses an auto-dismissing `fk-toast` carrying `"Dokumenta apstrāde pabeigta. Persona atpazīta kā <Name>."` (name comes pre-normalized from Slice A); failed state renders the server-supplied Latvian message. Polling pauses when `document.hidden === true` and resumes on a one-shot `visibilitychange` listener.
- `static/css/parent_theme.css` ships full styling for `.fk-spinner`, `.fk-toast` (+ success / warning variants), and the previously-unstyled `.fk-ocr-suggestion` chip family. `prefers-reduced-motion` disables the spinner animation.

### P4 Slice C delivered — wizard gating + auto-save + consent gate (2026-05-24)
- Consent persistence is stamped server-side only. `apps.registrations.services.create_or_update_draft` writes `personal_data_consent_at` (now) and `personal_data_consent_version` (`apps.registrations.models.PERSONAL_DATA_CONSENT_VERSION = "v1-2026-05"`) when the form supplies `personal_data_consent=True`. Re-stamp rule: stamp on first True, AND when the stored version mismatches the current constant; once set, the fields are never cleared. The template renders the checkbox pre-checked only when stored version matches current AND timestamp is non-null.
- `apps/registrations/templates/registrations/_terms_v1.html` ships default Latvian T&C text marked "pending legal review" via a `{% comment %}` header. Production cutover requires legal sign-off, and any material text change must bump `PERSONAL_DATA_CONSENT_VERSION` so consent re-stamps on next save.
- Auto-save endpoint contract on `registrations:application-workspace` branches on `X-Requested-With: XMLHttpRequest`: success (200) returns `{"saved_at": "<ISO>", "consent_recorded": <bool>}`; form invalid (400) returns `{"errors": [{"field", "label", "message"}, ...]}`; service `ValueError` (400) returns `{"errors": [{"field": "__all__", "label": "", "message": "<exc>"}]}`; non-editable applications still raise Http404. AJAX POSTs never submit even if `submit_action=submit` is in the payload — auto-save can never accidentally graduate a draft.
- Wizard step-gating contract: inputs in `submit_required_fields` (plus the two document inputs) carry `data-step-required="<step-name>"` and `data-step-error-empty="<lv-msg>"` (and `data-step-error-format="<lv-msg>"` for `*_personal_id` inputs). `static/js/wizard.js` reads these attrs, validates on blur/change/input, and toggles `[data-wizard-next].disabled` accordingly. `member_actual_address` is skipped when `member_same_address_as_guardian` is checked, mirroring the server-side waiver in `forms.py::clean()`. The consent checkbox participates in the step-1 gate via `data-step-required="documents"` + `data-personal-data-consent`.
- `apps/registrations/messages.py` holds wizard / consent / save-indicator Latvian strings as plain top-level `str` constants. The template injects them via `data-step-error-empty`, `data-step-error-format`, `data-save-message-saving|saved|error` attributes — `wizard.js` reads from the DOM, never hardcodes Latvian.

### P4 Slice D delivered — camera capture + mobile-first workspace (2026-05-25)
- `templates/parent_ui/includes/document_card.html` now owns the upload UI for every document kind (guardian ID, member ID, member portrait). Each card renders a single canonical hidden `<input type="file">` (visually-hidden via `.fk-visually-hidden`) plus two visible `<label for="id_<field>">` controls: "Augšupielādēt failu" (native label→input wiring) and "Uzņemt attēlu" (carries `data-camera-affordance`, lives inside `.fk-camera-only`).
- `member_portrait_document` moved from the member section into the documents section in `RegistrationApplicationForm.section_order` so all three document uploads live in step 1.
- `static/js/async_upload.js` ships a camera-affordance shim: clicking a `label[data-camera-affordance]` calls `event.preventDefault()`, sets `accept="image/*"` and `capture="environment"` on the canonical input, then calls `input.click()`. A `pointerdown` listener on the non-camera file labels clears stale `capture` attrs (handles the camera-cancelled-without-pick edge case).
- `.fk-camera-only` is hidden on non-coarse pointers via `@media not (pointer: coarse)` — no JS feature detection, no UA sniffing. `wizard.js` step-gating is untouched (single canonical input per slot).
- Mobile-first polish: `.fk-wizard-nav--sticky` modifier on per-step nav rows turns sticky on `(pointer: coarse) and (max-width: 720px)`; container padding uses `clamp(16px, 4vw, 32px)`; `.fk-address-row` wraps the actual-address + same-as-guardian fields and stacks at `max-width: 720px`; `.fk-save-indicator` switches to `position: static` on mobile so it doesn't collide with the sticky CTA.
- Touch-target floors enforced at class level: `.fk-button` already ≥48 px; `.fk-button--small` bumped to 40 px; date inputs covered by the existing `.fk-form-field input[type="date"]` 46 px rule. `.fk-checkbox-row` wrapper (≥44 px, 10 px vertical padding) is available for consent + address-sync rows. Hidden file inputs are exempted (tap surface lives on the visible labels).
- Defensive cleanup: `apps/registrations/templatetags/reg_filters.py::get_item` now returns `None` for non-dict input (was AttributeError), so partials referencing context that lands in a later task render harmlessly during the transition.
- `apps/registrations/presentation.py` exposes a new public `FIELD_NAME_BY_KIND` constant (inverse of the existing private `_FIELD_TO_KIND`) consumed by the view to build `document_bound_fields` for the partial.
- Workspace-template internal class rename: `fk-wizard-nav-actions` → `fk-wizard-actions` to avoid substring collision with `fk-wizard-nav--sticky` in test regexes. Touched `parent_theme.css`, `application_workspace.html`, `new_registration.html`. No JS consumers; no template consumers outside the two renamed files.
- Each upload label carries a decorative Feather-style inline SVG icon (upload-arrow on the file label, camera on the camera label). Icons are `aria-hidden="true"` so screen readers read only the Latvian text. `.fk-button--full` (width 100% + `box-sizing: border-box`) stretches both labels equally inside the `.fk-upload-slot` flex column.
- Post-merge fix: multi-line `{# ... #}` template comments in `templates/parent_ui/includes/{document_card,save_indicator,toast,error_state,empty_state}.html` were leaking their bodies into the rendered page (Django's `{# #}` is single-line only). Converted to `{% comment %}...{% endcomment %}` (or deleted where the comment was task-history scaffolding). Regression test in `tests/registrations/test_application_workspace_template.py::TestSliceDWorkspaceTemplate.test_no_leaked_django_comment_markers` fails whenever a literal `{#` appears in the rendered workspace HTML.
- Full repo verification after Slice D landing: `uv run pytest -q` → `798 passed`, `uv run ruff check .` → passed, `uv run mypy .` → passed (143 source files).
- Manual LAN verification on `http://192.168.3.245:8000/applications/<id>/` complete (2026-05-25). Phone: 3 cards with two buttons each; "Uzņemt attēlu" opens the device camera; "Augšupielādēt failu" opens the file picker; sticky "Turpināt →" stays visible while scrolling; OCR toast still appears after upload; address-sync row stacks on step 2. Desktop: camera buttons hidden; inline wizard nav; stepper-click navigation works. Initial render exposed two template-comment leaks and unequal button widths — fixed in follow-up commits (see entries above).

- **P4 Slice E delivered (2026-05-25):** Closeout polish for the parent-flow entry/chooser/portal surfaces and Latvian copy normalization across all parent-facing pages.
  - `/register/`: removed duplicate `fk-section-card` include, repaired the broken `fk-button primary` class, dropped the `fk-eyebrow` wrapper, added `inputmode="email"` + `autocomplete="email"`, full-width primary CTA.
  - `/register/verify/`: switched the pending-email notice to the new `.fk-page-intro` helper, added `inputmode="numeric"` / `autocomplete="one-time-code"` / `autofocus` to the code input, full-width CTA.
  - `/portal/`: replaced the bespoke `<div class="fk-empty-state">` markup with the shared `empty_state.html` partial (now accepts optional `cta_url`/`cta_label`); stripped inline `style="margin-top:…"` attributes inside the application-card region in favour of a `.fk-app-meta--review` modifier; action anchors and helper-card CTA gain `fk-button--full`. Dynamic `<span style="width:N%">` widths inside `.fk-progress-bar` preserved (encode content, not styling).
  - CSS: `.fk-page-intro` helper added; new `@media (max-width: 720px)` block stacks `.fk-applications`, `.fk-application-card`, `.fk-app-actions .fk-button`, `.fk-helper-card` for the mobile baseline.
  - Latvian copy: new regression test `tests/registrations/test_parent_surface_copy_contract.py` scans rendered visible text on `/register/`, `/register/verify/`, `/portal/` (empty + with apps), `/applications/<id>/`, plus a static scan of `new_registration.html`, for English-token leakage. Token list fixed; legitimate fragments allowlisted in code with comments. Initial sweep found no English leaks (codebase was already Latvian-by-default; three Latvian-phrase guards were added to absorb the Latvian preposition "no").
  - Manual LAN verification on 192.168.3.245 (2026-05-25):
    - Slice E surfaces (`/register/`, `/register/verify/`, `/portal/`) rendered correctly at narrow viewports with full-width CTAs and no English-text leakage.
    - LAN check also surfaced two regressions adjacent to Slice E that were fixed in follow-up commits (see below) and six pre-existing bugs that are out of Slice E scope and have been queued as P4.5 (see `docs/milestones.md`).
  - Slice E LAN follow-up fixes (also 2026-05-25):
    - **Wizard CTA cut off on mobile (commits `80b3109`, `3d849cd`):** `.fk-wizard-nav .fk-button` fills its grid track (`width: 100%; box-sizing: border-box; padding: 0 14px; font-size: 14px`); `.fk-wizard-actions` overridden to `grid-template-columns: 1fr` at 720 px. Regression tests added under `TestParentThemeCssPortalMobile`.
    - **OCR summary rendered raw field IDs (commit `8351c2a`):** added `OCR_FIELD_LABELS` and `parse_ocr_summary` in `apps/registrations/presentation.py`; the workspace view now passes structured `(label, value)` tuples; the template renders a Latvian-labeled `<dl>` with the kind label resolved via `document_kind_labels`. Encryption/storage unchanged. New test file `tests/registrations/test_ocr_summary_presentation.py` covers helper + rendered DOM + CSS contract. One existing assertion in `test_workspace_ocr_decryption.py` was updated to match the new presentation contract.
    - **`member_same_address_as_guardian` checkbox blocked step advance (commit `fa80c45`):** removed field from `_field_step_map` in `RegistrationForm.__init__`; wizard treats unchecked checkbox as a valid (unfilled) optional field. New test file `tests/registrations/test_member_same_address_checkbox.py`.
    - **Document kind labels shown in English (commit `3d849cd`):** `DOCUMENT_KIND_LABELS` in `presentation.py` now contains explicit Latvian strings; `document_card.html` simplified to always use the map. New test file `tests/registrations/test_document_kind_labels.py`.
    - **Review step showed redundant "Saglabāt melnrakstu" button (commits `6732f4b`, `fb16bb1`):** removed save_draft button and `.fk-wizard-actions` wrapper from review step in both `application_workspace.html` and `new_registration.html`; "Iesniegt pieteikumu" now uses `fk-button--primary fk-button--full` matching the Turpināt style. New test file `tests/registrations/test_review_step_submit.py` (5 tests).
  - Test suite: 847 passed (up from 798 baseline); ruff and mypy clean.

- **P4.5 delivered — parent-flow quality-debt sweep (2026-05-25)**
  - Guardian full-name no longer doubled in new-app prefill: `_merge_ocr_extractions` removed model-value fallback; OCR wins unconditionally (`commit 58115e1` + `0a80b4e`).
  - Member OCR fields no longer bleed into new-app prefill: member block removed from `_merge_ocr_extractions`; each new registration starts with a fresh child record. Two stale tests updated (`commit 15bcf86`).
  - OCR stub now emits `date_of_birth` in `person_fields` (member: `2015-06-15`, guardian: `1985-03-10`). `_ocr_extracted_fields` maps `date_of_birth` → `member_birth_date` for member identity docs so the workspace prefill path can populate the DOB field after OCR completes (`commit 77e7fc4`).
  - Document card DOM updates to "Aktīvs" state immediately after async upload: `markCardAsUploaded` in `async_upload.js` swaps badge + body and inserts the `data-uploaded-document` hook (`commit 38bab23`).
  - Step-gating now recognises pre-uploaded documents on draft resume: `document_card.html` emits `[data-uploaded-document]` when a doc is present; `wizard.js::isFileFieldFilled` reads it via `.fk-upload-slot` (`commit aca78bf`).
  - Mobile wizard: stepper clicks restricted to `visitedSteps` Set (prevents bypassing step gating by tapping ahead); `fk-step--visited` CSS class marks navigable steps; `.fk-step-number` bumped to 44 × 44 px for reliable touch targets (`commit e3a0d18`).
  - Guardian phone now prefilled from the latest application's `guardian_phone` (falls back to `account.phone` only when no prior app exists or its phone is empty). The contact phone the parent typed into a prior application is the authoritative source over the registration-time phone (`commit 1f23a7d`).
  - Test suite: 856 passed; ruff and mypy clean.

### Test suite consolidation (2026-05-24)
- `tests/` reduced from 18,277 LOC / 807 tests / 153 s → **16,276 LOC / 762 tests / 84 s** (−11% LOC, −45% runtime). Plan: `docs/superpowers/plans/2026-05-24-test-suite-consolidation.md`.
- Shared fixture homes (use these for new tests instead of repeating per-test bootstrap):
  - `tests/conftest.py` — cross-app: `parent_account`, `other_parent_account`, `verified_client`, `other_verified_client`, `staff_client` (renamed from `admin_client` to avoid shadowing pytest-django's built-in).
  - `tests/registrations/conftest.py` — registrations-scoped: `guardian_identity_file`, `member_identity_file`, `member_portrait_file`, `kit_sizes`, `submit_payload`, `draft_application`, `draft_with_documents`, `submitted_application`, `fix_requested_application`, `rejected_application`.
- Visual / template / CSS contract for parent pages lives in **`tests/registrations/test_visual_contract.py`** (consolidated from the former `test_parent_visual_pages.py` and `test_task2_logo_and_css.py` + the visual half of `test_verified_registration_entry.py`). Add new visual assertions here, not in workflow / permissions test files.
- Removed files: `test_parent_visual_pages.py`, `test_task2_logo_and_css.py`, `test_personal_data_consent_schema.py`, `test_ocr_prefill_vs_suggestion.py`, `test_p3_remaining_gaps.py`. Their behaviors are preserved in the natural-home files listed above (or were duplicates of existing coverage).

### Task 6 follow-up debt
- Revisit desktop typography in Task 6 UI pass: blue text renders too heavy/thick on desktop and needs refinement.
- Django admin document UX should distinguish active vs replaced (soft-deleted) documents and hide or clearly disable preview/download actions for replaced rows.
- Training group assignment on approval (currently left empty).
- Admin activity audit entries for review actions.
- **DOB-driven member-form prefill.** Normalizer now surfaces `data.date_of_birth` (validated live on 2026-05-22), so `DocumentExtraction.summary` carries DOB. Outstanding: wire OCR-derived DOB into the member form prefill with the same source-badge treatment as other identity fields.
- **Surname normalization for Latvian IDs.** Live validation showed `data.first_surname` alone does not always match the manifest last name (likely diacritic / two-surname cases on guardian samples); consider folding `data.second_surname` and harmonizing diacritics before scoring downstream.

### Approved design and research direction (2026-05-05)
- **Build now:** whole-app visual system and registration form redesign (major parent-flow changes allowed).
- **Registration entry direction:** implemented in P1 as guardian email entry with one-time email code verification, verified continuation, guardian-only prefill, and chooser/dashboard for existing guardians. See `docs/superpowers/specs/2026-05-08-p1-field-contract-and-verified-registration-gate-design.md`.
- **Security fix — parent identity verification:** implemented in P1. Typed email in registration draft is a claim, not proof of ownership. Verified access now gates registration continuation and portal access. See `docs/superpowers/specs/2026-05-08-p1-field-contract-and-verified-registration-gate-design.md`.
- **Research spikes / preferred directions:** OCR vendor direction narrowed to **tiny-IDP** only, agreement generation with manual signing first and **DocuSeal self-hosted** favored for future richer processing, and SMTP/email provider strategy for scale.
- **Hosting stance:** self-hosted is not assumed more secure by default; compare self-hosted and SaaS by security posture, ops maturity, compliance, and API portability.
- **Visual direction:** unified design system, calm centered parent flow, denser admin shell, club logo hero-style on parent entry screens.
- **Style source of truth:** `style-guide/` supersedes `design-template.html`. Canonical tokens currently: font `Anton`, blue `#0f0851`, red `#ce1c20`.
- **Agreement handling, first slice:** after admin approval, generate agreement, allow manual signing outside platform (LV qualified electronic signature or paper), then mark signed and optionally upload signed copy. Richer countersign/order automation may follow later.
- **GDPR/EU compliance mandatory** for all third-party integrations.
- **Service boundary:** self-hosted services may live in separate infrastructure/Ansible projects; this repo should integrate loosely via adapters and external config, not own their deployment lifecycle.
- Spec: `docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md`.

Reference docs:
- Canonical product spec: `docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md`
- Milestones: `docs/milestones.md`
- Style guide assets: `style-guide/`
- Style guide tokens: `style-guide/tokens.md`, `style-guide/tokens.css`
- Design template (exploratory only, superseded by `style-guide/` on conflict): `design-template.html`

## Milestones
- `M1` — Foundation and security baseline
- `M2` — Parent registration intake
- `M3` — Admin review and member creation
- `M4` — Billing and Invoice Ninja sync
- `M5` — Admin operations and export
- `M6` — Production readiness

Use `docs/milestones.md` as authoritative milestone tracker and base for future development tasks. Keep it updated as scope/status changes.

Archive rule:
- `docs/archive/` is historical only.
- Do not use archived docs for planning, execution, or status by default.
- Read archived docs only when user explicitly asks for history/archive context.

## Commands
```bash
uv sync                                # install deps
uv run python manage.py migrate        # run migrations
uv run python manage.py runserver      # start dev server locally
uv run python manage.py qcluster       # start background-job worker (P3.5+)
uv run pytest                          # run test suite
uv run ruff check .                    # lint
uv run mypy .                          # type check
```

Rules:
- Always use `uv run` for Python commands.
- Do not assume `venv/` or `pip` exist.
- For user-accessible dev servers, expose app through `kimaki tunnel`, not localhost-only.
- For acceptance testing, expose usable app slices early, not only at end.

### Background worker (django-q2)

The web process and the worker process must both be running in local dev — they're separate terminals.

- **Start:** `uv run python manage.py qcluster` (separate terminal from `runserver`)
- **Broker:** Django ORM (`Q_CLUSTER.orm = "default"`) — no Redis needed
- **Worker env:** the qcluster process must have the same `.env` as the web process (specifically `OCR_ENCRYPTION_KEY`, `TINY_IDP_API_URL`, `TINY_IDP_API_KEY`). Missing keys cause job failures inside the worker, not at boot.
- **Retry policy:** `Q_CLUSTER.max_attempts = 2`. Jobs that *raise* are retried once; jobs that return normally (including OCR jobs that persist a classified FAILED state) are not retried.
- **Inspection:** Django admin → "Failed tasks" and "Successful tasks" (django_q models). For ad-hoc inspection: `uv run python manage.py shell` then `from django_q.models import Task; Task.objects.filter(success=False)`.
- **Tests:** `tests/conftest.py` sets `Q_CLUSTER_SYNC=1` so jobs run in-process during pytest. No real cluster needed for the test suite.
- **Jobs registered:**
  - `apps.integrations.tasks.ocr_extract_job(document_id)` — runs OCR via the existing `safe_extract_document_data` wrapper, persists `DocumentExtraction` + updates `Document.ocr_status` + tags `field_sources`. Enqueued by `apps.integrations.tasks.enqueue_ocr_job(document_id)`.
  - Retry semantics: raises `RetryableOCRError` for transient classified codes (`request_timeout`, `provider_unavailable`, `rate_limited`) so django-q2 retries once. Terminal codes (`auth_failed`, `invalid_response`, `provider_misconfigured`) persist FAILED and return — no retry.

## Coding Conventions
- **TDD first** — write failing test, then implementation, then verify.
- **Plan before coding** — multi-step work needs written plan.
- **Verify before completion** — run `uv run pytest -q && uv run ruff check . && uv run mypy .` before claiming done.
- Use `apps/<domain>/` layout; each app should eventually contain `models.py`, `services.py`, `views.py`, `urls.py`.
- Business rules live in `services.py` / `rules.py`, not views or templates.
- No sensitive PII in logs. Mask personal IDs; redact external API payloads.
- All external API calls (Invoice Ninja, OCR) run through background jobs with retry state.
- Develop directly on `main` for this project unless the user asks for a worktree. Keep commits small and verifiable so iteration on `main` stays safe.
- When a worktree is explicitly requested, create it inside the project (for example `.worktrees/`), copy the project-root `.env` in, and (if exposed via a tunnel) update `SITE_URL` and related trusted-origin settings in the worktree `.env` so CSRF-protected forms work.
- Current acceptance-test baseline uses LAN bind on `192.168.3.245:8000`.
- Ask before major structural changes or architecture changes.
- Keep context lean; read only files needed for current task.
- Keep `README.md` and project docs accurate when architecture or workflows change.

## Security Rules (PII / Documents)
- Registration identity documents stored under `PRIVATE_DOCUMENTS_ROOT` (`private-uploads/`), separate from `MEDIA_ROOT`.
- OCR-extracted document metadata (number, issuer, issuance date, expiry, etc.) is sensitive data and must be protected with same posture as underlying identity documents.
- No public file URLs for registration documents. Every preview/download passes through admin-only Django views that enforce staff authorization.
- Identity documents stored in private storage; streamed through authenticated backend views.
- No public file URLs. Every download checks application/member authorization.
- Personal IDs masked in list/search; full values only on restricted detail views.
- Magic links: single-use, short TTL, revoked after use, rate-limited.
- Document view/download/delete actions audited via `AuditEvent`.
- Secrets stored outside repo (`.env`); never committed.

## Scope Boundaries
**MVP in scope:** parent registration (Latvian), admin approval workflow, member registry, training group assignment, secure documents, OCR assist (non-blocking), Invoice Ninja billing sync, sibling discount, CSV export.

**Out of scope:** coach portal, adult members, attendance tracking, WhatsApp bot, event planning, direct FA integration.

## Skills / Workflows
- **brainstorming** — invoke before creative feature or design change.
- **writing-plans** — use when implementing multi-step work from spec.
- **test-driven-development** — required for feature and bugfix work.
- **verification-before-completion** — always run full verification before claiming done.
- **subagent-driven-development** — preferred execution mode for plan-driven work in this repo.
- **finishing-a-development-branch** — use when implementation is complete and ready for merge/PR decision.
- **uv** — always use `uv` for Python deps; never edit `pyproject.toml` manually without justification.
