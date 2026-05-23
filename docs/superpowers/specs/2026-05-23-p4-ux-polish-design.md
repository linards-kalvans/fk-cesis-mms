# P4 — Parent-flow UX polish + mobile-first workspace (design spec)

**Date:** 2026-05-23
**Status:** approved (brainstorming)
**Related plan:** `docs/milestones.md` §5 P4, §6 P4 acceptance
**Predecessor:** P3.5 — Async OCR UX + background-job baseline (complete 2026-05-23)
**Successor:** P5 — Approval-to-agreement flow

## Context

Parents are using the live LAN baseline (`http://192.168.3.245:8000`) and P3.5 async OCR shipped on 2026-05-22 with post-merge fixes on 2026-05-23. A polish backlog accumulated from P3.5 (spinners, chip styling, source badges, failure-message Latvianization, visibility-aware polling), and additional parent-facing UX gaps surfaced in brainstorming:

- step-gated validation with background draft auto-save
- camera capture for document uploads
- OCR success confirmation with title-cased names
- personal-data-consent gate on the ID-documents step

Approval-to-agreement work reshapes staff workflow, not parent UX, so consolidating parent polish first (a) closes the P3.5 polish loop, (b) compounds clarity for parents already using the system, and (c) gives the future staff-workflow expansion a stable parent surface to build on.

Multilingual architecture is an explicit non-priority (Section 8 of `docs/milestones.md`); the i18n work in this phase is Latvian copy normalization, not translation infrastructure.

## Renumbering impact

Inserting this phase shifts the rest of the roadmap:

| Old | New | Phase |
|-----|-----|-------|
| —   | P4  | Parent-flow UX polish + mobile-first workspace **(new, ships next)** |
| P4  | P5  | Approval-to-agreement flow |
| P5  | P6  | Billing / Invoice Ninja sync |
| P6  | P7  | Admin operations / export / audit polish |
| P7  | P8  | Calendar + WhatsApp attendance integration |

## Target outcome

### P3.5 leftover polish

- Calm branded spinner during `ocr_running` with "Apstrādājam dokumentu…" copy. Replaces the raw status text currently rendered.
- One-shot inline confirmation on `ocr_done`: "Dokumenta apstrāde pabeigta. Persona atpazīta kā <First Last>." The name is normalized (see below). Auto-dismisses after a short delay or on next user action.
- Refined OCR suggestion chip styling and source-badge visual consistency.
- Visibility-aware polling: pause polling when the tab is hidden (`document.visibilityState === 'hidden'`); resume on focus.
- Latvianized failure messages for upload, OCR, and validation errors. No English fallback (project is Latvian-only).

### Latvian copy normalization

All parent-facing templates, partials, and inline JS strings render in Latvian. Audit surfaces:

- `/register/` (guardian-email entry)
- `/register/verify/` (one-time code)
- `/portal/` (chooser / dashboard)
- `/applications/new/` (redirect target after P3.5 fix)
- `/applications/<id>/` (workspace wizard)
- Parent registration list

Admin surfaces (Django admin) stay unchanged.

### Name normalization from OCR

Names returned by tiny-IDP arrive ALL CAPS (passport/eID convention). All consumers must render Latvian title-case:

- Prefill values into the registration form
- The OCR success confirmation message
- Source-badge labels
- Admin OCR summary display

**Examples**
- `"JĀNIS BĒRZIŅŠ"` → `"Jānis Bērziņš"`
- `"BĒRZIŅŠ-KALNIŅŠ"` → `"Bērziņš-Kalniņš"` (hyphenated compound surname)
- `"VAN DER BERG"` → `"van der Berg"` (particles preserved lowercase)

**Implementation contract**
- A pure helper, unit-tested against representative Latvian + particle inputs. Python's `str.title()` is insufficient (mishandles hyphenation and apostrophes); a custom helper is required.
- Normalization happens at the OCR-result-processing layer **before** the decrypted prefill summary is persisted/consumed. The encrypted payload at rest is never rewritten; raw OCR audit posture is preserved.
- Location decided at planning time: most likely `apps/integrations/` or `apps/registrations/services/`.

### Step-gated wizard with inline validation and auto-save

**Validation gating**
- The "Turpināt" CTA on each wizard step is disabled until all required fields on that step are valid.
- Validation runs on `blur` for first-touch fields and on `change` for fields previously shown invalid (standard "validate after first miss" UX).
- Inline error messages render beneath each field. No top-of-form summary on per-field errors.

**Auto-save**
- Draft auto-saves on field change with a ~500 ms debounce, plus on `blur`, plus on step transition.
- Subtle "Saglabāts" indicator confirms persistence; placement TBD at planning time (near the wizard header is the working assumption).
- Transient save failures retry silently. A terminal failure (after retry budget) surfaces a non-blocking inline error.
- Auto-save respects existing `fix_requested` rules (status preserved) and ownership posture (verified parent only).
- The existing draft-save endpoint is reused; no new endpoint required for first slice.

### Personal data consent on step 1 (ID documents)

- Required checkbox at the top of the ID-documents step.
- Expandable inline T&C using a `<details>`/`<summary>` (or equivalent disclosure widget) collapsed by default with a "Lasīt vairāk" toggle. Content lives inline in a template partial — no separate page.
- The "Turpināt" CTA on step 1 is disabled until the checkbox is ticked AND step-1 field validation passes.
- Resume rule: if the draft was already saved with `personal_data_consent_version` matching the current version, no re-prompt on resume. Existing in-flight drafts have unset consent fields and re-consent on first resume.

**Schema change (the only one in this phase)**
- `RegistrationApplication.personal_data_consent_at: DateTimeField(null=True, blank=True)`
- `RegistrationApplication.personal_data_consent_version: CharField(max_length=32, null=True, blank=True)` — text version identifier such as `"v1-2026-05"`.
- Migration committed alongside the change.

**T&C content**
- The spec ships a default Latvian T&C draft (template partial like `apps/registrations/templates/registrations/_terms_v1.html`) covering:
  - which personal data is collected (ID document, OCR-extracted person fields, guardian/child PII)
  - how it is stored (encrypted at rest; private storage root)
  - retention and deletion posture
  - GDPR-style rights (access, correction, deletion request channel)
- The default text is **marked as pending legal review** before production cutover. Legal copy edits land at implementation time; this spec captures placement and behavior, not final wording.

**Audit**
- Consent timestamp + version are sufficient for first slice. Separate audit event rows are out of scope (general audit baseline is P7).

### Document/photo upload with camera capture

Each document/photo upload slot exposes two controls:

- **"Augšupielādēt failu"** — standard file picker (`<input type="file">` with the existing accept filter).
- **"Uzņemt attēlu"** — camera capture via `<input type="file" accept="image/*" capture="environment">`.

On devices/browsers without `capture` support, the "Uzņemt attēlu" control is hidden gracefully (feature-detected). No custom `getUserMedia` / canvas pipeline in this phase — browser-native capture only.

Captured images flow through the existing P3.5 async upload + OCR enqueue path. No changes to the upload endpoint, the `Document` model, or the OCR job.

### Mobile-first registration workspace

`/applications/<id>/` is laid out narrow-viewport-first then enhanced for desktop.

- Sticky primary CTA on mobile (bottom anchor, safe-area aware).
- Wizard steps use progressive disclosure: one step expanded at a time; prior steps collapsible/back-navigable.
- All interactive controls (wizard nav, document card actions, consent checkbox, camera/upload buttons) have touch targets ≥44 px.
- Reuses existing canonical tokens from `static/style-guide/tokens.css`; no new design system.

### Entry + chooser + portal polish

- `/register/`, `/register/verify/`, `/portal/`, and parent registration list audited at mobile breakpoints.
- Empty and error states use the shared cross-cutting primitives (see below).
- Visual cohesion with the workspace (same tokens, typography, spacing).

### Cross-cutting UX primitives

Introduced once, reused across the three parent surfaces:

- Shared empty-state partial.
- Shared error-state partial.
- Consistent spinner, toast, and inline-error patterns.

These primitives live in `apps/registrations/templates/registrations/_partials/` or equivalent location decided at planning time.

## Non-goals

- Admin redesign (admin polish stays in P7).
- Translation infrastructure / multilingual architecture (explicit non-priority).
- `getUserMedia`-based camera capture, image cropping/preview, or client-side compression.
- New business rules; no changes to `RegistrationApplication.status` flow beyond schema additions for consent.
- Audit event rows (P7).
- Mobile-first admin (P7).

## Out-of-scope assumptions

- Existing in-flight drafts are expected to re-consent on resume; this is acceptable for first slice and avoids a backfill migration.
- A consent version bump for already-approved members is **not** handled in this phase. The version field captures the version at consent time; future re-consent flows for existing approved members are deferred.
- T&C text changes are deploy-time changes (template + version identifier bump), not admin-edited content.

## Acceptance criteria

(Authoritative copy lives in `docs/milestones.md` §6 P4 acceptance. Summary here:)

1. P3.5 polish leftovers landed: spinner during `ocr_running`; success confirmation on `ocr_done`; refined chip + source-badge styling; visibility-aware polling; Latvianized failure messages.
2. Latvian copy normalized across all parent-facing surfaces; admin unchanged.
3. Name normalization from OCR: ALL CAPS → title-case at OCR-result-processing layer; handles hyphenation + particles; encrypted payload untouched; unit-tested.
4. Step-gated wizard with inline validation and auto-save: "Turpināt" disabled until step valid; blur/change validation; inline errors; 500 ms debounce + blur + step-transition auto-save; "Saglabāts" indicator; silent transient retry.
5. Personal data consent on step 1: required checkbox + expandable T&C; "Turpināt" disabled until ticked AND fields valid; `personal_data_consent_at` / `personal_data_consent_version` persisted; resume-without-re-prompt on matching version.
6. Document/photo upload with camera capture: file picker + camera capture controls per slot; HTML `capture` attribute only; graceful hide; reuses P3.5 async upload + OCR enqueue path.
7. Mobile-first registration workspace: narrow-viewport-first layout; sticky CTA; progressive disclosure; ≥44 px touch targets.
8. Entry + chooser + portal polished: mobile breakpoints fixed; empty/error states use shared primitives; visual cohesion with workspace.
9. Cross-cutting UX primitives: shared empty-state and error-state partials; consistent spinner/toast/inline-error patterns.
10. No regression on P1–P3.5 parent flows; non-blocking OCR failure path still passes; ownership/security posture unchanged.
11. Schema migration applied: two new nullable fields on `RegistrationApplication`; existing drafts default to unset.
12. Tests cover the items above (name-normalization helper, gating, auto-save behavior, consent persistence + resume, camera-capture upload, OCR confirmation rendering, visibility-aware polling, DOM-level mobile-breakpoint checks).
13. Documentation updated: `AGENTS.md` notes T&C version handling and consent fields; default T&C text marked pending legal review.

## Verification (for the P4 build, not this restructure)

- `uv run pytest` — full suite green; new tests cover acceptance §12.
- `uv run ruff check .` — green.
- `uv run mypy .` — green.
- Manual walk-through on mobile breakpoints (Playwright MCP browser at 360×640, 414×896): wizard step gating, auto-save indicator, consent gate, camera-capture control visibility, sticky CTA.
- Live OCR walk-through: upload identity document → spinner → success confirmation with normalized name → prefill applied.

## Open questions

- Final T&C copy is **pending legal review** — implementation can land the default draft; production cutover gated on legal sign-off.
- Exact placement of the "Saglabāts" indicator — resolved at planning time.
- Helper location for name normalization — resolved at planning time (`apps/integrations/` vs `apps/registrations/services/`).
