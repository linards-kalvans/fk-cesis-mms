# P7 close-out — audit the billing-confirm + group-merge admin actions

*Design spec. Status: approved for planning. Date: 2026-06-16.*

## 1. Problem / scope

Two admin mutations introduced during P7 Slice C-ii write data but are **not** recorded in the
`AuditEvent` log, leaving a gap in the otherwise-complete admin audit trail:

1. **Billing one-click confirm** — `BillingRecordAdmin.confirm_view` flips a record DRAFT→CONFIRMED
   (deferred from C-ii batch 1: "would need a new `AuditEvent` choices value + migration").
2. **Training-group merge** — `TrainingGroupAdmin.merge_training_groups` reparents members and
   **deletes** the duplicate groups (deferred from C-ii batch 2 Plan 3).

This is the last remaining **P7 dev work**. Out of scope (explicitly deferred, not P7): surfacing
account-without-guardian records in the admin menu; parent self-service email change with OTP.

No behaviour change to the actions themselves — this only adds audit records.

## 2. Design

### 2.1 New audit action choices
Add two values to `apps.core.models.AuditEvent.Action` (English labels, matching the existing
catalog of approve/reject/export/etc.):

```python
BILLING_RECORD_CONFIRMED = "billing_record_confirmed", "Billing record confirmed"
TRAINING_GROUPS_MERGED = "training_groups_merged", "Training groups merged"
```

A `core` migration (next after `0003_alter_auditevent_action`, i.e. `0004_alter_auditevent_action`)
captures the `AlterField` on `AuditEvent.action`'s choices. This is **choices-only** — no DB column
change (Django does not enforce choices at the DB level), but `makemigrations --check` requires it to
be committed.

### 2.2 Wiring (both admins already import `record_audit_event` + `AuditEvent`)

**`apps/billing/admin.py` — `BillingRecordAdmin.confirm_view`:** record the event only on the real
DRAFT→CONFIRMED transition (right after `record.save(...)`), **not** on the already-confirmed no-op
branch:
```python
        if record.status == BillingRecord.Status.DRAFT:
            record.status = BillingRecord.Status.CONFIRMED
            record.save(update_fields=["status", "updated_at"])
            record_audit_event(
                action=str(AuditEvent.Action.BILLING_RECORD_CONFIRMED),
                actor=request.user, request=request, target=record,
            )
            self.message_user(request, "Ieraksts apstiprināts.")
        else:
            ...  # unchanged no-op info message
```

**`apps/members/admin.py` — `TrainingGroupAdmin.merge_training_groups`:** record the event **after**
the `transaction.atomic()` block commits (so a rolled-back merge isn't audited), with the deleted
groups captured in metadata (the `others` list is still in memory before deletion — read the ids/names
before the `.delete()`, or hold them in locals):
```python
            others = [g for g in groups if g.pk != target.pk]
            other_count = len(others)
            merged_ids = [g.pk for g in others]
            merged_names = [g.name for g in others]
            with transaction.atomic():
                reparented = Member.objects.filter(
                    training_group__in=others
                ).update(training_group=target)
                TrainingGroup.objects.filter(pk__in=merged_ids).delete()
            record_audit_event(
                action=str(AuditEvent.Action.TRAINING_GROUPS_MERGED),
                actor=request.user, request=request, target=target,
                metadata={"merged_group_ids": merged_ids,
                          "merged_names": merged_names,
                          "members_reparented": reparented},
            )
            self.message_user(request, ...)  # unchanged success message
```
Target is the **surviving** group (the losers are deleted, so they can't be the target). `metadata`
preserves enough to reconstruct what was merged.

### 2.3 Rationale
`record_audit_event` is fail-safe (returns `None`, never raises), consistent with how the other admin
actions audit. Confirm audits the state change only (the no-op confirm writes nothing). Merge audits
the **committed** result — placing the call after the atomic block means a failed/rolled-back merge
produces no misleading audit row.

## 3. Testing

- **Confirm:** a real DRAFT confirm writes one `AuditEvent` with
  `action == BILLING_RECORD_CONFIRMED`, the acting user, and the record as target; confirming an
  already-CONFIRMED record writes **no** new audit row.
- **Merge:** a successful merge writes one `AuditEvent` with `action == TRAINING_GROUPS_MERGED`,
  the actor, the survivor as target, and metadata containing the merged group ids/names + the
  reparented-member count; a single-group selection and a no-delete-permission attempt write **no**
  audit row (they no-op before the merge).
- **Migration:** `makemigrations --check` clean after `0004` is committed.
- Full suite, ruff, mypy green; one choices-only migration.

## 4. Acceptance

1. Confirming a draft billing record from the admin records a `BILLING_RECORD_CONFIRMED` audit event
   (actor + target); the no-op confirm does not.
2. Merging training groups records a `TRAINING_GROUPS_MERGED` audit event (actor + surviving target +
   metadata of merged ids/names + reparented count); rejected merges (single-group, no permission) do
   not.
3. Both new actions appear in the `AuditEvent.Action` catalog; exactly one new `core` migration
   (choices-only); `makemigrations --check` clean.
4. No behaviour change to the confirm/merge actions themselves; full suite + ruff + mypy green.
5. With this delivered (and the manual admin-verification pass run), **P7 is complete**.
