# Admin Hub — open items and handover

Branch `dev`, unpushed. Plan: `docs/superpowers/plans/2026-09-07-admin-hub-ui.md`.
Spec: `docs/superpowers/specs/2026-09-07-admin-hub-ui-design.md`.

State at handover: 2045 tests pass on the fast lane, ruff and mypy clean across
479 files, working tree clean, 29 commits since `ce6c52f`, nothing pushed.

The Hub serves five staff screens under `/hub/`, all of them skins over the
existing Django admin action endpoints. No new models, no migrations.

---

## 1. Decisions that are yours, not mine

### 1.1 Authorization bar on Hub pages

Hub views gate on `is_staff` (`@staff_member_required`). Every endpoint they
POST to additionally requires `has_change_permission`.

The consequence: a staff account **without** change permission can open the
cockpit and read a child's personal code, address, and identity documents, on a
page where every action returns 403. Read access is therefore strictly wider
than write access, and the widened surface is exactly the personal data GDPR
cares most about.

Two ways to settle it:

- **Tighten** — add the same permission check to the Hub views, so the page is
  visible only to accounts that can act on it.
- **Accept** — record that `is_staff` is the intended read bar, on the basis
  that the same data is already readable through Django admin for these
  accounts.

I have not implemented either. Pick one.

### 1.2 Member's legal name in the download filename

Agreement downloads are now named `<member-name>-<sign-type>-<number>.pdf`, as
requested. That name travels in the `Content-Disposition` response header,
which reverse proxies and WAFs commonly log, and which browsers retain in
download history.

That is a child's full legal name in infrastructure logs. It may well be fine
under Eleving's data-classification policy — but it is a policy question, and I
cannot answer it. If it is not fine, the fix is to drop the name and keep
`<sign-type>-<number>.pdf`, which is a one-line change to
`download_filename()` in `apps/agreements/document_proxy.py`.

---

## 2. Known defects not fixed

### 2.1 Three audit calls omit `target_repr` and so record PII

`request_application_fix`, `reject_application` and `approve_application`
(`apps/registrations/services.py`, around lines 714, 747 and 820) call
`record_audit_event` without `target_repr`. It is then auto-filled from
`str(application)`, which renders as `<guardian e-mail> — <child name>`.

Pre-existing, not introduced on this branch. The inline-edit service added on
this branch passes `target_repr=f"pieteikums #{application.pk}"` precisely to
avoid this, so the fix is to do the same in these three places.

### 2.2 `start_material_amendment` never repoints `BillingRecord.agreement`

When a material amendment supersedes an agreement, the existing BillingRecord
keeps pointing at the superseded row. Two consequences:

- A later reassignment syncs the plan back onto the **superseded** agreement,
  not the current one.
- It is the hole in the duplicate guard described in §3 — that guard
  identifies a desync by `record.agreement_id == agreement.pk`, which is false
  in exactly this case.

Likely fix: repoint the record to the member's `is_current=True` agreement as
part of the amendment.

### 2.3 Dead blocked-reason branches

In `_billing_change_route`, the "invoices pushed to Invoice Ninja" and
"invoices sent to parent" branches cannot be reached in production: the
`status != DRAFT` check fires first, and `push_view` requires CONFIRMED. They
are reachable only from direct-DB fixtures. Harmless, but they read as live
guards when they are not.

### 2.4 Deferred, lower value

- Nightly sweeps have no explicit batch-size cap.
- `member_kit_size_shorts` is a dead field (kit size collapsed to one value).
- No bulk-select in the queue.
- `discontinue_agreement` never clears `is_current`.
- The schedule-row regex at `tests/admin_hub/test_hub_billing.py:99` matches
  only the last row.

---

## 3. The duplicate-billing guard (commit `0a1b001`)

Worth understanding before touching step 6.

`load_pipeline_objects` identifies the current BillingRecord by
`record.season == agreement.billing_plan.season`.
`recreate_missing_billing_record`'s already-exists guard filters on that same
value. So a record whose season disagrees with the agreement's plan is
invisible to **both**.

That is not a stalemate — it is a silent duplication. The recreate does not
refuse; it succeeds. `BillingRecord`'s unique key is `(member, season)` and the
seasons differ, so the new row is accepted, the old row keeps the invoices, and
the operator sees only a success message.

The Hub now surfaces such a row as `PipelineObjects.mismatched_record` and
withholds the recreate offer, naming both seasons instead.

Detection is deliberately narrow: only a record created for *this* agreement.
An ordinary returning member's earlier seasons also sort below the current plan
season, and flagging those would block the remedy for exactly the returning
member it exists to serve. §2.2 is the accepted hole.

### Diagnosing a suspected case

Read-only, no writes:

```python
from apps.agreements.models import Agreement
from apps.billing.models import BillingRecord

a = Agreement.objects.get(agreement_number="FKC-2026-020")
m = a.member
print("agreement", a.pk, a.agreement_number, a.state, "is_current", a.is_current)
print("plan season", a.billing_plan.season if a.billing_plan_id else None)
for r in BillingRecord.objects.filter(member=m).order_by("season"):
    print(r.pk, r.season, r.status, "agreement_id", r.agreement_id,
          "invoices", r.invoices.count())
```

Read the output as:

- **No rows** — the record is genuinely missing. The recreate offer is correct;
  use it.
- **A row whose season equals the plan season** — the matcher found it, so the
  Hub shows reassign rather than recreate. Nothing is wrong.
- **A row whose season differs and whose `agreement_id` is this agreement** —
  the desync. The Hub now blocks and names both seasons. Repair by aligning the
  agreement's `billing_plan` with the record's season, or by reassigning the
  record. **Do not recreate.**
- **A row whose season differs and whose `agreement_id` is some *other*
  agreement** — §2.2. The guard does **not** catch this, and the Hub will still
  offer recreate. Do not accept the offer; repair the link first.
