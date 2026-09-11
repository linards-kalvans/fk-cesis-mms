# Admin Hub UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an FK Cēsis-branded staff UI for the 8-step registration pipeline and the outstanding-invoice review, driving the Django admin action endpoints that already exist.

**Architecture:** A new `apps/admin_hub` app serves five staff-only pages under `/hub/`. It owns no models and no state transitions: every mutating form POSTs to an existing `admin:registrations_registrationapplication_*` or `BillingRecordAdmin` endpoint. Pipeline state is derived, not stored — the lane derivation is first extracted out of `apps/members/family_hub.py` into `apps/members/lanes.py` so the Family Hub and the Admin Hub read one source of truth.

**Tech Stack:** Django 5+ (project targets `django>=5.0`), Python ≥3.12, `uv` for all Python commands, pytest + pytest-django, ruff, mypy. Server-rendered templates; hand-written CSS; vanilla JS only where a form cannot express the behaviour.

**Spec:** `docs/superpowers/specs/2026-09-07-admin-hub-ui-design.md`

**Mock-ups (visual source of truth):** `style-guide/admin/` — `index.html` launcher, `01-pieteikumu-rinda.html`, `02-kabine-parbaude.html`, `03-ligums.html`, `04-plans-rekini.html`, `05-rekini-neapmaksatie.html`, `hub.css`.

## Global Constraints

- **All Python commands run through `uv`.** Never `pip`, never a bare `python`. Tests: `uv run pytest`.
- **TDD is mandatory** (AGENTS.md "Coding Conventions"): failing test first, then implementation, then verify.
- **Verification gate before claiming any task done:** `uv run pytest -q && uv run ruff check . && uv run mypy .`
- **Branch:** all work lands on `dev`. Never commit directly to `main`.
- **Business rules live in `services.py` / dedicated modules, not views or templates.**
- **No new models, no migrations, no new domain state transitions.** If a task appears to need one, stop and escalate.
- **All UI copy is Latvian.** Copy strings in this plan are the exact strings to use — they are taken from the approved mock-ups.
- **Staff-only:** every view in `apps/admin_hub` is wrapped in `staff_member_required`. No exceptions.
- **No PII in logs.** Do not log field values, personal codes, or document contents.
- **Documents are never served by a new path.** Reuse `documents:admin-document-preview` and `documents:admin-document-download`, which already enforce staff authorization.
- **Never invent derived state.** If a value is not persisted, it is not displayed. Two specific traps, both already corrected in the mock-ups: there is no agreement download counter anywhere in the domain, and `field_sources` is never reset when a parent overwrites an OCR-filled value — so no stored value means "the parent edited this".
- **Tests live in `tests/admin_hub/`**, which already holds the fixtures this plan uses (`reviewer`, `parent_account`, `submitted_application`, `approved_application`, `default_plan`, `active_plan`, `kit_sizes`).

---

### Task 1: Extract the lane derivation into its own module

`apps/members/family_hub.py` is 842 lines doing two jobs: deriving per-object status, and assembling the Family Hub / queue pages. The Admin Hub needs the first half only. Extract it, leaving re-exports so no existing import breaks.

**Files:**
- Create: `apps/members/lanes.py`
- Modify: `apps/members/family_hub.py` (delete the moved definitions, import them back)
- Test: `tests/admin_hub/test_lanes_module.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `apps.members.lanes.FamilyLaneStatus` — frozen dataclass with fields `key: str`, `label: str`, `badge: str`, `level: str`, `icon: str`, `next_action: str`, `urgency: int`
  - `apps.members.lanes.application_lane(application) -> FamilyLaneStatus`
  - `apps.members.lanes.agreement_lane(agreement) -> FamilyLaneStatus` (accepts `None`)
  - `apps.members.lanes.membership_lane(member) -> FamilyLaneStatus` (accepts `None`)
  - `apps.members.lanes.billing_lane(record) -> FamilyLaneStatus`
  - `apps.members.lanes.canonical_kit_size_label(obj) -> str`
  - The urgency constants `_URGENCY_INFORMATIONAL`, `_URGENCY_BILLING_PAYMENT_SYNC`, `_URGENCY_BILLING_PUSH`, `_URGENCY_BILLING_DRAFT`, `_URGENCY_AGREEMENT_NEEDS_ACTION`, `_URGENCY_APPLICATION_SUBMITTED`
  - `apps.members.family_hub` continues to expose every name above (re-export), so `tests/admin_hub/test_family_hub_*.py` keeps passing unchanged.

- [ ] **Step 1: Write the failing test**

Create `tests/admin_hub/test_lanes_module.py`:

```python
"""The lane derivation lives in apps.members.lanes; family_hub re-exports it."""

from __future__ import annotations

import pytest

from apps.members import family_hub, lanes

pytestmark = pytest.mark.django_db


_MOVED_NAMES = (
    "FamilyLaneStatus",
    "application_lane",
    "agreement_lane",
    "membership_lane",
    "billing_lane",
    "canonical_kit_size_label",
)


def test_lanes_module_exposes_the_moved_names():
    for name in _MOVED_NAMES:
        assert hasattr(lanes, name), f"apps.members.lanes is missing {name}"


def test_family_hub_re_exports_the_same_objects():
    """Existing imports from family_hub must keep working and resolve to the
    very same objects, so there is only one implementation."""
    for name in _MOVED_NAMES:
        assert getattr(family_hub, name) is getattr(lanes, name)


def test_family_hub_no_longer_defines_the_lanes_itself():
    """Guards against a copy-paste extraction that leaves both versions."""
    source = (
        __import__("pathlib").Path(family_hub.__file__).read_text(encoding="utf-8")
    )
    assert "def application_lane(" not in source
    assert "def agreement_lane(" not in source
    assert "def billing_lane(" not in source
    assert "class FamilyLaneStatus" not in source


def test_application_lane_behaviour_is_unchanged(submitted_application):
    lane = lanes.application_lane(submitted_application)
    assert lane.key == "application"
    assert lane.badge == "Iesniegts"
    assert lane.level == "pending"
    assert lane.next_action == "Apstiprināt"


def test_agreement_lane_handles_none():
    lane = lanes.agreement_lane(None)
    assert lane.key == "agreement"
    assert lane.level == "muted"


def test_draft_application_lane_is_muted(draft_application):
    lane = lanes.application_lane(draft_application)
    assert lane.badge == "Melnraksts"
    assert lane.level == "muted"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/admin_hub/test_lanes_module.py -v`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'apps.members.lanes'`

- [ ] **Step 3: Create the new module by moving code**

Create `apps/members/lanes.py`. Move — do not copy — these definitions out of `apps/members/family_hub.py`, in this order: the six `_URGENCY_*` constants, `FamilyLaneStatus`, `application_lane`, `agreement_lane`, `membership_lane`, `billing_lane`, `canonical_kit_size_label`. Keep every docstring and every branch byte-for-byte; this step must not change behaviour.

The module header:

```python
"""Per-object lane status derivation, shared by the Family Hub and Admin Hub.

Extracted from ``family_hub.py`` so that page assembly (there) and status
derivation (here) are separate concerns and both staff surfaces read one
implementation. Adding a new lane state means editing this file only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from apps.billing.models import BillingRecord
from apps.registrations.models import RegistrationApplication

if TYPE_CHECKING:
    from apps.agreements.models import Agreement
    from apps.members.models import Member
```

Check the moved bodies for names they reference (for example `BillingRecord`, `PaymentStatus`, `Agreement`) and add exactly the imports they need — no more. Run `uv run ruff check apps/members/lanes.py` to catch an unused or missing import.

- [ ] **Step 4: Re-export from family_hub**

In `apps/members/family_hub.py`, replace the deleted block with:

```python
# Lane derivation moved to apps/members/lanes.py (2026-09-07). Re-exported so
# existing callers and tests keep their import path.
from apps.members.lanes import (  # noqa: F401
    _URGENCY_AGREEMENT_NEEDS_ACTION,
    _URGENCY_APPLICATION_SUBMITTED,
    _URGENCY_BILLING_DRAFT,
    _URGENCY_BILLING_PAYMENT_SYNC,
    _URGENCY_BILLING_PUSH,
    _URGENCY_INFORMATIONAL,
    FamilyLaneStatus,
    agreement_lane,
    application_lane,
    billing_lane,
    canonical_kit_size_label,
    membership_lane,
)
```

- [ ] **Step 5: Run the new test plus the whole existing family-hub suite**

Run: `uv run pytest tests/admin_hub/ -q`
Expected: PASS — the new file passes and all pre-existing `test_family_hub_*.py` / `test_guardian_changelist.py` tests still pass. They are the real proof this refactor changed nothing.

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy .
git add apps/members/lanes.py apps/members/family_hub.py tests/admin_hub/test_lanes_module.py
git commit -m "refactor(members): extract lane derivation into apps/members/lanes.py"
```

---

### Task 2: Derive the 8-step pipeline

A loader that fetches the related rows, and a pure function that turns them into eight steps. Splitting them this way keeps the derivation testable without touching the database for every case.

**Files:**
- Create: `apps/admin_hub/__init__.py` (empty), `apps/admin_hub/apps.py`, `apps/admin_hub/pipeline.py`
- Test: `tests/admin_hub/test_pipeline.py`

**Interfaces:**
- Consumes: nothing from Task 1 (independent).
- Produces:
  - `PipelineStep` — frozen dataclass: `number: int`, `key: str`, `name: str`, `state: str`, `meta: str`. `state` is one of `"done"`, `"current"`, `"available"`, `"locked"`.
  - `PipelineObjects` — frozen dataclass: `application`, `member`, `agreement`, `billing_record`, `invoices: list`, `next_season_record`.
  - `STEP_DEFS: tuple[tuple[int, str, str], ...]`
  - `load_pipeline_objects(application) -> PipelineObjects` (hits the DB)
  - `build_pipeline(objects: PipelineObjects) -> list[PipelineStep]` (pure, exactly 8 entries, ordered by `number`)
  - `pipeline_progress(steps) -> tuple[int, int]` returning `(done_count, 8)`
  - `current_step(steps) -> PipelineStep | None`

- [ ] **Step 1: Write the failing test**

Create `tests/admin_hub/test_pipeline.py`:

```python
"""8-step pipeline derivation."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from apps.admin_hub.pipeline import (
    build_pipeline,
    current_step,
    load_pipeline_objects,
    pipeline_progress,
)

pytestmark = pytest.mark.django_db


def _states(steps):
    return {step.key: step.state for step in steps}


def test_pipeline_always_has_eight_ordered_steps(submitted_application):
    steps = build_pipeline(load_pipeline_objects(submitted_application))
    assert len(steps) == 8
    assert [step.number for step in steps] == list(range(1, 9))
    assert [step.key for step in steps] == [
        "verify",
        "approve",
        "agreement",
        "handover",
        "signed",
        "plan",
        "invoices",
        "next_season",
    ]


def test_submitted_application_is_on_step_one(submitted_application):
    steps = build_pipeline(load_pipeline_objects(submitted_application))
    states = _states(steps)
    assert states["verify"] == "current"
    assert states["approve"] == "available"
    assert states["agreement"] == "locked"
    assert pipeline_progress(steps) == (0, 8)
    assert current_step(steps).key == "verify"


def test_draft_application_has_nothing_available(draft_application):
    states = _states(build_pipeline(load_pipeline_objects(draft_application)))
    assert states["verify"] == "locked"
    assert states["approve"] == "locked"


def test_approved_application_completes_steps_one_and_two(approved_application):
    steps = build_pipeline(load_pipeline_objects(approved_application))
    states = _states(steps)
    assert states["verify"] == "done"
    assert states["approve"] == "done"
    done, total = pipeline_progress(steps)
    assert done >= 2
    assert total == 8


def test_sent_agreement_completes_handover(approved_application):
    from django.utils import timezone

    agreement = approved_application.approved_member.agreements.get(is_current=True)
    agreement.state = agreement.State.SENT
    agreement.sent_at = timezone.now()
    agreement.save(update_fields=["state", "sent_at"])

    states = _states(build_pipeline(load_pipeline_objects(approved_application)))
    assert states["agreement"] == "done"
    assert states["handover"] == "done"
    assert states["signed"] == "current"


def test_signed_agreement_completes_step_five(approved_application):
    from django.utils import timezone

    agreement = approved_application.approved_member.agreements.get(is_current=True)
    agreement.state = agreement.State.SIGNED
    agreement.sent_at = timezone.now()
    agreement.signed_at = timezone.now()
    agreement.save(update_fields=["state", "sent_at", "signed_at"])

    states = _states(build_pipeline(load_pipeline_objects(approved_application)))
    assert states["signed"] == "done"


def test_plan_step_needs_both_plan_and_first_month(approved_application, default_plan):
    agreement = approved_application.approved_member.agreements.get(is_current=True)
    agreement.billing_plan = default_plan
    agreement.first_billing_month = ""
    agreement.save(update_fields=["billing_plan", "first_billing_month"])

    states = _states(build_pipeline(load_pipeline_objects(approved_application)))
    assert states["plan"] != "done", "a plan without a first month is not finished"

    agreement.first_billing_month = "2026-09"
    agreement.save(update_fields=["first_billing_month"])
    states = _states(build_pipeline(load_pipeline_objects(approved_application)))
    assert states["plan"] == "done"


def test_invoices_step_is_done_only_when_every_invoice_is_pushed(
    approved_application, default_plan
):
    from apps.billing.models import BillingInvoice, BillingRecord

    member = approved_application.approved_member
    record = BillingRecord.objects.create(
        member=member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
    )
    first = BillingInvoice.objects.create(
        billing_record=record,
        sequence=1,
        due_date=datetime.date(2026, 9, 20),
        amount=Decimal("150.00"),
    )
    BillingInvoice.objects.create(
        billing_record=record,
        sequence=2,
        due_date=datetime.date(2026, 10, 20),
        amount=Decimal("150.00"),
        external_invoice_id="IN-2",
    )

    states = _states(build_pipeline(load_pipeline_objects(approved_application)))
    assert states["invoices"] != "done", "one un-pushed invoice blocks the step"

    first.external_invoice_id = "IN-1"
    first.save(update_fields=["external_invoice_id"])
    states = _states(build_pipeline(load_pipeline_objects(approved_application)))
    assert states["invoices"] == "done"


def test_only_one_step_is_current(approved_application):
    steps = build_pipeline(load_pipeline_objects(approved_application))
    assert [s.state for s in steps].count("current") <= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/admin_hub/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.admin_hub'`

- [ ] **Step 3: Create the app package**

`apps/admin_hub/__init__.py` — empty file.

`apps/admin_hub/apps.py`:

```python
"""Staff-facing Admin Hub UI. Owns no models: it renders and delegates."""

from django.apps import AppConfig


class AdminHubConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.admin_hub"
    verbose_name = "Admin Hub"
```

No `migrations/` directory — this app defines no models.

- [ ] **Step 4: Write the pipeline module**

`apps/admin_hub/pipeline.py`:

```python
"""Derivation of the eight-step registration pipeline.

The pipeline is *derived*, never stored. ``load_pipeline_objects`` does the
database work; ``build_pipeline`` is pure so every state combination is
testable without fixtures.

Each step's "done" test reads a value the domain actually persists. Step 4
("Izsniegts") keys off ``Agreement.sent_at`` rather than a download count,
because nothing in the domain counts downloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from apps.registrations.models import RegistrationApplication

if TYPE_CHECKING:
    from apps.agreements.models import Agreement
    from apps.billing.models import BillingInvoice, BillingRecord
    from apps.members.models import Member

DONE = "done"
CURRENT = "current"
AVAILABLE = "available"
LOCKED = "locked"

STEP_DEFS: tuple[tuple[int, str, str], ...] = (
    (1, "verify", "Datu pārbaude"),
    (2, "approve", "Apstiprināšana"),
    (3, "agreement", "Līgums"),
    (4, "handover", "Izsniegts"),
    (5, "signed", "Parakstītais"),
    (6, "plan", "Maksas plāns"),
    (7, "invoices", "Rēķini"),
    (8, "next_season", "Nākamā sezona"),
)


@dataclass(frozen=True)
class PipelineStep:
    number: int
    key: str
    name: str
    state: str
    meta: str


@dataclass(frozen=True)
class PipelineObjects:
    application: RegistrationApplication
    member: "Member | None"
    agreement: "Agreement | None"
    billing_record: "BillingRecord | None"
    invoices: list["BillingInvoice"]
    next_season_record: "BillingRecord | None"


def load_pipeline_objects(application: RegistrationApplication) -> PipelineObjects:
    """Fetch every row the pipeline derivation reads, in a bounded number of
    queries. Safe on a draft application, which has no member yet."""
    from apps.billing.models import BillingRecord

    member = application.approved_member
    agreement = None
    billing_record = None
    invoices: list[BillingInvoice] = []
    next_season_record = None

    if member is not None:
        agreement = (
            member.agreements.filter(is_current=True)
            .select_related("billing_plan")
            .first()
        )
        records = list(
            BillingRecord.objects.filter(member=member)
            .select_related("plan")
            .prefetch_related("invoices")
            .order_by("season")
        )
        current_season = agreement.billing_plan.season if (
            agreement is not None and agreement.billing_plan_id is not None
        ) else ""
        for record in records:
            if current_season and record.season == current_season:
                billing_record = record
            elif current_season and record.season > current_season:
                next_season_record = next_season_record or record
        if billing_record is None and records and not current_season:
            billing_record = records[0]
        if billing_record is not None:
            invoices = list(billing_record.invoices.all())

    return PipelineObjects(
        application=application,
        member=member,
        agreement=agreement,
        billing_record=billing_record,
        invoices=invoices,
        next_season_record=next_season_record,
    )


def _fmt_date(value) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def build_pipeline(objects: PipelineObjects) -> list[PipelineStep]:
    """Turn persisted state into eight ordered steps. Pure: no DB access."""
    from apps.agreements.models import Agreement

    status = RegistrationApplication.Status
    application = objects.application
    agreement = objects.agreement

    has_plan = agreement is not None and (
        agreement.billing_plan_id is not None and bool(agreement.first_billing_month)
    )
    pushed = [i for i in objects.invoices if i.external_invoice_id]

    done = {
        "verify": application.status in (status.APPROVED, status.REJECTED),
        "approve": application.status == status.APPROVED,
        "agreement": agreement is not None,
        "handover": agreement is not None and agreement.sent_at is not None,
        "signed": agreement is not None and agreement.state == Agreement.State.SIGNED,
        "plan": has_plan,
        "invoices": bool(objects.invoices) and len(pushed) == len(objects.invoices),
        "next_season": objects.next_season_record is not None,
    }
    available = {
        "verify": application.status in (status.SUBMITTED, status.FIX_REQUESTED),
        "approve": application.status == status.SUBMITTED,
        "agreement": objects.member is not None,
        "handover": agreement is not None,
        "signed": agreement is not None
        and agreement.state in (Agreement.State.GENERATED, Agreement.State.SENT),
        "plan": agreement is not None,
        "invoices": objects.billing_record is not None,
        "next_season": objects.billing_record is not None and done["signed"],
    }
    meta = {
        "verify": "",
        "approve": _fmt_date(application.reviewed_at) if done["approve"] else "",
        "agreement": _fmt_date(getattr(agreement, "generated_at", None)),
        "handover": _fmt_date(getattr(agreement, "sent_at", None)),
        "signed": _fmt_date(getattr(agreement, "signed_at", None)),
        "plan": agreement.first_billing_month if has_plan else "",
        "invoices": (
            f"{len(pushed)}/{len(objects.invoices)} izrakstīti"
            if objects.invoices
            else ""
        ),
        "next_season": (
            objects.next_season_record.season if objects.next_season_record else ""
        ),
    }

    steps: list[PipelineStep] = []
    current_claimed = False
    for number, key, name in STEP_DEFS:
        if done[key]:
            state = DONE
        elif available[key] and not current_claimed:
            state = CURRENT
            current_claimed = True
        elif available[key]:
            state = AVAILABLE
        else:
            state = LOCKED
        steps.append(
            PipelineStep(number=number, key=key, name=name, state=state, meta=meta[key])
        )
    return steps


def pipeline_progress(steps: list[PipelineStep]) -> tuple[int, int]:
    return (sum(1 for step in steps if step.state == DONE), len(STEP_DEFS))


def current_step(steps: list[PipelineStep]) -> PipelineStep | None:
    for step in steps:
        if step.state == CURRENT:
            return step
    return None
```

- [ ] **Step 5: Register the app so `apps.admin_hub` imports cleanly**

In `fk_cesis_mms/settings.py`, add `"apps.admin_hub",` to `INSTALLED_APPS` immediately after `"apps.analytics",`.

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/admin_hub/test_pipeline.py -v`
Expected: PASS, all cases.

The `approved_application` fixture calls `apps.registrations.services.approve_application`, which creates both the Member and the Agreement — so `member.agreements.get(is_current=True)` resolves. If it raises, something in `approve_application` changed; fix the cause, do not weaken the assertion.

- [ ] **Step 7: Verify and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy .
git add apps/admin_hub fk_cesis_mms/settings.py tests/admin_hub/test_pipeline.py
git commit -m "feat(admin-hub): derive the eight-step registration pipeline"
```

---

### Task 3: App shell, base template, and the application queue (S1)

**Files:**
- Create: `apps/admin_hub/urls.py`, `apps/admin_hub/views.py`, `apps/admin_hub/queries.py`
- Create: `templates/admin_hub/base_hub.html`, `templates/admin_hub/_step_rail.html`, `templates/admin_hub/queue.html`
- Create: `static/admin_hub/hub.css`
- Modify: `fk_cesis_mms/urls.py`
- Test: `tests/admin_hub/test_hub_queue.py`

**Interfaces:**
- Consumes: `apps.admin_hub.pipeline.{load_pipeline_objects, build_pipeline, pipeline_progress, current_step}` (Task 2); `apps.registrations.presentation.active_documents_by_kind`.
- Produces:
  - URL namespace `admin_hub` with names `queue`, and (added by later tasks) `cockpit`, `agreement`, `billing`, `invoices`.
  - `apps.admin_hub.queries.QUEUE_TABS: dict[str, str]` mapping tab slug → Latvian label.
  - `apps.admin_hub.queries.queue_rows(tab: str) -> list[QueueRow]` where `QueueRow` is a frozen dataclass with `application`, `steps`, `done`, `total`, `next_name`, `documents: dict[str, object]`, `is_aging: bool`.
  - `templates/admin_hub/base_hub.html` blocks, all used by later tasks:
    `hub_title`, `hub_page_class`, `hub_steprail`, `hub_nav_extra`,
    `hub_content`, `hub_actionbar`, `hub_scripts`. It also expects a
    `hub_section` context value (`"queue"` or `"invoices"`) to mark the active
    nav link.

- [ ] **Step 1: Write the failing test**

Create `tests/admin_hub/test_hub_queue.py`:

```python
"""Application queue page."""

from __future__ import annotations

import datetime

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


def test_queue_requires_staff(client):
    response = client.get(reverse("admin_hub:queue"))
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_queue_rejects_a_signed_in_non_staff_user(client, django_user_model):
    django_user_model.objects.create_user(username="parent_ish", password="x")
    client.login(username="parent_ish", password="x")
    response = client.get(reverse("admin_hub:queue"))
    assert response.status_code == 302, "non-staff must not reach the hub"


def test_queue_lists_a_submitted_application(client, reviewer, submitted_application):
    client.force_login(reviewer)
    response = client.get(reverse("admin_hub:queue"))
    assert response.status_code == 200
    body = response.content.decode()
    assert submitted_application.member_full_name in body
    assert "Pieteikumu rinda" in body


def test_queue_shows_pipeline_progress_and_next_action(
    client, reviewer, submitted_application
):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue")).content.decode()
    assert "0/8" in body
    assert "Datu pārbaude" in body


def test_queue_default_tab_hides_drafts(client, reviewer, draft_application):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue")).content.decode()
    assert draft_application.member_full_name not in body


def test_queue_all_tab_shows_drafts(client, reviewer, draft_application):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue"), {"tab": "visi"}).content.decode()
    assert draft_application.member_full_name in body


def test_queue_orders_newest_submission_first(client, reviewer, submitted_application):
    from django.utils import timezone
    from apps.registrations.models import RegistrationApplication

    older = RegistrationApplication.objects.create(
        claimed_email="older@example.lv",
        guardian=submitted_application.guardian,
        parent_account=submitted_application.parent_account,
        member_full_name="Older Child",
        status=RegistrationApplication.Status.SUBMITTED,
        submitted_at=timezone.now() - datetime.timedelta(days=10),
    )
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue")).content.decode()
    assert body.index(submitted_application.member_full_name) < body.index(
        older.member_full_name
    )


def test_queue_flags_an_application_waiting_over_three_days(
    client, reviewer, submitted_application
):
    from django.utils import timezone

    submitted_application.submitted_at = timezone.now() - datetime.timedelta(days=4)
    submitted_application.save(update_fields=["submitted_at"])
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue")).content.decode()
    assert "qrow--aging" in body


def test_queue_unknown_tab_falls_back_to_default(client, reviewer, submitted_application):
    client.force_login(reviewer)
    response = client.get(reverse("admin_hub:queue"), {"tab": "../etc/passwd"})
    assert response.status_code == 200
    assert submitted_application.member_full_name in response.content.decode()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/admin_hub/test_hub_queue.py -v`
Expected: FAIL — `NoReverseMatch: 'admin_hub' is not a registered namespace`

- [ ] **Step 3: Write the queue query layer**

`apps/admin_hub/queries.py`:

```python
"""Queryset + row assembly for the Admin Hub list pages.

Kept out of views.py so the row shape is unit-testable and the views stay
thin. Row counts here are club-scale (hundreds), so the per-row pipeline
lookup is deliberate: correctness over a premature join.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.utils import timezone

from apps.admin_hub.pipeline import (
    PipelineStep,
    build_pipeline,
    current_step,
    load_pipeline_objects,
    pipeline_progress,
)
from apps.registrations.models import RegistrationApplication
from apps.registrations.presentation import active_documents_by_kind

AGING_THRESHOLD = datetime.timedelta(days=3)

QUEUE_TABS: dict[str, str] = {
    "jaizskata": "Jāizskata",
    "jalabo": "Jālabo",
    "procesa": "Procesā",
    "pabeigti": "Pabeigti",
    "noraiditi": "Noraidīti",
    "visi": "Visi",
}
DEFAULT_TAB = "jaizskata"


@dataclass(frozen=True)
class QueueRow:
    application: RegistrationApplication
    steps: list[PipelineStep]
    done: int
    total: int
    next_name: str
    documents: dict[str, object]
    is_aging: bool


def normalize_tab(raw: str | None) -> str:
    """Never trust the query string: an unknown tab falls back to the default."""
    return raw if raw in QUEUE_TABS else DEFAULT_TAB


def _tab_queryset(tab: str):
    status = RegistrationApplication.Status
    base = RegistrationApplication.objects.select_related(
        "guardian",
        "parent_account",
        "approved_member",
        "approved_member__training_group",
    )
    if tab == "jaizskata":
        return base.filter(status=status.SUBMITTED).order_by("-submitted_at")
    if tab == "jalabo":
        return base.filter(status=status.FIX_REQUESTED).order_by("-updated_at")
    if tab == "procesa":
        return base.filter(
            status=status.APPROVED, approved_member__isnull=False
        ).order_by("-reviewed_at")
    if tab == "pabeigti":
        return base.filter(status=status.APPROVED).order_by("-reviewed_at")
    if tab == "noraiditi":
        return base.filter(status=status.REJECTED).order_by("-reviewed_at")
    return base.order_by("-created_at")


def queue_rows(tab: str) -> list[QueueRow]:
    now = timezone.now()
    rows: list[QueueRow] = []
    for application in _tab_queryset(tab):
        steps = build_pipeline(load_pipeline_objects(application))
        done, total = pipeline_progress(steps)
        step = current_step(steps)
        is_aging = bool(
            application.status == RegistrationApplication.Status.SUBMITTED
            and application.submitted_at
            and now - application.submitted_at > AGING_THRESHOLD
        )
        rows.append(
            QueueRow(
                application=application,
                steps=steps,
                done=done,
                total=total,
                next_name=step.name if step else "",
                documents=active_documents_by_kind(application),
                is_aging=is_aging,
            )
        )
    return rows


def tab_counts() -> dict[str, int]:
    return {tab: _tab_queryset(tab).count() for tab in QUEUE_TABS}
```

- [ ] **Step 4: Write the view and URLs**

`apps/admin_hub/views.py`:

```python
"""Admin Hub views. Every page is staff-only and renders derived state; all
mutations POST to the existing Django admin action endpoints."""

from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from apps.admin_hub import queries


@staff_member_required
def queue_view(request):
    tab = queries.normalize_tab(request.GET.get("tab"))
    return render(
        request,
        "admin_hub/queue.html",
        {
            "tab": tab,
            "tabs": queries.QUEUE_TABS,
            "tab_counts": queries.tab_counts(),
            "rows": queries.queue_rows(tab),
        },
    )
```

`apps/admin_hub/urls.py`:

```python
from django.urls import path

from apps.admin_hub import views

app_name = "admin_hub"

urlpatterns = [
    path("pieteikumi/", views.queue_view, name="queue"),
]
```

In `fk_cesis_mms/urls.py`, add this line **above** the `path("admin/", admin.site.urls)` entry so the hub prefix is matched first:

```python
    path("hub/", include("apps.admin_hub.urls")),
```

- [ ] **Step 5: Port the stylesheet**

```bash
mkdir -p static/admin_hub
cp style-guide/admin/hub.css static/admin_hub/hub.css
```

Add this comment as the second line of `static/admin_hub/hub.css`, after the existing header comment:

```css
/* Ported from style-guide/admin/hub.css. Keep the two in sync: the
   style-guide copy is the reviewable mock-up, this one ships. */
```

- [ ] **Step 6: Write the base template**

`templates/admin_hub/base_hub.html`:

```html
{% load static %}<!DOCTYPE html>
<html lang="lv">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block hub_title %}FK Cēsis · Administrācija{% endblock %}</title>
  <link rel="icon" type="image/png" href="{% static 'img/favicon.png' %}">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Anton&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{% static 'admin_hub/hub.css' %}">
</head>
<body>
<header class="hub-header">
  <div class="hub-header__inner">
    <div class="hub-brand">
      <img src="{% static 'img/fk-cesis-logo.png' %}" alt="FK Cēsis">
      <div>
        <h1 class="hub-brand__title anton">FK Cēsis</h1>
        <div class="hub-brand__sub">Administrācija</div>
      </div>
    </div>
    <nav class="hub-nav">
      <a href="{% url 'admin_hub:queue' %}" class="{% if hub_section == 'queue' %}is-active{% endif %}">Pieteikumi</a>
      {% block hub_nav_extra %}{% endblock %}
      <a href="{% url 'admin:index' %}">Django admin</a>
    </nav>
    <div class="hub-header__right">
      <div class="user-pill">
        <span class="user-avatar">{{ request.user.get_username|slice:":2"|upper }}</span>
        <span>{{ request.user.get_username }}</span>
      </div>
    </div>
  </div>
</header>

{% block hub_steprail %}{% endblock %}

<main class="hub-page {% block hub_page_class %}{% endblock %}">
  {% if messages %}
    {% for message in messages %}
      <div class="callout {% if message.tags == 'error' %}callout--danger{% elif message.tags == 'warning' %}callout--warn{% endif %}" style="margin-bottom:16px">
        <span class="callout__icon">i</span><span>{{ message }}</span>
      </div>
    {% endfor %}
  {% endif %}
  {% block hub_content %}{% endblock %}
</main>

{% block hub_actionbar %}{% endblock %}
{% block hub_scripts %}{% endblock %}
</body>
</html>
```

`templates/admin_hub/_step_rail.html`:

```html
{% comment %}Expects `steps` (list of PipelineStep) and optional `step_urls`
(dict of step key -> url). A step without a URL renders as a non-link.{% endcomment %}
<div class="steprail">
  <div class="steprail__inner">
    {% for step in steps %}
      {% if step.state == "done" %}{% with cls="step step--done" %}{% include "admin_hub/_step_rail_item.html" %}{% endwith %}
      {% elif step.state == "current" %}{% with cls="step step--current" %}{% include "admin_hub/_step_rail_item.html" %}{% endwith %}
      {% elif step.state == "available" %}{% with cls="step" %}{% include "admin_hub/_step_rail_item.html" %}{% endwith %}
      {% else %}{% with cls="step step--locked" %}{% include "admin_hub/_step_rail_item.html" %}{% endwith %}
      {% endif %}
    {% endfor %}
  </div>
</div>
```

`templates/admin_hub/_step_rail_item.html`:

```html
{% comment %}Expects `step` and `cls`. The rail is a status display, not a
navigation control - the page's own buttons move the reviewer between steps.
{% endcomment %}
<span class="{{ cls }}">
  <span class="step__num">{% if step.state == "done" %}&#10003;{% else %}{{ step.number }}{% endif %}</span>
  <span class="step__txt">
    <span class="step__name">{{ step.name }}</span>
    <span class="step__meta">{{ step.meta|default:"—" }}</span>
  </span>
</span>
```

- [ ] **Step 7: Add the dict-lookup template filter**

Django templates cannot index a dict by a loop variable, and the tab counts are
keyed by tab slug. Create `apps/admin_hub/templatetags/__init__.py` (empty file)
and `apps/admin_hub/templatetags/hub_tags.py`:

```python
"""Template filters for the Admin Hub."""

from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    """Dict lookup by a variable key - Django templates cannot do this."""
    if not hasattr(mapping, "get"):
        return ""
    return mapping.get(key, "")
```

- [ ] **Step 8: Write the queue template**

`templates/admin_hub/queue.html`:

```html
{% extends "admin_hub/base_hub.html" %}
{% load hub_tags %}

{% block hub_title %}FK Cēsis Admin — Pieteikumu rinda{% endblock %}

{% block hub_content %}
  <div class="page-head">
    <div>
      <h1 class="page-title">Pieteikumu rinda</h1>
      <p class="page-sub">Jaunākie iesniegtie pieteikumi augšā. Sarkanā svītra — iesniegts pirms vairāk nekā 3 dienām.</p>
    </div>
  </div>

  <nav class="tabs">
    {% for slug, label in tabs.items %}
      <a href="?tab={{ slug }}" class="{% if slug == tab %}is-active{% endif %}">
        {{ label }} <span class="tab-count">{{ tab_counts|get_item:slug }}</span>
      </a>
    {% endfor %}
  </nav>

  <div class="queue">
    {% for row in rows %}
      <article class="qrow{% if row.is_aging %} qrow--aging{% endif %}">
        <div class="qperson">
          <div class="qavatar">{{ row.application.member_full_name|slice:":1"|upper }}</div>
          <div>
            <h2 class="qname anton">{{ row.application.member_full_name|default:"Bez vārda" }}</h2>
            <div class="qmeta">
              <span>Dz. <strong>{{ row.application.member_birth_date|date:"d.m.Y"|default:"—" }}</strong></span>
              <span>Vecāks: <strong>{{ row.application.guardian_name|default:"—" }}</strong></span>
            </div>
          </div>
        </div>
        <div>
          <span class="cell-label">Statuss</span>
          <span class="badge badge--submitted">{{ row.application.get_status_display }}</span>
          <div class="pipe__next">{{ row.application.submitted_at|date:"d.m.Y H:i"|default:"—" }}</div>
        </div>
        <div class="qdocs">
          <span class="cell-label">Dokumenti</span>
          <div class="docdots">
            {% for kind, doc in row.documents.items %}
              <span class="docdot{% if not doc %} docdot--missing{% endif %}">{{ kind|slice:":1"|upper }}</span>
            {% endfor %}
          </div>
        </div>
        <div class="progress-wrap">
          <span class="cell-label">Process</span>
          <div class="pipe">
            <div class="pipe__segs">
              {% for step in row.steps %}
                <span class="pipe__seg{% if step.state == 'done' %} pipe__seg--done{% elif step.state == 'current' %} pipe__seg--current{% endif %}"></span>
              {% endfor %}
            </div>
            <span class="pipe__count">{{ row.done }}/{{ row.total }}</span>
          </div>
          {% if row.next_name %}
            <div class="pipe__next">Nākamais: <strong>{{ row.next_name }}</strong></div>
          {% else %}
            <div class="pipe__next">Nav darbību</div>
          {% endif %}
        </div>
        <div class="qactions">
          <a class="btn btn-red" href="{% url 'admin:registrations_registrationapplication_change' row.application.pk %}">Izskatīt →</a>
        </div>
      </article>
    {% empty %}
      <div class="card"><div class="card__body">
        <p class="hint">Šajā skatā nav pieteikumu.</p>
      </div></div>
    {% endfor %}
  </div>
{% endblock %}
```

The `Izskatīt →` link points at the Django admin change page for now; Task 5 repoints it at `admin_hub:cockpit`.

- [ ] **Step 9: Run test to verify it passes**

Run: `uv run pytest tests/admin_hub/test_hub_queue.py -v`
Expected: PASS.

- [ ] **Step 10: Look at the page**

Run: `uv run python manage.py runserver` and open `http://127.0.0.1:8000/hub/pieteikumi/` as a staff user. Compare against `style-guide/admin/01-pieteikumu-rinda.html` side by side. Fix layout drift in `static/admin_hub/hub.css` and mirror the fix back into `style-guide/admin/hub.css`.

- [ ] **Step 11: Verify and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy .
git add apps/admin_hub templates/admin_hub static/admin_hub fk_cesis_mms/urls.py tests/admin_hub/test_hub_queue.py
git commit -m "feat(admin-hub): add hub shell and application queue page"
```

---
### Task 3 amendments after review (2026-09-07)

Task 3's review found four Important defects **in this plan's own Step 3 and
Step 8 code**, plus three Minors. All were ruled on and fixed in commits
`59ea833` and the round-2 follow-up. The code blocks above are superseded on
these five points — the shipped implementation in `apps/admin_hub/queries.py`,
`apps/admin_hub/views.py` and `templates/admin_hub/queue.html` is authoritative.

1. **Status badge was hardcoded.** `queue.html` rendered
   `class="badge badge--submitted"` on every row, so a rejected application
   showed in "submitted" green. Fixed with a `STATUS_BADGE_CLASSES` map in
   `queries.py` (business logic stays out of templates), surfaced as
   `QueueRow.status_badge_class` with a `badge--neutral` fallback.

2. **Document dots collided.** The dot letter came from the internal
   `Document.Kind` value, giving `G`/`M`/`M` — two indistinguishable dots — and
   the mock-up's `title` tooltip was dropped. Fixed with an explicit
   `DOC_KIND_BADGES` map to `V` (Vecāka ID) / `B` (Bērna ID) / `P` (Portrets);
   `QueueRow.documents` is now a `list[dict]` of `{letter, title, present}` in a
   fixed guardian/member/portrait order.

3. **Two tabs were not disjoint, and one was misnamed.** "Procesā" and
   "Pabeigti" were both `status=APPROVED`; the extra `approved_member__isnull=False`
   is satisfied by every approved row, so they overlapped almost entirely. The
   split is now on current-agreement-signed state, and the second tab is
   **renamed `pabeigti`/"Pabeigti" → `parakstiti`/"Parakstīti"** — a signed
   agreement still has invoice and next-season steps outstanding, so calling that
   bucket "completed" would be false. This deliberately overrides the label in
   `style-guide/admin/01-pieteikumu-rinda.html`.

   Both tabs are built from **one shared subquery** of signed-member ids, so they
   are exact complements by construction:

   ```python
   signed_members = Agreement.objects.filter(
       is_current=True, state=Agreement.State.SIGNED
   ).values("member_id")
   ```

   A two-field `exclude()` must NOT be used here. Django compiles a multi-valued
   `exclude()` into `NOT (EXISTS(cond1) AND EXISTS(cond2))` as two *independent*
   subqueries, so `is_current` and `state=SIGNED` would not have to hold on the
   same `Agreement` row — a member with a current unsigned agreement plus a
   historical `is_current=False, state=SIGNED` row would vanish from both tabs.
   Round 1 shipped that bug; round 2 fixed it and added a regression test.

4. **Real N+1 with no pagination.** `queue_rows` cost one
   `active_documents_by_kind` plus up to ~3 `load_pipeline_objects` queries per
   row, and this plan's `queue.html` dropped the `.pager` block the mock-up
   actually has — so the archival tabs would query every historical row forever.
   Fixed with `Paginator` at `PAGE_SIZE = 25`: `queue_rows(tab)` is replaced by
   `queue_page(tab, page_number) -> (rows, page_obj)`, which paginates the
   **queryset before building rows** so only the current page's rows are built.
   An invalid or out-of-range `?page=` falls back to page 1 rather than raising.
   `tab_counts()`'s six `.count()` queries are left as they are — cheap, and
   they do not scale with row count.

5. **`hub_section` was missing** from `queue_view`'s context, leaving
   `base_hub.html`'s own documented nav contract unfulfilled. Now set to
   `"queue"`.

**Test-quality note for later tasks.** Three separate reviewers found tests in
this plan that asserted nothing meaningful — a `"" not in body` comparison that
can never pass, a name/assertion mismatch, and an unused import that failed the
ruff gate. When implementing Tasks 4-8, treat the test code in the brief with the
same skepticism as the implementation code: if a test would pass against a broken
implementation, say so rather than shipping it.

---

### Task 4: Field readout for the review cockpit

The right-hand pane of the cockpit. Pure data assembly, no rendering — so every provenance and default-checked rule is unit-testable.

**Files:**
- Create: `apps/admin_hub/fields.py`
- Test: `tests/admin_hub/test_hub_fields.py`

**Interfaces:**
- Consumes: `apps.members.lanes.canonical_kit_size_label` (Task 1).
- Produces:
  - `HubField` — frozen dataclass: `key: str`, `label: str`, `value: str`, `source_label: str`, `source_tone: str`, `note: str`, `checkable: bool`, `default_checked: bool`
  - `HubFieldGroup` — frozen dataclass: `title: str`, `hint: str`, `fields: list[HubField]`
  - `STAFF_SOURCE_LABELS: dict[str, str]`, `STAFF_SOURCE_TONES: dict[str, str]`
  - `build_field_groups(application) -> list[HubFieldGroup]`
  - `checkable_keys(groups) -> list[str]`

**Two rules that are easy to get wrong:**

1. **Provenance labels are staff-facing and must not reuse `SOURCE_LABEL_MAP`.** That map in `apps/registrations/presentation.py` is written for the parent ("Ievadījāt jūs" = *you entered*), which is nonsense on a staff screen. This module defines its own labels.
2. **There is no "parent edited this" state.** `field_sources` is set once and never reset when a parent overwrites an OCR-filled value (see `_apply_field_sources` in `apps/integrations/tasks.py`, which returns early for any non-draft application, and `_apply_field_sources_for_guardian_email` in `apps/registrations/services.py`, which only fills keys that are absent). Any label claiming an edit would be a lie. The five real values are `ocr_guardian_identity`, `ocr_member_identity`, `manual_only`, `derived_system_filled`, `review_hint_extracted`.

- [ ] **Step 1: Write the failing test**

Create `tests/admin_hub/test_hub_fields.py`:

```python
"""Field readout assembly for the review cockpit."""

from __future__ import annotations

import pytest

from apps.admin_hub.fields import (
    STAFF_SOURCE_LABELS,
    build_field_groups,
    checkable_keys,
)

pytestmark = pytest.mark.django_db


def _flat(groups):
    return {field.key: field for group in groups for field in group.fields}


def test_groups_are_in_review_order(submitted_application):
    groups = build_field_groups(submitted_application)
    assert [group.title for group in groups] == [
        "Bērns",
        "Vecāks / likumiskais pārstāvis",
        "Ekipējums un izvēles",
        "Piekrišanas",
    ]


def test_exactly_ten_fields_are_checkable(submitted_application):
    keys = checkable_keys(build_field_groups(submitted_application))
    assert keys == [
        "member_full_name",
        "member_personal_id",
        "member_birth_date",
        "member_actual_address",
        "guardian_first_name",
        "guardian_personal_id",
        "guardian_declared_address",
        "guardian_phone",
        "guardian_email",
        "member_kit_size_shirt",
    ]


def test_kit_size_is_a_single_field(submitted_application):
    fields = _flat(build_field_groups(submitted_application))
    assert fields["member_kit_size_shirt"].label == "Formas izmērs"
    assert "member_kit_size_shorts" not in fields, (
        "shirt/shorts were collapsed into one field by commit 21945c4"
    )


def test_guardian_email_is_pre_checked_as_system_verified(submitted_application):
    fields = _flat(build_field_groups(submitted_application))
    email = fields["guardian_email"]
    assert email.default_checked is True
    assert email.checkable is True, "a reviewer may still clear it"
    assert email.source_tone == "verified"


def test_only_the_email_is_pre_checked(submitted_application):
    groups = build_field_groups(submitted_application)
    pre_checked = [
        field.key
        for group in groups
        for field in group.fields
        if field.default_checked
    ]
    assert pre_checked == ["guardian_email"]


def test_email_is_not_pre_checked_without_a_verified_account(submitted_application):
    """parent_account is the only proof the address is reachable."""
    submitted_application.parent_account = None
    submitted_application.save(update_fields=["parent_account"])
    fields = _flat(build_field_groups(submitted_application))
    assert fields["guardian_email"].default_checked is False


def test_ocr_sourced_field_gets_the_document_tone(submitted_application):
    submitted_application.field_sources = {
        "member_full_name": "ocr_member_identity"
    }
    submitted_application.save(update_fields=["field_sources"])
    fields = _flat(build_field_groups(submitted_application))
    assert fields["member_full_name"].source_label == "No dokumenta"
    assert fields["member_full_name"].source_tone == "doc"


def test_review_hint_gets_the_attention_tone(submitted_application):
    submitted_application.field_sources = {
        "guardian_phone": "review_hint_extracted"
    }
    submitted_application.save(update_fields=["field_sources"])
    fields = _flat(build_field_groups(submitted_application))
    assert fields["guardian_phone"].source_tone == "flag"


def test_no_label_ever_claims_the_parent_edited_a_value():
    """field_sources cannot express an edit - see the module docstring."""
    for label in STAFF_SOURCE_LABELS.values():
        assert "labo" not in label.lower(), f"{label!r} implies an edit"


def test_unknown_source_value_degrades_quietly(submitted_application):
    submitted_application.field_sources = {"member_full_name": "something_new"}
    submitted_application.save(update_fields=["field_sources"])
    fields = _flat(build_field_groups(submitted_application))
    assert fields["member_full_name"].source_label == ""
    assert fields["member_full_name"].source_tone == ""


def test_empty_value_renders_as_a_dash_not_none(submitted_application):
    submitted_application.referral_code = ""
    submitted_application.save(update_fields=["referral_code"])
    fields = _flat(build_field_groups(submitted_application))
    assert fields["referral_code"].value == ""
    assert fields["referral_code"].checkable is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/admin_hub/test_hub_fields.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.admin_hub.fields'`

- [ ] **Step 3: Write the module**

`apps/admin_hub/fields.py`:

```python
"""Field readout for the review cockpit: what the parent submitted, grouped
for eyeball comparison against the uploaded document.

No machine comparison happens here, deliberately. The parent-facing form
pre-fills from OCR and the parent may correct a misread value before
submitting, so a value that differs from the document is not evidence of an
error - it is often evidence the parent fixed one.

Provenance labels are staff-facing and intentionally separate from
``apps.registrations.presentation.SOURCE_LABEL_MAP``, which is phrased for
the parent. Note what these labels do NOT say: ``field_sources`` is written
once and never reset when a parent overwrites an OCR-filled value, so no
stored value can mean "the parent edited this".
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.members.lanes import canonical_kit_size_label
from apps.registrations.models import RegistrationApplication

STAFF_SOURCE_LABELS: dict[str, str] = {
    "ocr_guardian_identity": "No dokumenta",
    "ocr_member_identity": "No dokumenta",
    "manual_only": "Ievadīts",
    "derived_system_filled": "No pārbaudīta konta",
    "review_hint_extracted": "Jāpārbauda",
}
STAFF_SOURCE_TONES: dict[str, str] = {
    "ocr_guardian_identity": "doc",
    "ocr_member_identity": "doc",
    "manual_only": "typed",
    "derived_system_filled": "typed",
    "review_hint_extracted": "flag",
}


@dataclass(frozen=True)
class HubField:
    key: str
    label: str
    value: str
    source_label: str = ""
    source_tone: str = ""
    note: str = ""
    checkable: bool = True
    default_checked: bool = False


@dataclass(frozen=True)
class HubFieldGroup:
    title: str
    hint: str
    fields: list[HubField]


def _fmt_date(value) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def _fmt_datetime(value) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if value else ""


def build_field_groups(
    application: RegistrationApplication,
) -> list[HubFieldGroup]:
    sources = application.field_sources or {}

    def field(
        key: str,
        label: str,
        value: object,
        *,
        source_key: str | None = None,
        note: str = "",
        checkable: bool = True,
        default_checked: bool = False,
        source_label: str | None = None,
        source_tone: str | None = None,
    ) -> HubField:
        raw_source = sources.get(source_key if source_key else key, "")
        return HubField(
            key=key,
            label=label,
            value="" if value is None else str(value),
            source_label=(
                source_label
                if source_label is not None
                else STAFF_SOURCE_LABELS.get(raw_source, "")
            ),
            source_tone=(
                source_tone
                if source_tone is not None
                else STAFF_SOURCE_TONES.get(raw_source, "")
            ),
            note=note,
            checkable=checkable,
            default_checked=default_checked,
        )

    same_address_note = (
        'Atzīmēts "tā pati adrese kā vecākam"'
        if application.member_same_address_as_guardian
        else ""
    )
    # A non-null parent_account IS the proof the address is reachable: the
    # one-time-code flow is what sets it. There is no separate boolean.
    email_verified = application.parent_account_id is not None

    child = HubFieldGroup(
        title="Bērns",
        hint="pret bērna ID",
        fields=[
            field("member_full_name", "Vārds, uzvārds", application.member_full_name),
            field("member_personal_id", "Personas kods", application.member_personal_id),
            field(
                "member_birth_date",
                "Dzimšanas datums",
                _fmt_date(application.member_birth_date),
            ),
            field(
                "member_actual_address",
                "Faktiskā adrese",
                application.member_actual_address,
                note=same_address_note,
            ),
        ],
    )

    guardian = HubFieldGroup(
        title="Vecāks / likumiskais pārstāvis",
        hint="pret vecāka ID",
        fields=[
            field(
                "guardian_first_name",
                "Vārds, uzvārds",
                application.guardian_name,
            ),
            field(
                "guardian_personal_id",
                "Personas kods",
                application.guardian_pid,
            ),
            field(
                "guardian_declared_address",
                "Adrese",
                application.guardian_address,
            ),
            field(
                "guardian_phone",
                "Tālrunis",
                application.guardian_contact_phone,
            ),
            field(
                "guardian_email",
                "E-pasts",
                application.guardian_contact_email,
                default_checked=email_verified,
                source_label="Sistēma apstiprinājusi" if email_verified else "",
                source_tone="verified" if email_verified else "",
                note=(
                    "Vienreizējais kods · nav jāpārbauda manuāli"
                    if email_verified
                    else "Konts vēl nav apstiprināts"
                ),
            ),
        ],
    )

    kit = HubFieldGroup(
        title="Ekipējums un izvēles",
        hint="bez dokumenta",
        fields=[
            field(
                "member_kit_size_shirt",
                "Formas izmērs",
                canonical_kit_size_label(application),
                note="Viens izmērs kreklam un šortiem",
            ),
            field(
                "preferred_agreement_signing",
                "Parakstīšanas veids",
                application.get_preferred_agreement_signing_display(),
                note="Nosaka 3.–5. soli",
                checkable=False,
            ),
            field(
                "preferred_payment_mode",
                "Maksājuma veids",
                application.get_preferred_payment_mode_display(),
                note="Nosaka 6. soļa priekšatlasi",
                checkable=False,
            ),
            field(
                "support_club_instead_of_multi_child_discount",
                "Vairāku bērnu atlaide",
                _discount_choice_label(
                    application.support_club_instead_of_multi_child_discount
                ),
                checkable=False,
            ),
            field(
                "referral_code",
                "Ieteikuma kods",
                application.referral_code,
                checkable=False,
            ),
        ],
    )

    consents = HubFieldGroup(
        title="Piekrišanas",
        hint="",
        fields=[
            field(
                "personal_data_consent",
                "Personas datu apstrāde",
                _fmt_datetime(application.personal_data_consent_at),
                note=(
                    f"Versija {application.personal_data_consent_version}"
                    if application.personal_data_consent_version
                    else "Nav piekrišanas"
                ),
                checkable=False,
            ),
        ],
    )

    return [child, guardian, kit, consents]


def _discount_choice_label(value: bool | None) -> str:
    if value is None:
        return ""
    return "Atteicās — atbalsta klubu" if value else "Piemēro atlaidi"


def checkable_keys(groups: list[HubFieldGroup]) -> list[str]:
    return [f.key for g in groups for f in g.fields if f.checkable]
```

- [ ] **Step 4: Add the `verified` badge tone to the stylesheet**

`hub.css` defines `src-badge--doc`, `--edited` and `--typed`. The email row needs a green one. Append to **both** `static/admin_hub/hub.css` and `style-guide/admin/hub.css`, directly after the `.src-badge--typed` rule:

```css
.src-badge--verified { color: var(--success); background: var(--success-bg); }
.src-badge--flag { color: var(--warn); background: var(--warn-bg); }
```

The `--flag` tone is what `review_hint_extracted` renders as; `--edited` is now unused by any code path and may be left in place or deleted.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/admin_hub/test_hub_fields.py -v`
Expected: PASS.

If `test_exactly_ten_fields_are_checkable` fails on ordering, fix `build_field_groups`, not the test — the order is the review order a human reads down the page.

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy .
git add apps/admin_hub/fields.py static/admin_hub/hub.css style-guide/admin/hub.css tests/admin_hub/test_hub_fields.py
git commit -m "feat(admin-hub): assemble the cockpit field readout"
```

---

### Task 5: Review cockpit (S2) — viewer, readout, approve

**Files:**
- Create: `templates/admin_hub/cockpit.html`, `templates/admin_hub/_viewer.html`, `templates/admin_hub/_field_group.html`
- Create: `static/admin_hub/viewer.js`, `static/admin_hub/checklist.js`
- Modify: `apps/admin_hub/views.py`, `apps/admin_hub/urls.py`, `templates/admin_hub/queue.html`
- Modify: `apps/registrations/admin.py` (`approve_view` — honour `next`)
- Test: `tests/admin_hub/test_hub_cockpit.py`, `tests/admin_hub/test_approve_next_redirect.py`

**Interfaces:**
- Consumes: `build_field_groups`, `checkable_keys` (Task 4); `load_pipeline_objects`, `build_pipeline`, `pipeline_progress` (Task 2); `apps.registrations.admin_panels.build_doc_panel(application, kind)`.
- Produces: URL name `admin_hub:cockpit` taking `pk`.

**Why `approve_view` changes:** it currently ends every POST branch with `self._change_redirect(object_id)`, which lands the reviewer in Django admin. `review_action_view` already solves this with `_after_review_redirect`, which validates `next` through `url_has_allowed_host_and_scheme`. Reuse that helper — do not write a second redirect path.

- [ ] **Step 1: Write the failing redirect test**

Create `tests/admin_hub/test_approve_next_redirect.py`:

```python
"""approve_view must honour a validated `next`, like review_action_view does."""

from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


@pytest.fixture
def approver(db):
    from django.contrib.auth.models import User

    user = User.objects.create_superuser(
        username="approver", email="a@example.lv", password="x"
    )
    return user


def test_approve_returns_to_a_safe_next(client, approver, submitted_application):
    client.force_login(approver)
    hub_url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    url = reverse(
        "admin:registrations_registrationapplication_approve",
        args=[submitted_application.pk],
    )
    response = client.post(f"{url}?next={hub_url}", {"training_group": ""})
    assert response.status_code == 302
    assert response["Location"] == hub_url


def test_approve_ignores_an_offsite_next(client, approver, submitted_application):
    client.force_login(approver)
    url = reverse(
        "admin:registrations_registrationapplication_approve",
        args=[submitted_application.pk],
    )
    response = client.post(f"{url}?next=https://evil.example.com/", {"training_group": ""})
    assert response.status_code == 302
    assert "evil.example.com" not in response["Location"]


def test_approve_without_next_still_lands_on_the_change_page(
    client, approver, submitted_application
):
    client.force_login(approver)
    url = reverse(
        "admin:registrations_registrationapplication_approve",
        args=[submitted_application.pk],
    )
    response = client.post(url, {"training_group": ""})
    assert response.status_code == 302
    assert str(submitted_application.pk) in response["Location"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/admin_hub/test_approve_next_redirect.py -v`
Expected: FAIL — the first test fails because the redirect goes to the admin change URL, and every test errors on `NoReverseMatch: admin_hub:cockpit` until Step 5 adds the route. Add the route first if you prefer a clean red; the redirect assertion is the one that must be red.

- [ ] **Step 3: Make `approve_view` honour `next`**

In `apps/registrations/admin.py`, inside `approve_view`'s POST branch, replace all three occurrences of

```python
            return self._change_redirect(object_id)
```

with

```python
            return self._after_review_redirect(request, object_id)
```

and the final success return

```python
        self.message_user(request, "Pieteikums apstiprināts.")
        return self._change_redirect(object_id)
```

with

```python
        self.message_user(request, "Pieteikums apstiprināts.")
        return self._after_review_redirect(request, object_id)
```

Do not touch the `request.method != "POST"` branch — the GET confirm page stays as it is.

- [ ] **Step 4: Write the failing cockpit test**

Create `tests/admin_hub/test_hub_cockpit.py`:

```python
"""Review cockpit page."""

from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


def test_cockpit_requires_staff(client, submitted_application):
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    response = client.get(url)
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_cockpit_renders_the_field_readout(client, reviewer, submitted_application):
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    assert "Datu pārbaude" in body
    assert "Formas izmērs" in body
    assert "Vecāks / likumiskais pārstāvis" in body
    assert submitted_application.member_full_name in body


def test_cockpit_shows_the_check_off_bar_with_the_renamed_action(
    client, reviewer, submitted_application
):
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    assert "Apstiprināt visus" in body
    assert "Atzīmēt visus" not in body, "the action was renamed"


def test_approve_button_is_never_gated_on_the_checklist(
    client, reviewer, submitted_application
):
    """The checklist is a working aid. Nothing about it may disable approval."""
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    assert "Apstiprināt pieteikumu" in body
    assert "is-disabled" not in body.split("Apstiprināt pieteikumu")[0][-400:]


def test_cockpit_posts_approval_to_the_existing_admin_endpoint(
    client, reviewer, submitted_application
):
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    approve_url = reverse(
        "admin:registrations_registrationapplication_approve",
        args=[submitted_application.pk],
    )
    assert approve_url in body
    assert "csrfmiddlewaretoken" in body


def test_cockpit_carries_a_next_back_to_itself(client, reviewer, submitted_application):
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    assert f'value="{url}"' in body


def test_cockpit_document_links_use_the_authorized_preview_view(
    client, reviewer, submitted_application
):
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    assert "/admin/documents/" in body, (
        "documents must be served by the existing staff-only proxy views"
    )


def test_cockpit_offers_rotation(client, reviewer, submitted_application):
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    assert "data-viewer-rotate" in body


def test_cockpit_404s_for_an_unknown_application(client, reviewer):
    client.force_login(reviewer)
    response = client.get(reverse("admin_hub:cockpit", args=[999999]))
    assert response.status_code == 404
```

- [ ] **Step 5: Add the view and route**

Append to `apps/admin_hub/views.py`:

```python
@staff_member_required
def cockpit_view(request, pk: int):
    from django.shortcuts import get_object_or_404

    from apps.admin_hub.fields import build_field_groups, checkable_keys
    from apps.admin_hub.pipeline import (
        build_pipeline,
        load_pipeline_objects,
        pipeline_progress,
    )
    from apps.documents.models import Document
    from apps.members.models import TrainingGroup
    from apps.registrations.admin_panels import build_doc_panel
    from apps.registrations.models import RegistrationApplication

    application = get_object_or_404(RegistrationApplication, pk=pk)
    objects = load_pipeline_objects(application)
    steps = build_pipeline(objects)
    done, total = pipeline_progress(steps)
    groups = build_field_groups(application)
    keys = checkable_keys(groups)
    default_checked = [
        field.key
        for group in groups
        for field in group.fields
        if field.default_checked
    ]

    return render(
        request,
        "admin_hub/cockpit.html",
        {
            "hub_section": "queue",
            "application": application,
            "objects": objects,
            "steps": steps,
            "steps_done": done,
            "steps_total": total,
            "groups": groups,
            "checkable_total": len(keys),
            "default_checked_count": len(default_checked),
            # Zipped in the view: Django templates cannot walk two parallel
            # lists together, and the label belongs beside its panel.
            "viewer_tabs": list(
                zip(
                    ["Bērna ID", "Vecāka ID", "Portrets"],
                    [
                        build_doc_panel(application, Document.Kind.MEMBER_IDENTITY),
                        build_doc_panel(application, Document.Kind.GUARDIAN_IDENTITY),
                        build_doc_panel(application, Document.Kind.MEMBER_PORTRAIT),
                    ],
                )
            ),
            "active_training_groups": list(
                TrainingGroup.objects.filter(is_active=True).order_by("name")
            ),
        },
    )
```

In `apps/admin_hub/urls.py` add:

```python
    path("pieteikumi/<int:pk>/", views.cockpit_view, name="cockpit"),
```

In `templates/admin_hub/queue.html`, repoint the row CTA:

```html
          <a class="btn btn-red" href="{% url 'admin_hub:cockpit' row.application.pk %}">Izskatīt →</a>
```

- [ ] **Step 6: Write the viewer partial**

`templates/admin_hub/_viewer.html`:

```html
{% comment %}Expects `viewer_tabs`: a list of (label, panel) pairs, where
each panel is a build_doc_panel dict. Rotation and zoom are presentation-only
CSS transforms - no stored file is ever modified.
{% endcomment %}
<div class="viewer">
  <div class="viewer__tabs">
    {% for label, panel in viewer_tabs %}
      <button type="button"
              class="viewer__tab {% if forloop.first %}is-active{% endif %}{% if not panel.active %} is-missing{% endif %}"
              data-viewer-tab="{{ forloop.counter0 }}"
              {% if not panel.active %}disabled{% endif %}>{{ label }}</button>
    {% endfor %}
  </div>

  <div class="viewer__frame">
    {% for label, panel in viewer_tabs %}
      <div class="viewer__stage" data-viewer-stage="{{ forloop.counter0 }}"
           {% if not forloop.first %}hidden{% endif %}>
        {% if panel.active %}
          {% if panel.preview_kind == "image" %}
            <img class="viewer__doc" data-viewer-doc
                 src="{% url 'documents:admin-document-preview' panel.active.id %}"
                 alt="Augšupielādētais dokuments">
          {% else %}
            <p class="hint" style="color:#fff">
              Šis fails nav attēls. Atveriet to jaunā cilnē vai lejupielādējiet.
            </p>
          {% endif %}
        {% else %}
          <p class="hint" style="color:#fff">Dokuments nav augšupielādēts.</p>
        {% endif %}
      </div>
    {% endfor %}

    <div class="viewer__bar">
      <button type="button" class="vbtn" data-viewer-rotate="-90" title="Pagriezt pa kreisi (Shift+←)">&#8634; 90°</button>
      <button type="button" class="vbtn" data-viewer-rotate="90" title="Pagriezt pa labi (Shift+→)">&#8635; 90°</button>
      <button type="button" class="vbtn" data-viewer-zoom="-0.15" title="Tālāk">&minus;</button>
      <span class="vbar__zoom" data-viewer-zoom-label>100 %</span>
      <button type="button" class="vbtn" data-viewer-zoom="0.15" title="Tuvāk">+</button>
      <button type="button" class="vbtn" data-viewer-reset title="Ietilpināt logā">&#10530; Ietilpināt</button>
      <span class="vbar__spacer"></span>
      {% for label, panel in viewer_tabs %}{% if forloop.first and panel.active %}
        <a class="vbtn" target="_blank" rel="noopener"
           href="{% url 'documents:admin-document-preview' panel.active.id %}">&#8599; Jaunā cilnē</a>
        <a class="vbtn vbtn--accent"
           href="{% url 'documents:admin-document-download' panel.active.id %}">&#8681; Lejupielādēt</a>
      {% endif %}{% endfor %}
    </div>
  </div>
</div>
```

- [ ] **Step 7: Write the viewer script**

`static/admin_hub/viewer.js`:

```javascript
/* Document viewer: tab switching, rotation, zoom. Presentation only -
   nothing here writes to the server or modifies a stored document. */
(function () {
  "use strict";

  var stages = document.querySelectorAll("[data-viewer-stage]");
  var tabs = document.querySelectorAll("[data-viewer-tab]");
  var zoomLabel = document.querySelector("[data-viewer-zoom-label]");
  var state = { deg: 0, scale: 1 };

  function activeDoc() {
    var visible = document.querySelector("[data-viewer-stage]:not([hidden])");
    return visible ? visible.querySelector("[data-viewer-doc]") : null;
  }

  function apply() {
    var doc = activeDoc();
    if (doc) {
      doc.style.transform =
        "rotate(" + state.deg + "deg) scale(" + state.scale + ")";
    }
    if (zoomLabel) {
      zoomLabel.textContent = Math.round(state.scale * 100) + " %";
    }
  }

  function reset() {
    state.deg = 0;
    state.scale = 1;
    apply();
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      var index = tab.getAttribute("data-viewer-tab");
      tabs.forEach(function (t) { t.classList.remove("is-active"); });
      tab.classList.add("is-active");
      stages.forEach(function (stage) {
        stage.hidden = stage.getAttribute("data-viewer-stage") !== index;
      });
      reset();
    });
  });

  document.querySelectorAll("[data-viewer-rotate]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      state.deg += parseInt(btn.getAttribute("data-viewer-rotate"), 10);
      apply();
    });
  });

  document.querySelectorAll("[data-viewer-zoom]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var delta = parseFloat(btn.getAttribute("data-viewer-zoom"));
      state.scale = Math.min(3, Math.max(0.3, state.scale + delta));
      apply();
    });
  });

  var resetBtn = document.querySelector("[data-viewer-reset]");
  if (resetBtn) { resetBtn.addEventListener("click", reset); }

  document.addEventListener("keydown", function (event) {
    if (!event.shiftKey) { return; }
    if (event.key === "ArrowLeft") { state.deg -= 90; apply(); }
    if (event.key === "ArrowRight") { state.deg += 90; apply(); }
  });

  apply();
})();
```

- [ ] **Step 8: Write the checklist script**

`static/admin_hub/checklist.js`:

```javascript
/* Per-field check-off. Field keys and booleans only - never field values -
   so no personal data reaches browser storage. Every read and write is
   guarded: a private window or blocked site data must still render.

   Storage records an explicit boolean per field, never an absence, because
   some rows (the system-verified e-mail) default to checked: deleting a key
   would make a deliberate clear revert on the next load. */
(function () {
  "use strict";

  var root = document.querySelector("[data-checklist]");
  if (!root) { return; }

  var storeKey = "fkc.hub.checks." + root.getAttribute("data-checklist");
  var rows = root.querySelectorAll(".frow[data-field]");
  // Two counters render this number (the pinned bar and the action bar), so
  // collect all of them, not just the first.
  var countEls = document.querySelectorAll("[data-checklist-count]");
  var trackEl = document.querySelector("[data-checklist-track]");

  function load() {
    try { return JSON.parse(localStorage.getItem(storeKey)) || {}; }
    catch (err) { return {}; }
  }

  function save(state) {
    try { localStorage.setItem(storeKey, JSON.stringify(state)); }
    catch (err) { /* storage unavailable - stay in-memory for this page */ }
  }

  function refresh() {
    var done = root.querySelectorAll(".frow[data-field].frow--checked").length;
    countEls.forEach(function (el) {
      el.textContent = done + " / " + rows.length;
    });
    if (trackEl) {
      trackEl.style.width = rows.length
        ? (done / rows.length * 100) + "%"
        : "0%";
    }
  }

  function restore() {
    var state = load();
    rows.forEach(function (row) {
      var stored = state[row.getAttribute("data-field")];
      var on = stored === undefined
        ? row.getAttribute("data-default-checked") === "true"
        : stored === true;
      row.classList.toggle("frow--checked", on);
    });
  }

  rows.forEach(function (row) {
    var button = row.querySelector(".frow__check");
    if (!button) { return; }
    button.addEventListener("click", function () {
      var on = row.classList.toggle("frow--checked");
      var state = load();
      state[row.getAttribute("data-field")] = on;
      save(state);
      refresh();
    });
  });

  var allBtn = document.querySelector("[data-checklist-all]");
  if (allBtn) {
    allBtn.addEventListener("click", function () {
      var state = load();
      rows.forEach(function (row) {
        row.classList.add("frow--checked");
        state[row.getAttribute("data-field")] = true;
      });
      save(state);
      refresh();
    });
  }

  restore();
  refresh();
})();
```

- [ ] **Step 9: Write the field-group partial and the cockpit page**

`templates/admin_hub/_field_group.html`:

```html
{% comment %}Expects `group` (HubFieldGroup).{% endcomment %}
<div class="fgroup">
  <div class="fgroup__head">
    <h3 class="anton">{{ group.title }}</h3>
    {% if group.hint %}<span class="badge badge--sm badge--neutral">{{ group.hint }}</span>{% endif %}
  </div>
  <div class="fgroup__list">
    {% for field in group.fields %}
      <div class="frow"
           {% if field.checkable %}data-field="{{ field.key }}"{% endif %}
           {% if field.default_checked %}data-default-checked="true"{% endif %}>
        <div class="frow__label">{{ field.label }}</div>
        <div class="frow__value">
          {% if field.value %}
            <div class="v">{{ field.value }}</div>
          {% else %}
            <div class="v v--empty">Nav norādīts</div>
          {% endif %}
          {% if field.source_label or field.note %}
            <div class="sub">
              {% if field.source_label %}
                <span class="src-badge src-badge--{{ field.source_tone|default:'typed' }}">{{ field.source_label }}</span>
              {% endif %}
              {% if field.note %}<span>{{ field.note }}</span>{% endif %}
            </div>
          {% endif %}
        </div>
        {% if field.checkable %}
          <button type="button" class="frow__check"
                  title="Atzīmēt kā pārbaudītu">&#10003;</button>
        {% else %}
          <span></span>
        {% endif %}
      </div>
    {% endfor %}
  </div>
</div>
```

`templates/admin_hub/cockpit.html`:

```html
{% extends "admin_hub/base_hub.html" %}
{% load static %}

{% block hub_title %}FK Cēsis Admin — {{ application.member_full_name }}{% endblock %}
{% block hub_page_class %}hub-page--flush{% endblock %}

{% block hub_steprail %}{% include "admin_hub/_step_rail.html" %}{% endblock %}

{% block hub_content %}
  <div class="crumbs">
    <a href="{% url 'admin_hub:queue' %}">← Pieteikumu rinda</a>
    <span>/</span>
    <span>Pieteikums #{{ application.pk }}</span>
  </div>

  <div class="page-head" style="margin-bottom:16px">
    <div>
      <h1 class="page-title">{{ application.member_full_name|default:"Bez vārda" }}</h1>
      <p class="page-sub">
        Pieteikums <strong>#{{ application.pk }}</strong>
        · iesniegts <strong>{{ application.submitted_at|date:"d.m.Y H:i"|default:"—" }}</strong>
        · vecāks <strong>{{ application.guardian_name|default:"—" }}</strong>
      </p>
    </div>
    <div class="row">
      <span class="badge badge--submitted">{{ application.get_status_display }}</span>
      <a class="btn btn-secondary btn-sm"
         href="{% url 'admin:registrations_registrationapplication_change' application.pk %}">Atvērt Django admin</a>
    </div>
  </div>

  <div class="cockpit">
    {% include "admin_hub/_viewer.html" %}

    <section data-checklist="{{ application.pk }}">
      <div class="checkbar">
        <div>
          <div class="checkbar__count" data-checklist-count>{{ default_checked_count }} / {{ checkable_total }}</div>
          <div class="checkbar__label">pārbaudīti lauki · palīglīdzeklis</div>
        </div>
        <div class="checkbar__track"><span data-checklist-track></span></div>
        <button type="button" class="btn btn-secondary btn-sm" data-checklist-all>&#10003; Apstiprināt visus</button>
      </div>

      {% for group in groups %}{% include "admin_hub/_field_group.html" %}{% endfor %}

      <div class="card" style="margin-top:18px">
        <div class="card__head">
          <span class="card__step">2</span>
          <h2 class="anton">Apstiprināšana</h2>
        </div>
        <form method="post"
              action="{% url 'admin:registrations_registrationapplication_approve' application.pk %}?next={{ request.path|urlencode }}">
          {% csrf_token %}
          <input type="hidden" name="next" value="{{ request.path }}">
          <div class="card__body">
            <p class="hint" style="margin-bottom:14px">
              Apstiprinot tiek izveidots biedra ieraksts un vecāks saņem e-pastu.
              Treniņu grupu var piešķirt arī vēlāk. Lauku atzīmes ir tikai pārbaudes
              palīglīdzeklis — tās neietekmē apstiprināšanu.
            </p>
            <div class="form-grid">
              <div class="f">
                <label for="approve_training_group">Treniņu grupa</label>
                <select name="training_group" id="approve_training_group">
                  <option value="">— Piešķirsim vēlāk —</option>
                  {% for group in active_training_groups %}
                    <option value="{{ group.id }}">{{ group.name }}</option>
                  {% endfor %}
                </select>
              </div>
            </div>
          </div>
          <div class="card__foot">
            <span class="hint">Solis 2 no 8</span>
            <span class="card__spacer"></span>
            <button type="submit" class="btn btn-red">Apstiprināt pieteikumu →</button>
          </div>
        </form>
      </div>

      <details class="tray" style="margin-top:14px">
        <summary>&#9888; Riskantās darbības — labojuma pieprasījums, noraidīšana</summary>
        <div class="tray__body">
          <form method="post"
                action="{% url 'admin:registrations_registrationapplication_review-action' application.pk %}">
            {% csrf_token %}
            <input type="hidden" name="next" value="{{ request.path }}">
            <div class="f f--full">
              <label for="review_message">Ziņojums vecākam</label>
              <textarea name="review_message" id="review_message" rows="3"></textarea>
            </div>
            <div class="row" style="margin-top:12px">
              <button type="submit" name="action" value="request_fix" class="btn btn-secondary">Pieprasīt labojumu</button>
              <button type="submit" name="action" value="reject" class="btn btn-danger-outline">Noraidīt pieteikumu</button>
            </div>
          </form>
        </div>
      </details>
    </section>
  </div>
{% endblock %}

{% block hub_actionbar %}
  <div class="actionbar">
    <div class="actionbar__inner">
      <span class="actionbar__note"><strong data-checklist-count>{{ default_checked_count }} / {{ checkable_total }}</strong> lauku atzīmēti</span>
      <span class="actionbar__note">·</span>
      <span class="actionbar__note">Solis {{ steps_done }} / {{ steps_total }}</span>
      <span class="actionbar__spacer"></span>
      <a class="btn btn-secondary" href="{% url 'admin_hub:queue' %}">← Atpakaļ uz rindu</a>
    </div>
  </div>
{% endblock %}

{% block hub_scripts %}
  <script src="{% static 'admin_hub/viewer.js' %}"></script>
  <script src="{% static 'admin_hub/checklist.js' %}"></script>
{% endblock %}
```

- [ ] **Step 10: Run both test files**

Run: `uv run pytest tests/admin_hub/test_hub_cockpit.py tests/admin_hub/test_approve_next_redirect.py -v`
Expected: PASS.

- [ ] **Step 11: Exercise it by hand**

With `runserver` up, open a submitted application from the queue. Confirm: the document rotates with the toolbar and with `Shift+←/→`; ticking fields updates both counters; a reload keeps the ticks; the e-mail row starts ticked; clearing the e-mail tick survives a reload; approving returns you to the cockpit rather than Django admin.

- [ ] **Step 12: Verify and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy .
git add apps/admin_hub templates/admin_hub static/admin_hub apps/registrations/admin.py tests/admin_hub/test_hub_cockpit.py tests/admin_hub/test_approve_next_redirect.py
git commit -m "feat(admin-hub): add review cockpit with document viewer and field check-off"
```

---
### Task 6: Agreement page (S3) — steps 3, 4, 5

**Files:**
- Create: `templates/admin_hub/agreement.html`
- Modify: `apps/admin_hub/views.py`, `apps/admin_hub/urls.py`
- Test: `tests/admin_hub/test_hub_agreement.py`

**Interfaces:**
- Consumes: Task 2 pipeline; `apps.members.lanes.agreement_lane` (Task 1).
- Produces: URL name `admin_hub:agreement` taking `pk` (the **application** pk, so the whole hub keys off one identifier).

**Endpoints this page posts to — all pre-existing:**

| Control | Endpoint | Body |
|---|---|---|
| Atzīmēt kā nosūtītu | `admin:registrations_registrationapplication_review-action` | `action=mark_agreement_sent`, `next` |
| Parakstīšanas veids | same | `action=set_signing_path`, `signing_path=electronic\|paper`, `next` |
| Ģenerēt atkārtoti | same | `action=regenerate_agreement`, `next` |
| Atzīmēt kā parakstītu | same | `action=mark_agreement_signed`, `next` |
| Atcelt līgumu | same | `action=void_agreement`, `void_reason`, `next` |
| Lejupielādēt | `admin:registrations_registrationapplication_docuseal_document` | GET, args `[application.pk, agreement.pk]` |
| Augšupielādēt parakstīto | `admin:registrations_registrationapplication_signed_artifact_upload` | POST multipart, args `[application.pk, agreement.pk]` |
| Skatīt parakstīto | `admin:registrations_registrationapplication_signed_artifact` | GET, args `[application.pk, agreement.pk]` |

**Correction (2026-09-08): the sentence this plan originally carried here was
false.** It claimed `review_action_view` ends every branch with
`_after_review_redirect` and that no backend change was needed. Mapping every
branch showed only three actions honoured `next` — `mark_agreement_sent`,
`mark_agreement_signed`, `set_billing_setup` (11 call sites) — while thirteen
ignored it (46 sites), including `set_signing_path`, `regenerate_agreement` and
`void_agreement`, which this task drives. Every one of those bounced the reviewer
into Django admin, defeating the Hub.

Task 5's fix round corrected this once for every action the Hub uses
(`request_fix`, `reject`, `set_signing_path`, `regenerate_agreement`,
`void_agreement`, `create_next_season_billing`), extracting the validation into a
`_validated_next` helper so each call site keeps its own no-`next` fallback —
`reject` in particular must still land on the changelist, not the change page.
`url_has_allowed_host_and_scheme` remains the only gate on `next`; it must not be
weakened. **So by the time this task runs, the actions below do honour `next` —
verify that rather than assuming it, and do not add a second redirect path.**

**Step 6 gates step 5.** The spec requires the billing plan to be set before the
signed transition completes, because `mark_agreement_signed` is what materialises
the `BillingRecord` from the agreement's `billing_plan` + `first_billing_month`.
So "Atzīmēt kā parakstītu" needs **two** preconditions, not one: a signed
artifact **and** a plan. When the plan is missing, the button is disabled and the
card points the reviewer at the plan page instead.

- [ ] **Step 1: Write the failing test**

Create `tests/admin_hub/test_hub_agreement.py`:

```python
"""Agreement page — steps 3 to 5."""

from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


@pytest.fixture
def application_with_agreement(approved_application):
    return approved_application


def test_agreement_page_requires_staff(client, application_with_agreement):
    url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    response = client.get(url)
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_agreement_page_renders_all_three_step_cards(
    client, reviewer, application_with_agreement
):
    client.force_login(reviewer)
    url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    body = client.get(url).content.decode()
    assert "Līguma sagatavošana" in body
    assert "Lejupielāde un izsniegšana" in body
    assert "Parakstītais līgums" in body


def test_agreement_page_posts_mark_sent_to_the_existing_endpoint(
    client, reviewer, application_with_agreement
):
    client.force_login(reviewer)
    url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    body = client.get(url).content.decode()
    assert reverse(
        "admin:registrations_registrationapplication_review-action",
        args=[application_with_agreement.pk],
    ) in body
    assert 'value="mark_agreement_sent"' in body


def test_mark_signed_is_disabled_without_an_uploaded_artifact(
    client, reviewer, application_with_agreement
):
    agreement = application_with_agreement.approved_member.agreements.get(
        is_current=True
    )
    agreement.state = agreement.State.SENT
    agreement.sent_at = timezone.now()
    agreement.save(update_fields=["state", "sent_at"])

    client.force_login(reviewer)
    url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    body = client.get(url).content.decode()
    assert 'value="mark_agreement_signed"' in body
    marker = body.split('value="mark_agreement_signed"')[0]
    assert "disabled" in marker[-300:], (
        "without a signed artifact the transition must not be offered"
    )


def test_mark_signed_is_disabled_without_a_billing_plan(
    client, reviewer, application_with_agreement
):
    """The signed transition materialises the BillingRecord from the
    agreement's plan, so step 6 must be done before step 5 can complete."""
    agreement = application_with_agreement.approved_member.agreements.get(
        is_current=True
    )
    agreement.state = agreement.State.SENT
    agreement.sent_at = timezone.now()
    agreement.billing_plan = None
    agreement.first_billing_month = ""
    agreement.save(
        update_fields=["state", "sent_at", "billing_plan", "first_billing_month"]
    )

    client.force_login(reviewer)
    url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    body = client.get(url).content.decode()
    assert "Vispirms norādiet maksas plānu" in body
    marker = body.split('value="mark_agreement_signed"')[0]
    assert "disabled" in marker[-300:]


def test_page_shows_the_lifecycle_timeline(
    client, reviewer, application_with_agreement
):
    client.force_login(reviewer)
    url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    body = client.get(url).content.decode()
    assert "Vēsture" in body


def test_page_404s_when_the_application_has_no_member(
    client, reviewer, submitted_application
):
    """A submitted application has no agreement to show."""
    client.force_login(reviewer)
    url = reverse("admin_hub:agreement", args=[submitted_application.pk])
    response = client.get(url)
    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/admin_hub/test_hub_agreement.py -v`
Expected: FAIL — `NoReverseMatch: Reverse for 'agreement' not found`

- [ ] **Step 3: Add the view**

Append to `apps/admin_hub/views.py`:

```python
@staff_member_required
def agreement_view(request, pk: int):
    from django.http import Http404
    from django.shortcuts import get_object_or_404

    from apps.admin_hub.pipeline import (
        build_pipeline,
        load_pipeline_objects,
        pipeline_progress,
    )
    from apps.billing.models import MembershipPlan
    from apps.members.lanes import agreement_lane
    from apps.registrations.models import RegistrationApplication

    application = get_object_or_404(RegistrationApplication, pk=pk)
    objects = load_pipeline_objects(application)
    if objects.agreement is None:
        raise Http404("Šim pieteikumam vēl nav līguma.")

    steps = build_pipeline(objects)
    done, total = pipeline_progress(steps)
    agreement = objects.agreement

    return render(
        request,
        "admin_hub/agreement.html",
        {
            "hub_section": "queue",
            "application": application,
            "member": objects.member,
            "agreement": agreement,
            "lane": agreement_lane(agreement),
            "steps": steps,
            "steps_done": done,
            "steps_total": total,
            "has_signed_artifact": bool(agreement.signed_artifact),
            # mark_agreement_signed materialises the BillingRecord from these
            # two values, so step 5 cannot complete before step 6.
            "has_billing_plan": bool(
                agreement.billing_plan_id and agreement.first_billing_month
            ),
            "lifecycle_events": list(
                agreement.lifecycle_events.order_by("-created_at")[:20]
            ),
            "active_plans": list(
                MembershipPlan.objects.filter(is_active=True).order_by("season", "name")
            ),
        },
    )
```

In `apps/admin_hub/urls.py` add:

```python
    path("pieteikumi/<int:pk>/ligums/", views.agreement_view, name="agreement"),
```

- [ ] **Step 4: Write the template**

`templates/admin_hub/agreement.html`:

```html
{% extends "admin_hub/base_hub.html" %}

{% block hub_title %}FK Cēsis Admin — {{ member.full_name }} · Līgums{% endblock %}
{% block hub_page_class %}hub-page--flush{% endblock %}
{% block hub_steprail %}{% include "admin_hub/_step_rail.html" %}{% endblock %}

{% block hub_content %}
  {% url 'admin:registrations_registrationapplication_review-action' application.pk as review_action_url %}

  <div class="crumbs">
    <a href="{% url 'admin_hub:queue' %}">← Pieteikumu rinda</a><span>/</span>
    <a href="{% url 'admin_hub:cockpit' application.pk %}">{{ member.full_name }}</a><span>/</span>
    <span>Līgums</span>
  </div>

  <div class="page-head" style="margin-bottom:16px">
    <div>
      <h1 class="page-title">{{ member.full_name }} · Līgums</h1>
      <p class="page-sub">
        Līgums <strong>{{ agreement.agreement_number|default:"—" }}</strong>
        {% if member.training_group %}· {{ member.training_group.name }}{% endif %}
        · vecāks <strong>{{ application.guardian_name|default:"—" }}</strong>
      </p>
    </div>
    <div class="row">
      <span class="badge badge--approved">{{ agreement.get_state_display }}</span>
    </div>
  </div>

  <div class="split-side">
    <div class="stack">

      <section class="card">
        <div class="card__head {% if agreement.sent_at %}card__head--done{% endif %}">
          <span class="card__step">{% if agreement.sent_at %}&#10003;{% else %}3{% endif %}</span>
          <h2 class="anton">Līguma sagatavošana</h2>
          {% if agreement.sent_at %}
            <span class="badge badge--sm badge--submitted" style="margin-left:auto">Nosūtīts {{ agreement.sent_at|date:"d.m.Y H:i" }}</span>
          {% endif %}
        </div>
        <div class="card__body">
          <form method="post" action="{{ review_action_url }}">
            {% csrf_token %}
            <input type="hidden" name="next" value="{{ request.path }}">
            <div class="form-grid">
              <div class="f">
                <label for="signing_path">Parakstīšanas veids</label>
                <select name="signing_path" id="signing_path">
                  <option value="paper" {% if agreement.signing_path == "paper" %}selected{% endif %}>Ar roku, papīra dokuments</option>
                  <option value="electronic" {% if agreement.signing_path == "electronic" %}selected{% endif %}>Elektroniski</option>
                </select>
                <span class="f-hint">Vecāka izvēle pieteikumā: {{ application.get_preferred_agreement_signing_display|default:"nav norādīta" }}</span>
              </div>
            </div>
            <div class="row" style="margin-top:14px">
              <button type="submit" name="action" value="set_signing_path" class="btn btn-secondary">Saglabāt veidu</button>
            </div>
          </form>
        </div>
        <div class="card__foot">
          <span class="hint">Ģenerēts {{ agreement.generated_at|date:"d.m.Y H:i" }}</span>
          <span class="card__spacer"></span>
          <form method="post" action="{{ review_action_url }}">
            {% csrf_token %}
            <input type="hidden" name="next" value="{{ request.path }}">
            <button type="submit" name="action" value="regenerate_agreement" class="btn btn-secondary">&#8635; Ģenerēt atkārtoti</button>
          </form>
          <form method="post" action="{{ review_action_url }}">
            {% csrf_token %}
            <input type="hidden" name="next" value="{{ request.path }}">
            <button type="submit" name="action" value="mark_agreement_sent"
                    class="btn btn-primary" {% if agreement.sent_at %}disabled{% endif %}>
              Atzīmēt kā nosūtītu
            </button>
          </form>
        </div>
      </section>

      <section class="card">
        <div class="card__head {% if agreement.sent_at %}card__head--done{% endif %}">
          <span class="card__step">{% if agreement.sent_at %}&#10003;{% else %}4{% endif %}</span>
          <h2 class="anton">Lejupielāde un izsniegšana</h2>
        </div>
        <div class="card__body">
          <div class="dltile">
            <div class="dltile__icon">PDF</div>
            <div class="dltile__txt">
              <strong>{{ agreement.agreement_number|default:"Līgums" }}.pdf</strong>
              <span>Ģenerēts {{ agreement.generated_at|date:"d.m.Y H:i" }}</span>
            </div>
            <a class="btn btn-primary"
               href="{% url 'admin:registrations_registrationapplication_docuseal_document' application.pk agreement.pk %}">&#8681; Lejupielādēt</a>
          </div>
          <p class="hint" style="margin-top:14px">
            Sistēma šobrīd neveic elektronisko parakstīšanu. Izdrukā, izsniedz vecākam
            un augšupielādē parakstīto eksemplāru zemāk.
          </p>
        </div>
      </section>

      <section class="card">
        <div class="card__head {% if agreement.signed_at %}card__head--done{% endif %}">
          <span class="card__step">{% if agreement.signed_at %}&#10003;{% else %}5{% endif %}</span>
          <h2 class="anton">Parakstītais līgums</h2>
          {% if not has_signed_artifact %}
            <span class="badge badge--sm badge--fix" style="margin-left:auto">Gaida augšupielādi</span>
          {% endif %}
        </div>
        <div class="card__body stack">
          <form method="post" enctype="multipart/form-data"
                action="{% url 'admin:registrations_registrationapplication_signed_artifact_upload' application.pk agreement.pk %}">
            {% csrf_token %}
            <input type="hidden" name="next" value="{{ request.path }}">
            <div class="dropzone">
              <div class="dropzone__icon">&#8679;</div>
              <strong>Augšupielādē parakstīto līgumu</strong>
              <p class="hint" style="margin:6px 0 14px">PDF, JPG vai PNG · glabājas privātajā krātuvē</p>
              <input type="file" name="signed_artifact" accept=".pdf,.jpg,.jpeg,.png">
              <div class="row" style="justify-content:center;margin-top:12px">
                <button type="submit" class="btn btn-primary">Augšupielādēt</button>
              </div>
            </div>
          </form>

          {% if has_signed_artifact %}
            <div class="filecard">
              <div class="filecard__icon">PDF</div>
              <div class="filecard__txt">
                <strong>{{ agreement.signed_artifact_original_filename }}</strong>
                <span>{{ agreement.signed_artifact_file_size|filesizeformat }} · augšupielādēts {{ agreement.signed_artifact_uploaded_at|date:"d.m.Y H:i" }}</span>
              </div>
              <a class="btn btn-secondary btn-sm"
                 href="{% url 'admin:registrations_registrationapplication_signed_artifact' application.pk agreement.pk %}">&#128065; Skatīt</a>
            </div>
          {% endif %}

          {% if has_billing_plan %}
            <div class="callout">
              <span class="callout__icon">i</span>
              <span>Atzīmējot kā parakstītu, tiek izveidots šīs sezonas maksājumu ieraksts pēc 6. solī norādītā plāna.</span>
            </div>
          {% else %}
            <div class="callout callout--warn">
              <span class="callout__icon">&#9888;</span>
              <span>
                Vispirms norādiet maksas plānu — bez tā parakstīšanas atzīmēšana
                nevar izveidot maksājumu ierakstu.
                <a href="{% url 'admin_hub:billing' application.pk %}" style="text-decoration:underline">Atvērt 6. soli →</a>
              </span>
            </div>
          {% endif %}
        </div>
        <div class="card__foot">
          <span class="hint">Solis 5 no 8</span>
          <span class="card__spacer"></span>
          <form method="post" action="{{ review_action_url }}">
            {% csrf_token %}
            <input type="hidden" name="next" value="{% url 'admin_hub:billing' application.pk %}">
            <button type="submit" name="action" value="mark_agreement_signed"
                    class="btn btn-red"
                    {% if not has_signed_artifact or not has_billing_plan %}disabled{% endif %}>
              Atzīmēt kā parakstītu →
            </button>
          </form>
        </div>
      </section>

      <details class="tray">
        <summary>&#9888; Riskantās darbības — atcelt līgumu</summary>
        <div class="tray__body stack">
          <div class="callout callout--warn">
            <span class="callout__icon">&#9888;</span>
            <span>Līguma atcelšana saglabā vēsturi, bet atsauc rēķinus ar kredītrēķinu.</span>
          </div>
          <form method="post" action="{{ review_action_url }}">
            {% csrf_token %}
            <input type="hidden" name="next" value="{{ request.path }}">
            <div class="f f--full">
              <label for="void_reason">Iemesls</label>
              <textarea name="void_reason" id="void_reason" rows="3"></textarea>
            </div>
            <div class="row" style="margin-top:12px">
              <button type="submit" name="action" value="void_agreement" class="btn btn-danger-outline">Atcelt līgumu</button>
            </div>
          </form>
        </div>
      </details>
    </div>

    <aside class="sidecar">
      <div class="minicard">
        <h3 class="anton">Līguma dati</h3>
        <dl class="kv">
          <dt>Numurs</dt><dd>{{ agreement.agreement_number|default:"—" }}</dd>
          <dt>Stāvoklis</dt><dd>{{ agreement.get_state_display }}</dd>
          <dt>Veids</dt><dd>{{ agreement.get_signing_path_display }}</dd>
          <dt>Ģenerēts</dt><dd>{{ agreement.generated_at|date:"d.m.Y"|default:"—" }}</dd>
          <dt>Nosūtīts</dt><dd>{{ agreement.sent_at|date:"d.m.Y"|default:"—" }}</dd>
          <dt>Parakstīts</dt><dd>{{ agreement.signed_at|date:"d.m.Y"|default:"—" }}</dd>
        </dl>
      </div>

      <div class="minicard">
        <h3 class="anton">Vēsture</h3>
        <ul class="timeline">
          {% for event in lifecycle_events %}
            <li>
              <span class="tl__dot tl__dot--done">&#10003;</span>
              <div>
                <div class="tl__txt">{{ event.get_event_type_display }}</div>
                <div class="tl__when">{{ event.created_at|date:"d.m.Y H:i" }}{% if event.actor_label %} · {{ event.actor_label }}{% endif %}</div>
              </div>
            </li>
          {% empty %}
            <li><span class="tl__dot">—</span><div><div class="tl__txt">Nav notikumu</div></div></li>
          {% endfor %}
        </ul>
      </div>
    </aside>
  </div>
{% endblock %}
```

**Ordering note:** this template references `{% url 'admin_hub:billing' %}`, which Task 7 adds. To keep Task 6 independently green, add the route to `apps/admin_hub/urls.py` now together with a `billing_view` stub that renders `admin_hub/billing.html` with an empty context, then fill both in during Task 7. Do not leave a `NoReverseMatch` behind.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/admin_hub/test_hub_agreement.py -v`
Expected: PASS.

The `approved_application` fixture creates the Agreement along with the Member (via `approve_application`), so no extra setup is needed.

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy .
git add apps/admin_hub templates/admin_hub tests/admin_hub/test_hub_agreement.py
git commit -m "feat(admin-hub): add agreement page for steps 3-5"
```

---

### Task 7: Plan and invoices page (S4) — steps 6, 7, 8

**Files:**
- Create: `templates/admin_hub/billing.html`
- Modify: `apps/admin_hub/views.py`, `apps/admin_hub/urls.py` (replace the Task 6 stub)
- Modify: `apps/billing/admin.py` (per-record push endpoint)
- Test: `tests/admin_hub/test_hub_billing.py`

**Interfaces:**
- Consumes: Task 2 pipeline; `apps.billing.services.derive_installment_schedule(plan, total, first_billing_month=..., installment_count=...) -> list[tuple[date, Decimal]]`.
- Produces: URL name `admin_hub:billing` taking the application `pk`; admin URL name `admin:billing_billingrecord_push`.

**Why a new billing endpoint:** issuing invoices is currently only a *changelist* action (`push_to_invoice_ninja`), and Django admin actions always redirect to the changelist — so a Hub button would dump the reviewer in Django admin. `BillingRecordAdmin` already has both the pattern (`confirm_view` in `get_urls`) and the redirect helper (`_safe_redirect`, which honours `next`). Add a per-record `push_view` that mirrors `confirm_view`. This adds no domain logic: it calls the same `enqueue_push_billing_record` and records the same `BILLING_PUSH_TRIGGERED` audit event as the bulk action.

- [ ] **Step 1: Write the failing test**

Create `tests/admin_hub/test_hub_billing.py`:

```python
"""Plan + invoices page — steps 6 to 8."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


@pytest.fixture
def signed_application(approved_application, default_plan, reviewer):
    agreement = approved_application.approved_member.agreements.get(is_current=True)
    agreement.billing_plan = default_plan
    agreement.first_billing_month = "2026-09"
    agreement.state = agreement.State.SIGNED
    agreement.sent_at = timezone.now()
    agreement.signed_at = timezone.now()
    agreement.save(
        update_fields=[
            "billing_plan",
            "first_billing_month",
            "state",
            "sent_at",
            "signed_at",
        ]
    )
    return approved_application


def test_billing_page_requires_staff(client, signed_application):
    url = reverse("admin_hub:billing", args=[signed_application.pk])
    response = client.get(url)
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_billing_page_renders_the_three_step_cards(client, reviewer, signed_application):
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()
    assert "Maksas plāns" in body
    assert "Rēķini" in body
    assert "Nākamā sezona" in body


def test_plan_form_posts_set_billing_setup(client, reviewer, signed_application):
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()
    assert 'value="set_billing_setup"' in body
    assert 'name="billing_plan"' in body
    assert 'name="first_billing_month"' in body


def test_schedule_preview_lists_the_installments(client, reviewer, signed_application):
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()
    assert "Aprēķinātais grafiks" in body
    assert "2026" in body


def test_invoice_table_shows_a_created_invoice(
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
        amount=Decimal("30.00"),
    )
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()
    assert "30,00" in body or "30.00" in body
    assert "Nav izrakstīts" in body


def test_push_endpoint_honours_next(client, signed_application, default_plan):
    from django.contrib.auth.models import User
    from apps.billing.models import BillingRecord

    admin_user = User.objects.create_superuser(
        username="pusher", email="p@example.lv", password="x"
    )
    record = BillingRecord.objects.create(
        member=signed_application.approved_member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
    )
    client.force_login(admin_user)
    hub_url = reverse("admin_hub:billing", args=[signed_application.pk])
    push_url = reverse("admin:billing_billingrecord_push", args=[record.pk])
    response = client.post(f"{push_url}?next={hub_url}")
    assert response.status_code == 302
    assert response["Location"] == hub_url


def test_push_endpoint_refuses_an_unconfirmed_record(client, signed_application, default_plan):
    from django.contrib.auth.models import User
    from apps.billing.models import BillingRecord

    admin_user = User.objects.create_superuser(
        username="pusher2", email="p2@example.lv", password="x"
    )
    record = BillingRecord.objects.create(
        member=signed_application.approved_member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.DRAFT,
    )
    client.force_login(admin_user)
    push_url = reverse("admin:billing_billingrecord_push", args=[record.pk])
    response = client.post(push_url)
    assert response.status_code == 302
    record.refresh_from_db()
    assert record.external_status != "synced"


def test_next_season_action_is_disabled_without_a_current_record(
    client, reviewer, signed_application
):
    """signed_application has no BillingRecord yet, so step 8 cannot run."""
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()
    assert 'value="create_next_season_billing"' in body
    marker = body.split('value="create_next_season_billing"')[0]
    assert "disabled" in marker[-300:]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/admin_hub/test_hub_billing.py -v`
Expected: FAIL — `NoReverseMatch: Reverse for 'billing' not found`

- [ ] **Step 3: Add the per-record push endpoint**

In `apps/billing/admin.py`, add to `BillingRecordAdmin.get_urls`'s `custom` list, after the `confirm` entry:

```python
            path(
                "<int:object_id>/push/",
                self.admin_site.admin_view(self.push_view),
                name="billing_billingrecord_push",
            ),
```

And add the view method directly after `confirm_view`:

```python
    def push_view(self, request, object_id):
        """Issue one record's invoices. Same work as the bulk action, but
        addressable per record so the Admin Hub can offer it inline and come
        back via `next`. No new domain logic: it enqueues the same job and
        records the same audit event."""
        from apps.integrations.tasks import enqueue_push_billing_record

        if not self.has_change_permission(request):
            raise PermissionDenied
        record = get_object_or_404(BillingRecord, pk=object_id)
        if record.status != BillingRecord.Status.CONFIRMED:
            self.message_user(
                request,
                "Vispirms apstipriniet maksājumu ierakstu.",
                level=messages.ERROR,
            )
            return self._safe_redirect(request, object_id)
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
        self.message_user(request, "Rēķinu izrakstīšana sākta.")
        return self._safe_redirect(request, object_id)
```

Read `_safe_redirect` before wiring this up (it is defined a little further down the same class) and confirm it takes `(request, object_id)`. If its `next` validation differs from `_after_review_redirect`'s, use it as-is — do not add a second redirect helper.

- [ ] **Step 4: Add the view and route**

Append to `apps/admin_hub/views.py`:

```python
@staff_member_required
def billing_view(request, pk: int):
    from django.http import Http404
    from django.shortcuts import get_object_or_404

    from apps.admin_hub.pipeline import (
        build_pipeline,
        load_pipeline_objects,
        pipeline_progress,
    )
    from apps.billing.models import MembershipPlan
    from apps.billing.services import derive_installment_schedule
    from apps.registrations.models import RegistrationApplication

    application = get_object_or_404(RegistrationApplication, pk=pk)
    objects = load_pipeline_objects(application)
    if objects.agreement is None:
        raise Http404("Šim pieteikumam vēl nav līguma.")

    steps = build_pipeline(objects)
    done, total = pipeline_progress(steps)
    agreement = objects.agreement
    record = objects.billing_record

    # Preview the schedule from whatever is selected now, so the reviewer sees
    # the consequence before saving. Falls back to an empty list when there is
    # no plan yet - never to a guess.
    schedule: list[tuple[object, object]] = []
    plan = agreement.billing_plan
    if plan is not None:
        total_amount = record.final_amount if record is not None else plan.annual_amount
        schedule = derive_installment_schedule(
            plan,
            total_amount,
            first_billing_month=agreement.first_billing_month,
        )

    return render(
        request,
        "admin_hub/billing.html",
        {
            "hub_section": "queue",
            "application": application,
            "member": objects.member,
            "agreement": agreement,
            "record": record,
            "invoices": objects.invoices,
            "next_season_record": objects.next_season_record,
            "schedule": schedule,
            "steps": steps,
            "steps_done": done,
            "steps_total": total,
            "active_plans": list(
                MembershipPlan.objects.filter(is_active=True).order_by("season", "name")
            ),
        },
    )
```

In `apps/admin_hub/urls.py` add:

```python
    path("pieteikumi/<int:pk>/maksajumi/", views.billing_view, name="billing"),
```

- [ ] **Step 5: Write the template**

`templates/admin_hub/billing.html`:

```html
{% extends "admin_hub/base_hub.html" %}

{% block hub_title %}FK Cēsis Admin — {{ member.full_name }} · Maksājumi{% endblock %}
{% block hub_page_class %}hub-page--flush{% endblock %}
{% block hub_steprail %}{% include "admin_hub/_step_rail.html" %}{% endblock %}

{% block hub_content %}
  {% url 'admin:registrations_registrationapplication_review-action' application.pk as review_action_url %}

  <div class="crumbs">
    <a href="{% url 'admin_hub:queue' %}">← Pieteikumu rinda</a><span>/</span>
    <a href="{% url 'admin_hub:agreement' application.pk %}">{{ member.full_name }}</a><span>/</span>
    <span>Maksas plāns un rēķini</span>
  </div>

  <div class="page-head" style="margin-bottom:16px">
    <div>
      <h1 class="page-title">{{ member.full_name }} · Maksājumi</h1>
      <p class="page-sub">
        Līgums <strong>{{ agreement.agreement_number|default:"—" }}</strong>
        · parakstīts {{ agreement.signed_at|date:"d.m.Y"|default:"—" }}
        {% if record %}· sezona <strong>{{ record.season }}</strong>{% endif %}
      </p>
    </div>
  </div>

  <div class="split-side">
    <div class="stack">

      <section class="card">
        <div class="card__head">
          <span class="card__step">6</span>
          <h2 class="anton">Maksas plāns</h2>
        </div>
        <form method="post" action="{{ review_action_url }}">
          {% csrf_token %}
          <input type="hidden" name="next" value="{{ request.path }}">
          <div class="card__body stack">
            <div class="form-grid">
              <div class="f f--full">
                <label for="billing_plan">Plāns</label>
                <select name="billing_plan" id="billing_plan">
                  {% for plan in active_plans %}
                    <option value="{{ plan.pk }}" {% if agreement.billing_plan_id == plan.pk %}selected{% endif %}>
                      {{ plan.name }} — {{ plan.annual_amount }} {{ plan.currency }}, {{ plan.installment_count }} daļas
                    </option>
                  {% endfor %}
                </select>
                <span class="f-hint">Summas tiek fiksētas ierakstā — vēlākas plāna izmaiņas neietekmē jau izveidotos rēķinus.</span>
              </div>
              <div class="f">
                <label for="first_billing_month">Pirmais rēķina mēnesis</label>
                <input type="month" name="first_billing_month" id="first_billing_month"
                       value="{{ agreement.first_billing_month }}">
                <span class="f-hint">Formāts GGGG-MM</span>
              </div>
            </div>

            {% if schedule %}
              <div>
                <div class="row" style="justify-content:space-between;margin-bottom:10px">
                  <strong style="color:var(--fk-blue)">Aprēķinātais grafiks</strong>
                  <span class="muted" style="font-weight:600">{{ schedule|length }} daļas</span>
                </div>
                <div class="sched">
                  {% for due_date, amount in schedule %}
                    <div class="schedrow">
                      <span class="schedrow__seq">{{ forloop.counter }}</span>
                      <span>{{ due_date|date:"F Y" }}</span>
                      <span class="muted">termiņš {{ due_date|date:"d.m.Y" }}</span>
                      <span class="schedrow__amt">{{ amount }} €</span>
                    </div>
                  {% endfor %}
                </div>
              </div>
            {% else %}
              <p class="hint">Izvēlieties plānu un pirmo mēnesi, lai redzētu grafiku.</p>
            {% endif %}
          </div>
          <div class="card__foot">
            {% if record %}
              <span class="hint">Kopā <strong style="color:var(--fk-blue)">{{ record.final_amount }} €</strong> · bāze {{ record.base_amount }} € · atlaide {{ record.discount_amount }} €</span>
            {% endif %}
            <span class="card__spacer"></span>
            <button type="submit" name="action" value="set_billing_setup" class="btn btn-primary">Saglabāt plānu →</button>
          </div>
        </form>
      </section>

      <section class="card">
        <div class="card__head">
          <span class="card__step">7</span>
          <h2 class="anton">Rēķini</h2>
          <span class="badge badge--sm badge--neutral" style="margin-left:auto">Invoice Ninja</span>
        </div>
        <div class="card__body">
          {% if invoices %}
            <div class="tablewrap">
              <table class="grid">
                <thead>
                  <tr>
                    <th style="width:44px">#</th><th>Termiņš</th>
                    <th class="num">Summa</th><th class="num">Apmaksāts</th><th class="num">Atlikums</th>
                    <th>IN statuss</th><th>Maksājums</th>
                  </tr>
                </thead>
                <tbody>
                  {% for invoice in invoices %}
                    <tr>
                      <td class="strong">{{ invoice.sequence }}</td>
                      <td>{{ invoice.due_date|date:"d.m.Y" }}</td>
                      <td class="num">{{ invoice.amount }} €</td>
                      <td class="num">{{ invoice.paid_to_date }} €</td>
                      <td class="num">{{ invoice.balance|default:invoice.amount }} €</td>
                      <td>
                        {% if invoice.external_invoice_id %}
                          <span class="badge badge--sm badge--approved">{{ invoice.external_status|default:"izrakstīts" }}</span>
                        {% else %}
                          <span class="badge badge--sm badge--neutral">Nav izrakstīts</span>
                        {% endif %}
                      </td>
                      <td>
                        <span class="badge badge--sm badge--{{ invoice.payment_status|default:'unpaid' }}">
                          {{ invoice.get_payment_status_display|default:"Nav apmaksāts" }}
                        </span>
                      </td>
                    </tr>
                  {% endfor %}
                </tbody>
              </table>
            </div>
          {% else %}
            <p class="hint">Rēķini vēl nav izveidoti. Tie rodas, kad līgums tiek atzīmēts kā parakstīts.</p>
          {% endif %}
        </div>
        {% if record %}
          <div class="card__foot">
            <span class="hint">Ieraksta stāvoklis: {{ record.get_status_display }}</span>
            <span class="card__spacer"></span>
            {% if record.status != "confirmed" %}
              <form method="post" action="{% url 'admin:billing_billingrecord_confirm' record.pk %}?next={{ request.path|urlencode }}">
                {% csrf_token %}
                <button type="submit" class="btn btn-secondary">Apstiprināt ierakstu</button>
              </form>
            {% endif %}
            <form method="post" action="{% url 'admin:billing_billingrecord_push' record.pk %}?next={{ request.path|urlencode }}">
              {% csrf_token %}
              <button type="submit" class="btn btn-red" {% if record.status != "confirmed" %}disabled{% endif %}>
                Izrakstīt rēķinus →
              </button>
            </form>
          </div>
        {% endif %}
      </section>

      <section class="card {% if not record %}card--locked{% endif %}">
        <div class="card__head {% if not record %}card__head--locked{% endif %}">
          <span class="card__step">8</span>
          <h2 class="anton">Nākamā sezona</h2>
          {% if next_season_record %}
            <span class="badge badge--sm badge--submitted" style="margin-left:auto">Izveidots — {{ next_season_record.season }}</span>
          {% endif %}
        </div>
        <form method="post" action="{{ review_action_url }}">
          {% csrf_token %}
          <input type="hidden" name="next" value="{{ request.path }}">
          <div class="card__body">
            <div class="form-grid">
              <div class="f">
                <label for="next_year_plan">Nākamās sezonas plāns</label>
                <select name="next_year_plan" id="next_year_plan">
                  <option value="">— Izvēlieties plānu —</option>
                  {% for plan in active_plans %}
                    <option value="{{ plan.pk }}">{{ plan.name }} — {{ plan.season }}</option>
                  {% endfor %}
                </select>
              </div>
            </div>
            <p class="hint" style="margin-top:12px">
              Nākamās sezonas ieraksts pārmanto pašreizējā līguma atlaides un maksājuma
              veidu. Rēķini netiek izrakstīti automātiski.
            </p>
          </div>
          <div class="card__foot">
            <span class="hint">Solis 8 no 8</span>
            <span class="card__spacer"></span>
            <button type="submit" name="action" value="create_next_season_billing"
                    class="btn btn-primary" {% if not record or next_season_record %}disabled{% endif %}>
              Izveidot nākamās sezonas ierakstu
            </button>
          </div>
        </form>
      </section>
    </div>

    <aside class="sidecar">
      <div class="minicard">
        <h3 class="anton">Maksājumu kopsavilkums</h3>
        <dl class="kv">
          {% if record %}
            <dt>Sezona</dt><dd>{{ record.season }}</dd>
            <dt>Bāzes summa</dt><dd>{{ record.base_amount }} €</dd>
            <dt>Atlaide</dt><dd>{{ record.discount_amount }} €</dd>
            <dt>Gala summa</dt><dd style="color:var(--fk-blue)">{{ record.final_amount }} €</dd>
            <dt>Veids</dt><dd>{{ record.get_payment_mode_display }}</dd>
            <dt>Stāvoklis</dt><dd>{{ record.get_status_display }}</dd>
          {% else %}
            <dt>Ieraksts</dt><dd>Nav izveidots</dd>
          {% endif %}
        </dl>
      </div>
    </aside>
  </div>
{% endblock %}
```

The invoice `payment_status` values (`unpaid`, `partial`, `paid`) match the `badge--unpaid` / `--partial` / `--paid` classes in `hub.css` by design — that is why the raw value is interpolated into the class name.

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/admin_hub/test_hub_billing.py -v`
Expected: PASS.

- [ ] **Step 7: Verify and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy .
git add apps/admin_hub templates/admin_hub apps/billing/admin.py tests/admin_hub/test_hub_billing.py
git commit -m "feat(admin-hub): add plan and invoices page for steps 6-8"
```

---

### Task 8: Outstanding invoices (S5), bulk guard, navigation, docs

**Files:**
- Create: `templates/admin_hub/invoices.html`, `templates/admin_hub/bulk_confirm.html`
- Create: `apps/admin_hub/invoices.py`
- Modify: `apps/admin_hub/views.py`, `apps/admin_hub/urls.py`, `templates/admin_hub/base_hub.html`
- Modify: `AGENTS.md`, `README.md`
- Test: `tests/admin_hub/test_hub_invoices.py`

**Interfaces:**
- Consumes: `apps.billing.models.{BillingInvoice, BillingRecord, PaymentStatus}`.
- Produces:
  - `apps.admin_hub.invoices.INVOICE_TABS: dict[str, str]`
  - `apps.admin_hub.invoices.invoice_queryset(tab: str)`
  - `apps.admin_hub.invoices.invoice_totals(queryset) -> dict[str, object]`
  - `apps.admin_hub.invoices.BULK_CONFIRM_THRESHOLD: int`
  - URL names `admin_hub:invoices`, `admin_hub:bulk_confirm`

**Scope reminder:** overdue reminder e-mails are **out of scope** (spec, resolved 2026-09-07). Do not add a reminder button. The nightly-sweep batch caps are also out of scope and tracked separately; this task only adds the interactive selection guard.

- [ ] **Step 1: Write the failing test**

Create `tests/admin_hub/test_hub_invoices.py`:

```python
"""Outstanding invoices page."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.admin_hub.invoices import BULK_CONFIRM_THRESHOLD

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


@pytest.fixture
def unpaid_invoice(approved_application, default_plan):
    from apps.billing.models import BillingInvoice, BillingRecord

    record = BillingRecord.objects.create(
        member=approved_application.approved_member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
    )
    return BillingInvoice.objects.create(
        billing_record=record,
        sequence=1,
        due_date=datetime.date(2026, 7, 20),
        amount=Decimal("30.00"),
        external_invoice_id="IN-77",
        external_status="sent",
        payment_status="unpaid",
        balance=Decimal("30.00"),
    )


def test_invoices_page_requires_staff(client):
    response = client.get(reverse("admin_hub:invoices"))
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_invoices_page_lists_an_unpaid_invoice(client, reviewer, unpaid_invoice):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:invoices")).content.decode()
    assert "Neapmaksātie rēķini" in body
    assert unpaid_invoice.billing_record.member.full_name in body


def test_invoices_page_shows_the_outstanding_total(client, reviewer, unpaid_invoice):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:invoices")).content.decode()
    assert "Atlikums kopā" in body


def test_overdue_invoice_is_flagged(client, reviewer, unpaid_invoice):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:invoices"), {"tab": "kaveti"}).content.decode()
    assert "is-overdue" in body


def test_invoices_page_has_no_reminder_action(client, reviewer, unpaid_invoice):
    """Reminder e-mails were explicitly ruled out of scope."""
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:invoices")).content.decode()
    assert "atgādin" not in body.lower()


def test_unknown_tab_falls_back_to_the_default(client, reviewer, unpaid_invoice):
    client.force_login(reviewer)
    response = client.get(reverse("admin_hub:invoices"), {"tab": "nonsense"})
    assert response.status_code == 200


def test_bulk_confirm_page_reports_the_selection_size(client, reviewer):
    client.force_login(reviewer)
    ids = ",".join(str(n) for n in range(BULK_CONFIRM_THRESHOLD + 1))
    response = client.get(
        reverse("admin_hub:bulk_confirm"),
        {"ids": ids, "op": "push"},
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert str(BULK_CONFIRM_THRESHOLD + 1) in body
    assert "Apstiprināt" in body


def test_bulk_confirm_states_the_batch_cap(client, reviewer):
    client.force_login(reviewer)
    ids = ",".join(str(n) for n in range(BULK_CONFIRM_THRESHOLD + 1))
    body = client.get(
        reverse("admin_hub:bulk_confirm"), {"ids": ids, "op": "push"}
    ).content.decode()
    assert str(BULK_CONFIRM_THRESHOLD) in body


def test_bulk_confirm_rejects_a_non_numeric_id_list(client, reviewer):
    client.force_login(reviewer)
    response = client.get(
        reverse("admin_hub:bulk_confirm"), {"ids": "1,2,../etc", "op": "push"}
    )
    assert response.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/admin_hub/test_hub_invoices.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.admin_hub.invoices'`

- [ ] **Step 3: Write the invoice query layer**

`apps/admin_hub/invoices.py`:

```python
"""Querysets and totals for the outstanding-invoice review page.

Reads Invoice Ninja sync state that the nightly sweeps and the per-record
push write; it never calls the provider itself.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.billing.models import BillingInvoice, PaymentStatus

INVOICE_TABS: dict[str, str] = {
    "neapmaksati": "Neapmaksāti",
    "kaveti": "Kavēti",
    "daleji": "Daļēji apmaksāti",
    "kludas": "Sinhronizācijas kļūdas",
    "nav_izrakstiti": "Nav izrakstīti",
    "visi": "Visi",
}
DEFAULT_INVOICE_TAB = "neapmaksati"

# An interactive bulk action above this many rows asks for confirmation first.
# This is a UI guard against a mis-click, not the nightly-sweep batch cap -
# that is tracked as its own change (see the spec).
BULK_CONFIRM_THRESHOLD = 50


def normalize_invoice_tab(raw: str | None) -> str:
    return raw if raw in INVOICE_TABS else DEFAULT_INVOICE_TAB


def invoice_queryset(tab: str):
    today = timezone.localdate()
    base = BillingInvoice.objects.filter(cancelled_at__isnull=True).select_related(
        "billing_record",
        "billing_record__member",
        "billing_record__member__guardian",
        "billing_record__member__training_group",
    )
    if tab == "neapmaksati":
        return base.exclude(payment_status=PaymentStatus.PAID).order_by("due_date")
    if tab == "kaveti":
        return (
            base.exclude(payment_status=PaymentStatus.PAID)
            .filter(due_date__lt=today)
            .order_by("due_date")
        )
    if tab == "daleji":
        return base.filter(payment_status=PaymentStatus.PARTIAL).order_by("due_date")
    if tab == "kludas":
        return base.exclude(external_error_code="").order_by("-updated_at")
    if tab == "nav_izrakstiti":
        return base.filter(external_invoice_id="").order_by("due_date")
    return base.order_by("-due_date")


def invoice_totals(queryset) -> dict[str, object]:
    today = timezone.localdate()
    rows = list(queryset)
    outstanding = Decimal("0.00")
    for invoice in rows:
        balance = invoice.balance if invoice.balance is not None else invoice.amount
        outstanding += balance
    aggregates = queryset.aggregate(paid=Sum("paid_to_date"))
    return {
        "count": len(rows),
        "outstanding": outstanding,
        "overdue_count": sum(
            1
            for invoice in rows
            if invoice.due_date < today
            and invoice.payment_status != PaymentStatus.PAID
        ),
        "unsynced_count": sum(1 for invoice in rows if not invoice.external_invoice_id),
        "paid_total": aggregates["paid"] or Decimal("0.00"),
        "rows": rows,
    }


def parse_id_list(raw: str) -> list[int] | None:
    """Parse a comma-separated id list. Returns None when anything is not an
    integer, so the caller can answer 400 instead of guessing."""
    if not raw:
        return []
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    try:
        return [int(part) for part in parts]
    except ValueError:
        return None
```

- [ ] **Step 4: Add the views and routes**

Append to `apps/admin_hub/views.py`:

```python
@staff_member_required
def invoices_view(request):
    from apps.admin_hub import invoices as invoice_queries

    tab = invoice_queries.normalize_invoice_tab(request.GET.get("tab"))
    queryset = invoice_queries.invoice_queryset(tab)
    totals = invoice_queries.invoice_totals(queryset)
    return render(
        request,
        "admin_hub/invoices.html",
        {
            "hub_section": "invoices",
            "tab": tab,
            "tabs": invoice_queries.INVOICE_TABS,
            "totals": totals,
            "today": timezone.localdate(),
            "bulk_threshold": invoice_queries.BULK_CONFIRM_THRESHOLD,
        },
    )


@staff_member_required
def bulk_confirm_view(request):
    from django.http import HttpResponseBadRequest

    from apps.admin_hub import invoices as invoice_queries

    ids = invoice_queries.parse_id_list(request.GET.get("ids", ""))
    if ids is None:
        return HttpResponseBadRequest("Nederīgs ierakstu saraksts.")
    return render(
        request,
        "admin_hub/bulk_confirm.html",
        {
            "hub_section": "invoices",
            "count": len(ids),
            "ids": ids,
            "op": request.GET.get("op", ""),
            "threshold": invoice_queries.BULK_CONFIRM_THRESHOLD,
        },
    )
```

Add `from django.utils import timezone` to the imports at the top of `views.py`.

In `apps/admin_hub/urls.py` add:

```python
    path("rekini/", views.invoices_view, name="invoices"),
    path("rekini/apstiprinat/", views.bulk_confirm_view, name="bulk_confirm"),
```

- [ ] **Step 5: Write the two templates**

`templates/admin_hub/invoices.html`:

```html
{% extends "admin_hub/base_hub.html" %}
{% load hub_tags %}

{% block hub_title %}FK Cēsis Admin — Neapmaksātie rēķini{% endblock %}

{% block hub_content %}
  <div class="page-head">
    <div>
      <h1 class="page-title">Neapmaksātie rēķini</h1>
      <p class="page-sub">Dati no Invoice Ninja sinhronizācijas. Kavējums rēķināts pret šodienas datumu.</p>
    </div>
  </div>

  <div class="stat-strip">
    <div class="stat stat--alert">
      <div class="stat__icon">&euro;</div>
      <div><div class="stat__value">{{ totals.outstanding }}</div><div class="stat__label">Atlikums kopā (EUR)</div></div>
    </div>
    <div class="stat stat--warn">
      <div class="stat__icon">&#9200;</div>
      <div><div class="stat__value">{{ totals.overdue_count }}</div><div class="stat__label">Kavēti rēķini</div></div>
    </div>
    <div class="stat">
      <div class="stat__icon">&#129534;</div>
      <div><div class="stat__value">{{ totals.count }}</div><div class="stat__label">Rēķini skatā</div></div>
    </div>
    <div class="stat stat--ok">
      <div class="stat__icon">&#10003;</div>
      <div><div class="stat__value">{{ totals.paid_total }}</div><div class="stat__label">Apmaksāts (EUR)</div></div>
    </div>
  </div>

  <nav class="tabs">
    {% for slug, label in tabs.items %}
      <a href="?tab={{ slug }}" class="{% if slug == tab %}is-active{% endif %}">{{ label }}</a>
    {% endfor %}
  </nav>

  <div class="tablecard">
    <div class="tablewrap">
      <table class="grid">
        <thead>
          <tr>
            <th>Biedrs</th><th>Sezona</th><th>Daļa</th><th>Termiņš</th>
            <th class="num">Summa</th><th class="num">Apmaksāts</th><th class="num">Atlikums</th>
            <th>Maksājums</th><th>IN statuss</th>
          </tr>
        </thead>
        <tbody>
          {% for invoice in totals.rows %}
            <tr class="{% if invoice.due_date < today %}is-overdue{% endif %}">
              <td>
                <div class="cellstack">
                  <strong>{{ invoice.billing_record.member.full_name }}</strong>
                  <span>
                    {{ invoice.billing_record.member.guardian.display_name|default:"—" }}
                    {% if invoice.billing_record.member.training_group %}· {{ invoice.billing_record.member.training_group.name }}{% endif %}
                  </span>
                </div>
              </td>
              <td>{{ invoice.billing_record.season }}</td>
              <td>{{ invoice.sequence }}</td>
              <td>
                {% if invoice.due_date < today %}
                  <span class="badge badge--sm badge--overdue">{{ invoice.due_date|date:"d.m.Y" }}</span>
                {% else %}
                  {{ invoice.due_date|date:"d.m.Y" }}
                {% endif %}
              </td>
              <td class="num">{{ invoice.amount }} €</td>
              <td class="num">{{ invoice.paid_to_date }} €</td>
              <td class="num">{{ invoice.balance|default:invoice.amount }} €</td>
              <td><span class="badge badge--sm badge--{{ invoice.payment_status|default:'unpaid' }}">{{ invoice.get_payment_status_display|default:"Nav apmaksāts" }}</span></td>
              <td>
                {% if invoice.external_error_code %}
                  <span class="badge badge--sm badge--rejected">{{ invoice.external_error_code }}</span>
                {% elif invoice.external_invoice_id %}
                  <span class="badge badge--sm badge--approved">{{ invoice.external_status|default:"izrakstīts" }}</span>
                {% else %}
                  <span class="badge badge--sm badge--neutral">Nav izrakstīts</span>
                {% endif %}
              </td>
            </tr>
          {% empty %}
            <tr><td colspan="9" class="muted" style="text-align:center;padding:22px">Šajā skatā nav rēķinu.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
{% endblock %}
```

`templates/admin_hub/bulk_confirm.html`:

```html
{% extends "admin_hub/base_hub.html" %}

{% block hub_title %}FK Cēsis Admin — Apstiprināt masveida darbību{% endblock %}

{% block hub_content %}
  <div class="page-head">
    <div>
      <h1 class="page-title">Apstiprināt darbību</h1>
      <p class="page-sub">Izvēlēti daudz ierakstu — pārliecinieties, pirms turpināt.</p>
    </div>
  </div>

  <div class="card" style="max-width:720px">
    <div class="card__body stack">
      <div class="callout callout--warn">
        <span class="callout__icon">&#9888;</span>
        <span>
          Izvēlēti <strong>{{ count }}</strong> ieraksti. Vienā izpildē tiek apstrādāti
          ne vairāk par <strong>{{ threshold }}</strong> — pārējie paliek rindā nākamajai reizei.
        </span>
      </div>
      <p class="hint">Darbība: <strong>{{ op }}</strong></p>
    </div>
    <div class="card__foot">
      <a class="btn btn-secondary" href="{% url 'admin_hub:invoices' %}">Atcelt</a>
      <span class="card__spacer"></span>
      <button type="button" class="btn btn-red">Apstiprināt un turpināt</button>
    </div>
  </div>
{% endblock %}
```

- [ ] **Step 6: Wire the nav link**

In `templates/admin_hub/base_hub.html`, fill the `hub_nav_extra` block usage by replacing the `{% block hub_nav_extra %}{% endblock %}` line with:

```html
      <a href="{% url 'admin_hub:invoices' %}" class="{% if hub_section == 'invoices' %}is-active{% endif %}">Rēķini</a>
      {% block hub_nav_extra %}{% endblock %}
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/admin_hub/test_hub_invoices.py -v`
Expected: PASS.

- [ ] **Step 8: Update the project docs**

In `AGENTS.md`, under `## Architecture`, add one line describing `apps/admin_hub` as the staff-facing UI that renders derived state and delegates every mutation to the existing admin endpoints. Under `## Current Status`, add a dated entry naming the five pages and pointing at both this plan and the spec.

In `README.md`, add `/hub/pieteikumi/` and `/hub/rekini/` to whatever section lists the application's entry points.

Also record the two out-of-scope follow-ups so they are not lost:

- nightly-sweep batch caps for `sync_billing_payments()` and `send_due_invoices()`
- removing the dead `member_kit_size_shorts` field and `KitSizeOption.Kind.SHORTS`

- [ ] **Step 9: Full verification**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
```

All three must pass. Then walk the whole flow by hand against a real submitted application: queue → cockpit → approve → agreement → mark sent → download → upload signed → mark signed → plan → issue invoices → invoices list. Every redirect should land back in the Hub, never in Django admin.

- [ ] **Step 10: Commit**

```bash
git add apps/admin_hub templates/admin_hub AGENTS.md README.md tests/admin_hub/test_hub_invoices.py
git commit -m "feat(admin-hub): add outstanding invoices page, bulk guard, and docs"
```

---

## Notes for the executor

**Keep the two stylesheets in sync.** `style-guide/admin/hub.css` is the reviewable mock-up; `static/admin_hub/hub.css` ships. Any visual fix goes into both. `style-guide` is already exposed through `STATICFILES_DIRS` under the `style-guide` prefix, so the mock-ups stay openable in a running app for side-by-side comparison.

**Do not add domain logic.** If a page seems to need a new transition, a new model field, or a new external call, stop and escalate — the value of this work is that it is a skin. The two deliberate exceptions, both argued in their tasks, are `approve_view` honouring `next` (Task 5) and the per-record invoice push endpoint (Task 7). Both reuse existing helpers and existing jobs.

**Things that look derivable but are not.** Do not display: how many times an agreement was downloaded; whether a parent edited an OCR-filled value; whether a reviewer verified a field on another device. None of these are persisted.
