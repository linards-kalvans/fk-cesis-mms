# Family hub action anchor design

## Problem

After a staff member completes a child-specific action in the Django-admin
family hub, the server redirects to the top of the family page. Staff must
scroll back to the child whose workflow they were processing.

## Scope

- Every rendered child-specific hub POST control returns to its child card.
- This includes application, agreement, membership, and billing controls.
- An application anchor remains valid when approval creates its Member.
- A DocuSeal PDF-link failure that returns to the hub preserves the child card.

Out of scope: restoring open `<details>` disclosures, JavaScript state,
business workflow changes, model changes, migrations, and permission changes.

## Design

Each child context row exposes `anchor_id`:

- `child-application-<application pk>` when the child has a source
  application;
- `child-member-<member pk>` only for members without one.

The child card uses this string as its HTML `id`. Each child form sends it in
a hidden `return_anchor` field. The DocuSeal PDF link sends it as a query
parameter for its error-return route.

The admin action view accepts only an exact local child-anchor pattern and
appends it as a redirect fragment. Missing or invalid values retain the old
base-hub redirect. The fragment is presentation state only; object lookup,
staff permission, CSRF, and cross-family `404` checks stay unchanged.

## Verification

Pytest covers stable rendered anchors, application approval returning to its
pre-approval application anchor, agreement/membership/billing redirects,
invalid-anchor fallback, and DocuSeal error-return anchoring. Browser hash
scrolling itself is native browser behavior and needs no custom JavaScript
test.
