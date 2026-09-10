# Admin Hub Plan Setup Before Signing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Admin Hub membership-plan setup and its installment preview into the agreement signing step, then reduce the derived pipeline from eight steps to seven and leave the billing page invoices-only.

**Architecture:** Keep `Agreement.billing_plan` and `Agreement.first_billing_month` as the pre-signing billing intent. The Hub agreement view renders a plain POST form to the existing Django-admin `review-action` endpoint (`set_billing_setup`), then derives the preview only from saved agreement values. `mark_agreement_signed` and its existing signal remain the only path that materializes the `BillingRecord`.

**Tech Stack:** Python 3.12, Django 5+, pytest + pytest-django, server-rendered Django templates, existing Admin Hub CSS, `uv`, ruff, mypy.

**Approved design:** `docs/superpowers/specs/2026-09-10-admin-hub-plan-before-signing-design.md`

---

## Design constraints

- Scope is `apps/admin_hub` and its tests only. Do not change Django admin, Family Hub, services, models, migrations, endpoints, emails, integrations, CSS, or JavaScript.
- All user-facing copy remains Latvian. Reuse existing `sched`, `schedrow`, card, button, and callout classes.
- Keep `set_billing_setup` as sole pre-signing writer. Its existing validation, idempotency, audit event, month normalization, and `next` redirect behavior are the contract.
- Keep post-signing `BillingRecord` reassignment behavior unchanged but remove its Admin Hub entry point with the billing-page form.
- Plan setup must not lock step 5 itself: it is where staff set the missing data. Only the sign action is disabled until both persisted fields exist.
- Do not add a preview based on unsaved form fields. After each successful save redirect, render the schedule from `Agreement.billing_plan` and `Agreement.first_billing_month`.

## File map

| File | Responsibility |
|---|---|
| `apps/admin_hub/pipeline.py` | Seven-step derived pipeline, state conditions, labels, and metadata. |
| `apps/admin_hub/views.py` | Agreement-page plan choices/preview and seven-step URL routing; remove billing-page plan-preview wiring. |
| `templates/admin_hub/agreement.html` | Step-5 plan form + saved schedule preview; remove old link-to-step-6 warning. |
| `templates/admin_hub/billing.html` | Invoices/next-season only; renumber cards and remove plan-save actionbar. |
| `tests/admin_hub/test_pipeline.py` | Pure state and count regression coverage. |
| `tests/admin_hub/test_hub_agreement.py` | Agreement-page plan form, preview, action gate, and save-to-sign snapshot flow. |
| `tests/admin_hub/test_hub_billing.py` | Billing-page absence tests plus existing invoice/next-season behavior. |

---

### Task 1: Redefine the derived pipeline as seven steps

**Files:**
- Modify: `tests/admin_hub/test_pipeline.py`
- Modify: `apps/admin_hub/pipeline.py`

- [ ] **Step 1: Write failing pipeline tests**

Replace the eight-step assertions with these tests. Keep existing submitted, draft, invoice, one-current-step, and record-selection tests.

```python
def test_pipeline_always_has_seven_ordered_steps(submitted_application):
    steps = build_pipeline(load_pipeline_objects(submitted_application))

    assert len(steps) == 7
    assert [step.number for step in steps] == list(range(1, 8))
    assert [step.key for step in steps] == [
        "verify",
        "approve",
        "agreement",
        "handover",
        "signed",
        "invoices",
        "next_season",
    ]


def test_signed_step_is_current_without_a_plan(approved_application):
    from django.utils import timezone

    agreement = approved_application.approved_member.agreements.get(is_current=True)
    agreement.state = agreement.State.SENT
    agreement.sent_at = timezone.now()
    agreement.billing_plan = None
    agreement.first_billing_month = ""
    agreement.save(
        update_fields=["state", "sent_at", "billing_plan", "first_billing_month"]
    )

    states = _states(build_pipeline(load_pipeline_objects(approved_application)))
    assert states["handover"] == "done"
    assert states["signed"] == "current"
    assert states["invoices"] == "locked"


def test_signed_agreement_completes_step_five_only_with_billing_setup(
    approved_application, default_plan
):
    from django.utils import timezone

    agreement = approved_application.approved_member.agreements.get(is_current=True)
    agreement.state = agreement.State.SIGNED
    agreement.sent_at = timezone.now()
    agreement.signed_at = timezone.now()
    agreement.billing_plan = default_plan
    agreement.first_billing_month = "2026-09"
    agreement.save(
        update_fields=[
            "state", "sent_at", "signed_at", "billing_plan", "first_billing_month"
        ]
    )

    states = _states(build_pipeline(load_pipeline_objects(approved_application)))
    assert states["signed"] == "done"


def test_approved_application_uses_seven_step_total(approved_application):
    done, total = pipeline_progress(build_pipeline(load_pipeline_objects(approved_application)))
    assert done >= 2
    assert total == 7
```

Delete `test_plan_step_needs_both_plan_and_first_month`; there is no longer a separate `plan` pipeline key. Update `test_submitted_application_is_on_step_one` to expect `pipeline_progress(steps) == (0, 7)`.

- [ ] **Step 2: Run pipeline tests red**

Run:

```bash
uv run pytest -q tests/admin_hub/test_pipeline.py
```

Expected: failures because `STEP_DEFS` still contains `plan`, pipeline total remains 8, and step 6/7/8 state mapping has not shifted.

- [ ] **Step 3: Implement seven-step derivation**

In `apps/admin_hub/pipeline.py`, replace `STEP_DEFS` and remove all `plan` dictionary entries. Preserve existing `has_plan` calculation because signed-state integrity must be explicit even though `mark_agreement_signed` enforces it.

```python
STEP_DEFS: tuple[tuple[int, str, str], ...] = (
    (1, "verify", "Datu pārbaude"),
    (2, "approve", "Apstiprināšana"),
    (3, "agreement", "Līgums"),
    (4, "handover", "Izsniegts"),
    (5, "signed", "Parakstītais"),
    (6, "invoices", "Rēķini"),
    (7, "next_season", "Nākamā sezona"),
)
```

Use these `done`, `available`, and `meta` entries:

```python
done = {
    "verify": application.status in (status.APPROVED, status.REJECTED),
    "approve": application.status == status.APPROVED,
    "agreement": agreement is not None,
    "handover": agreement is not None and agreement.sent_at is not None,
    "signed": (
        agreement is not None
        and agreement.state == Agreement.State.SIGNED
        and has_plan
    ),
    "invoices": bool(objects.invoices) and len(pushed) == len(objects.invoices),
    "next_season": objects.next_season_record is not None,
}
available = {
    "verify": application.status in (status.SUBMITTED, status.FIX_REQUESTED),
    "approve": application.status == status.SUBMITTED,
    "agreement": objects.member is not None,
    "handover": agreement is not None,
    "signed": agreement is not None
    and agreement.state in (Agreement.State.GENERATED, Agreement.State.SENT),
    "invoices": objects.billing_record is not None,
    "next_season": objects.billing_record is not None and done["signed"],
}
meta = {
    "verify": "",
    "approve": _fmt_date(application.reviewed_at) if done["approve"] else "",
    "agreement": _fmt_date(getattr(agreement, "generated_at", None)),
    "handover": _fmt_date(getattr(agreement, "sent_at", None)),
    "signed": _fmt_date(getattr(agreement, "signed_at", None)),
    "invoices": (
        f"{len(pushed)}/{len(objects.invoices)} izrakstīti" if objects.invoices else ""
    ),
    "next_season": (
        objects.next_season_record.season if objects.next_season_record else ""
    ),
}
```

The `signed` availability deliberately does **not** depend on `has_plan`: plan setup is rendered on that same step. The `signed` done condition includes `has_plan` to make malformed imported data visible instead of falsely completing the stage.

- [ ] **Step 4: Run pipeline tests green**

Run:

```bash
uv run pytest -q tests/admin_hub/test_pipeline.py
```

Expected: PASS. Exactly seven ordered steps; sent agreements without plan make step 5 current; invoice and next-season gates still use existing persisted rows.

- [ ] **Step 5: Commit pipeline change**

```bash
git add apps/admin_hub/pipeline.py tests/admin_hub/test_pipeline.py
git commit -m "refactor(admin-hub): merge plan into signing step"
```

---

### Task 2: Render and save billing setup from agreement step 5

**Files:**
- Modify: `tests/admin_hub/test_hub_agreement.py`
- Modify: `apps/admin_hub/views.py`
- Modify: `templates/admin_hub/agreement.html`

- [ ] **Step 1: Write failing agreement-page tests**

Add these tests below the existing card and signing-button tests. They use exact form field names accepted by `RegistrationApplicationAdmin.review_action_view`.

```python
def test_agreement_page_shows_plan_setup_form(
    client, reviewer, application_with_agreement
):
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    ).content.decode()

    action_url = reverse(
        "admin:registrations_registrationapplication_review-action",
        args=[application_with_agreement.pk],
    )
    assert action_url in body
    assert 'name="billing_plan"' in body
    assert 'name="first_billing_month"' in body
    assert 'value="set_billing_setup"' in body


def test_agreement_page_shows_hint_without_saved_billing_setup(
    client, reviewer, application_with_agreement
):
    agreement = application_with_agreement.approved_member.agreements.get(is_current=True)
    agreement.billing_plan = None
    agreement.first_billing_month = ""
    agreement.save(update_fields=["billing_plan", "first_billing_month"])

    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    ).content.decode()

    assert "Izvēlieties plānu un pirmo mēnesi, lai redzētu grafiku." in body
    assert "Aprēķinātais grafiks" not in body
    assert "Vispirms norādiet maksas plānu" not in body


def test_agreement_page_shows_schedule_from_saved_setup(
    client, reviewer, application_with_agreement, default_plan
):
    agreement = application_with_agreement.approved_member.agreements.get(is_current=True)
    agreement.billing_plan = default_plan
    agreement.first_billing_month = "2026-09"
    agreement.save(update_fields=["billing_plan", "first_billing_month"])

    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    ).content.decode()

    assert "Aprēķinātais grafiks" in body
    assert re.search(r'<div class="schedrow">.*?</div>', body, re.DOTALL)


def test_agreement_page_preselects_saved_plan(
    client, reviewer, application_with_agreement, default_plan
):
    agreement = application_with_agreement.approved_member.agreements.get(is_current=True)
    agreement.billing_plan = default_plan
    agreement.first_billing_month = "2026-09"
    agreement.save(update_fields=["billing_plan", "first_billing_month"])

    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    ).content.decode()

    assert re.search(
        rf'<option value="{default_plan.pk}"\s+selected>', body, re.DOTALL
    )


def test_hub_plan_setup_then_sign_snapshots_selected_billing_values(
    client, reviewer, application_with_agreement, default_plan
):
    from apps.billing.models import BillingRecord

    agreement = application_with_agreement.approved_member.agreements.get(is_current=True)
    agreement.state = agreement.State.SENT
    agreement.sent_at = timezone.now()
    agreement.billing_plan = None
    agreement.first_billing_month = ""
    agreement.save(
        update_fields=["state", "sent_at", "billing_plan", "first_billing_month"]
    )

    client.force_login(reviewer)
    action_url = reverse(
        "admin:registrations_registrationapplication_review-action",
        args=[application_with_agreement.pk],
    )
    agreement_url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    response = client.post(
        action_url,
        {
            "action": "set_billing_setup",
            "billing_plan": str(default_plan.pk),
            "first_billing_month": "2026-09",
            "next": agreement_url,
        },
    )
    assert response.status_code == 302
    assert response["Location"] == agreement_url

    agreement.refresh_from_db()
    assert agreement.billing_plan_id == default_plan.pk
    assert agreement.first_billing_month == "2026-09"

    client.post(
        action_url,
        {"action": "mark_agreement_signed", "next": agreement_url},
    )
    record = BillingRecord.objects.get(member=agreement.member, season=default_plan.season)
    assert record.plan_id == default_plan.pk
    assert record.first_billing_month == "2026-09"
```

Update `test_mark_signed_is_disabled_without_a_billing_plan` to assert the inline plan form is present and the old warning callout/link is absent. Keep the discriminating uploaded-artifact-without-plan test: it must still assert the actual sign button has `disabled`.

- [ ] **Step 2: Run agreement-page tests red**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_agreement.py
```

Expected: failures because the agreement view does not yet pass active plans or a schedule and the template has no plan form or schedule markup.

- [ ] **Step 3: Add agreement-view context**

In `apps/admin_hub/views.py::agreement_view`, add lazy local imports with the existing imports in the function:

```python
import datetime
from decimal import Decimal

from apps.billing.models import MembershipPlan
from apps.billing.services import derive_installment_schedule
```

After `agreement = objects.agreement`, compute only a saved-value preview:

```python
schedule: list[tuple[datetime.date, Decimal]] = []
if agreement.billing_plan_id is not None and agreement.first_billing_month:
    schedule = derive_installment_schedule(
        agreement.billing_plan,
        agreement.billing_plan.annual_amount,
        first_billing_month=agreement.first_billing_month,
    )
has_billing_plan = (
    agreement.billing_plan_id is not None and bool(agreement.first_billing_month)
)
```

Pass these values in the existing render context:

```python
"active_plans": list(
    MembershipPlan.objects.filter(is_active=True).order_by("season", "name")
),
"schedule": schedule,
"has_billing_plan": has_billing_plan,
```

Remove the existing `"has_billing_plan": _step_is_done(steps, "plan")` entry. Do not add a new service or a Hub POST view.

In `_step_urls`, remove `plan` from the billing-page mapping so the final block is:

```python
for key in ("invoices", "next_season"):
    urls[key] = billing
```

- [ ] **Step 4: Move plan form and preview into step-5 template card**

In `templates/admin_hub/agreement.html`, keep the existing step-5 `<section class="card">` and its `Parakstītais līgums` heading. At the start of that card's existing `<div class="card__body stack">`, before signed-artifact upload, insert this plan-setup subsection. Keep the existing `{% url ... as review_action_url %}` declaration at line 8.

```html
          <div class="stack">
            <div>
              <div class="row" style="justify-content:space-between;margin-bottom:10px">
                <strong style="color:var(--fk-blue)">Maksas plāns un grafiks</strong>
                {% if has_billing_plan %}
                  <span class="badge badge--sm badge--submitted">
                    {{ agreement.billing_plan.name }} · {{ agreement.first_billing_month }}
                  </span>
                {% endif %}
              </div>
            </div>
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
                        <option value="{{ plan.pk }}" {% if agreement.billing_plan_id == plan.pk %}selected{% endif %}>
                          {{ plan.name }} — {{ plan.annual_amount }} {{ plan.currency }}, {{ plan.installment_count }} daļas
                        </option>
                      {% endfor %}
                    </select>
                  </div>
                  <div class="f">
                    <label for="first_billing_month">Pirmais rēķina mēnesis</label>
                    <input type="month" name="first_billing_month" id="first_billing_month" value="{{ agreement.first_billing_month }}">
                    <span class="f-hint">Formāts GGGG-MM</span>
                  </div>
                </div>
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
              <div class="row" style="margin-top:14px">
                <button type="submit" class="btn btn-primary">Saglabāt plānu →</button>
              </div>
            </form>
          </div>
```

Keep the existing signed-artifact upload form after this subsection, inside the same step-5 card. Update that card foot hint to `Solis 5 no 7`. Replace its `has_billing_plan` callout with the positive statement below and remove the negative warning/link entirely:

```html
          {% if has_billing_plan %}
            <div class="callout">
              <span class="callout__icon">i</span>
              <span>Atzīmējot kā parakstītu, tiek izveidots šīs sezonas maksājumu ieraksts pēc augstāk norādītā plāna.</span>
            </div>
          {% endif %}
```

Keep both in-card and actionbar `disabled` conditions exactly as:

```django
{% if not has_signed_artifact or not has_billing_plan %}disabled{% endif %}
```

Change the actionbar navigation label from `Maksas plāns →` to `Rēķini →`. Keep the existing post-sign redirect to the billing page, which is now step 6.

- [ ] **Step 5: Run agreement-page tests green**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_agreement.py
```

Expected: PASS. The form posts to existing endpoint, saved values render a preview, missing plan disables sign without hiding step 5, and selected values become the signed record snapshot.

- [ ] **Step 6: Commit agreement-page change**

```bash
git add apps/admin_hub/views.py templates/admin_hub/agreement.html tests/admin_hub/test_hub_agreement.py
git commit -m "feat(admin-hub): set billing plan before signing"
```

---

### Task 3: Make billing page invoices-only

**Files:**
- Modify: `tests/admin_hub/test_hub_billing.py`
- Modify: `apps/admin_hub/views.py`
- Modify: `templates/admin_hub/billing.html`

- [ ] **Step 1: Replace plan-card tests with invoices-only tests**

Replace `test_billing_page_renders_the_three_step_cards` and all `plan_form_*`, `schedule_preview_*`, and `plan_change_is_blocked_*` tests with the following. Keep all invoice push and next-season tests unchanged.

```python
def test_billing_page_renders_invoices_and_next_season_only(
    client, reviewer, signed_application
):
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()

    assert "Rēķini" in body
    assert "Nākamā sezona" in body
    assert 'value="set_billing_setup"' not in body
    assert 'id="plan-form"' not in body
    assert "Aprēķinātais grafiks" not in body


def test_billing_page_renumbers_invoices_and_next_season(
    client, reviewer, signed_application
):
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()

    assert '<span class="card__step">6</span>\n          <h2 class="anton">Rēķini</h2>' in body
    assert '<span class="card__step">7</span>\n          <h2 class="anton">Nākamā sezona</h2>' in body
    assert "Solis 7 no 7" in body
```

Remove now-unused `re` import if no retained test uses it. Remove helper functions `_plan_form_action` and `_plan_form_submit_button_tag`; no remaining test needs them.

- [ ] **Step 2: Run billing-page tests red**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_billing.py
```

Expected: failures because the billing template still renders plan form/schedule and labels invoices/next-season as 7/8.

- [ ] **Step 3: Remove obsolete billing view wiring**

In `apps/admin_hub/views.py`:

1. Delete `_billing_change_route` completely.
2. Delete now-unused `datetime`, `Decimal`, and `derive_installment_schedule` imports from `billing_view`. Retain `MembershipPlan` because step 7 still needs active plans.
3. Remove the `billing_change_url, billing_change_blocked_reason = ...` assignment.
4. Remove the full `schedule`, `plan`, `first_billing_month`, and `derive_installment_schedule` block.
5. Remove these render-context keys:

```python
"billing_change_url": billing_change_url,
"billing_change_blocked_reason": billing_change_blocked_reason,
"schedule": schedule,
"active_plans": list(
    MembershipPlan.objects.filter(is_active=True).order_by("season", "name")
),
```

The next-season selector still needs active plans. Retain it under a narrowly named context key:

```python
"next_season_active_plans": list(
    MembershipPlan.objects.filter(is_active=True).order_by("season", "name")
),
```

Keep the `MembershipPlan` import solely for this next-season list. In the template, use `next_season_active_plans` only in the next-season selector.

- [ ] **Step 4: Remove billing plan card and update billing template**

In `templates/admin_hub/billing.html`:

1. Remove `{% url 'admin:registrations_registrationapplication_review-action' ... as review_action_url %}` only if it is reintroduced directly for the next-season form. Keep it because step 7 still posts `create_next_season_billing` to that endpoint.
2. Delete the entire first `<section class="card">` containing `id="plan-form"`, plan selector, schedule, and `set_billing_setup` submit.
3. Change invoice card step from `7` to `6`.
4. Change next-season card step from `8` to `7`, its foot from `Solis 8 no 8` to `Solis 7 no 7`, and its plan loop from `active_plans` to `next_season_active_plans`.
5. Delete the actionbar comment and button that submit `form="plan-form"`. Leave the back link and add no replacement action button.

The invoice table, confirm/push forms, next-season form, summary sidecar, and their permission/disabled conditions must remain byte-for-byte unchanged except for the plan-loop context rename and visible step numbers.

- [ ] **Step 5: Run billing-page tests green**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_billing.py
```

Expected: PASS. Billing page has only invoice and next-season cards; no plan writer or schedule remains; invoice push and next-season gates remain covered.

- [ ] **Step 6: Run Hub regression suite**

Run:

```bash
uv run pytest -q tests/admin_hub
```

Expected: PASS. This catches changed step totals and rail navigation in queue/cockpit pages as well as the three changed units.

- [ ] **Step 7: Commit invoices-only billing page**

```bash
git add apps/admin_hub/views.py templates/admin_hub/billing.html tests/admin_hub/test_hub_billing.py
git commit -m "feat(admin-hub): make billing page invoices only"
```

---

### Task 4: Full verification and documentation status

**Files:**
- Modify: `docs/milestones.md` only if its Admin Hub summary says “8-step” or says the billing page owns plan setup. Otherwise no documentation edit.

- [ ] **Step 1: Check milestone wording before editing**

Run:

```bash
rg -n "8-step|Maksas plāns un rēķini|plan setup|billing plan" docs/milestones.md
```

Expected: inspect only current Admin Hub summary. Do not edit unrelated milestone records.

- [ ] **Step 2: Update milestone only when wording is stale**

If the Admin Hub summary explicitly states the old eight-step/step-6-plan arrangement, replace only that sentence with:

```markdown
- **Maksas plāns un rēķini** (`/hub/pieteikumi/<pk>/maksajumi/`) — step 6 invoices and step 7 next-season billing. Current agreement plan and first billing month are selected in signing step 5 before the BillingRecord is created.
```

If no stale wording exists, make no milestone change.

- [ ] **Step 3: Run full required verification**

Run sequentially:

```bash
uv run pytest -q && uv run ruff check . && uv run mypy . && uv run python manage.py makemigrations --check
```

Expected: every command exits 0. `makemigrations --check` reports no changes because this work changes presentation and derived state only.

- [ ] **Step 4: Manual LAN acceptance**

On `http://192.168.3.245:8000/hub/`, use an approved application and verify:

1. Agreement page shows step 5 plan/month form with default selection.
2. Saving valid setup returns to agreement page and shows normalized saved month plus schedule rows.
3. Without plan or month, “Atzīmēt kā parakstītu” remains disabled even after artifact upload.
4. With saved plan/month and artifact, signing succeeds and opens billing page.
5. Billing page shows invoices as step 6 and next season as step 7; it has no plan form or schedule.
6. New `BillingRecord` has the selected plan and first billing month.

- [ ] **Step 5: Commit documentation only if changed**

If `docs/milestones.md` changed:

```bash
git add docs/milestones.md
```

If it did not change, do not create an empty commit.
