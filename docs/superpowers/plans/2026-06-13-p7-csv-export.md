# P7 Slice B — CSV Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Staff-only, audited CSV export of members and registration applications from the Django admin, with a safe-by-default action and a superuser-gated "with sensitive data" action.

**Architecture:** A reusable `apps/core/export.py` CSV helper (UTF-8 BOM, `;` delimiter, value formatting, formula-injection guard). Per-model column/row builders in `apps/<app>/exports.py` (pure, unit-testable). Two admin changelist actions per model call the helper and record a `DATA_EXPORTED` audit event (reusing P7 Slice A). The sensitive action is superuser-only (hidden via `get_actions` + a defensive check).

**Tech Stack:** Django 5.x, Python `csv`, pytest-django, `uv run` for everything. SQLite for tests.

Spec: `docs/superpowers/specs/2026-06-13-p7-csv-export-design.md`. Depends on P7 Slice A (`apps.core.audit.record_audit_event`, `apps.core.models.AuditEvent`).

---

## File Structure

- `apps/core/export.py` — **new** `csv_response(...)` + `_format` + `_guard`.
- `apps/core/models.py` — add `DATA_EXPORTED` to `AuditEvent.Action`.
- `apps/core/migrations/0003_alter_auditevent_action.py` — **generated** (choices change → AlterField; DB no-op but keeps `makemigrations --check` clean).
- `apps/members/exports.py` — **new** column lists + `member_row(...)`.
- `apps/members/admin.py` — add the two export actions + `get_actions` gating to `MemberAdmin`.
- `apps/registrations/exports.py` — **new** column lists + `application_row(...)`.
- `apps/registrations/admin.py` — add the two export actions + `get_actions` gating to `RegistrationApplicationAdmin`.
- Tests (new): `tests/core/test_csv_export.py`, `tests/members/test_member_export.py`, `tests/registrations/test_application_export.py`.

**Conventions / facts to use:**
- `Member.guardian` is **non-null** (FK, CASCADE) → access `m.guardian.*` directly. `Member.training_group` is nullable → guard with `m.training_group_id`.
- `RegistrationApplication` read accessors exist: `guardian_name`, `guardian_pid`, `guardian_contact_phone`, `guardian_address`, `guardian_contact_email`. `status` is a `TextChoices` → `get_status_display()`.
- `RegistrationApplicationAdmin.get_queryset` already does `select_related("guardian", "parent_account")`.
- Audit helper: `from apps.core.audit import record_audit_event`; actions referenced as `str(AuditEvent.Action.X)` (no django-stubs → keeps mypy clean; matches Slice A wiring).
- Admin actions receive `(self, request, queryset)` and may return an `HttpResponse` (triggers a download).

---

### Task 1: CSV helper `apps/core/export.py`

**Files:**
- Create: `apps/core/export.py`
- Test: `tests/core/test_csv_export.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_csv_export.py
"""csv_response — UTF-8 BOM + semicolon CSV with value formatting + injection guard."""

import csv
import datetime
import io

from apps.core.export import csv_response


def _parse(resp):
    body = resp.content.decode("utf-8")
    assert body.startswith("﻿")  # UTF-8 BOM
    reader = csv.reader(io.StringIO(body[1:]), delimiter=";")
    return list(reader)


def test_header_and_delimiter_and_bom():
    resp = csv_response(filename="x.csv", columns=["A", "B"], rows=[["1", "2"]])
    assert resp["Content-Type"].startswith("text/csv")
    assert 'attachment; filename="x.csv"' in resp["Content-Disposition"]
    rows = _parse(resp)
    assert rows[0] == ["A", "B"]
    assert rows[1] == ["1", "2"]


def test_value_formatting():
    resp = csv_response(
        filename="x.csv",
        columns=["a", "b", "c", "d"],
        rows=[[None, True, False, datetime.date(2026, 9, 20)]],
    )
    assert _parse(resp)[1] == ["", "jā", "nē", "2026-09-20"]


def test_formula_injection_guard():
    resp = csv_response(filename="x.csv", columns=["a"], rows=[["=SUM(A1:A2)"], ["+1"], ["@x"], ["-3"], ["safe"]])
    data = _parse(resp)
    assert data[1] == ["'=SUM(A1:A2)"]
    assert data[2] == ["'+1"]
    assert data[3] == ["'@x"]
    assert data[4] == ["'-3"]
    assert data[5] == ["safe"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_csv_export.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.core.export'`.

- [ ] **Step 3: Implement the helper**

```python
# apps/core/export.py
"""CSV export helper — UTF-8 BOM + semicolon delimiter for Latvian Excel,
with value formatting and a spreadsheet formula-injection guard."""

from __future__ import annotations

import csv
import datetime
import io
from collections.abc import Iterable, Sequence
from typing import Any

from django.http import HttpResponse

_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _format(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "jā" if value else "nē"
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(value)


def _guard(text: str) -> str:
    if text and text[0] in _INJECTION_PREFIXES:
        return "'" + text
    return text


def csv_response(*, filename: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> HttpResponse:
    buf = io.StringIO()
    buf.write("﻿")  # UTF-8 BOM so Latvian Excel detects UTF-8
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(list(columns))
    for row in rows:
        writer.writerow([_guard(_format(cell)) for cell in row])
    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_csv_export.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint/type + commit**

```bash
uv run ruff check apps/core/export.py tests/core/test_csv_export.py
uv run mypy apps/core/export.py
git add apps/core/export.py tests/core/test_csv_export.py
git commit -m "feat(core): csv_response export helper (BOM, ; delimiter, injection guard) (P7 export)"
```

---

### Task 2: `DATA_EXPORTED` audit action

**Files:**
- Modify: `apps/core/models.py` (`AuditEvent.Action`)
- Create: `apps/core/migrations/0003_alter_auditevent_action.py` (generated)
- Test: `tests/core/test_audit_event_model.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_audit_event_model.py`:

```python
def test_data_exported_action_exists():
    assert "data_exported" in set(AuditEvent.Action.values)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_audit_event_model.py::test_data_exported_action_exists -v`
Expected: FAIL — `"data_exported"` not in values.

- [ ] **Step 3: Add the choices value**

In `apps/core/models.py`, in `AuditEvent.Action`, add (e.g. after the billing failure values):

```python
        DATA_EXPORTED = "data_exported", "Data exported"
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations core`
Expected: creates `apps/core/migrations/0003_alter_auditevent_action.py` (an `AlterField` on `auditevent.action` reflecting the new choices — DB no-op but required so `makemigrations --check` stays clean). If it proposes anything beyond this single AlterField, STOP and report.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/core/test_audit_event_model.py -v`
Then: `uv run python manage.py makemigrations --check --dry-run` (expect: No changes detected).
Expected: PASS; no missing migrations.

- [ ] **Step 6: Commit**

```bash
git add apps/core/models.py apps/core/migrations/0003_alter_auditevent_action.py tests/core/test_audit_event_model.py
git commit -m "feat(core): add DATA_EXPORTED audit action (P7 export)"
```

---

### Task 3: Members CSV export

**Files:**
- Create: `apps/members/exports.py`
- Modify: `apps/members/admin.py` (`MemberAdmin`)
- Test: `tests/members/test_member_export.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/members/test_member_export.py
"""Members CSV export — column sets, gating, audit."""

import csv
import io

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from apps.core.models import AuditEvent
from apps.members.admin import MemberAdmin
from apps.members.exports import member_columns, member_row
from apps.members.models import Guardian, Member, TrainingGroup

pytestmark = pytest.mark.django_db


def _member():
    g = Guardian.objects.create(full_name="Anna Ozola", email="a@example.com", phone="+37120000000", address="Rīga", personal_id="010180-12345")
    grp = TrainingGroup.objects.create(name="U-12", is_active=True)
    return Member.objects.create(full_name="Jānis Ozols", personal_id="010110-22222", guardian=g, training_group=grp)


def _request(user):
    req = RequestFactory().post("/admin/")
    req.user = user
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


def _parse(resp):
    body = resp.content.decode("utf-8")[1:]  # strip BOM
    return list(csv.reader(io.StringIO(body), delimiter=";"))


def test_member_row_safe_excludes_personal_id():
    m = _member()
    cols = member_columns(sensitive=False)
    row = member_row(m, sensitive=False)
    assert len(row) == len(cols)
    flat = " ".join(str(c) for c in row)
    assert "010110-22222" not in flat  # member personal_id excluded
    assert "a@example.com" not in flat  # guardian email excluded


def test_member_row_sensitive_includes_personal_id_and_contact():
    m = _member()
    row = member_row(m, sensitive=True)
    flat = " ".join(str(c) for c in row)
    assert "010110-22222" in flat
    assert "a@example.com" in flat


def test_safe_export_action_returns_csv_and_audits():
    m = _member()
    admin_obj = MemberAdmin(Member, AdminSite())
    staff = User.objects.create_user(username="staff", email="s@example.com", is_staff=True)
    resp = admin_obj.export_csv(_request(staff), Member.objects.all())
    rows = _parse(resp)
    assert rows[0] == member_columns(sensitive=False)
    assert "010110-22222" not in resp.content.decode("utf-8")
    e = AuditEvent.objects.get(action=str(AuditEvent.Action.DATA_EXPORTED))
    assert e.actor == staff
    assert e.metadata["sensitive"] is False
    assert e.metadata["count"] == 1


def test_sensitive_action_hidden_from_non_superuser():
    admin_obj = MemberAdmin(Member, AdminSite())
    staff = User.objects.create_user(username="staff2", email="s2@example.com", is_staff=True)
    actions = admin_obj.get_actions(_request(staff))
    assert "export_csv_with_sensitive" not in actions


def test_sensitive_action_refuses_non_superuser_and_no_audit():
    m = _member()
    admin_obj = MemberAdmin(Member, AdminSite())
    staff = User.objects.create_user(username="staff3", email="s3@example.com", is_staff=True)
    result = admin_obj.export_csv_with_sensitive(_request(staff), Member.objects.all())
    assert result is None
    assert not AuditEvent.objects.filter(action=str(AuditEvent.Action.DATA_EXPORTED)).exists()


def test_sensitive_action_for_superuser_exports_and_audits():
    m = _member()
    admin_obj = MemberAdmin(Member, AdminSite())
    su = User.objects.create_superuser(username="su", email="su@example.com", password="pw")
    resp = admin_obj.export_csv_with_sensitive(_request(su), Member.objects.all())
    assert "010110-22222" in resp.content.decode("utf-8")
    e = AuditEvent.objects.get(action=str(AuditEvent.Action.DATA_EXPORTED))
    assert e.metadata["sensitive"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/members/test_member_export.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.members.exports` / `MemberAdmin` has no `export_csv`.

- [ ] **Step 3: Implement the exports module**

```python
# apps/members/exports.py
"""Column definitions + row builder for the Members CSV export."""

from apps.members.models import Member

MEMBER_SAFE_COLUMNS = ["ID", "Vārds uzvārds", "Dzimšanas datums", "Vecāks", "Treniņu grupa"]
MEMBER_SENSITIVE_EXTRA = ["Personas kods", "Vecāka e-pasts", "Vecāka tālrunis", "Vecāka adrese"]


def member_columns(*, sensitive: bool) -> list[str]:
    return MEMBER_SAFE_COLUMNS + MEMBER_SENSITIVE_EXTRA if sensitive else list(MEMBER_SAFE_COLUMNS)


def member_row(member: Member, *, sensitive: bool) -> list:
    g = member.guardian  # non-null FK
    row: list = [
        member.pk,
        member.full_name,
        member.birth_date,
        g.full_name,
        member.training_group.name if member.training_group_id else "",
    ]
    if sensitive:
        row += [member.personal_id, g.email, g.phone, g.address]
    return row
```

- [ ] **Step 4: Implement the admin actions**

In `apps/members/admin.py`, add imports and update `MemberAdmin`:

```python
from django.contrib import admin, messages
from django.utils import timezone

from apps.core.audit import record_audit_event
from apps.core.export import csv_response
from apps.core.models import AuditEvent
from apps.members.exports import member_columns, member_row
```

Add to `MemberAdmin`:

```python
    actions = ["export_csv", "export_csv_with_sensitive"]

    def _export_members(self, request, queryset, *, sensitive: bool):
        qs = queryset.select_related("guardian", "training_group")
        rows = [member_row(m, sensitive=sensitive) for m in qs]
        record_audit_event(
            action=str(AuditEvent.Action.DATA_EXPORTED),
            actor=request.user, request=request,
            target_type="member", target_repr=f"member export ({len(rows)} rows)",
            metadata={"count": len(rows), "sensitive": sensitive, "format": "csv"},
        )
        ts = timezone.localtime().strftime("%Y%m%d-%H%M")
        return csv_response(filename=f"members-{ts}.csv", columns=member_columns(sensitive=sensitive), rows=rows)

    @admin.action(description="Eksportēt CSV (bez sensitīviem datiem)")
    def export_csv(self, request, queryset):
        return self._export_members(request, queryset, sensitive=False)

    @admin.action(description="Eksportēt CSV ar sensitīviem datiem")
    def export_csv_with_sensitive(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(request, "Nepieciešamas superlietotāja tiesības.", level=messages.ERROR)
            return None
        return self._export_members(request, queryset, sensitive=True)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("export_csv_with_sensitive", None)
        return actions
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/members/test_member_export.py -v`
Expected: PASS (6 passed).

- [ ] **Step 6: Lint/type + regression + commit**

```bash
uv run pytest tests/members/ -q
uv run ruff check apps/members/exports.py apps/members/admin.py tests/members/test_member_export.py
uv run mypy apps/members/exports.py apps/members/admin.py
git add apps/members/exports.py apps/members/admin.py tests/members/test_member_export.py
git commit -m "feat(members): admin CSV export (safe + superuser sensitive, audited) (P7 export)"
```

---

### Task 4: Registrations CSV export

**Files:**
- Create: `apps/registrations/exports.py`
- Modify: `apps/registrations/admin.py` (`RegistrationApplicationAdmin`)
- Test: `tests/registrations/test_application_export.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/registrations/test_application_export.py
"""Registration applications CSV export — column sets, gating, audit."""

import csv
import io

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from apps.accounts.models import ParentAccount
from apps.core.models import AuditEvent
from apps.members.services import resolve_guardian_for_account
from apps.registrations.admin import RegistrationApplicationAdmin
from apps.registrations.exports import application_columns, application_row
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _application():
    acct = ParentAccount.objects.create(email="parent@example.com", phone="+37129999999")
    g = resolve_guardian_for_account(acct)
    g.full_name = "Anna Ozola"; g.personal_id = "010180-12345"; g.phone = "+37129999999"; g.address = "Rīga"; g.save()
    return RegistrationApplication.objects.create(
        parent_account=acct, guardian=g, claimed_email=acct.email,
        member_full_name="Jānis Ozols", member_personal_id="010110-22222",
        member_actual_address="Cēsis", status=RegistrationApplication.Status.SUBMITTED,
    )


def _request(user):
    req = RequestFactory().post("/admin/")
    req.user = user
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


def test_safe_row_excludes_sensitive():
    a = _application()
    flat = " ".join(str(c) for c in application_row(a, sensitive=False))
    assert "010110-22222" not in flat
    assert "parent@example.com" not in flat
    assert "Cēsis" not in flat


def test_sensitive_row_includes_sensitive():
    a = _application()
    flat = " ".join(str(c) for c in application_row(a, sensitive=True))
    assert "010110-22222" in flat
    assert "parent@example.com" in flat
    assert "Cēsis" in flat


def test_safe_export_audits_non_sensitive():
    _application()
    admin_obj = RegistrationApplicationAdmin(RegistrationApplication, AdminSite())
    staff = User.objects.create_user(username="staff", email="s@example.com", is_staff=True)
    resp = admin_obj.export_csv(_request(staff), RegistrationApplication.objects.all())
    body = resp.content.decode("utf-8")
    assert body[1:].split("\r\n")[0].split(";") == application_columns(sensitive=False)
    e = AuditEvent.objects.get(action=str(AuditEvent.Action.DATA_EXPORTED))
    assert e.metadata["sensitive"] is False and e.metadata["count"] == 1


def test_sensitive_hidden_and_refused_for_non_superuser():
    _application()
    admin_obj = RegistrationApplicationAdmin(RegistrationApplication, AdminSite())
    staff = User.objects.create_user(username="staff2", email="s2@example.com", is_staff=True)
    assert "export_csv_with_sensitive" not in admin_obj.get_actions(_request(staff))
    assert admin_obj.export_csv_with_sensitive(_request(staff), RegistrationApplication.objects.all()) is None
    assert not AuditEvent.objects.filter(action=str(AuditEvent.Action.DATA_EXPORTED)).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_application_export.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.registrations.exports` / no `export_csv`.

- [ ] **Step 3: Implement the exports module**

```python
# apps/registrations/exports.py
"""Column definitions + row builder for the Registration-applications CSV export."""

from apps.registrations.models import RegistrationApplication

APPLICATION_SAFE_COLUMNS = [
    "ID", "Statuss", "Bērns", "Bērna dzimšanas datums", "Vecāks",
    "Maksājuma veids", "Līguma parakstīšana", "Iesniegts", "Pārskatīts",
]
APPLICATION_SENSITIVE_EXTRA = [
    "Bērna personas kods", "Bērna adrese", "Vecāka e-pasts",
    "Vecāka tālrunis", "Vecāka personas kods", "Vecāka adrese",
]


def application_columns(*, sensitive: bool) -> list[str]:
    return (
        APPLICATION_SAFE_COLUMNS + APPLICATION_SENSITIVE_EXTRA
        if sensitive
        else list(APPLICATION_SAFE_COLUMNS)
    )


def application_row(app: RegistrationApplication, *, sensitive: bool) -> list:
    row: list = [
        app.pk,
        app.get_status_display(),
        app.member_full_name,
        app.member_birth_date,
        app.guardian_name,
        app.preferred_payment_mode,
        app.preferred_agreement_signing,
        app.submitted_at,
        app.reviewed_at,
    ]
    if sensitive:
        row += [
            app.member_personal_id,
            app.member_actual_address,
            app.guardian_contact_email,
            app.guardian_contact_phone,
            app.guardian_pid,
            app.guardian_address,
        ]
    return row
```

- [ ] **Step 4: Implement the admin actions**

In `apps/registrations/admin.py`, add imports:

```python
from django.contrib import messages
from django.utils import timezone

from apps.core.audit import record_audit_event
from apps.core.export import csv_response
from apps.core.models import AuditEvent
from apps.registrations.exports import application_columns, application_row
```

Add to `RegistrationApplicationAdmin` (it already has `get_queryset` with `select_related("guardian", "parent_account")`, which the accessors need):

```python
    actions = ["export_csv", "export_csv_with_sensitive"]

    def _export_applications(self, request, queryset, *, sensitive: bool):
        rows = [application_row(a, sensitive=sensitive) for a in queryset]
        record_audit_event(
            action=str(AuditEvent.Action.DATA_EXPORTED),
            actor=request.user, request=request,
            target_type="registrationapplication",
            target_repr=f"registration export ({len(rows)} rows)",
            metadata={"count": len(rows), "sensitive": sensitive, "format": "csv"},
        )
        ts = timezone.localtime().strftime("%Y%m%d-%H%M")
        return csv_response(
            filename=f"registrations-{ts}.csv",
            columns=application_columns(sensitive=sensitive),
            rows=rows,
        )

    @admin.action(description="Eksportēt CSV (bez sensitīviem datiem)")
    def export_csv(self, request, queryset):
        return self._export_applications(request, queryset, sensitive=False)

    @admin.action(description="Eksportēt CSV ar sensitīviem datiem")
    def export_csv_with_sensitive(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(request, "Nepieciešamas superlietotāja tiesības.", level=messages.ERROR)
            return None
        return self._export_applications(request, queryset, sensitive=True)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("export_csv_with_sensitive", None)
        return actions
```

Note: `apps/registrations/admin.py` already imports `from django.contrib import admin`; add `messages` to that or a separate import. Verify the queryset passed to `_export_applications` carries the `select_related` (the admin action receives the changelist queryset, which is built from `get_queryset`, so it does).

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_application_export.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Lint/type + regression + commit**

```bash
uv run pytest tests/registrations/ -q
uv run ruff check apps/registrations/exports.py apps/registrations/admin.py tests/registrations/test_application_export.py
uv run mypy apps/registrations/exports.py apps/registrations/admin.py
git add apps/registrations/exports.py apps/registrations/admin.py tests/registrations/test_application_export.py
git commit -m "feat(registrations): admin CSV export (safe + superuser sensitive, audited) (P7 export)"
```

---

### Task 5: full gate + docs

**Files:**
- Modify: `AGENTS.md`, `docs/milestones.md`, `docs/audit-log.md`

- [ ] **Step 1: Full gate**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check --dry-run
```
Expected: all green; "No changes detected" for migrations. Fail loud on any failure. (`ruff format` is NOT an enforced gate — do not reformat unrelated files.)

- [ ] **Step 2: Update docs**

- `AGENTS.md`: add a "P7 Slice B — CSV export delivered" entry — `apps/core/export.py` helper (BOM, `;`, injection guard); `DATA_EXPORTED` audit action (+ migration `core/0003`); safe + superuser-gated-sensitive admin actions on Members + Registration applications; column sets; reuses Slice A audit. Note Slice C (admin search/filter + doc-UX + sync-health) remains.
- `docs/milestones.md`: mark the CSV-export part of P7 (acceptance items 2, 3) delivered.
- `docs/audit-log.md`: add `data_exported` to the event catalog (Billing/Exports line) so operators know exports are audited (with `sensitive` flag + `count`).

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md docs/milestones.md docs/audit-log.md
git commit -m "docs: record P7 Slice B CSV export delivery"
```

---

## Self-Review Notes

- **Spec coverage:** §4 helper → T1; §5 `DATA_EXPORTED` (+ the choices migration Django requires) → T2; §6 admin actions + gating → T3 (members) + T4 (registrations); §7 column sets → T3/T4 exports modules; §7a security (safe-default, superuser-gate, injection guard, no row logging) → T1 guard + T3/T4 gating + audit metadata (count/flags only); §8 testing → each task's tests; §9 acceptance → covered; docs → T5.
- **Migration note:** adding a `TextChoices` value triggers a Django `AlterField` migration (`core/0003`) even though it's a DB no-op — T2 generates it so `makemigrations --check` stays clean (run in T5).
- **Name/type consistency:** `csv_response(*, filename, columns, rows)` (T1) used identically in T3/T4; `member_columns/member_row` (T3), `application_columns/application_row` (T4); `record_audit_event(action=str(AuditEvent.Action.DATA_EXPORTED), …, metadata={"count","sensitive","format"})` identical across both admins; `get_actions` gating + defensive `is_superuser` check identical.
- **No-row-data-in-audit:** metadata carries only `count`/`sensitive`/`format` — never exported values (spec §7a).
- **Implementer caveats:** `Member.guardian` confirmed non-null (direct access OK); `RegistrationApplication` accessors + `get_status_display` confirmed present; the registrations admin already `select_related`s guardian+parent_account (accessors won't N+1). `messages` import must be added to each admin module.
