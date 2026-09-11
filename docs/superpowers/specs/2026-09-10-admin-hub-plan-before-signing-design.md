# Admin Hub: Move Plan Setup to Agreement Page — Design Specification

> **Date:** 2026-09-10
> **Status:** Design review
> **Scope:** Admin Hub UI only. Django admin and Family Hub unchanged.

---

## 1. Problem

The current Admin Hub places the membership-plan selector and first-billing-month picker on the **step-6 billing page** (`/hub/pieteikumi/<pk>/maksajumi/`), while the **step-5 signing card** on the agreement page (`/hub/pieteikumi/<pk>/ligums/`) merely warns the reviewer to "go to step 6" to set the plan. This creates a confusing two-step detour: the reviewer must jump from the agreement page to the billing page, configure the plan, then return to the agreement page to sign.

The service layer already enforces the invariant: `mark_agreement_signed` raises `ValueError` when `billing_plan` is missing or `first_billing_month` is blank. The `set_billing_setup` service and the `review-action` POST endpoint are the sole writers. The signing button on the agreement page already checks `has_billing_plan` (derived from step-6's done state) and disables accordingly.

The UX fix is purely presentational: move the plan-setup form and schedule preview from the billing page into the agreement page's step-5 card, and make the billing page invoices-only.

## 2. Scope

### In scope

1. **Pipeline redefinition:** Replace the 8-step pipeline with 7 steps by merging the former "plan" (step 6) into the new "signed" (step 5). No new domain state — the pipeline is derived, never stored.
2. **Agreement page (step 5 card):** Add a plan-setup form (plan selector + month picker) and a computed installment-schedule preview. The form posts to the existing `review-action` endpoint with `action=set_billing_setup`. Signing button remains disabled until the form is saved (plan + month both present).
3. **Billing page:** Remove the plan-setup form and schedule preview. Keep invoices, push, and next-season cards intact. The existing post-signing `BillingRecord` reassignment behavior is unchanged.
4. **Pipeline URL mapping:** Step 5 now owns the agreement page; step 6 maps to invoices; step 7 to next season.
5. **Test updates:** Update existing pipeline tests for the new 7-step layout; add agreement-page tests for the plan form and schedule preview.

### Out of scope

- Django admin changes (registration application change page, billing admin).
- Family Hub changes.
- New migrations, models, or fields.
- New endpoints or service functions.
- Invoice Ninja integration changes.
- Parent-facing surfaces.
- DocuSeal integration changes.
- Email notification changes.
- Audit event changes.
- Background job changes.

## 3. Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Admin Hub — Agreement page (/hub/pieteikumi/<pk>/ligums/)
│                                                         │
│  Card 3 (step 5 — Parakstītais līgums)                  │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Plan Setup (NEW)                                   │  │
│  │ ┌───────────────────────────────────────────────┐ │  │
│  │ │ <select name="billing_plan"> ... </select>     │ │  │
│  │ │ <input type="month" name="first_billing_month">│ │  │
│  │ │ [Saglabāt plānu →]  (posts review-action)      │ │  │
│  │ └───────────────────────────────────────────────┘ │  │
│  │                                                   │  │
│  │ Schedule Preview (NEW)                            │  │
│  │ ┌───────────────────────────────────────────────┐ │  │
│  │ │ 1. Oct 2026  ·  termiņš 20.10.2026  ·  100 €  │ │  │
│  │ │ 2. Nov 2026  ·  termiņš 20.11.2026  ·  100 €  │ │  │
│  │ │ 3. Dec 2026  ·  termiņš 20.12.2026  ·  100 €  │ │  │
│  │ └───────────────────────────────────────────────┘ │  │
│  │                                                   │  │
│  │ ────────────────────────────────────────────────  │  │
│  │                                                   │  │
│  │ Signed artifact upload (existing)                 │  │
│  │                                                   │  │
│  │ [Atzīmēt kā parakstītu →] (disabled until plan)   │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  Admin Hub — Billing page (/hub/pieteikumi/<pk>/maksajumi/)
│                                                         │
│  Card 1 (step 6 — Rēķini)                               │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Invoice table (existing)                           │  │
│  │ [Apstiprināt ierakstu] [Izrakstīt rēķinus →]      │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  Card 2 (step 7 — Nākamā sezona)                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Next-season form (existing)                        │  │
│  │ [Izveidot nākamās sezonas ierakstu]               │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## 4. Pipeline Redefinition

### 4.1 Step definitions

The current 8-step tuple in `apps/admin_hub/pipeline.py` is:

```python
STEP_DEFS = (
    (1, "verify", "Datu pārbaude"),
    (2, "approve", "Apstiprināšana"),
    (3, "agreement", "Līgums"),
    (4, "handover", "Izsniegts"),
    (5, "signed", "Parakstītais"),
    (6, "plan", "Maksas plāns"),
    (7, "invoices", "Rēķini"),
    (8, "next_season", "Nākamā sezona"),
)
```

Replace with 7 steps:

```python
STEP_DEFS = (
    (1, "verify", "Datu pārbaude"),
    (2, "approve", "Apstiprināšana"),
    (3, "agreement", "Līgums"),
    (4, "handover", "Izsniegts"),
    (5, "signed", "Parakstītais"),
    (6, "invoices", "Rēķini"),
    (7, "next_season", "Nākamā sezona"),
)
```

The former "plan" key is removed entirely. Its done-condition (`has_plan`) is folded into the "signed" step's done-condition.

### 4.2 Done conditions

| Step | Key | Done condition (new) |
|------|-----|---------------------|
| 1 | verify | `application.status ∈ {APPROVED, REJECTED}` |
| 2 | approve | `application.status == APPROVED` |
| 3 | agreement | `agreement is not None` |
| 4 | handover | `agreement is not None and agreement.sent_at is not None` |
| 5 | signed | `agreement is not None and agreement.state == SIGNED` |
| 6 | invoices | `objects.invoices and all invoices have external_invoice_id` |
| 7 | next_season | `objects.next_season_record is not None` |

The former step-6 "plan" done-condition (`has_plan = billing_plan_id is not None and first_billing_month is non-blank`) is **folded into the "signed" step's done-condition**: step 5 is now done only when `agreement.state == SIGNED` (which itself requires a plan + month at the service level). The plan step no longer has its own done check.

### 4.3 Availability conditions

| Step | Key | Available condition (new) |
|------|-----|--------------------------|
| 1 | verify | `application.status ∈ {SUBMITTED, FIX_REQUESTED}` |
| 2 | approve | `application.status == SUBMITTED` |
| 3 | agreement | `objects.member is not None` |
| 4 | handover | `agreement is not None` |
| 5 | signed | `agreement is not None and agreement.state ∈ {GENERATED, SENT}` |
| 6 | invoices | `objects.billing_record is not None` |
| 7 | next_season | `objects.billing_record is not None and step-5 done` |

The critical change: step 5 is reachable whenever an agreement is generated or sent, so staff can set up billing there. Its signing action is independently disabled until `has_plan` is true, and `mark_agreement_signed` retains the server-side guard. The pipeline must not lock the page that owns the missing setup.

### 4.4 Step URL mapping

The `_step_urls` function in `views.py` maps step keys to URLs. Update the mapping:

```python
def _step_urls(application, objects):
    cockpit = reverse("admin_hub:cockpit", args=[application.pk])
    urls = {"verify": cockpit, "approve": cockpit}
    if objects.agreement is not None:
        agreement = reverse("admin_hub:agreement", args=[application.pk])
        billing = reverse("admin_hub:billing", args=[application.pk])
        # Steps 3, 4, 5 → agreement page
        for key in ("agreement", "handover", "signed"):
            urls[key] = agreement
        # Steps 6, 7 → billing page (invoices, next_season)
        for key in ("invoices", "next_season"):
            urls[key] = billing
    return urls
```

## 5. Agreement Page Changes

### 5.1 View changes (`apps/admin_hub/views.py::agreement_view`)

Add two new context variables:

```python
# Schedule preview: derive from the agreement's current plan + month.
# Returns an empty list when there is no plan yet.
schedule: list[tuple[datetime.date, Decimal]] = []
if agreement.billing_plan_id is not None and agreement.first_billing_month:
    schedule = derive_installment_schedule(
        agreement.billing_plan,
        agreement.billing_plan.annual_amount,
        first_billing_month=agreement.first_billing_month,
    )

# Active plans for the selector.
active_plans = list(
    MembershipPlan.objects.filter(is_active=True).order_by("season", "name")
)
```

Pass `schedule` and `active_plans` to the template context.

### 5.2 Template changes (`templates/admin_hub/agreement.html`)

Add a new section inside the step-5 card ("Parakstītais līgums"), **before** the artifact upload form:

```html
<section class="card">
  <div class="card__head {% if has_billing_plan %}card__head--done{% endif %}">
    <span class="card__step">{% if has_billing_plan %}&#10003;{% else %}5{% endif %}</span>
    <h2 class="anton">Maksas plāns un grafiks</h2>
    {% if has_billing_plan %}
      <span class="badge badge--sm badge--submitted" style="margin-left:auto">
        {{ agreement.billing_plan.name }} · {{ agreement.first_billing_month }}
      </span>
    {% endif %}
  </div>
  <div class="card__body stack">
    <form method="post" action="{{ review_action_url }}">
      {% csrf_token %}
      <input type="hidden" name="next" value="{{ request.path }}">
      <input type="hidden" name="action" value="set_billing_setup">
      <div class="form-grid">
        <div class="f f--full">
          <label for="billing_plan">Plāns</label>
          <select name="billing_plan" id="billing_plan">
            <option value="">— Izvēlieties plānu —</option>
            {% for plan in active_plans %}
              <option value="{{ plan.pk }}"
                      {% if agreement.billing_plan_id == plan.pk %}selected{% endif %}>
                {{ plan.name }} — {{ plan.annual_amount }} {{ plan.currency }}, {{ plan.installment_count }} daļas
              </option>
            {% endfor %}
          </select>
          <span class="f-hint">Summas tiek fiksētas ierakstā — vēlākas plāna izmaiņas neietekmē jau izveidotos rēķinus.</span>
        </div>
        <div class="f">
          <label for="first_billing_month">Pirmais rēķina mēnesis</label>
          <input type="month" name="first_billing_month" id="first_billing_month"
                 value="{{ agreement.first_billing_month }}">
          <span class="f-hint">Formāts GGGG-MM</span>
        </div>
      </div>
      <div class="row" style="margin-top:14px">
        <button type="submit" class="btn btn-primary">Saglabāt plānu →</button>
      </div>
    </form>

    {% if schedule %}
      <div>
        <div class="row" style="justify-content:space-between;margin-bottom:10px">
          <strong style="color:var(--fk-blue)">Aprēķinātais grafiks</strong>
          <span class="muted" style="font-weight:600">{{ schedule|length }} daļas</span>
        </div>
        <div class="sched">
          {% for due_date, amount in schedule %}
            <div class="schedrow">
              <span class="schedrow__seq">{{ forloop.counter }}</span>
              <span>{{ due_date|date:"F Y" }}</span>
              <span class="muted">termiņš {{ due_date|date:"d.m.Y" }}</span>
              <span class="schedrow__amt">{{ amount }} €</span>
            </div>
          {% endfor %}
        </div>
      </div>
    {% else %}
      <p class="hint">Izvēlieties plānu un pirmo mēnesi, lai redzētu grafiku.</p>
    {% endif %}
  </div>
</section>
```

This form posts to `review_action_url` (the existing Django admin review-action endpoint) with `action=set_billing_setup`, using the same two field names (`billing_plan`, `first_billing_month`) that the existing `set_billing_setup` action expects. No new endpoint is needed.

The schedule preview renders the same `schedrow` markup that was previously on the billing page, using `derive_installment_schedule` from the view.

### 5.3 Signing button gate

The existing `mark_agreement_signed` button's `disabled` condition already checks `not has_signed_artifact or not has_billing_plan`. **No change needed** — the `has_billing_plan` context variable (derived from step-5's done state in the pipeline) already gates the button. The template's `has_billing_plan` reads `_step_is_done(steps, "plan")` — this must be updated to read `_step_is_done(steps, "signed")` since the plan step no longer exists.

Change in `agreement_view`:

```python
# OLD:
"has_billing_plan": _step_is_done(steps, "plan"),

# NEW:
"has_billing_plan": agreement.billing_plan_id is not None and bool(agreement.first_billing_month),
```

Using the direct field check is safer than relying on a step key that no longer exists.

### 5.4 Actionbar sign-off button

The actionbar's sign-off button also uses `has_billing_plan`. Update to the same direct field check. The `form="mark-signed-form"` attribute still works — the form ID is unchanged.

### 5.5 Warning callout

The existing "Vispirms norādiet maksas plānu" warning callout (shown when `not has_billing_plan`) becomes redundant because the plan setup form is now inline in the same card. **Remove the warning callout.** The card itself now shows the plan selector, so the warning is self-evident when the fields are empty.

## 6. Billing Page Changes

### 6.1 Template changes (`templates/admin_hub/billing.html`)

**Remove** the entire "Maksas plāns" card (step 6) which contains:
- The plan selector form
- The schedule preview
- The "Saglabāt plānu →" submit button

**Keep** the "Rēķini" card (now step 6) and the "Nākamā sezona" card (now step 7) unchanged.

### 6.2 View changes (`apps/admin_hub/views.py::billing_view`)

Remove the schedule preview computation:

```python
# REMOVE:
schedule: list[tuple[datetime.date, Decimal]] = []
plan = record.plan if record is not None else agreement.billing_plan
first_billing_month = (
    record.first_billing_month if record is not None else agreement.first_billing_month
)
if plan is not None:
    total_amount = record.final_amount if record is not None else plan.annual_amount
    schedule = derive_installment_schedule(
        plan,
        total_amount,
        first_billing_month=first_billing_month,
    )
```

Remove `schedule` from the template context.

Remove `active_plans` from the template context (no longer needed on this page).

Remove `billing_change_url` and `billing_change_blocked_reason` from the template context (no longer needed — the plan form is gone).

### 6.3 Helper function

The `_billing_change_route` function in `views.py` can be **deleted** — it was only used to compute `billing_change_url` and `billing_change_blocked_reason` for the billing page's plan form, which is now removed.

## 7. Data Flow

```
User selects plan + month on agreement page
    │
    │ POST → review-action?next=<agreement-page>&action=set_billing_setup
    │        billing_plan=<plan_pk>&first_billing_month=YYYY-MM
    │
    ▼
Django admin review-action POST handler
    │
    │ Calls: apps.agreements.services.set_billing_setup(
    │           agreement, billing_plan, first_billing_month, actor
    │         )
    │
    ▼
set_billing_setup validates:
  - agreement not signed/superseded/discontinued
  - first_billing_month non-blank
  - plan is active
  - month parses as YYYY-MM
  - month normalizes past skip months
  - month >= cutoff-derived default
  - month year == plan season start year
  │
  │ On success:
  │   - Persists Agreement.billing_plan + first_billing_month (normalized)
  │   - Emits BILLING_PLAN_ASSIGNED audit event
  │
  ▼
Redirect back to agreement page (next param)
    │
    ▼
agreement_view re-renders with:
  - updated agreement context (plan + month now set)
  - schedule preview (derived from new plan + month)
  - has_billing_plan = True
  - signing button now enabled (if artifact also present)
```

## 8. Component Boundaries

| Component | File | Responsibility |
|-----------|------|----------------|
| Pipeline derivation | `apps/admin_hub/pipeline.py` | 7-step tuple, done/available/meta logic |
| Agreement view | `apps/admin_hub/views.py::agreement_view` | Pass `schedule`, `active_plans`, `has_billing_plan` |
| Agreement template | `templates/admin_hub/agreement.html` | Plan form, schedule preview, signing gate |
| Billing view | `apps/admin_hub/views.py::billing_view` | Remove schedule/plans/URLs from context |
| Billing template | `templates/admin_hub/billing.html` | Remove plan card |
| View helpers | `apps/admin_hub/views.py` | Remove `_billing_change_route`, update `_step_urls` |
| URL routing | `apps/admin_hub/urls.py` | No change |
| Service layer | `apps/agreements/services.py::set_billing_setup` | No change — reused as-is |
| Billing services | `apps/billing/services.py::derive_installment_schedule` | No change — reused for preview |

## 9. Error Behavior

| Error | Source | User-facing behavior |
|-------|--------|---------------------|
| Invalid month format | `set_billing_setup` → `parse_first_billing_month` | `ValueError` → Django admin `messages.error` → re-render agreement page with form fields intact |
| Inactive plan | `set_billing_setup` → `billing_plan.is_active` | Same as above |
| Month before cutoff | `set_billing_setup` → normalization check | Same as above |
| Month year ≠ plan season year | `set_billing_setup` → season-year check | Same as above |
| Agreement already signed | `set_billing_setup` → state guard | Same as above |
| No plan selected (empty form) | `set_billing_setup` → blank-month check | Same as above |

All errors flow through the existing Django admin review-action POST handler, which maps `ValueError` to a user-facing message via `messages.error()`. The message is in Latvian (the service raises Latvian strings). No new error messages are introduced.

## 10. Why Reusing `set_billing_setup` Is Safe

1. **It owns the only pre-signing write path.** The service raises `ValueError` on signed/superseded/discontinued agreements. On the agreement page, staff set the plan *before* signing, so this is the correct writer and its guard remains authoritative. Post-signing reassignment uses the separate existing `BillingRecord` route and remains outside this Hub change.

2. **The POST endpoint already accepts the same field names.** The `review-action` endpoint dispatches `action=set_billing_setup` and reads `billing_plan` and `first_billing_month` from POST. The new form on the agreement page uses exactly these field names. No new endpoint wiring is needed.

3. **Validation is idempotent.** `set_billing_setup` returns early (no audit, no write) when the new values match the existing values. Resubmitting the form with the same plan/month is a no-op.

4. **The audit trail is preserved.** Every real mutation emits a `BILLING_PLAN_ASSIGNED` audit event with old/new plan IDs, old/new months, and the scheduled installment count. Moving the form to a different page does not change the audit.

5. **No new dependencies.** The service imports `apps.billing.services` functions (`derive_first_billing_month`, `normalize_first_billing_month`, etc.) lazily inside the function body to avoid circular imports. The view's schedule preview also imports `derive_installment_schedule` lazily. No new import cycles are introduced.

## 11. Test Requirements

### 11.1 Pipeline tests (`tests/admin_hub/test_pipeline.py`)

Update existing tests for the 7-step layout:

- `test_pipeline_always_has_eight_ordered_steps` → `test_pipeline_always_has_seven_ordered_steps`: assert `len(steps) == 7`, step numbers `[1..7]`, keys `["verify", "approve", "agreement", "handover", "signed", "invoices", "next_season"]`.
- `test_submitted_application_is_on_step_one`: unchanged (step 1 is still "verify").
- `test_draft_application_has_nothing_available`: unchanged.
- `test_approved_application_completes_steps_one_and_two`: update `total == 7` assertion.
- `test_sent_agreement_completes_handover`: step 5 ("signed") is current when the agreement is sent and not yet signed, whether or not a plan has been saved.
- **New test:** `test_signed_step_without_plan_is_current_but_action_is_gated`: when agreement is SENT but `has_plan` is false, step 5 ("signed") is `current`, step 6 ("invoices") is `locked`, and the agreement page's signing action is disabled.
- **New test:** `test_signed_step_becomes_current_with_plan`: when agreement is SENT and `has_plan` is true, step 5 ("signed") is `current`.
- `test_plan_step_needs_both_plan_and_first_month`: **deleted** — the plan step no longer exists. Its logic is absorbed into step 5.
- `test_invoices_step_is_done_only_when_every_invoice_is_pushed`: update `total == 7`.
- `test_reassign_across_season_boundary_keeps_record_current`: update `total == 7`.

### 11.2 Agreement page tests (`tests/admin_hub/test_hub_agreement.py`)

- `test_agreement_page_renders_all_three_step_cards`: update — the third card is now a 2-in-1 card (plan setup + signed artifact). Assert "Maksas plāns un grafiks" and "Parakstītais līgums" (or the updated card headings).
- **New test:** `test_agreement_page_shows_plan_form`: assert `name="billing_plan"` and `name="first_billing_month"` are present in the rendered HTML.
- **New test:** `test_agreement_plan_form_posts_to_review_action`: assert the form's action is the review-action URL.
- **New test:** `test_agreement_plan_form_submits_set_billing_setup`: assert `value="set_billing_setup"` is present in the form.
- **New test:** `test_agreement_page_shows_schedule_preview_when_plan_set`: set a plan + month on the agreement, render the page, assert "Aprēķinātais grafiks" and at least one `schedrow` div.
- **New test:** `test_agreement_page_shows_schedule_hint_when_no_plan`: no plan set, assert "Izvēlieties plānu un pirmo mēnesi, lai redzētu grafiku." and assert "Aprēķinātais grafiks" is absent.
- **New test:** `test_agreement_plan_form_preselects_current_plan`: set a plan on the agreement, render the page, assert the plan's `<option>` carries `selected`.
- `test_mark_signed_is_disabled_without_a_billing_plan`: update — the plan form is now on the same page, so the test should assert the warning callout is gone and the plan selector is present instead.
- `test_mark_signed_is_disabled_with_artifact_but_no_billing_plan`: same update as above.
- `test_mark_signed_is_enabled_once_both_preconditions_are_met`: unchanged — still asserts the button is enabled when plan + artifact are present.

### 11.3 Billing page tests (`tests/admin_hub/test_hub_billing.py`)

- `test_billing_page_renders_the_three_step_cards`: update — the billing page now has **two** cards ("Rēķini" and "Nākamā sezona"), not three. Remove the "Maksas plāns" assertion.
- `test_plan_form_posts_set_billing_setup`: **deleted** — the plan form is no longer on this page.
- `test_schedule_preview_lists_the_installments`: **deleted**.
- `test_schedule_preview_hint_when_no_plan_is_selected`: **deleted**.
- `test_schedule_preview_uses_the_record_plan_and_month_once_one_exists`: **deleted**.
- `test_plan_form_posts_set_billing_setup_before_signing`: **deleted**.
- `test_plan_form_posts_reassign_once_a_record_exists`: **deleted**.
- `test_plan_change_is_blocked_with_a_reason_once_invoices_are_issued`: **deleted**.
- `test_push_endpoint_honours_next`: unchanged.
- `test_push_endpoint_refuses_an_unconfirmed_record`: unchanged.
- `test_push_endpoint_refuses_a_get_request`: unchanged.
- `test_push_endpoint_is_a_noop_for_an_already_synced_record`: unchanged.
- `test_next_season_action_is_disabled_without_a_current_record`: unchanged.
- `test_next_season_action_is_disabled_when_a_next_season_record_already_exists`: unchanged.
- `test_next_season_action_is_enabled_when_current_record_exists_and_no_next_season_record`: unchanged.
- `test_invoice_table_shows_a_created_invoice`: unchanged.

### 11.4 Integration test

- **New test:** `test_agreement_plan_setup_then_sign`: end-to-end test that sets a plan on the agreement page via POST, verifies `has_billing_plan` becomes true and the signing button is enabled, then signs the agreement and verifies a `BillingRecord` is created with the correct plan and month.

## 12. Explicit Out-of-Scope Items

1. **No new Django admin changes.** The review-action endpoint lives in Django admin; we reuse it. No new admin actions, no admin template changes.
2. **No Family Hub changes.** The Family Hub agreement and billing pages are untouched.
3. **No database migrations.** No new fields, no model changes, no migration files.
4. **No new Python dependencies.** All imports are from existing apps (`apps.agreements`, `apps.billing`).
5. **No new JavaScript.** The plan form is a plain HTML form with no JS interactions.
6. **No CSS changes.** The existing `schedrow` / `sched` CSS classes (already used on the billing page's schedule preview) are reused. No new CSS is needed.
7. **No email changes.** `set_billing_setup` does not send emails. No new email templates.
8. **No audit event changes.** `set_billing_setup` already emits `BILLING_PLAN_ASSIGNED`. No new audit actions.
9. **No background job changes.** No new tasks, no new django-q schedules.
10. **No Invoice Ninja changes.** The push flow is unchanged.
11. **No DocuSeal changes.** The signing flow is unchanged.
12. **No parent-facing changes.** `/register/`, `/portal/`, application workspace are untouched.
13. **No analytics changes.** The Hub is staff-only and not tracked.

## 13. Files Modified

| File | Change |
|------|--------|
| `apps/admin_hub/pipeline.py` | Replace `STEP_DEFS` (8 → 7 steps, remove "plan" key); update `build_pipeline` done/available conditions for "signed" step to include `has_plan`; update `meta` dict |
| `apps/admin_hub/views.py` | `agreement_view`: add `schedule` + `active_plans` context; change `has_billing_plan` to direct field check; `billing_view`: remove `schedule`/`active_plans`/`billing_change_url`/`billing_change_blocked_reason` from context; remove `_billing_change_route` function; update `_step_urls` |
| `templates/admin_hub/agreement.html` | Add plan-setup form + schedule preview section inside step-5 card; remove the "Vispirms norādiet maksas plānu" warning callout |
| `templates/admin_hub/billing.html` | Remove the "Maksas plāns" card (step 6) entirely |
| `tests/admin_hub/test_pipeline.py` | Update for 7 steps; delete plan-step tests; add signed-step-without-plan test |
| `tests/admin_hub/test_hub_agreement.py` | Add plan-form tests; update card-rendering test; update disabled-state tests |
| `tests/admin_hub/test_hub_billing.py` | Delete plan-form tests; update card-rendering test |

## 14. Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `_step_urls` mapping breaks navigation | Low | The mapping is simple string-key → URL; tests cover every key |
| Plan form posts to wrong endpoint | Low | The form uses the same `review_action_url` variable already used by all other forms on the page |
| Existing tests miss the 8→7 count | Medium | The first pipeline test asserts `len(steps) == 7` — it will fail immediately if missed |
| Billing page still renders plan fields | Medium | Deleting the card from the template + removing context vars in the view; tests assert absence |

## 15. Verification

After implementation:

1. `uv run pytest tests/admin_hub/test_pipeline.py -q` — all pipeline tests pass with 7 steps.
2. `uv run pytest tests/admin_hub/test_hub_agreement.py -q` — agreement page tests pass, including new plan-form tests.
3. `uv run pytest tests/admin_hub/test_hub_billing.py -q` — billing page tests pass with plan-form tests removed.
4. `uv run pytest -q -m "not slow"` — full fast lane passes.
5. `uv run ruff check .` — lint clean.
6. `uv run mypy .` — type check clean.
7. Manual LAN verification: open an agreement page → plan form renders → save → schedule preview appears → sign button enables → sign → redirect to billing page (invoices only, no plan form).
