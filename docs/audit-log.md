# Audit log — operator guide

How to read and use the audit trail (FK Cēsis MMS, P7 Slice A).

## What it is

Every sensitive staff or system action is recorded as an immutable **`AuditEvent`** row:
*who* did *what*, to *which object*, *when*, and (for browser actions) *from where*. The log is
**append-only** — it cannot be edited or deleted through the app, even by superusers. Rows are
automatically pruned after a retention window (default 2 years; see [Retention](#retention)).

## Where to read it

Django admin → **Core → Audit events** (`/admin/core/auditevent/`). Staff login required; there
is no parent-facing view.

The changelist shows, per event:

| Column | Meaning |
|--------|---------|
| **Created at** | When the action happened (server local time, Europe/Riga). |
| **Action** | What happened (see the [catalog](#event-catalog)). |
| **Actor label** | Who did it — a staff email, a parent's email, or `system: <job>` for automated jobs. |
| **Target type** / (repr) | Which object (e.g. `registrationapplication`, `document`, `agreement`, `billingrecord`) and a human label. |
| **IP address** | Client IP for browser-originated actions (document views, review actions); blank for automated jobs. |

Click a row to see full detail, including **Metadata** (small structured context such as
`{"from_status": "submitted", "to_status": "approved"}` or `{"error_code": "unavailable"}`) and
the **user agent**.

## Finding things

- **Filter** (right sidebar): by **action**, by **target type**, and by **created date**.
- **Date drill-down**: the date hierarchy bar at the top (year → month → day).
- **Search box**: matches **actor label**, **target repr**, and **target id**.

Common questions:

- *"Who viewed/downloaded this child's ID document?"* — filter Action = `Document previewed` /
  `Document downloaded`, then search the document id (the `target_id`), or search the child's name
  if it appears in `target_repr`. The IP column shows where from.
- *"Everything that happened to application #42"* — search `42` (matches `target_id`); optionally
  filter target type = `registrationapplication`.
- *"Everything a given staff member did"* — search their email (matches `actor_label`).
- *"All recent failures"* — filter Action by the `… failed` events (`Invoice push failed`,
  `Invoice send failed`, `Payment sync failed`, `Agreement sync failed`).

## Event catalog

**Registration review** (staff): `application_approved`, `application_rejected`,
`application_fix_requested`.
**Members** (staff): `training_group_assigned`, `training_group_cleared`.
**Documents**: `document_previewed`, `document_downloaded` (staff, with IP), `document_deleted`
(on replace — actor is the parent; or staff admin delete).
**Agreements**: `agreement_sent`, `agreement_signed` (arrives from the DocuSeal webhook →
`system`), `agreement_voided`, `agreement_sync_failed`.
**Billing**: `billing_push_triggered`, `payment_sync_triggered` (staff admin actions);
`invoice_push_failed`, `invoice_send_failed`, `payment_sync_failed` (automated jobs).

**Deliberately NOT recorded:** routine *successful* automated runs (each nightly payment sync,
each successful invoice send) — only state changes, staff-triggered actions, and failures are
logged, to keep the trail signal-rich. Parent-portal browsing/reads are not audited.

## What's stored (and what isn't)

Stored: actor (+ a label snapshot that survives the user being deleted), action, a denormalized
target snapshot (survives the target being deleted), small redacted metadata, IP + user-agent for
browser actions, and the timestamp.

**Never stored** in an audit row: Latvian personal ID codes, document file contents, email message
bodies, OTP codes, magic-link tokens, or API keys. Metadata holds only statuses, error codes,
document kinds, group names, and database IDs. `actor_label` and `ip_address` do hold identifying
data by design (that is the point of an audit trail) and are bounded by the retention window.

## Retention

Audit events older than **`AUDIT_RETENTION_DAYS`** (env, default **730** = 2 years) are deleted by
a nightly background job (`prune_audit_events`, registered as the `audit-retention-prune` django-q
Schedule, runs at `AUDIT_PRUNE_HOUR`, default 02:00 local). The job runs in the `qcluster` worker.

To change the window, set `AUDIT_RETENTION_DAYS` in the environment (`.env`) and restart the
`qcluster` worker. Lowering it prunes older rows on the next nightly run.

## Power-user queries (shell)

For ad-hoc analysis beyond the admin filters, the ORM is available:

```bash
uv run python manage.py shell
```
```python
from apps.core.models import AuditEvent

# All document downloads in the last 30 days, newest first:
from django.utils import timezone
import datetime
since = timezone.now() - datetime.timedelta(days=30)
AuditEvent.objects.filter(action=AuditEvent.Action.DOCUMENT_DOWNLOADED, created_at__gte=since)

# Everything for one application:
AuditEvent.objects.filter(target_type="registrationapplication", target_id="42")
```

## Notes / limitations

- The trail records actions taken **through the app and its admin**. Direct database edits (e.g.
  `manage.py shell`, raw SQL) are **not** audited.
- Audit writing is **fail-safe**: if recording an event ever errors, the underlying action still
  succeeds and the failure is logged to the application log — so a missing event never indicates a
  failed business action, only a failed *recording*. Such failures are rare and surface in the
  `qcluster`/web logs as a `record_audit_event failed for action=…` warning.
