# P7 Slice C-ii (batch 1) — Admin quick wins

*Design spec. Status: approved for planning. Date: 2026-06-14.*

## 1. Problem / scope

Three user-prioritised admin flow-polish items (the first batch of P7 Slice C-ii):

1. The **Registrations** app sits low in the admin left-side menu (Django orders apps
   alphabetically); staff want it at the **top** — it's the most-used surface.
2. The applications changelist shows status but **not the agreement status**, so staff can't see
   at a glance where each approved application's agreement stands without opening it.
3. Confirming a billing record is a three-step dance (open → change the `status` dropdown → save).
   Staff want **one-click confirm**: a button near the top of the BillingRecord change page and
   directly from the billing-records list.

Builds on C-i (admin is the registration review surface). The remaining, broader C-ii items
(cross-links application↔member↔agreement↔billing, sync-health badges/filters, search/filter
polish, document active-vs-replaced UX, training-group de-duplication) are a **later batch** — out
of scope here.

No model changes, no migrations. Services/state machines unchanged.

## 2. Item 1 — Registrations app to the top of the admin menu

Swap the default admin site for a thin custom `AdminSite` using Django's `AdminConfig.default_site`
mechanism (no model re-registration needed):

- `apps/core/admin_site.py`: `class FkAdminSite(admin.AdminSite)` overriding `get_app_list(request, app_label=None)`
  — call `super().get_app_list(...)`, then reorder so the app with `app_label == "registrations"`
  is first; the rest keep Django's default (alphabetical) order.
- `apps/core/apps.py`: add `class FkAdminConfig(admin.apps.AdminConfig): default_site = "apps.core.admin_site.FkAdminSite"`.
- `fk_cesis_mms/settings.py`: replace `"django.contrib.admin"` in `INSTALLED_APPS` with
  `"apps.core.apps.FkAdminConfig"`.

This affects the admin index page and the nav sidebar (both consume `get_app_list`). All existing
`@admin.register(...)` registrations continue to work unchanged (they register against the default
site, which the config swaps).

## 3. Item 2 — Agreement status column on the applications changelist

Add an `agreement_status` display method to `RegistrationApplicationAdmin.list_display` (placed
before `quick_actions`):

- For an application with an `approved_member`: return `agreement_status_copy(get_current_agreement(obj.approved_member))`
  (the existing Latvian copy helper in `apps/agreements/presentation.py`; returns `None` when there
  is no agreement → render "—").
- Otherwise: "—".
- `short_description = "Līguma statuss"`.

Reuses the per-row agreement lookup `quick_actions` already performs; `get_queryset` already
`select_related("approved_member")`. The per-row `get_current_agreement` query is acceptable for the
modest review queue (consistent with the C-i note).

## 4. Item 3 — One-click billing-record confirm

`BillingRecordAdmin` (`apps/billing/admin.py`):

- **Confirm endpoint** via `get_urls()`: `confirm/<int:object_id>/`, registered name
  `billing_billingrecord_confirm`, wrapped by `self.admin_site.admin_view`. POST-only,
  `has_change_permission`-gated, CSRF on. If the record's `status == DRAFT` → set
  `status = CONFIRMED`, save (`update_fields=["status", "updated_at"]`), `message_user` success;
  if already CONFIRMED → `message_user` info (no-op). Redirect back to the referring page (change
  page when confirmed from the change form; changelist when confirmed from the list — use the
  request's `next`/referer, defaulting to the change page).
- **Top button on the change page**: a `change_form_template`
  (`templates/admin/billing/billingrecord/change_form.html`, extending `admin/change_form.html`)
  with a top action bar that renders an **"Apstiprināt"** POST button (to the confirm endpoint,
  `{% csrf_token %}`) **only when** the record is DRAFT. The existing `status` dropdown + save stays
  as a fallback.
- **Per-row button on the changelist**: a `confirm_action` `list_display` method that, for a DRAFT
  row, renders a one-click **"Apstiprināt"** POST form to the confirm endpoint (CSRF token minted
  from the request via the `get_token(self._request)` + `get_queryset` request-storage pattern
  established in the registrations `quick_actions`); for a CONFIRMED row renders "✓ Apstiprināts".
  `short_description = "Apstiprināt"`. Add `confirm_action` to `list_display`.

One-click (no intermediate confirmation page) per the "single button" requirement; confirm is
low-risk and reversible (the status dropdown can still move it back). The redirect honors where the
action was triggered so list-confirm returns to the list and change-page-confirm returns to the
record.

**Audit:** confirming is not added to the `AuditEvent` catalog in this batch (would need a new
choices value + migration like `DATA_EXPORTED`); flagged for a later addition if staff confirms
should be audited.

## 5. Testing

- **Item 1:** `FkAdminSite.get_app_list` returns the registrations app first (assert the first
  entry's `app_label == "registrations"` given a request); a logged-in staff GET of `/admin/`
  renders with Registrations ahead of the other apps. Confirm all models are still registered
  (e.g. the `BillingRecord` / `Member` / `AuditEvent` changelists still reverse + 200).
- **Item 2:** the applications changelist shows the agreement status copy for an approved
  application with an agreement, and "—" for a draft/no-agreement application.
- **Item 3:** the confirm endpoint flips DRAFT→CONFIRMED (POST), is a no-op + message when already
  CONFIRMED, is POST-only + permission-gated (anonymous/ view-only-staff rejected); the change page
  shows the "Apstiprināt" button only for DRAFT; the changelist renders a real one-click POST
  confirm form (with CSRF token + the confirm endpoint URL) for DRAFT rows and "✓ Apstiprināts" for
  CONFIRMED rows; a list-confirm POST flips the status.

## 6. Acceptance

1. The Registrations app appears at the top of the admin left-side menu/index; all other admin
   models remain registered and reachable.
2. The applications changelist shows an "Līguma statuss" column reflecting each approved
   application's current agreement state.
3. A DRAFT billing record can be confirmed in one click — from a button near the top of its change
   page and from a per-row button on the billing-records list — landing back where the action was
   triggered; the old dropdown+save path still works.
4. The confirm endpoint is staff-permission-gated, CSRF-safe, and a no-op when already confirmed.
5. Full suite, ruff, and mypy green; no migrations.
