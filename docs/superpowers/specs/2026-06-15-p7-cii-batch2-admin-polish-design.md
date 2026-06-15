# P7 Slice C-ii (batch 2) — Full admin polish

*Design spec. Status: approved for planning. Date: 2026-06-15.*

## 1. Problem / scope

Batch 1 (delivered 2026-06-14) shipped the three user-prioritised admin quick wins. Batch 2
completes the **broader C-ii** scope — the remaining admin flow-polish work — in four areas:

1. **Cross-links** — staff cannot navigate between related records (Guardian ↔ Application ↔
   Member ↔ Agreement ↔ Billing) except via Django's default one-way FK links.
2. **Sync-health badges/filters** — Invoice Ninja push / payment sync state and agreement sync
   state are shown as raw text; no visual badge, no "sync failed" filter, no Latvian error copy in
   the admin (the error→copy helpers exist but aren't wired to the admin display).
3. **Search/filter polish** — several admins are under-equipped: `DocumentAdmin` has no
   `search_fields`/`list_filter` at all; `TrainingGroup`/`MembershipPlan` are unsearchable; several
   admins lack `date_hierarchy`/`ordering`.
4. **Document active-vs-replaced UX + training-group de-duplication** — `DocumentAdmin` lists active
   and soft-deleted (replaced) documents identically; and `TrainingGroup.name` has no uniqueness
   constraint, so duplicate groups can be created with no way to merge them.

All of this is Django-admin presentation work plus **one** small model change (the training-group
uniqueness constraint, the only migration in batch 2). Services, state machines, and parent-facing
surfaces are unchanged.

This spec is implemented as **three independently-testable plans** (see §7):
Plan 1 = cross-links; Plan 2 = visibility (sync-health + search/filter + doc active-vs-replaced);
Plan 3 = training-group de-duplication.

## 2. Shared foundation

Two small reusable helpers in the `core` app, used across the per-app admins:

- `apps/core/admin_links.py::admin_link(obj, label=None) -> str` — returns a `format_html` anchor to
  `reverse("admin:<app_label>_<model_name>_change", args=[obj.pk])`; label defaults to `str(obj)`.
  Returns `"—"` (plain) when `obj` is `None`. A companion `admin_links(queryset_or_iterable, ...)`
  renders a comma/`<br>`-separated list of links for to-many relations (capped with a "+N" overflow
  marker to keep cells/rows compact).
- `apps/core/admin_badges.py::status_badge(text, level) -> str` — returns a `format_html` `<span>`
  with a CSS class per `level` (`"ok"` green / `"fail"` red / `"pending"` amber / `"muted"` grey).
  Styled by `static/admin/fk_badges.css`, attached to the relevant ModelAdmins via an inner `Media`
  class. (Inline-style fallback is acceptable if a Media/staticfiles wiring proves fiddly, but the
  CSS file is preferred for one source of truth.)

Both helpers return `SafeString`; mypy gets `# type: ignore[return-value]` consistent with the
existing `format_html` display methods in the repo.

## 3. Plan 1 — Cross-links (navigation)

Make the relationship web navigable in both directions. **Verified reverse relations:**
`guardian.members`, `guardian.applications`, `parent_account.guardian`,
`member.source_application` (OneToOne), `member.agreements`, `member.billing_records`,
`agreement.billing_records`, `agreement.member`, `application.approved_member`,
`application.guardian`, `application.parent_account`, `billing_record.member`,
`billing_record.agreement`.

### 3.1 Change-page "Saistītie ieraksti" link rows
A compact related-records block on each change page, built from `admin_link`/`admin_links`:

- **RegistrationApplicationAdmin** — links to approved **Member**, **Vecāks** (Guardian),
  ParentAccount, current **Līgums** (Agreement, via the member's current agreement), and the
  member's **BillingRecords**. This admin already has a custom C-i `change_form_template` +
  `build_review_context`; the related-records block is added to that context and rendered near the
  top action bar (so it sits with the other review affordances, not buried in the form).
- **MemberAdmin** — links to source **Application** (`member.source_application`), **Vecāks**
  (Guardian), current **Līgums**, and **BillingRecords**. Added as readonly link methods surfaced in
  the change form (MemberAdmin uses the default change template → readonly display methods in
  `fields`/`readonly_fields`).
- **AgreementAdmin** — links to **Member**, source **Application** (via
  `member.source_application`), and **BillingRecords** (`agreement.billing_records`). Readonly link
  methods.
- **BillingRecordAdmin** — `member` and `agreement` rendered as clickable links; link to source
  **Application** (via `member.source_application`) and to **Vecāks** (Guardian, via
  `member.guardian`). Readonly link methods.
- **GuardianAdmin** — new related-records block linking to its **Members** (`guardian.members`),
  its **Applications** (`guardian.applications`), and its **BillingRecords** (aggregated across
  `guardian.members` → `member.billing_records`). Readonly link methods.

### 3.2 Changelist link columns (high-value only)
To keep lists scannable, add only the two highest-value clickable columns:

- **RegistrationApplicationAdmin** changelist: a **Biedrs** column linking to the approved member
  (`"—"` when not yet approved), placed before `agreement_status`.
- **BillingRecordAdmin** changelist: the existing plain-text `guardian_name` column becomes a
  clickable **Vecāks** link; add a **Līgums** column linking to the record's agreement (`"—"` when
  null).

(`AgreementAdmin`/`MemberAdmin` already FK-link `member`/`guardian` via Django's default changelist
rendering of FK fields shown through `__str__`; no extra column needed there.)

## 4. Plan 2 — Visibility (sync-health + search/filter + document active-vs-replaced)

### 4.1 Sync-health badges + filter
- **BillingRecordAdmin**: replace the raw `external_status` and `payment_status` columns with
  badge-rendering display methods using `status_badge` — green when `synced`/`paid`, red when an
  error code is set, amber for in-progress, grey/`—` when empty. The badge `title` (tooltip) carries
  the Latvian copy from `apps.billing.messages.get_invoice_error_message(external_error_code)` (and
  the payment equivalent) when an error code is present. Add a custom
  `SyncHealthFilter(admin.SimpleListFilter)` (parameter `sync_health`) with choices **OK** /
  **Neizdevās** (failed) / **Procesā** (pending) / **Nav sinhronizēts** (not synced), translating to
  queryset filters on `external_status`/`external_error_code`.
- **AgreementAdmin**: add a sync-health badge column derived from `external_state` /
  `external_error_code` (tooltip via `apps.agreements.messages.get_agreement_error_message`) and the
  same style of `SimpleListFilter`. (Agreement uses `external_state`, not `external_status`.)

### 4.2 Search/filter polish (no model changes)
- **DocumentAdmin**: `search_fields = ("application__member_full_name", "application__id", "kind")`;
  `list_filter = ("kind", "ocr_status", <active/replaced filter — see 4.3>)`;
  `date_hierarchy = "uploaded_by_parent_at"`; `ordering = ("-uploaded_by_parent_at",)`.
- **TrainingGroupAdmin**: `search_fields = ("name",)`. (Constraint + merge come in Plan 3.)
- **MembershipPlanAdmin**: `search_fields = ("name", "season")`.
- **RegistrationApplicationAdmin**: `date_hierarchy = "submitted_at"`; `ordering = ("-submitted_at",)`;
  broaden `list_filter` to include `preferred_agreement_signing` (in addition to `status`).
- **AgreementAdmin**: `date_hierarchy = "generated_at"`; `ordering = ("-generated_at",)`.
- **BillingRecordAdmin**: `date_hierarchy = "created_at"`; `ordering = ("-created_at",)`; add `plan`
  to `list_filter`.

(Exact field names verified against the models; any field that turns out not to exist is dropped
during implementation rather than invented.)

### 4.3 Document active-vs-replaced
- **DocumentAdmin**: an **Aktīvs/Vēsturisks** badge column via `status_badge` (`is_active` →
  green "Aktīvs", else grey "Vēsturisks (aizstāts)"); a custom active/replaced
  `SimpleListFilter` (parameter `state`, choices Active / Replaced) translating to
  `deleted_at__isnull=True/False`. Ordering `-uploaded_by_parent_at` (shared with 4.2) keeps the
  newest upload — typically the active one — on top. The C-i review panel already separates
  active/replaced correctly; this fixes the *flat DocumentAdmin list* only.

## 5. Plan 3 — Training-group de-duplication (the only migration)

- **Model + migration**: add a case-insensitive uniqueness constraint to `TrainingGroup`:
  `UniqueConstraint(Lower("name"), name="uniq_training_group_name_ci")` in `Meta.constraints`
  (`from django.db.models.functions import Lower`). Verified there are **no existing duplicate
  names** today, so the migration applies cleanly. The model also gets a `clean()` that raises a
  `ValidationError` on a case-insensitive name clash, so the admin form surfaces a friendly Latvian
  message rather than only a DB `IntegrityError`.
- **Search**: `search_fields = ("name",)` (also listed in 4.2; whichever plan lands first adds it,
  the other treats it as already-present).
- **Merge admin action** `merge_training_groups` on `TrainingGroupAdmin`: select two or more groups
  → an intermediate confirmation page (admin action returning a `TemplateResponse`) lets staff pick
  the **target** group → on confirm, inside a transaction:
  `Member.objects.filter(training_group__in=others).update(training_group=target)` then
  `others.delete()`; `message_user` reports how many members were reparented and how many groups
  removed. Guard: a single-group selection is rejected with an info message.

No audit event is added for the merge in this batch (consistent with batch 1's deferral of
confirm-audit); flagged for a later addition if staff wants merges audited.

## 6. Testing

TDD throughout (RED → GREEN). Per area:

- **Cross-links:** for each change page, assert the rendered HTML contains the expected
  `reverse("admin:..._change", args=[related.pk])` URL; assert the `"—"` fallback when a relation is
  absent (e.g. an unapproved application has no member link). For the two changelist columns, assert
  the link URL appears in the changelist HTML.
- **Sync-health:** assert the badge HTML (CSS class + Latvian tooltip for an errored record) and
  that `?sync_health=failed` narrows the changelist to errored records only; same shape for the
  agreement filter.
- **Search/filter:** functional — a `?q=<term>` search returns the matching row; a `?<filter>=<val>`
  narrows the list; `date_hierarchy`/`ordering` render without error.
- **Document active-vs-replaced:** assert the Aktīvs/Vēsturisks badge for an active vs a
  soft-deleted document and that the active/replaced filter narrows correctly.
- **Training-group dedup:** a case-insensitive duplicate `create()` raises `IntegrityError`
  (constraint) and the admin form `clean()` raises `ValidationError`; the merge action reparents all
  members to the target and deletes the others (assert member counts + group deletion); a
  single-group merge is a no-op with a message.

## 7. Plan split & sequencing

Three independently-shippable plans, each green on its own:

1. **Plan 1 — Cross-links** (incl. the shared `admin_link`/`admin_links` helper). No migration.
2. **Plan 2 — Visibility** (sync-health badges/filter + search/filter polish + document
   active-vs-replaced; incl. the shared `status_badge` helper + `fk_badges.css`). No migration.
3. **Plan 3 — Training-group de-duplication** (constraint **migration** + `clean()` + merge action +
   search).

Plans 1 and 2 are pure presentation and order-independent. Plan 3 carries the only migration. Each
plan ends on a full gate (pytest/ruff/mypy/`makemigrations --check`); only Plan 3 expects a new
migration.

## 8. Acceptance

1. From any of Guardian / Application / Member / Agreement / BillingRecord change pages, staff can
   click through to every directly-related record; the application and billing changelists carry the
   two new link columns; absent relations render "—".
2. BillingRecord and Agreement changelists show color sync-health badges with Latvian error tooltips
   and offer a sync-health filter that isolates failed/pending/ok/not-synced rows.
3. DocumentAdmin is searchable + filterable (incl. active-vs-replaced) with a date drill and a sane
   default order; TrainingGroup and MembershipPlan are searchable; the application/agreement/billing
   admins gain date drill + ordering.
4. Active vs replaced documents are visually distinguished in the DocumentAdmin list.
5. Duplicate (case-insensitive) training-group names are rejected at the DB and the admin form; staff
   can merge duplicate groups (reparenting members) from the admin.
6. Full suite, ruff, and mypy green; exactly one new migration (Plan 3), `makemigrations --check`
   otherwise clean.
