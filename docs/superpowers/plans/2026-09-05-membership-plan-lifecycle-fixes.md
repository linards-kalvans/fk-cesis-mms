# Membership Plan Lifecycle Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make membership-plan defaults replaceable, keep integration product IDs staff-hidden, and safely create or recreate individual billing records from signed applications.

**Architecture:** `MembershipPlan` owns default handover so every writer gets the same invariant. The registrations admin reuses the existing review-action endpoint and the billing service owns record creation and its audit event. A signed agreement is immutable billing history; renewal adds a record for a distinct season under that agreement.

**Tech Stack:** Python 3.12, Django 5/6, PostgreSQL/SQLite, pytest-django, Django admin, pytest, ruff, mypy.

**Status:** DEV complete. All tasks implemented and verified.

---

### Task 1: Default-plan handover and product-ID admin contract

**Files:**
- Modify: `apps/billing/models.py: MembershipPlan.clean and MembershipPlan.save`
- Modify: `apps/billing/admin.py: MembershipPlanAdmin`
- Test: `tests/billing/test_membership_plan.py`
- Create: `tests/billing/test_membership_plan_admin.py`

- [x] **Step 1: Write failing model tests**

```python
def test_saving_new_default_clears_previous_default():
    old = MembershipPlan.objects.create(name="2026", season="2026/2027", is_active=True, is_default=True)
    new = MembershipPlan.objects.create(name="2027", season="2027/2028", is_active=True, is_default=True)

    old.refresh_from_db()
    assert old.is_default is False
    assert new.is_default is True


def test_inactive_plan_cannot_be_default():
    plan = MembershipPlan(name="Inactive", season="2027/2028", is_active=False, is_default=True)
    with pytest.raises(ValidationError, match="Noklusējuma plānam"):
        plan.full_clean()
```

- [x] **Step 2: Run model tests red**

Run: `uv run pytest -q tests/billing/test_membership_plan.py`

Expected: default replacement test fails because `clean()` reports an existing default.

- [x] **Step 3: Write failing admin tests**

```python
def test_membership_plan_change_form_hides_external_product_id(staff_client, plan):
    response = staff_client.get(reverse("admin:billing_membershipplan_change", args=[plan.pk]))
    assert response.status_code == 200
    assert 'name="external_product_id"' not in response.content.decode()
    assert "External product id" not in response.content.decode()
```

- [x] **Step 4: Run admin test red**

Run: `uv run pytest -q tests/billing/test_membership_plan_admin.py`

Expected: FAIL because Django admin currently renders every model field.

- [x] **Step 5: Implement minimal model and admin behavior**

```python
class MembershipPlan(TimeStampedModel):
    def clean(self) -> None:
        super().clean()
        if self.is_default and not self.is_active:
            raise ValidationError({"is_default": "Noklusējuma plānam jābūt aktīvam."})

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.is_default:
            MembershipPlan.objects.filter(is_default=True).exclude(pk=self.pk).update(
                is_default=False
            )
        return super().save(*args, **kwargs)


@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    exclude = ("external_product_id",)
```

Import `transaction` from `django.db`. Keep the existing database constraints.

- [x] **Step 6: Run focused tests green**

Run: `uv run pytest -q tests/billing/test_membership_plan.py tests/billing/test_membership_plan_admin.py`

Expected: PASS.

### Task 2: Safe billing-record creation services and audit choice

**Files:**
- Modify: `apps/billing/services.py: create/recreate helpers`
- Modify: `apps/core/models.py: AuditEvent.Action`
- Create: `apps/core/migrations/0010_alter_auditevent_action.py`
- Create: `tests/billing/test_billing_record_recreation.py`
- Modify: `tests/billing/test_plan_lifecycle_services.py`

- [x] **Step 1: Write failing service tests**

```python
def test_recreate_requires_explicit_external_invoice_confirmation(signed_agreement):
    with pytest.raises(ValueError, match="confirmation"):
        recreate_missing_billing_record(
            signed_agreement.member,
            signed_agreement,
            external_invoice_confirmed_absent=False,
            actor=None,
        )


def test_recreate_creates_missing_current_season_record_and_audits(signed_agreement, staff_user):
    record = recreate_missing_billing_record(
        signed_agreement.member,
        signed_agreement,
        external_invoice_confirmed_absent=True,
        actor=staff_user,
    )
    assert record.plan_id == signed_agreement.billing_plan_id
    assert record.season == signed_agreement.billing_plan.season
    assert AuditEvent.objects.filter(
        action=AuditEvent.Action.BILLING_RECORD_RECREATED,
        target_id=str(record.pk),
    ).exists()


def test_recreate_refuses_when_current_season_record_exists(signed_agreement):
    create_draft_billing_for_member(signed_agreement.member, signed_agreement)
    with pytest.raises(ValueError, match="already exists"):
        recreate_missing_billing_record(
            signed_agreement.member,
            signed_agreement,
            external_invoice_confirmed_absent=True,
            actor=None,
        )
```

- [x] **Step 2: Run recreation tests red**

Run: `uv run pytest -q tests/billing/test_billing_record_recreation.py`

Expected: FAIL because `recreate_missing_billing_record` and the audit choice do not exist.

- [x] **Step 3: Add audit choice and migration**

```python
class AuditEvent(TimeStampedModel):
    class Action(models.TextChoices):
        BILLING_RECORD_RECREATED = (
            "billing_record_recreated", "Billing record recreated"
        )
```

Run `uv run python manage.py makemigrations core --name alter_auditevent_action` and verify it depends on `core.0009_alter_auditevent_action`.

- [x] **Step 4: Implement safe recreate service**

```python
def recreate_missing_billing_record(
    member,
    agreement,
    *,
    external_invoice_confirmed_absent: bool,
    actor=None,
):
    if not external_invoice_confirmed_absent:
        raise ValueError("external invoice confirmation required")
    if agreement.state != Agreement.State.SIGNED or agreement.member_id != member.pk:
        raise ValueError("signed agreement required")
    if agreement.billing_plan_id is None:
        raise ValueError("billing plan required")
    if BillingRecord.objects.filter(member=member, season=agreement.billing_plan.season).exists():
        raise ValueError("billing record already exists for season")

    record = create_draft_billing_for_member(member, agreement)
    record_audit_event(
        action=str(AuditEvent.Action.BILLING_RECORD_RECREATED),
        actor=actor,
        target=record,
        metadata={"plan_id": agreement.billing_plan_id, "season": record.season},
    )
    return record
```

Use a transaction and existing guardian-lock creation path. If a concurrent
creation returns an existing row, do not emit the recreate event; raise the
same duplicate error instead. Do not call Invoice Ninja.

- [x] **Step 5: Extend renewal service tests**

```python
def test_renewal_uses_existing_signed_agreement_without_mutating_it(
    signed_agreement, next_season_plan, staff_user
):
    original_plan_id = signed_agreement.billing_plan_id
    record = renew_member_billing(
        signed_agreement.member, next_season_plan,
        first_billing_month="2027-09", actor=staff_user,
    )
    signed_agreement.refresh_from_db()
    assert record.agreement_id == signed_agreement.pk
    assert signed_agreement.billing_plan_id == original_plan_id
```

- [x] **Step 6: Run focused service tests green**

Run: `uv run pytest -q tests/billing/test_billing_record_recreation.py tests/billing/test_plan_lifecycle_services.py`

Expected: PASS.

### Task 3: Individual signed-application renewal and recreate controls

**Files:**
- Modify: `apps/registrations/admin_panels.py: build_review_context`
- Modify: `apps/registrations/admin.py: RegistrationApplicationAdmin.review_action_view`
- Modify: `templates/registrations/admin/_agreement_module.html`
- Modify: `tests/registrations/test_admin_agreement_billing_setup.py`
- Create: `tests/registrations/test_admin_signed_billing_actions.py`

- [x] **Step 1: Write failing signed-application action tests**

```python
def test_signed_application_creates_next_season_draft(
    staff_client, signed_application, next_season_plan
):
    response = staff_client.post(review_action_url(signed_application), {
        "action": "create_next_season_billing",
        "billing_plan": next_season_plan.pk,
        "first_billing_month": "2027-09",
    })
    assert response.status_code == 302
    record = BillingRecord.objects.get(
        member=signed_application.approved_member, season=next_season_plan.season
    )
    assert record.agreement_id == signed_application.approved_member.agreements.get(is_current=True).pk


def test_signed_application_recreate_requires_checkbox(staff_client, signed_application):
    response = staff_client.post(
        review_action_url(signed_application), {"action": "recreate_current_billing"}, follow=True
    )
    assert "Invoice Ninja" in response.content.decode()
    assert BillingRecord.objects.count() == 0
```

- [x] **Step 2: Run signed-application tests red**

Run: `uv run pytest -q tests/registrations/test_admin_signed_billing_actions.py`

Expected: FAIL because neither action exists.

- [x] **Step 3: Add review context and template controls**

Add `next_season_membership_plans` to `build_review_context`: active plans
whose `season` differs from the current agreement plan. Add
`current_season_billing_missing`: true only for a signed agreement with a
billing plan and no member record for that plan season.

Render these signed-only forms in `_agreement_module.html`:

```django
<form method="post" action="{{ review_action_url }}">
  {% csrf_token %}
  <select name="billing_plan" required>{% for plan in next_season_membership_plans %}...{% endfor %}</select>
  <input type="month" name="first_billing_month" required>
  <button name="action" value="create_next_season_billing">Izveidot nākamās sezonas norēķinus</button>
</form>

{% if current_season_billing_missing %}
<details><summary>Atjaunot trūkstošu norēķinu ierakstu</summary>
  <form method="post" action="{{ review_action_url }}">
    {% csrf_token %}
    <label><input type="checkbox" name="external_invoice_confirmed_absent" required> Es apstiprinu, ka Invoice Ninja nav atbilstoša rēķina.</label>
    <button name="action" value="recreate_current_billing">Atjaunot ierakstu</button>
  </form>
</details>
{% endif %}
```

- [x] **Step 4: Add server-side POST guards**

In `review_action_view`, add `create_next_season_billing` and
`recreate_current_billing` branches before the generic unrecognized action
path. Both must require an approved member and current signed agreement.

For renewal: resolve an active posted plan, reject the current agreement plan
season, require and parse `YYYY-MM`, call `renew_member_billing`, and show
Latvian success/error messages. A returned `None` becomes an already-existing
season message, not a duplicate write.

For recreate: map the checkbox to a boolean, call
`recreate_missing_billing_record`, and map service `ValueError` values to
Latvian messages. Redirect to the application change page in every case.

- [x] **Step 5: Add UI and guard tests**

Test that signed pages render only distinct-season active plans; missing
current record renders the confirmation control; unsigned and discontinued
members do not receive controls; invalid/inactive/current-season plan posts do
not write; a duplicate post leaves exactly one record; successful recreate
emits its audit event.

- [x] **Step 6: Run registrations tests green**

Run: `uv run pytest -q tests/registrations/test_admin_agreement_billing_setup.py tests/registrations/test_admin_signed_billing_actions.py`

Expected: PASS.

### Task 4: Disable deletion and complete verification

**Files:**
- Modify: `apps/billing/admin.py: BillingRecordAdmin.has_delete_permission`
- Modify: `tests/billing/test_billing_admin.py`
- Modify: `docs/milestones.md`

- [x] **Step 1: Write failing deletion-permission test**

```python
def test_billing_record_admin_denies_delete_permission(rf, staff_user, billing_record):
    request = rf.get("/")
    request.user = staff_user
    assert BillingRecordAdmin(BillingRecord, admin.site).has_delete_permission(
        request, billing_record
    ) is False
```

- [x] **Step 2: Run deletion test red**

Run: `uv run pytest -q tests/billing/test_billing_admin.py`

Expected: FAIL because `BillingRecordAdmin` inherits Django's delete permission.

- [x] **Step 3: Implement deletion denial**

```python
class BillingRecordAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False
```

This removes object deletion and the changelist bulk-delete action. Do not
delete or alter any existing records in this feature.

- [x] **Step 4: Update milestone status**

Add a concise delivered entry under `docs/milestones.md` recording default
handover, hidden Invoice Ninja product IDs, individual signed-agreement
next-season records, and deletion/recreate safety. State bulk renewal remains
out of scope.

- [x] **Step 5: Run focused test set**

Run: `uv run pytest -q tests/billing/test_membership_plan.py tests/billing/test_membership_plan_admin.py tests/billing/test_billing_record_recreation.py tests/billing/test_billing_admin.py tests/registrations/test_admin_agreement_billing_setup.py tests/registrations/test_admin_signed_billing_actions.py`

Expected: PASS.

- [x] **Step 6: Run full repository verification**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy . && uv run python manage.py makemigrations --check`

Expected: all commands exit 0.
