# Membership Plan Lifecycle Fixes

## Problem

Staff cannot replace an existing default membership plan. The Invoice Ninja
product identifier is exposed as a staff input even though the integration
owns it. A signed member cannot receive a next-season billing record from the
application admin page. Finally, deleting a local billing record destroys its
Invoice Ninja linkage and there is no controlled recovery route.

## Decisions

### Default-plan handover

Saving an active `MembershipPlan` with `is_default=True` clears
`is_default` on every other plan in the same database transaction, then saves
the chosen plan. The existing partial unique constraint remains a final
database guard. A default plan must remain active.

This makes the normal staff operation a replacement rather than an error while
preserving the one-default invariant for all writers, not only Django admin.

Atomic handover: old default is unset and new default is set in a single
`transaction.atomic()` block, so no writer can observe a moment where no
plan is default.

### Invoice Ninja product identifier

`MembershipPlan.external_product_id` is an integration-owned cache of the
catalog product created or found by Invoice Ninja push jobs. It remains stored
and writable by integration tasks, but is hidden from the MembershipPlan admin
form via `exclude = ("external_product_id",)`. Staff must never supply it.

`MembershipPlan.external_product_id` remains integration-owned and hidden from
`MembershipPlan` staff add/change forms.

### Signed-member season renewal

A signed agreement remains historical: its chosen plan, signed state, invoices,
and money snapshots are never changed. The application admin's agreement
module instead offers a next-season form. Staff select an active plan whose
season differs from the signed agreement's plan, provide the first billing
month, and create one draft `BillingRecord` linked to the existing signed
agreement.

The existing `(member, season)` unique constraint is the overlap boundary. A
request for a season that already has a record is a safe no-op/error and makes
no duplicate record. Bulk renewal is deliberately outside this feature.

Current-season recreation: if a signed agreement has no current-season
`BillingRecord`, staff can recreate one from the application admin page. The
recreate form requires explicit confirmation that no Invoice Ninja invoice
exists for the season, uses the signed agreement's original plan and first
billing month, and emits a redacted `BILLING_RECORD_RECREATED` audit event
(plan ID + season only; no prices, no personal data, no Invoice Ninja data).

### Billing-record deletion and controlled recreate

`BillingRecord` deletion is denied in Django admin via
`has_delete_permission` returning `False`. This removes both object deletion
and the changelist bulk-delete action.

For an already-missing current-season record, the signed application page
offers a separate recreate disclosure. It uses the signed agreement's original
plan and first billing month, and requires a posted staff confirmation that
Invoice Ninja has no matching invoice. The application does not query Invoice
Ninja in this flow.

Only a real creation is audited through a new redacted
`BILLING_RECORD_RECREATED` action. Audit metadata carries plan and season IDs
only; it stores no Invoice Ninja data, prices, or personal data.

## State flow

```text
Signed agreement
├── its current plan has no BillingRecord
│   └── staff confirms no Invoice Ninja invoice
│       └── recreate current-season draft record
└── staff selects a plan for another season
    └── create next-season draft record on same agreement
        └── unique(member, season) blocks overlap
```

## Out of scope

- Bulk next-season renewal actions.
- Creating a new agreement during renewal.
- Changing a signed agreement's plan or historical billing values.
- Cancelling, crediting, or looking up Invoice Ninja invoices.
- Recovering Invoice Ninja linkage already lost through historic deletion.

## Acceptance criteria

1. Marking an active plan as default replaces the prior default without a
   validation or database error.
2. The membership-plan admin has no editable or displayed product-ID field.
3. A signed application's next-season action creates one draft record under
   the current signed agreement and changes no historical records.
4. A second request for the same member and season cannot create overlap.
5. Billing-record deletion is unavailable in Django admin.
6. Recreate requires explicit staff confirmation, only creates a missing
   current-season record, and emits a redacted audit event.
