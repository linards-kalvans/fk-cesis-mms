# Guardian consolidation — Plan 2: unified admin

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One admin entry for the parent — the `Guardian` change page manages the domain fields *and* the account-owned `email`/`phone`/`is_active`; `ParentAccount` disappears from the menu (but stays registered).

**Architecture:** A custom `GuardianAdminForm` adds account-backed form fields; `GuardianAdmin.save_model` writes them to the linked `ParentAccount` (email via `change_parent_email`). `FkAdminSite.get_app_list` filters out the `ParentAccount` model entry so the "Accounts" section leaves the menu while the model stays registered (URLs/cross-links still resolve). `ParentAccountAdmin` slims down; the redundant "Vecāka konts" review cross-link is dropped.

**Tech Stack:** Django 5.x admin, pytest-django, `uv run`. One no-op `AlterModelOptions` migration (the Guardian relabel).

**Depends on Plan 1** (proxies + NOT NULL must be in place; the form edits the account through them). Spec: `docs/superpowers/specs/2026-06-15-guardian-parentaccount-consolidation-design.md` (§3.4).

---

## File Structure

- `apps/members/admin.py` — `GuardianAdminForm` (new) + `GuardianAdmin` rework (`form`, `save_model`, `has_add_permission`, `search_fields`, fieldsets).
- `apps/members/models.py` — `Guardian.Meta` `verbose_name`/`verbose_name_plural` = "Vecāks"/"Vecāki" (relabel the single entry).
- `apps/members/migrations/0008_*.py` — generated `AlterModelOptions` (no DB change).
- `apps/core/admin_site.py` — `FkAdminSite.get_app_list` filters out `ParentAccount`.
- `apps/accounts/admin.py` — slim `ParentAccountAdmin` (drop the email-routing `save_model` and the `related_records` block added earlier).
- `apps/registrations/admin_panels.py` — drop the "Vecāka konts" entry from `related_links`.
- Tests (new/extend): `tests/members/test_guardian_admin_form.py`, `tests/core/test_admin_app_ordering.py` (extend), `tests/registrations/test_admin_cross_links.py` (adjust).

**Verified current code:**
- `GuardianAdmin` (`apps/members/admin.py`): `list_display=("full_name","email","phone")`, `search_fields=("full_name","email","personal_id")`, `readonly_fields=("related_records",)`, a `related_records` display method.
- `change_parent_email(account, new_email) -> ParentAccount` (`apps/accounts/services.py:325`): normalizes, rejects duplicates (`ValueError`), atomic, no-op when unchanged.
- `FkAdminSite.get_app_list` (`apps/core/admin_site.py`): calls `super().get_app_list`, stable-sorts so `registrations` is first.
- `ParentAccountAdmin` (`apps/accounts/admin.py`): `list_display`/`search_fields`/`list_filter`, a `related_records` method (added earlier this session), and a `save_model` routing email changes through `change_parent_email`.
- `build_review_context` (`apps/registrations/admin_panels.py`): `related_links` dict includes `"Vecāka konts": admin_link(application.parent_account)`.
- After Plan 1: `Guardian.email`/`phone` are read-only properties; `parent_account` is NOT NULL.

---

### Task 1: GuardianAdminForm — edit account fields from the Guardian page

**Files:**
- Modify: `apps/members/admin.py`, `apps/members/models.py`
- Create: migration via `makemigrations` (relabel)
- Test: `tests/members/test_guardian_admin_form.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/members/test_guardian_admin_form.py
"""The Guardian change page edits the account's email/phone/is_active."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.accounts.models import ParentAccount
from apps.members.models import Guardian

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _guardian():
    acc = ParentAccount.objects.create(email="old@example.com", phone="+371", is_active=True)
    return Guardian.objects.create(full_name="Vecāks", parent_account=acc)


def test_change_page_shows_account_fields():
    g = _guardian()
    c = _staff_client()
    html = c.get(reverse("admin:members_guardian_change", args=[g.pk])).content.decode()
    assert "old@example.com" in html       # email initial from the account
    assert 'name="email"' in html
    assert 'name="phone"' in html
    assert 'name="is_active"' in html


def test_save_writes_phone_and_is_active_to_account():
    g = _guardian()
    c = _staff_client()
    c.post(reverse("admin:members_guardian_change", args=[g.pk]), {
        "full_name": "Vecāks", "personal_id": "", "address": "",
        "email": "old@example.com", "phone": "+37100099", "is_active": "",
    })
    g.refresh_from_db()
    assert g.parent_account.phone == "+37100099"
    assert g.parent_account.is_active is False


def test_save_routes_email_change_through_service():
    g = _guardian()
    c = _staff_client()
    c.post(reverse("admin:members_guardian_change", args=[g.pk]), {
        "full_name": "Vecāks", "personal_id": "", "address": "",
        "email": "new@example.com", "phone": "+371", "is_active": "on",
    })
    g.refresh_from_db()
    assert g.parent_account.email == "new@example.com"


def test_duplicate_email_is_rejected():
    g = _guardian()
    ParentAccount.objects.create(email="taken@example.com")
    c = _staff_client()
    resp = c.post(reverse("admin:members_guardian_change", args=[g.pk]), {
        "full_name": "Vecāks", "personal_id": "", "address": "",
        "email": "taken@example.com", "phone": "+371", "is_active": "on",
    })
    g.refresh_from_db()
    assert g.parent_account.email == "old@example.com"  # unchanged
    assert resp.status_code == 200  # re-renders the form with an error


def test_guardian_add_is_disabled():
    c = _staff_client()
    assert c.get(reverse("admin:members_guardian_add")).status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/members/test_guardian_admin_form.py -v`
Expected: FAIL — no account fields on the form; add not disabled.

- [ ] **Step 3: Implement the form + admin**

In `apps/members/admin.py`, add the form and rework `GuardianAdmin` (keep the existing `related_records` method):
```python
from django import forms

from apps.accounts.services import change_parent_email


class GuardianAdminForm(forms.ModelForm):
    email = forms.EmailField(label="E-pasts (pieslēgšanās)", required=True)
    phone = forms.CharField(label="Tālrunis", max_length=20, required=False)
    is_active = forms.BooleanField(label="Konts aktīvs", required=False)

    class Meta:
        model = Guardian
        fields = ("full_name", "personal_id", "address")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        account = getattr(self.instance, "parent_account", None)
        if account is not None:
            self.fields["email"].initial = account.email
            self.fields["phone"].initial = account.phone
            self.fields["is_active"].initial = account.is_active

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        account = getattr(self.instance, "parent_account", None)
        clash = ParentAccount.objects.filter(email__iexact=email)
        if account is not None:
            clash = clash.exclude(pk=account.pk)
        if clash.exists():
            raise forms.ValidationError("E-pasts jau pieder citam kontam.")
        return email
```

Rework `GuardianAdmin`:
```python
@admin.register(Guardian)
class GuardianAdmin(admin.ModelAdmin):
    form = GuardianAdminForm
    list_display = ("full_name", "email", "phone")
    search_fields = ("full_name", "parent_account__email", "personal_id")
    readonly_fields = ("related_records",)
    fields = ("related_records", "full_name", "personal_id", "address",
              "email", "phone", "is_active")

    def has_add_permission(self, request):
        return False  # guardians are created by the registration flow

    @admin.display(description="Saistītie ieraksti")
    def related_records(self, obj):
        # ... unchanged from the existing method ...

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        account = obj.parent_account
        new_phone = form.cleaned_data.get("phone", "")
        new_active = form.cleaned_data.get("is_active", False)
        if account.phone != new_phone or account.is_active != new_active:
            account.phone = new_phone
            account.is_active = new_active
            account.save(update_fields=["phone", "is_active", "updated_at"])
        new_email = form.cleaned_data.get("email", "")
        if new_email and new_email != account.email:
            change_parent_email(account, new_email)
```
Ensure `ParentAccount` is imported in `apps/members/admin.py` (`from apps.accounts.models import ParentAccount`). Keep the existing `related_records` body verbatim.

In `apps/members/models.py`, add `Meta` to `Guardian` (relabel the single entry):
```python
    class Meta:
        verbose_name = "Vecāks"
        verbose_name_plural = "Vecāki"
```

- [ ] **Step 4: Generate the relabel migration + run tests**

```bash
uv run python manage.py makemigrations members   # AlterModelOptions (no DB change)
uv run pytest tests/members/test_guardian_admin_form.py -v
```
Expected: a `0008_*` options-only migration; 5 passed.

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/members/ -q && \
uv run ruff check apps/members/admin.py apps/members/models.py tests/members/test_guardian_admin_form.py && \
uv run mypy apps/members/admin.py apps/members/models.py && \
git add apps/members/admin.py apps/members/models.py apps/members/migrations/0008_*.py tests/members/test_guardian_admin_form.py && \
git commit -m "feat(members): Guardian admin edits account email/phone/is_active; add disabled; relabel Vecāki"
```

---

### Task 2: Hide ParentAccount from the menu + slim its admin + drop redundant cross-link

**Files:**
- Modify: `apps/core/admin_site.py`, `apps/accounts/admin.py`, `apps/registrations/admin_panels.py`
- Test: `tests/core/test_admin_app_ordering.py` (extend), `tests/registrations/test_admin_cross_links.py` (adjust)

- [ ] **Step 1: Write the failing tests**

Add to `tests/core/test_admin_app_ordering.py`:
```python
def test_parent_account_hidden_from_menu_but_registered():
    from django.urls import reverse
    req = RequestFactory().get("/admin/")
    req.user = User.objects.create_superuser("staff3", "s3@example.com", "pw")
    labels_models = {
        (app["app_label"], m["object_name"])
        for app in admin.site.get_app_list(req)
        for m in app["models"]
    }
    assert ("accounts", "ParentAccount") not in labels_models  # not in the menu
    # still registered → change URL resolves
    assert reverse("admin:accounts_parentaccount_changelist")
```

Adjust the registrations cross-link test: the application review block no longer renders a "Vecāka konts" link. In `tests/registrations/test_admin_cross_links.py::test_change_page_shows_related_records_block`, the guardian/member assertions stay; if any assertion references the parent-account link, remove it (the block keeps Biedrs/Vecāks/Līgums/Rēķini).

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/core/test_admin_app_ordering.py -v`
Expected: FAIL — `ParentAccount` still appears in `get_app_list`.

- [ ] **Step 3: Filter ParentAccount out of the menu**

In `apps/core/admin_site.py`, update `get_app_list`:
```python
    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        # Hide ParentAccount from the menu/index — it's managed via the Guardian
        # page. It stays registered, so its change URL still resolves.
        for app in app_list:
            if app["app_label"] == "accounts":
                app["models"] = [
                    m for m in app["models"] if m["object_name"] != "ParentAccount"
                ]
        app_list = [app for app in app_list if app["models"]]
        # registrations first; the rest keep Django's default order.
        app_list.sort(key=lambda app: app["app_label"] != "registrations")
        return app_list
```

- [ ] **Step 4: Slim ParentAccountAdmin + drop the review cross-link**

In `apps/accounts/admin.py`: remove the `related_records` method + its `readonly_fields` entry and the `format_html`/`admin_link`/`admin_links` imports added earlier; remove the `save_model` email-routing override (email changes now happen on the Guardian page). Leave `list_display`/`search_fields`/`list_filter` so the still-registered change page works.

In `apps/registrations/admin_panels.py`: remove the `"Vecāka konts": admin_link(application.parent_account),` entry from the `related_links` dict (account is managed via the guardian now). Keep Biedrs/Vecāks/Līgums/Rēķini.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_admin_app_ordering.py tests/registrations/test_admin_cross_links.py tests/accounts/ -q`
Expected: PASS.

- [ ] **Step 6: Lint/type + commit**

```bash
uv run ruff check apps/core/admin_site.py apps/accounts/admin.py apps/registrations/admin_panels.py tests/core/test_admin_app_ordering.py && \
uv run mypy apps/core/admin_site.py apps/accounts/admin.py apps/registrations/admin_panels.py && \
git add apps/core/admin_site.py apps/accounts/admin.py apps/registrations/admin_panels.py tests/core/test_admin_app_ordering.py tests/registrations/test_admin_cross_links.py && \
git commit -m "feat(admin): hide ParentAccount from menu, slim its admin, drop redundant cross-link (guardian consolidation)"
```

---

### Task 3: Full gate + docs

**Files:**
- Modify: `AGENTS.md`, `docs/milestones.md`

- [ ] **Step 1: Full gate**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check --dry-run
```
Expected: green; "No changes detected" (the `0008` relabel migration is committed). Fail loud on any failure.

- [ ] **Step 2: Update docs**

- `AGENTS.md`: add "Guardian/ParentAccount consolidation — Plan 2 (unified admin) delivered": the Guardian change page now edits account `email` (via `change_parent_email`) / `phone` / `is_active`; Guardian add disabled; relabelled "Vecāki"; `ParentAccount` filtered out of the admin menu (still registered); `ParentAccountAdmin` slimmed; "Vecāka konts" review cross-link dropped. **Consolidation complete.**
- `docs/milestones.md`: mark the Guardian consolidation complete (Plans 1 + 2).

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md docs/milestones.md && git commit -m "docs: record guardian consolidation Plan 2 (unified admin); consolidation complete"
```

---

## Self-Review Notes

- **Spec coverage (§3.4):** single Guardian entry editing account fields → T1; email change via `change_parent_email` → T1; `has_add_permission=False` → T1; `search_fields` email→`parent_account__email` → T1; relabel "Vecāki" → T1; `FkAdminSite` hides ParentAccount (kept registered) → T2; slim `ParentAccountAdmin` → T2; drop "Vecāka konts" cross-link → T2; docs → T3.
- **Depends on Plan 1:** the form reads/writes `parent_account` assuming it is always present (NOT NULL) and that `email`/`phone` are proxies — do not run Plan 2 before Plan 1 lands.
- **`change_parent_email` reuse:** the form's `clean_email` pre-checks uniqueness for a friendly error; `save_model` still calls `change_parent_email`, which re-validates (defence in depth) and is a no-op when unchanged.
- **Menu filter safety:** filtering the model out of `get_app_list` removes the empty "accounts" app from the index/nav but keeps the model registered, so `reverse("admin:accounts_parentaccount_change", ...)` still resolves (covered by the test).
- **Type/name consistency:** `GuardianAdminForm`, `change_parent_email`, the form field names `email`/`phone`/`is_active` are consistent across the form, `save_model`, and the tests.
- **Migration:** only the no-op `AlterModelOptions` relabel (`0008`) — `makemigrations --check` must be clean after it is committed.
