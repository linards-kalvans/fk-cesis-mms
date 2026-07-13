# P12 — Parent invoice visibility

*Design spec. Status: approved for planning. Date: 2026-07-13.*

## 1. Problem

Parents can register children and staff can push, send, and sync membership invoices through Invoice Ninja, but parents cannot see invoice state in the MMS parent portal. They depend on email and staff follow-up to know which membership invoices exist, what is due, what is paid, and whether the app has the latest payment status.

P12 gives verified parents read-only invoice visibility for their own family. It does not create new invoice types.

## 2. Goals

- Show issued invoices on the existing `/portal/` page.
- Limit invoice visibility to the currently verified parent account and its linked Guardian/family.
- Group invoices by child and season so siblings and installments stay readable.
- Show member, season, installment sequence, due date, amount, sent status, payment status, and last payment sync time.
- Provide a parent-safe invoice open/pay link only when Django has a stored safe external URL.
- Route parent link clicks through Django first, so ownership is checked before redirecting to Invoice Ninja.
- Keep empty and unavailable-link states parent-friendly and Latvian.

## 3. Non-goals

- No separate `/invoices/` parent area in this milestone.
- No custom invoice creation; P14 owns one-off invoices.
- No parent invoice detail page.
- No guessed Invoice Ninja URL construction from base URL + invoice id.
- No exposure of unissued future draft installments.
- No parent-visible raw sync error codes.
- No payment collection inside Django.
- No new JavaScript.

## 4. Confirmed scope decisions

1. P12 lives on the existing `/portal/` page.
2. Parents see only issued invoices: `BillingInvoice.sent_at IS NOT NULL` or `BillingInvoice.external_status == "sent"`.
3. Parent invoice rows are grouped by child + season.
4. Sync freshness is shown as a timestamp only. No stale-warning threshold in P12.
5. Invoice links use a Django proxy route, not direct Invoice Ninja links.
6. The safe external URL is stored on `BillingInvoice` and filled only by payment sync/fetch when the provider returns a verified URL field.

## 5. Data model

Add one field:

- `BillingInvoice.external_url = models.URLField(blank=True, default="")`

Why:

- Current invoice rows store external id/status/payment projection but no parent-safe URL.
- A stored URL avoids guessing Invoice Ninja route shapes.
- Keeping the URL on `BillingInvoice` matches the object parents open and the object payment sync updates.

No new parent invoice model is added. Existing `BillingRecord` and `BillingInvoice` remain the billing source of truth.

## 6. Integration contract

Extend the payment fetch result:

- `PaymentResult.external_url: str = ""`

Provider behaviour:

- Stub provider returns a deterministic URL during sync tests.
- Invoice Ninja provider maps a known safe parent-facing URL from the fetch response into `external_url`.
- If the provider response does not contain a known safe URL field, it returns an empty string.
- The implementation must not synthesize URLs from `INVOICE_NINJA_API_URL` and invoice ids.

Sync job behaviour:

- Payment sync saves `BillingInvoice.external_url` alongside the existing payment projection.
- If fetch returns an empty URL, the existing stored URL should not be replaced unless implementation confirms clearing is safer. Default: preserve existing non-empty URL.

## 7. Portal data flow

`parent_portal(request)` already resolves the verified `ParentAccount`. P12 adds invoice context derived only from that account:

```text
ParentAccount
  -> Guardian (1:1)
    -> Member rows
      -> BillingRecord rows
        -> issued BillingInvoice rows
```

The query must select only invoices owned by the current parent account. It must not start from unscoped `BillingInvoice.objects` without filtering through the guardian/member ownership chain.

Invoice groups:

```text
child + season group
  header: child name, season, final amount/currency
  rows: issued invoice installments
```

Custom/non-membership invoices are not implemented yet. If future P14 rows are introduced later, they must render with a distinct label and must not masquerade as membership dues.

## 8. Portal UI

Add one section below the existing applications section:

- Heading: `Mani rēķini`
- Empty state copy: `Šobrīd nav izsūtītu rēķinu.`

Each group card shows:

- child/member full name
- season
- billing record final amount and currency

Each invoice row shows:

- installment sequence (`#1`, `#2`, etc.)
- due date
- amount
- sent status (`Izsūtīts` for issued rows; fallback `—`)
- payment status label from existing `PaymentStatus` choices/messages:
  - `Nav apmaksāts`
  - `Daļēji apmaksāts`
  - `Apmaksāts`
  - fallback `—`
- sync freshness:
  - formatted `last_synced_at` when present
  - `Vēl nav sinhronizēts` when missing
- link state:
  - if `external_url` exists: show `Atvērt rēķinu`
  - if no `external_url`: show muted copy `Saite būs pieejama pēc maksājuma sinhronizācijas.`

The link href points to the Django proxy route, not the external URL.

## 9. Parent invoice open route

Add route:

```text
GET /portal/invoices/<invoice_id>/open/
```

Behaviour:

1. Resolve current parent account from session.
2. Query `BillingInvoice` through the current parent’s Guardian/member/billing ownership chain.
3. Require the invoice to be issued (`sent_at IS NOT NULL` or `external_status="sent"`).
4. Require `external_url` to be non-empty.
5. Redirect to `external_url`.

If there is no verified parent session, redirect to the existing parent entry flow, matching current parent-route convention.

Return `404` for owned-resource denial/unavailable cases:

- invoice does not exist in the current parent's scoped queryset
- invoice belongs to another guardian
- invoice is not issued
- invoice has no URL

Why `404`: it matches existing private-resource posture and avoids leaking invoice existence across families.

## 10. Security and privacy

- Parent invoice queries must be ownership-scoped through `ParentAccount`/`Guardian`.
- No other guardian’s invoice id may reveal existence or metadata.
- The portal must not show raw external API errors or error codes to parents.
- External URL is only used after Django ownership check.
- No public media or document URLs are introduced.
- No PII is added to logs.

## 11. Error and empty states

- No invoices: render Latvian empty state.
- Invoice exists but has no safe URL: render muted Latvian unavailable-link copy.
- Payment sync missing: render `Vēl nav sinhronizēts`.
- Provider errors remain staff-facing in admin/P11 surfaces, not on parent portal.

## 12. Acceptance criteria

P12 is complete when:

1. `/portal/` lists every issued membership invoice linked to the verified guardian’s members.
2. The portal does not list unissued/future draft invoices.
3. Invoice rows show member, season, installment sequence, due date, amount, sent status, payment status, and last sync time.
4. Invoice rows are grouped by child + season.
5. The invoice open link appears only when `BillingInvoice.external_url` is non-empty.
6. The open link goes through the Django proxy route and redirects only after ownership and issued-state checks pass.
7. Another guardian cannot see or open the invoice; denied attempts return `404`.
8. Empty and unavailable-link states are Latvian and parent-friendly.
9. No custom invoice support is added in P12.

## 13. Test strategy

Add tests for:

- migration/model field: `BillingInvoice.external_url` exists with blank default.
- provider/payment sync: when payment fetch returns `external_url`, sync saves it on the invoice.
- provider safety: unknown/missing URL fields do not produce guessed URLs.
- portal ownership: a verified parent sees only their own issued invoice rows.
- portal filtering: unissued invoices are hidden.
- portal grouping: invoices are grouped by child + season.
- portal display: paid, partial, unpaid, and no-sync states render Latvian copy.
- portal link: proxy link appears only when `external_url` exists.
- proxy route: owned + issued + URL redirects.
- proxy route: other guardian, unissued invoice, and missing URL return `404`; no session redirects to the existing parent entry flow.

## 14. Documentation

Update docs after implementation:

- `docs/milestones.md`: mark P12 delivered and record verification evidence.
- Optional short operator note only if live validation discovers a specific Invoice Ninja URL field or operational caveat.

## 15. Open implementation note

Invoice Ninja response shape for a parent-safe invoice URL must be verified from the provider response or a realistic fixture. If the safe field is not available during implementation, keep `external_url` empty and ship the portal/status visibility without external link until live validation confirms the field.
