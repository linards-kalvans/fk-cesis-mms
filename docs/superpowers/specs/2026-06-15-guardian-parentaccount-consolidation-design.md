# Guardian / ParentAccount consolidation — design

*Design spec. Status: approved for planning. Date: 2026-06-15.*

## 1. Problem

The parent/guardian is modelled by **two** rows today:

- **`ParentAccount`** (`apps/accounts/models.py`) — the authentication principal:
  `email` (unique, the login), `phone`, `is_active`, `last_login`. Login is magic-link / OTP
  via a session key (`PARENT_ACCOUNT_SESSION_KEY`); it is *not* a Django auth user. Billing and
  agreements never read it.
- **`Guardian`** (`apps/members/models.py`) — the domain entity: `full_name`, `personal_id`,
  `email`, `phone`, `address`, `external_client_id` (Invoice Ninja client), and a nullable 1:1
  `parent_account`. This is what billing (IN client), agreements (DocuSeal), and members
  (sibling linkage via `guardian.members`) all read.

Two problems:

1. **Double bookkeeping of contact data.** `email` and `phone` live on *both* models and are kept in
   sync by helpers — `change_parent_email` mirrors the email; phone syncs Guardian→Account on submit
   asymmetrically. This is a divergence hazard. (`services.py:66` already notes "guardian_email is
   derived from ParentAccount" — the `Guardian.email` column is conceptually a redundant mirror.)
2. **Two admin entries.** The left menu shows both "Accounts → Parent accounts" and
   "Members → Guardians". Staff want **one** entry and a single edit/detail page that manages the
   whole parent.

Two latent invariant gaps the consolidation must also close: an account can exist with **no**
Guardian (authenticated but never registered), and the approval-time fallback can create a Guardian
with **no** account (orphan). The "1:1" is not enforced today — in the current dev DB *all* Guardian
rows are orphaned (`parent_account = NULL`) and several are duplicates sharing one email.

## 2. Decisions (already taken)

- **De-duplicate fields** (not a full model merge, not sync-hardening): each shared field gets one
  owner; the auth/domain model split is preserved.
- **Link + merge existing data, then enforce NOT NULL** on `Guardian.parent_account`.
- **One admin entry = `Guardian`**; `ParentAccount` folded into the Guardian change page and removed
  from the menu.

## 3. Target design

### 3.1 Field ownership / model changes (`Guardian`)
- **Drop** the `email` and `phone` columns.
- Add read-only proxies so every existing reader keeps working unchanged:
  ```python
  @property
  def email(self) -> str:
      return self.parent_account.email if self.parent_account_id else ""

  @property
  def phone(self) -> str:
      return self.parent_account.phone if self.parent_account_id else ""
  ```
- `parent_account` becomes `null=False` (remains `OneToOneField` → unique; `on_delete=PROTECT`
  unchanged).
- `ParentAccount` owns the canonical `email` (already unique) and `phone`. `full_name`,
  `personal_id`, `address`, `external_client_id` stay Guardian-only; `is_active`, `last_login` stay
  ParentAccount-only.

No ORM query filters on `Guardian.email`/`phone` exist (verified) — every use is an attribute read
(`agreements/services.py:61,240`, `integrations/tasks.py:546`, `invoice_ninja.py:181`,
`docuseal.py:51,70,71`), so the property proxies are a drop-in. These call sites need **no change**.

### 3.2 Single-writer collapse
- **`change_parent_email`** (`apps/accounts/services.py`): drop the `Guardian.email` mirror update —
  `ParentAccount.email` is the only store. Keep the uniqueness validation + atomic semantics.
- **Draft-save** (`apps/registrations/services.py:426-432`): stop writing `guardian.phone`; route the
  form's `guardian_phone` value to `parent_account.phone`. **Delete** the asymmetric submit-time phone
  sync (`services.py:644-648`).
- **`RegistrationApplication.guardian_contact_phone`** accessor (`models.py:162-163`): reads
  `self.guardian.phone` — now the proxy, so it transparently returns the account's phone. **No change
  needed.** `guardian_contact_email` already reads the account — unchanged.
- **Approval orphan fallback** (`apps/registrations/services.py:~774`, the bare
  `Guardian.objects.create()`): change so a Guardian is never created without an account — require /
  resolve `application.parent_account` (raise a clear error if somehow absent, rather than minting an
  orphan).

### 3.3 Data migration (link + merge + enforce)
Two migrations in `apps/members/migrations/`:

**Migration A — data (`RunPython`, reversible-noop):**
For every `Guardian` (reading the still-present `email`/`phone` columns):
1. **Link to an account:** find `ParentAccount` by `email`; if none, create one
   (`email=guardian.email`, `phone=guardian.phone`). Set `guardian.parent_account`.
2. **Backfill account phone:** where `ParentAccount.phone` is empty and the guardian has a phone, copy
   it up.
3. **Merge duplicates** that collapse onto one account: group guardians by resolved account; choose a
   **survivor** (prefer one with `external_client_id` set, then one with members, then lowest pk);
   repoint `Member.guardian` and `RegistrationApplication.guardian` from the losers to the survivor
   (agreements follow via member — no direct guardian FK); delete the losers. Preserve the survivor's
   `external_client_id` (do not clobber a set value with an empty one).

Use the model state from the migration's `apps.get_model` (not imported models). Guard each step so
the migration is idempotent and safe on an already-clean DB.

**Migration B — schema:** `AlterField parent_account → null=False`, then
`RemoveField Guardian.email`, `RemoveField Guardian.phone`.

(Two separate migration files: data must run while the columns still exist; schema removes them
after. Migration B depends on A.)

### 3.4 Unified admin — one entry, one page
- **`Guardian` is the single management surface** (relabel the admin to "Vecāki" / Guardians).
  - A custom `GuardianAdminForm` adds three form-level fields backed by the linked account:
    `email`, `phone`, `is_active`. Initial values are read from `instance.parent_account`.
  - On save: `phone` and `is_active` are written to `parent_account` directly; an **`email` change is
    routed through `change_parent_email(account, new_email)`** (uniqueness + verified-login
    semantics, relocated from the old ParentAccount admin form). Save order: persist the Guardian /
    non-email account fields first, then apply the email change.
  - `has_add_permission = False` — guardians are created by the registration flow (mirrors
    `BillingRecordAdmin`), so the admin never mints an account from scratch.
  - The existing `related_records` block (members / applications / agreements) stays as the canonical
    cross-link block.
  - `search_fields`: replace the now-property `email` with `parent_account__email`
    (`("full_name", "parent_account__email", "personal_id")`). `list_display` may keep the `email`/
    `phone` proxies (display-only; not sortable).
- **`ParentAccount` is removed from the left menu** by filtering its entry out in
  `apps/core/admin_site.py::FkAdminSite.get_app_list` — but it stays **registered** so its change URL
  still resolves (cross-links degrade gracefully either way; account-without-guardian records remain
  reachable by direct URL). Net effect: the "Accounts" menu section disappears; only "Vecāki"
  remains. The old `ParentAccountAdmin.save_model` email-change routing and the `related_records`
  block added to it earlier are removed (email-change now lives on the Guardian form).
- The **"Vecāka konts" cross-link** in the application review block (`build_review_context`) is
  dropped — the account is now managed via the guardian, so the separate link is redundant.

**Accepted tradeoff:** parents who authenticated but never started a registration (account, no
guardian) won't appear in the menu — reachable only by direct URL. They carry no domain data;
surfacing them is a possible later enhancement.

## 4. Testing

- **Migration:** a data-migration test (using the historical/post-migration models) that an orphan
  guardian is linked to its account by email; that duplicates collapse to one survivor with
  members/applications repointed and `external_client_id` preserved; that a missing account is
  created; that `parent_account` is NOT NULL afterwards.
- **Proxies:** `guardian.email`/`guardian.phone` return the account's values; unchanged readers
  (a DocuSeal payload build, an IN `ensure_client` body, the agreement-email recipient) still see the
  right values.
- **Single writer:** changing the guardian phone in the registration flow updates
  `ParentAccount.phone` (not a dropped column); `change_parent_email` updates only the account and the
  proxy reflects it; the submit-time phone-sync path is gone.
- **Unified admin:** the Guardian change page renders and edits `email`/`phone`/`is_active`; an email
  change via the form goes through `change_parent_email` (rejects a duplicate email); `ParentAccount`
  is absent from the admin index/menu but its change URL still resolves; Guardian add is disabled.
- **Full gate** green; exactly one new migration pair (data + schema); `makemigrations --check`
  clean afterwards.

## 5. Blast radius

- **Call sites reading `guardian.email`/`phone`:** none change (proxies).
- **Test fixtures** that construct `Guardian.objects.create(email=…, phone=…)` must drop those kwargs
  and set the values on the `ParentAccount` instead — a sweep across the suite (the implementation
  plan enumerates and fixes each).
- **Forms / field-source mapping** (`apps/registrations/forms.py`, `services.py` field-source dicts):
  `guardian_phone`'s write target moves from Guardian to ParentAccount; `guardian_email` stays
  account-derived.
- **Admin:** `GuardianAdmin` gains the custom form; `ParentAccountAdmin` slims down; `FkAdminSite`
  gains menu filtering.

## 6. Plan split & sequencing

Two implementation plans (one spec):

1. **Plan 1 — model + migration + single-writer.** Proxies, `parent_account` NOT NULL, the link+merge
   data migration + schema migration, the write-path collapse (`change_parent_email`, draft-save
   phone → account, drop submit-sync, accessor, approval orphan fix), and the test-fixture sweep.
   Ends green with the duplication removed.
2. **Plan 2 — unified admin.** `GuardianAdminForm` (account fields + email-change routing),
   `has_add_permission=False`, search-field fix, relabel; `FkAdminSite` menu filtering to hide
   `ParentAccount`; slim `ParentAccountAdmin`; drop the redundant "Vecāka konts" review cross-link.

Plan 1 must land first (the admin form depends on the proxies + NOT NULL invariant).

## 7. Acceptance

1. `Guardian` has no `email`/`phone` columns; `guardian.email`/`guardian.phone` read through the
   linked `ParentAccount`; all billing/agreement/DocuSeal readers work unchanged.
2. `Guardian.parent_account` is NOT NULL; existing orphan/duplicate guardians are linked/merged with
   no loss of member, application, agreement, or `external_client_id` linkage.
3. Editing a guardian's email/phone/active state — and the registration phone write — all flow to the
   single `ParentAccount` store; no mirror columns remain to diverge.
4. The admin left menu shows **one** parent entry ("Vecāki"); its change page edits the domain +
   account fields together; email changes route through `change_parent_email`; `ParentAccount` is not
   in the menu but remains reachable/registered.
5. Full suite, ruff, and mypy green; exactly one new migration pair; `makemigrations --check` clean.
