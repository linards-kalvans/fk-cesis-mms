# Admin Hub Flow Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove approval's redundant Hub handoff, preview pending invoice installments, and make Hub invoice push confirm-and-queue in one deliberate POST.

**Architecture:** The cockpit submits approval with the already-known agreement Hub URL as its safe `next` destination. The billing view derives non-persistent preview rows from a `BillingRecord` using the exact schedule semantics of invoice materialization, while the template keeps preview separate from persisted `BillingInvoice` rows. The existing Django-admin `BillingRecordAdmin.push_view` receives one explicit `confirm_and_push` POST flag; it confirms a draft under a database transaction, audits that transition, and then follows the existing enqueue and push-audit path. Ordinary direct push requests retain their confirmed-only guard.

**Tech Stack:** Python 3.12, Django 5, PostgreSQL-compatible transactions, pytest + pytest-django, server-rendered templates, `uv`, ruff, mypy.

**Approved design:** `docs/superpowers/specs/2026-09-10-admin-hub-flow-improvements-design.md`

---

## Design decisions

1. **Approval redirects to agreement with a local `next` URL, not a new Hub endpoint.** `RegistrationApplicationAdmin.approve_view` already validates `next`, creates the agreement inside the approval service, and redirects. Giving both the query string and hidden form field the agreement URL removes UI-only dead step without changing domain behavior.
2. **Preview is derived, not persisted.** The preview exists before the worker materializes `BillingInvoice` rows. Creating rows merely to preview would falsely imply invoices exist and could interfere with the worker's idempotency contract.
3. **Preview mirrors materialization semantics.** It must respect `scheduled_installment_count`, `first_billing_month`, and upfront payment mode. A zero-value record previews no invoice rows, matching `materialize_installments`.
4. **One-click behavior is opt-in.** `confirm_and_push=1` is accepted only by the existing protected `push_view`. Direct requests without it still refuse draft records, preserving admin safeguard and expected security contract.
5. **Confirmation precedes enqueue under `transaction.atomic()`.** Worker can never observe a still-draft record from this route. Both `BILLING_RECORD_CONFIRMED` and `BILLING_PUSH_TRIGGERED` audit events remain explicit and separately queryable.

## File map

| File | Change |
|---|---|
| `apps/admin_hub/views.py` | Add a read-only invoice-preview builder; pass rows to billing template; expose agreement redirect target to cockpit. |
| `templates/admin_hub/cockpit.html` | Send approval directly to agreement page through existing safe `next` handling; remove post-approval continuation CTA. |
| `templates/admin_hub/billing.html` | Render clearly labelled preview table before materialized invoices; replace draft confirmation + disabled push with one flagged push form. |
| `apps/billing/admin.py` | Extend `push_view` for explicit flag, atomic draft confirmation, and existing audits/enqueue path. |
| `tests/admin_hub/test_hub_cockpit.py` | Assert approval next destination and no redundant continuation CTA. |
| `tests/admin_hub/test_hub_billing.py` | Assert preview display/absence and Hub form flag. |
| `tests/billing/test_admin_confirm_audit.py` | Assert draft one-click push confirms/audits/enqueues while ordinary draft push still refuses. |

## Test strategy

- **Framework:** existing pytest + pytest-django admin-view test convention.
- **Test:** rendered HTML contracts using exact form/button extraction; safe redirect and auth behavior through Django test client; mocked enqueue for request-time behavior; database audit/state assertions.
- **Do not test:** Invoice Ninja provider HTTP or worker materialization internals; they are unchanged and covered by existing integration/task suites.
- **Red phase:** run each target test function before implementation. It must fail because old redirect, missing preview/flag, or draft refusal remains.

### Task 1: Redirect Hub approval directly to agreement

**Files:**
- Modify: `tests/admin_hub/test_hub_cockpit.py`
- Modify: `apps/admin_hub/views.py:cockpit_view`
- Modify: `templates/admin_hub/cockpit.html:approve-form and hub_actionbar`

- [ ] **Step 1: Write failing cockpit redirect tests**

Replace `test_cockpit_carries_a_next_back_to_itself` and `test_approve_action_is_withdrawn_once_approved` with:

```python
def test_cockpit_approval_posts_next_to_agreement(client, reviewer, submitted_application):
    client.force_login(reviewer)
    cockpit_url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    agreement_url = reverse("admin_hub:agreement", args=[submitted_application.pk])
    body = client.get(cockpit_url).content.decode()

    assert f"?next={agreement_url}" in body
    assert f'value="{agreement_url}"' in body


def test_approved_cockpit_has_no_redundant_agreement_continue_button(
    client, reviewer, approved_application
):
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:cockpit", args=[approved_application.pk])
    ).content.decode()

    assert "Turpināt: Līgums" not in body
```

Keep approval-disabled assertions in `test_approve_action_is_withdrawn_once_approved`, but remove its old continuation-label assertion.

- [ ] **Step 2: Run cockpit tests red**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_cockpit.py
```

Expected: redirect assertion fails because template uses `request.path`; approved-cockpit assertion fails because it still renders `Turpināt: Līgums`.

- [ ] **Step 3: Expose direct agreement destination**

In `apps/admin_hub/views.py::cockpit_view`, keep the existing conditional `agreement_url` for approved action-bar context. Add an unconditional local route to render context:

```python
"approval_next_url": reverse("admin_hub:agreement", args=[application.pk]),
```

Use this separate context key because a submitted application has no `objects.agreement` yet, but approval creates it before redirect.

- [ ] **Step 4: Change approval form and remove redundant CTA**

In `templates/admin_hub/cockpit.html`, replace approval form route and hidden input:

```django
action="{% url 'admin:registrations_registrationapplication_approve' application.pk %}?next={{ approval_next_url|urlencode }}"
...
<input type="hidden" name="next" value="{{ approval_next_url }}">
```

In the action bar, remove only this branch:

```django
{% elif agreement_url %}
  <a class="btn btn-red" href="{{ agreement_url }}">Turpināt: Līgums →</a>
```

Keep the fallback `nav darbību šajā solī` branch for rejected/fix-requested states.

- [ ] **Step 5: Run cockpit tests green**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_cockpit.py tests/admin_hub/test_approve_next_redirect.py
```

Expected: PASS. Existing safe-next tests prove direct admin approval behavior still works; Hub form now targets agreement.

- [ ] **Step 6: Commit Task 1**

```bash
git add apps/admin_hub/views.py templates/admin_hub/cockpit.html tests/admin_hub/test_hub_cockpit.py
git commit -m "fix(admin-hub): open agreement after approval"
```

### Task 2: Render read-only pending invoice preview

**Files:**
- Modify: `tests/admin_hub/test_hub_billing.py`
- Modify: `apps/admin_hub/views.py:billing_view`
- Modify: `templates/admin_hub/billing.html`

- [ ] **Step 1: Write failing preview tests**

Add this helper and tests to `tests/admin_hub/test_hub_billing.py`:

```python
def _invoice_push_button_tag(body: str) -> str:
    match = re.search(r'<button[^>]*>\s*Izrakstīt rēķinus[^<]*</button>', body, re.S)
    assert match is not None, "invoice push button must be present"
    return match.group(0)


def test_billing_page_shows_derived_preview_before_invoice_rows_exist(
    client, reviewer, signed_application, default_plan
):
    from apps.billing.models import BillingRecord

    record = BillingRecord.objects.create(
        member=signed_application.approved_member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        first_billing_month="2026-09",
        scheduled_installment_count=2,
    )
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:billing", args=[signed_application.pk])).content.decode()

    assert "Rēķinu priekšskatījums" in body
    assert "Priekšskatījums" in body
    assert "Rēķini vēl nav izveidoti Invoice Ninja." in body
    assert "20.09.2026" in body
    assert "20.10.2026" in body
    assert "150,00" in body or "150.00" in body
    assert "Apstiprināt ierakstu" not in body
    assert "confirm_and_push" in body
    assert "disabled" not in _invoice_push_button_tag(body)


def test_billing_preview_is_absent_after_invoice_rows_exist(
    client, reviewer, signed_application, default_plan
):
    from apps.billing.models import BillingInvoice, BillingRecord

    record = BillingRecord.objects.create(
        member=signed_application.approved_member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
    )
    BillingInvoice.objects.create(
        billing_record=record,
        sequence=1,
        due_date=datetime.date(2026, 9, 20),
        amount=Decimal("300.00"),
    )
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:billing", args=[signed_application.pk])).content.decode()

    assert "Rēķinu priekšskatījums" not in body
    assert "Priekšskatījums" not in body
    assert "Nav izrakstīts" in body
```

- [ ] **Step 2: Run preview tests red**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_billing.py::test_billing_page_shows_derived_preview_before_invoice_rows_exist tests/admin_hub/test_hub_billing.py::test_billing_preview_is_absent_after_invoice_rows_exist
```

Expected: first test fails because no preview exists and current draft push is disabled. The second test may already pass because it locks down existing persisted-invoice behavior; retain it as a non-regression boundary before adding the new preview branch.

- [ ] **Step 3: Derive preview in billing view**

In `apps/admin_hub/views.py::billing_view`, locally import `Decimal` and `derive_installment_schedule`. After `record = objects.billing_record`, calculate only when record exists, no persisted invoice rows exist, and final total is nonzero:

```python
invoice_preview = []
if record is not None and not objects.invoices and record.final_amount != Decimal("0.00"):
    schedule = derive_installment_schedule(
        record.plan,
        record.final_amount,
        first_billing_month=record.first_billing_month,
        installment_count=record.scheduled_installment_count,
    )
    if record.payment_mode == BillingRecord.PaymentMode.UPFRONT:
        invoice_preview = [(schedule[0][0], record.final_amount)]
    else:
        invoice_preview = schedule
```

Add `"invoice_preview": invoice_preview` to render context. This matches `materialize_installments`: zero total has no rows, partial count limits rows, and upfront becomes one row for full total.

- [ ] **Step 4: Render preview and singular action**

In `templates/admin_hub/billing.html`, preserve the existing invoice table exactly inside the first branch, then add the preview branch between it and existing empty-state paragraph:

```django
{% if invoices %}
  {# Existing lines 39–72: persisted invoice table, unchanged. #}
{% elif invoice_preview %}
  <div class="callout" style="margin-bottom:14px">
    <span class="callout__icon">i</span>
    <span>Rēķini vēl nav izveidoti Invoice Ninja. Pēc izrakstīšanas šis priekšskatījums kļūs par rēķinu sarakstu.</span>
  </div>
  <div class="tablewrap">
    <table class="grid">
      <thead><tr><th>#</th><th>Termiņš</th><th class="num">Summa</th><th>Statuss</th></tr></thead>
      <tbody>
        {% for due_date, amount in invoice_preview %}
          <tr>
            <td class="strong">{{ forloop.counter }}</td>
            <td>{{ due_date|date:"d.m.Y" }}</td>
            <td class="num">{{ amount }} €</td>
            <td><span class="badge badge--sm badge--neutral">Priekšskatījums</span></td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
{% else %}
  <p class="hint">Rēķini vēl nav izveidoti. Tie rodas, kad līgums tiek atzīmēts kā parakstīts.</p>
{% endif %}
```

Place an `Rēķinu priekšskatījums` heading directly above this table.

In the record card footer, delete the draft-only confirmation form. Replace the push form with:

```django
{% if record.external_status == "synced" %}
  <span class="hint">Rēķini jau ir izrakstīti.</span>
{% else %}
  <form method="post" action="{% url 'admin:billing_billingrecord_push' record.pk %}?next={{ request.path|urlencode }}">
    {% csrf_token %}
    {% if not record_confirmed %}<input type="hidden" name="confirm_and_push" value="1">{% endif %}
    <button type="submit" class="btn btn-red">Izrakstīt rēķinus →</button>
  </form>
{% endif %}
```

For an already-synced record, do not render this form. Render a neutral `Rēķini jau ir izrakstīti.` status instead. Keep `push_view`'s existing synced no-op unchanged for direct Django-admin callers and stale concurrent requests.

- [ ] **Step 5: Run preview tests green**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_billing.py
```

Expected: PASS. Preview uses record snapshot, never coexists with invoice rows, and template has one enabled draft action.

- [ ] **Step 6: Commit Task 2**

```bash
git add apps/admin_hub/views.py templates/admin_hub/billing.html tests/admin_hub/test_hub_billing.py
git commit -m "feat(admin-hub): preview pending invoices"
```

### Task 3: Atomically confirm and enqueue Hub invoice push

**Files:**
- Modify: `tests/billing/test_admin_confirm_audit.py`
- Modify: `apps/billing/admin.py:BillingRecordAdmin.push_view`

- [ ] **Step 1: Write failing one-click endpoint test**

Add to `tests/billing/test_admin_confirm_audit.py`:

```python
def test_push_with_confirm_flag_confirms_audits_and_enqueues(
    active_plan, guardian
):
    from unittest.mock import patch

    rec = _draft(active_plan, guardian)
    c = _staff_client()
    url = reverse("admin:billing_billingrecord_push", args=[rec.pk])

    with patch("apps.integrations.tasks.enqueue_push_billing_record") as enqueue:
        response = c.post(url, {"confirm_and_push": "1"})

    assert response.status_code == 302
    rec.refresh_from_db()
    assert rec.status == BillingRecord.Status.CONFIRMED
    enqueue.assert_called_once_with(rec.pk)
    actions = set(AuditEvent.objects.filter(target_id=str(rec.pk)).values_list("action", flat=True))
    assert str(AuditEvent.Action.BILLING_RECORD_CONFIRMED) in actions
    assert str(AuditEvent.Action.BILLING_PUSH_TRIGGERED) in actions
```

Keep `tests/admin_hub/test_hub_billing.py::test_push_endpoint_refuses_an_unconfirmed_record` unchanged. It proves requests without the flag still refuse drafts.

- [ ] **Step 2: Run endpoint tests red**

Run:

```bash
uv run pytest -q tests/billing/test_admin_confirm_audit.py::test_push_with_confirm_flag_confirms_audits_and_enqueues tests/admin_hub/test_hub_billing.py::test_push_endpoint_refuses_an_unconfirmed_record
```

Expected: new test fails because push view rejects draft; existing direct-refusal test passes.

- [ ] **Step 3: Add atomic explicit-flag handling**

Add `from django.db import transaction` near existing Django imports in `apps/billing/admin.py`.

In `BillingRecordAdmin.push_view`, replace the current draft guard through enqueue/audit block with:

```python
        confirm_and_push = request.POST.get("confirm_and_push") == "1"
        with transaction.atomic():
            record = BillingRecord.objects.select_for_update().get(pk=object_id)
            if record.status == BillingRecord.Status.DRAFT:
                if not confirm_and_push:
                    self.message_user(
                        request,
                        "Vispirms apstipriniet maksājumu ierakstu.",
                        level=messages.ERROR,
                    )
                    return self._safe_redirect(request, object_id)
                record.status = BillingRecord.Status.CONFIRMED
                record.save(update_fields=["status", "updated_at"])
                record_audit_event(
                    action=str(AuditEvent.Action.BILLING_RECORD_CONFIRMED),
                    actor=request.user,
                    request=request,
                    target=record,
                )
            if record.external_status == "synced":
                self.message_user(request, "Rēķini jau ir izrakstīti.")
                return self._safe_redirect(request, object_id)
            enqueue_push_billing_record(record.pk)
            record_audit_event(
                action=str(AuditEvent.Action.BILLING_PUSH_TRIGGERED),
                actor=request.user,
                request=request,
                target=record,
            )
```

Leave the existing success message and final `_safe_redirect` immediately after this block. Do not broaden the accepted flag values; only literal `"1"` opts into confirm-and-push.

- [ ] **Step 4: Run endpoint tests green**

Run:

```bash
uv run pytest -q tests/billing/test_admin_confirm_audit.py tests/admin_hub/test_hub_billing.py
```

Expected: PASS. Flagged request confirms and queues; unflagged draft still refuses; GET and already-synced regressions remain green.

- [ ] **Step 5: Commit Task 3**

```bash
git add apps/billing/admin.py tests/billing/test_admin_confirm_audit.py
git commit -m "feat(billing): combine hub confirm and invoice push"
```

### Task 4: Full Hub regression and delivery verification

**Files:**
- No new production files.
- Modify only existing test files from Tasks 1–3 if a targeted assertion exposes a legitimate contract mismatch.

- [ ] **Step 1: Run Admin Hub regression suite**

Run:

```bash
uv run pytest -q tests/admin_hub
```

Expected: PASS. This covers pipeline URLs, Hub staff access, template comment guard, and approval/billing action redirects.

- [ ] **Step 2: Run full required checks**

Run:

```bash
uv run pytest -q -m "not slow" && uv run ruff check . && uv run mypy . && uv run python manage.py makemigrations --check
```

Expected: all commands exit 0; migration check reports no changes.

- [ ] **Step 3: Manual LAN acceptance**

At `http://192.168.3.245:8000/hub/`, verify:

1. Submit-ready application approval opens its agreement page directly.
2. After agreement signing creates a draft billing record, billing page has no `Apstiprināt ierakstu` control.
3. Billing page shows schedule rows with sequence, due date, amount, `Priekšskatījums`, and clear not-yet-created Invoice Ninja copy.
4. `Izrakstīt rēķinus` makes one POST; billing record becomes confirmed and worker receives push task.
5. After worker push, persisted Invoice Ninja invoice list replaces preview.
6. Direct Django-admin push of a draft without the flag still refuses it.

- [ ] **Step 4: Update `docs/milestones.md` only if status wording changed**

Append one concise Admin Hub delivered bullet only after LAN acceptance, stating direct approval→agreement, derived preview, and one-click confirm-and-push. Do not alter unrelated in-progress documentation.

- [ ] **Step 5: Commit any acceptance documentation**

```bash
git add docs/milestones.md
git commit -m "docs(admin-hub): record invoice flow acceptance"
```

Run this step only if Task 4 Step 4 changed `docs/milestones.md`.

## Acceptance criteria by unit

| Unit | Verifiable criterion |
|---|---|
| Approval cockpit | Approved result redirects to exact agreement Hub URL; no continuation CTA remains. |
| Preview | Snapshot-consistent rows appear only before persistent invoice rows and explicitly remain a preview. |
| One-click push | Draft becomes confirmed, two audit events exist, and exactly one job enqueue occurs. |
| Direct admin protection | Unflagged draft push remains rejected; no enqueue or push audit. |
| Safety | Staff-only, POST-only, CSRF, safe redirect, and synced no-op tests remain green. |
