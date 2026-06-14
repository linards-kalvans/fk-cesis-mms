# P7 Slice C-i — Consolidate registration review into the Django admin

*Design spec. Status: approved for planning. Date: 2026-06-14.*

## 1. Problem

Staff use **two parallel UIs**. A bespoke review flow lives outside Django admin:
`registrations.views.admin_review_queue` (a custom list of SUBMITTED applications) and
`admin_review_detail` (a custom page rendering document/OCR panels + a lightbox, the
approve/reject/request-fix actions, training-group assignment, and the full agreement module —
with **all actions at the bottom of the page**). The Django admin
`RegistrationApplicationAdmin` is a separate, read-mostly change form whose only link to the
review flow is a `review_link` column that bounces staff *out* to the custom page;
`AgreementAdmin` is read-only and also bounces out.

Consequences: review and edit are split across two screens; the queue isn't in the admin nav (you
only land there after an action); actions require opening the detail page and scrolling to the
bottom; and there is duplicate machinery (two list views, custom templates, `review.css`,
`doc_lightbox.js`) to maintain.

This slice (**C-i** of P7 Slice C) consolidates the review flow into the Django admin change view
and changelist. The broader admin polish (cross-links to billing, sync-health badges/filters,
search/filter polish, training-group de-duplication) is **C-ii**, a separate spec.

## 2. Approach (chosen)

**Custom `change_form_template` + `get_urls()` per-object action endpoints.** The admin change
page for `RegistrationApplication` renders the review panels (reusing the existing
`_doc_panel.html` / `_agreement_module.html` partials) above the native edit form, with an action
bar pinned at the **top**. Each flow action is a dedicated admin URL registered via
`ModelAdmin.get_urls()`; the view calls the **existing service unchanged**, messages the staff
user, and redirects back. The native admin edit form (member fields + preferences) remains for the
"edit" half of the single view.

Rejected: readonly-method HTML + bulk `actions` (bulk-only transitions are clumsy per-object; rich
OCR/lightbox HTML in readonly methods is messy); admin inlines for documents/agreement (form-row
oriented — the OCR readout + thumbnail lightbox need custom template rendering, so the custom
template is needed anyway).

## 3. Change-form layout

Custom `change_form_template` (e.g. `templates/admin/registrations/registrationapplication/change_form.html`)
extending `admin/change_form.html`:

```
Registration application: Jānis Ozols (SUBMITTED)
┌ ACTION BAR (top) ──────────────────────────────────────────────┐
│ status == SUBMITTED:  [Apstiprināt ▾(training-group select)]    │
│                       [Pieprasīt labojumus ▾]  [Noraidīt ▾]     │
│   reject / request-fix / void reveal an inline reason textarea  │
│ post-approval: training-group reassign + agreement module        │
└─────────────────────────────────────────────────────────────────┘
REVIEW PANELS (read-only): member + guardian data · document
  thumbnails + OCR readout + confidence chips + lightbox · review
  message history · agreement module (state, signing path, DocuSeal
  link/retry/sync, lifecycle timestamps) · training-group module
NATIVE EDIT FORM: member fields, preferences, kit sizes (fieldset-
  grouped); status / consent / review-meta stay read-only · [Save]
```

The action bar and panels render only the controls valid for the application's current state
(mirrors the existing `_agreement_module.html` conditionals). The panels are built by a reusable
helper (the current `_build_doc_panel` + OCR-summary/confidence extraction, extracted out of
`views.py` into a module the admin `change_view` imports) and passed via `extra_context`.

## 4. Action endpoints

Registered in `RegistrationApplicationAdmin.get_urls()` as named admin URLs (prefix
`registrations_registrationapplication_<action>`), each accepting the object id, POST-only, CSRF
on, `self.has_change_permission(request, obj)`-gated. Each calls the existing service and
`self.message_user(...)`, then redirects (default: back to the change page; reject → the filtered
changelist). The full set (services unchanged, all already audited at the service layer in P7
Slice A):

| Endpoint | Service | Input | Redirect |
|----------|---------|-------|----------|
| approve | `approve_application(app, user, training_group=…)` | optional group select; via confirm page (§5) | changelist |
| request_fix | `request_application_fix(app, user, msg)` | required reason | change page |
| reject | `reject_application(app, user, msg)` | required reason | changelist |
| assign_group | `assign_training_group(member, group, user)` | group select | change page |
| agreement_sent | `mark_agreement_sent(agreement, user)` | — | change page |
| agreement_signed | `mark_agreement_signed(agreement, user)` | — | change page |
| agreement_void | `void_agreement(agreement, user, reason)` | required reason | change page |
| agreement_regenerate | `regenerate_agreement(member, signing_path=…, actor=user)` | — | change page |
| agreement_set_path | `set_signing_path(agreement, path, user)` | path select | change page |
| agreement_retry_docuseal | `enqueue_create_agreement_submission(agreement.id)` | — | change page |
| agreement_sync_docuseal | `enqueue_sync_agreement_submission(agreement.id)` | — | change page |

Service `ValueError`s are caught and surfaced via `self.message_user(..., level=ERROR)` (no 500);
this replaces the custom view's 400 responses.

## 5. Approve confirmation

Approve is consequential (creates Member + Agreement + downstream billing) and not trivially
reversible. The approve endpoint shows a **lightweight intermediate confirmation page** ("Apstiprināt
pieteikumu — Jānis Ozols?" with the optional training-group select and a Cancel) before committing.
Reject / request-fix / void already gate via their required reason textarea, so they need no extra
confirm. (The documents are visible directly above the action bar on the change form.)

## 6. Changelist quick actions

`list_display` gains a status-aware quick-action column rendering the **safe next step** as a
one-click POST button:
- agreement state `generated` → "Atzīmēt nosūtītu" (→ `agreement_sent` endpoint),
- agreement state `sent` → "Atzīmēt parakstītu" (→ `agreement_signed` endpoint),
- plus always an "Atvērt →" link to the change form.

Approve/reject/void are **not** offered from the list (they live on the change form per §3/§5).
The existing `status` `list_filter` and `search_fields` stay. The post-action redirect lands on
this changelist (filtered), replacing the retired queue.

## 7. Deletions / repoints

- Delete views `admin_review_queue`, `admin_review_detail` and their helpers that no longer have a
  caller (e.g. the inline `_build_doc_panel` moves to the reusable helper module; `_require_staff`
  stays only if still used elsewhere — otherwise removed).
- Delete URL routes `registrations:admin-review-queue`, `registrations:admin-review-detail`.
- Delete templates `admin_review_queue.html`, `admin_review_detail.html`. **Keep** the panel
  partials (`_doc_panel.html`, `_agreement_module.html`) — reused by the change-form template.
- **Keep** `static/admin/css/review.css` + `static/admin/js/doc_lightbox.js`; load them on the
  admin change page via `RegistrationApplicationAdmin.Media` (or the change-form template's
  `extrastyle`/`extrahead`).
- Repoint `AgreementAdmin.get_absolute_url()` and `RegistrationApplicationAdmin.review_link` to the
  admin change URL (`admin:registrations_registrationapplication_change`). The `review_link` column
  is superseded by the "Atvērt →" quick-action link (remove or fold in).

## 8. Permissions / audit / security

- Endpoints require `has_change_permission` (staff with change rights), CSRF-protected (standard
  admin POST). Non-staff hit the admin login (admin's own gate).
- Audit: approve/reject/request-fix, training-group assignment, and agreement transitions are
  recorded at the **service layer** (P7 Slice A) and remain audited unchanged by this move.
- No new PII surface — the same data the custom page showed, now inside the staff-only admin.

## 9. Out of scope

- Cross-links application↔member↔agreement↔billing, sync-health badges/filters, search/filter
  polish, training-group de-duplication → **C-ii**.
- The parent-facing `application_workspace` (a separate, non-admin surface) is untouched.
- No changes to the review/agreement/billing **services** or state machines — this is a
  presentation/entry-point consolidation only.

## 10. Testing

- **Action endpoints:** each transitions correctly (calls the service, state changes), redirects as
  specified, is POST-only + permission-gated (non-staff/anonymous rejected), and surfaces a service
  `ValueError` as an admin message (not a 500). Approve goes through the confirm page (GET shows
  confirm; POST commits).
- **Change form:** renders the top action bar with the controls valid for the object's status, the
  document/OCR panels, and the agreement/training-group modules; the native edit form still saves
  member fields.
- **Changelist:** renders the correct status-aware quick-action button per row (generated→sent,
  sent→signed, none otherwise) + the open link; quick-action POST transitions + redirects.
- **Removal:** `reverse("registrations:admin-review-queue"/"admin-review-detail")` raises
  `NoReverseMatch`; the deleted templates are gone; `AgreementAdmin.get_absolute_url` points at the
  admin change URL.
- **Regression:** the agreement/approval/training-group service test suites pass unchanged (services
  untouched); existing parent-workspace tests unaffected.

## 11. Acceptance

1. Staff review **and** edit an application on a single screen — the Django admin change page —
   with flow actions at the **top**, not the bottom.
2. The custom review queue and detail views/templates/URLs are removed; the admin changelist is the
   entry point and post-action redirect target.
3. Approve / request-fix / reject (with reason) and the full agreement lifecycle + training-group
   assignment all work from the change page; agreement send/sign are also one-click from the
   changelist for the valid states.
4. Approve is guarded by a confirmation step; service errors surface as admin messages.
5. All transitions remain audited (service layer); endpoints are staff-permission-gated + CSRF-safe.
6. Full suite, ruff, and mypy green.
