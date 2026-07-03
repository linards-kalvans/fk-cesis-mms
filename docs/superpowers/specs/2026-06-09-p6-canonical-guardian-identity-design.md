# P6 follow-up — Canonical guardian identity

*Design spec. Status: approved for planning. Date: 2026-06-09.*

## 1. Problem

Repeated registrations from the same parent create **separate `Guardian` rows**. In
billing this produces separate Invoice Ninja clients and, more importantly, breaks
**sibling-discount linkage** — the discount derives from one guardian's set of children
(`Guardian.members`), so a guardian-per-application means every guardian has exactly one
member and the discount can never trigger. Surfaced during P6 Slice C live testing
(2026-06-09).

### Root cause

There are three uncoordinated copies of "the parent":

- `ParentAccount` — the verified identity. `email` is `unique`, established by the
  email-OTP gate. `RegistrationApplication.parent_account` already FKs to it.
- `RegistrationApplication.guardian_*` — denormalized, independently-editable copies of
  name/personal_id/email/phone/address.
- `Guardian` (members app) — minted fresh at **every** approval
  (`apps/registrations/services.py::approve_application` → `Guardian.objects.create`, no
  lookup), with **no link** back to `ParentAccount`.

A unique, deduplicated parent identity already exists (`ParentAccount`); the duplication
exists only because `Guardian` is a parallel, unlinked, per-approval copy.

## 2. Approach (chosen)

**Read-through with a canonical `Guardian` that is 1:1 with `ParentAccount`.**

- `Guardian` becomes the single canonical guardian-profile entity per verified parent.
- The application stops denormalizing guardian data; all reads go through the FK, so a
  profile edit propagates to every application and agreement automatically — propagation
  is a property of the schema, not cascade code.

Rejected alternative: keep `guardian_*` snapshots on the application and add an explicit
propagation cascade (write-through cache). Smaller blast radius now, but it preserves the
denormalization that caused the bug and reintroduces sync-drift risk. Not chosen.

## 3. Scope

In scope (this spec): the guardian-identity model change, resolution-at-initiation flow,
locked-profile parent UX, approval/billing fix, admin-initiated email change, and the
go-forward cutover.

Out of scope:

- **Invoice issue/send policy** (Draft vs auto-issue) — the other P6 follow-up; gets its
  own short spec.
- **Parent self-service email change** — deferred enhancement (see §9).
- **Backfill / merge of existing duplicate guardians and IN reconciliation** — not needed:
  the cutover is a fresh start (§8).

## 4. Data model

- Add `Guardian.parent_account = OneToOneField("accounts.ParentAccount", null=True, on_delete=PROTECT)`.
  One verified email → exactly one `Guardian`, forever.
- Add `RegistrationApplication.guardian = ForeignKey("members.Guardian", null=True, on_delete=PROTECT)`,
  set at initiation.
- **Drop all five `guardian_*` fields** from `RegistrationApplication`:
  `guardian_full_name`, `guardian_personal_id`, `guardian_email`, `guardian_phone`,
  `guardian_declared_address`.
- The editable profile fields live on `Guardian` (where they already exist):
  `full_name`, `personal_id`, `phone`, `address`.
- **Verified email is single-source-of-truth on `ParentAccount.email`** (already `unique`),
  read through `application.parent_account.email`. `Guardian.email` is kept as a synced
  mirror (the Invoice Ninja client contact reads it); a single writer keeps it consistent
  (set at resolve; updated on admin email change).
- **`Guardian.phone` is canonical** for the guardian profile. `ParentAccount.phone` is kept
  synced at save and is no longer the prefill source (today `submit_application` syncs
  `account.phone` from the application; that logic repoints to keep `account.phone ==
  guardian.phone`).

## 5. Resolution flow

- At draft **initiation** (`/applications/new/` → blank draft), `get_or_create` the
  `Guardian` for the request's verified `ParentAccount`, mirror `email` from the account,
  and set `application.guardian`.
- Guardian rows now exist for any verified parent who starts a registration, not only
  approved ones. Benign: `guardian.members` is empty until approval, so no billing fires
  and the sibling-discount engine sees nothing until a `Member` exists.
- **`approve_application` stops creating `Guardian`.** It links the new `Member` to
  `application.guardian`. Sibling discount (`guardian.members`) and the IN client key
  (`guardian.pk`) then work automatically across a parent's children. Idempotency and the
  `@transaction.atomic` guarantee are preserved.

## 6. Parent-form UX (locked profile)

`RegistrationApplicationForm` is a plain `forms.Form` (not a ModelForm), so the four
guardian `CharField`s stay; only the persistence target and initialization change.

- Fields **initialize from `application.guardian`** and **persist to `application.guardian`**
  (via the service), not to application columns.
- First registration (empty profile): fields editable; saving writes them to the `Guardian`.
- Returning parent (profile already populated): fields render **read-only/locked**; an
  explicit "Rediģēt vecāka datus" toggle unlocks them; saving writes back to the one
  `Guardian` row → every application and agreement reading through the FK reflects the
  change immediately.
- Reuses the existing guardian-ID-document reuse + OCR path. On first registration, guardian
  ID OCR fills the profile and is persisted to the `Guardian`; the OCR-prefill merge
  (`_merge_ocr_extractions`) writes to the `Guardian`, not to dropped application columns.
- The "Adrese tāda pati kā vecāka" member-address sync reads `application.guardian.address`.

## 7. Read-through edit surface

Repoint `application.guardian_*` reads to `application.guardian.*` (and the verified email
to `application.parent_account.email`). ~105 references across app code:

- `apps/registrations/`: `forms.py`, `services.py`, `views.py`, `models.py`, `admin.py`
- `apps/agreements/services.py`
- `apps/integrations/`: `tasks.py`, `docuseal.py`
- Templates: `parent_portal.html`, `new_registration.html`, `application_workspace.html`,
  `admin_review_queue.html`, `admin_review_detail.html`
- `static/js/async_upload.js`

Mechanical repoint; concentrated in the form/service persistence layer.

## 8. Cutover (fresh start)

Django DB **and** Invoice Ninja data are wiped at cutover (per the existing operational
note: wiping IN data requires clearing Django `external_*` ids; restart the `qcluster`
worker after task-code changes). Consequences:

- No merge command, no IN reconciliation, no historical data migration.
- Migrations: add the two FKs, drop the five `guardian_*` columns. Schema-only.

## 9. Admin email change

- Email change is **admin-initiated** for this spec. Staff change the email on the
  `ParentAccount` via Django admin.
- A small service enforces the `unique` constraint (reject if another account owns the new
  email) and updates the `Guardian.email` mirror in the same operation.
- Rationale: `ParentAccount.email` is the OTP auth identity; changing it without proving
  control of the new address is a redirect/hijack vector, so self-service must verify the
  new address. Admin is trusted staff, fits the realistic "parent called, wrong email, fix
  it" case, and keeps scope contained.
- **Deferred:** parent self-service email change with OTP re-verification of the new
  address. Track in milestone gaps.

## 10. Agreements

Agreements FK `Member → Guardian` and store no guardian-name field, so a profile edit
propagates to the Django **display** of even signed agreements. The signed PDF in DocuSeal
stays frozen (source of truth for the signed artifact). Live-display propagation is the
intended behaviour.

## 11. Testing

- **Dedup invariant:** two registrations from the same account → one `Guardian`, two
  `Member`s.
- **Approval reuse:** approval links the new `Member` to the existing `Guardian`; no new
  `Guardian` row; idempotent re-approval unchanged.
- **Sibling discount:** now triggers across a guardian's children (full price for the
  earliest, discount for the rest; opt-out path intact).
- **Locked-field UX:** populated profile renders locked; unlock-and-edit writes to the
  `Guardian`; the edit is visible on a second application and on the workspace/portal.
- **Read-through display:** guardian data renders correctly on portal, workspace, admin
  review, and the DocuSeal payload via the FK.
- **Admin email change:** uniqueness rejection; mirror update; verified email reads update
  through `parent_account.email`.
- **Regression:** verified entry, chooser, continue draft, start new, save draft, submit,
  async upload, OCR enqueue still work; ownership/security posture unchanged.

## 12. Acceptance

1. One verified parent email maps to exactly one `Guardian`, established at registration
   initiation.
2. Approval reuses the resolved `Guardian`; no duplicate `Guardian` rows on repeat
   registration.
3. Sibling discount applies across a parent's children, and the IN push uses one client per
   parent.
4. Guardian profile fields are locked for returning parents, unlockable by explicit action,
   and edits propagate to all applications and agreements via read-through.
5. The five `guardian_*` fields are removed from `RegistrationApplication`; verified email
   is single-source on `ParentAccount.email`.
6. Staff can change a parent's email from Django admin with uniqueness enforced and the
   `Guardian.email` mirror updated.
7. Full suite, ruff, and mypy green; manual LAN verification of the dedup + discount path.
