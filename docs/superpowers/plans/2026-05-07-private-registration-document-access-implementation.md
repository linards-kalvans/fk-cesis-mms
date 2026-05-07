# Private Registration Document Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move registration documents to clearly private storage and expose admin-only preview/download endpoints through Django admin without leaking direct file URLs.

**Architecture:** Keep authorization and file-response construction in `apps/documents/services.py`, use thin Django views for preview/download, and register Django admin links that point only to protected backend endpoints. Move document storage to a dedicated `PRIVATE_DOCUMENTS_ROOT` and preserve existing relative file names so migration can copy old files into the new root without changing database values.

**Tech Stack:** Python 3.12+, Django 5.x, pytest + pytest-django, `uv`, Django admin, `FileResponse`, local filesystem storage.

---

## 1. Design decisions

### 1.1 Private root separate from `MEDIA_ROOT`
**Decision:** Add `PRIVATE_DOCUMENTS_ROOT = BASE_DIR / "private-uploads"` in settings and route `Document.file` through a dedicated storage class bound to that root.

**Why:** `MEDIA_ROOT` is a conventional web-mappable location. Even if this project does not currently expose `/media/`, future reverse-proxy or template mistakes could do so. A separate private root makes the security boundary visible in configuration.

### 1.2 Preserve existing relative file names
**Decision:** Keep document file names like `private/child-identity/...` and change the storage root, not the DB path format.

**Why:** Existing database rows can keep their current `file.name` values. A data migration only needs to copy bytes from old root to new root, avoiding record rewrites and reducing rollout risk.

### 1.3 Service-gated access
**Decision:** Put lookup and authorization in `apps/documents/services.py` with a public API for “fetch authorized document” and “build file response”.

**Why:** Preview/download share the same permission logic, and later audit logging should attach at one seam instead of being duplicated across views.

### 1.4 Backend-only document delivery
**Decision:** Serve preview/download through Django views returning `FileResponse`; never use `document.file.url`.

**Why:** The application, not the storage backend, must remain source of truth for document authorization.

### 1.5 Admin-only first slice
**Decision:** First implementation allows only Django admin users (`is_staff`) to preview/download.

**Why:** This matches approved scope and keeps policy narrow until verified-parent access rules are designed separately.

---

## 2. File-by-file plan

### Create
- `apps/documents/storage.py`
  - deconstructible private filesystem storage class for document files
  - optional helper to compute old/new storage roots for migration
- `apps/documents/services.py`
  - document authorization and `FileResponse` builder
- `apps/documents/views.py`
  - admin preview/download views
- `apps/documents/urls.py`
  - named routes for preview/download
- `apps/documents/admin.py`
  - `DocumentAdmin` registration with preview/download links
- `apps/documents/migrations/0003_private_document_storage.py`
  - alter field to private storage and copy existing files from old root to new root
- `tests/documents/test_admin_document_access.py`
  - document storage, endpoint auth, and admin UI tests

### Modify
- `apps/documents/models.py`
  - use dedicated storage object on `file` field
- `fk_cesis_mms/settings.py`
  - add `PRIVATE_DOCUMENTS_ROOT`
- `fk_cesis_mms/urls.py`
  - include protected document routes before Django admin catch-all
- `docs/milestones.md`
  - note A1 progress after implementation lands
- `AGENTS.md`
  - update current status / security baseline notes after implementation lands
- `README.md`
  - document private document storage behavior if README already covers local file layout or admin usage

### Existing files to consult while implementing
- `apps/registrations/services.py`
- `apps/registrations/views.py`
- `tests/registrations/test_application_workflow.py`
- `fk_cesis_mms/settings.py`

---

## 3. Test strategy

### Framework
- `pytest` + `pytest-django`
- use Django `Client` for endpoint and admin-page tests
- use `override_settings` and `tmp_path` to isolate storage roots per test

### What to test
- document files save under `PRIVATE_DOCUMENTS_ROOT`
- anonymous requests redirect to admin login
- authenticated non-admin requests get `404`
- admin preview returns `200` with `inline` disposition
- admin download returns `200` with `attachment` disposition
- preview/download stream through backend, not redirect to storage URL
- Django admin change page shows Preview/Download links
- soft-deleted document returns `404`

### What not to test
- browser-native PDF/image rendering
- object-storage behavior
- audit event payloads
- parent-access policy
- migration internals beyond a focused copy helper test or manual verification

### Verification commands
- `uv run pytest tests/documents/test_admin_document_access.py -q`
- `uv run pytest -q`
- `uv run ruff check .`
- `uv run mypy .`

---

## 4. Acceptance criteria per unit

### Unit A — private storage configuration
- new documents save under `PRIVATE_DOCUMENTS_ROOT`
- no code path uses `document.file.url` for registration documents
- old files remain accessible after migration copy

### Unit B — protected document endpoints
- anonymous user gets admin-login redirect
- logged-in non-admin gets `404`
- admin preview/download both succeed through backend endpoint
- preview/download differ only by response disposition

### Unit C — Django admin integration
- `Document` is accessible in Django admin
- change page exposes Preview/Download links only when file exists
- links point to protected routes, not raw storage paths

### Unit D — project documentation
- milestone/security notes mention private document access is now implemented
- agent/project guide reflects private storage + admin endpoint pattern

---

## 5. Documentation scope

Update docs only after code and tests are green:
- `docs/milestones.md`: move A1 note from planned to implemented in current snapshot / M1/M2 acceptance notes
- `AGENTS.md`: mention private document access now goes through admin-only protected endpoints backed by `PRIVATE_DOCUMENTS_ROOT`
- `README.md`: only if current README discusses local storage layout or admin document handling; keep changes minimal

---

## 6. Task plan

### Task 1: Write failing tests for private storage and protected access

**Files:**
- Create: `tests/documents/test_admin_document_access.py`
- Consult: `tests/registrations/test_application_workflow.py`
- Consult: `tests/accounts/test_login_views.py`

- [ ] **Step 1: Write the storage-root test and endpoint-auth tests**

```python
import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.documents.models import Document
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _make_admin_user():
    return get_user_model().objects.create_user(
        username="admin",
        email="admin@example.com",
        password="password123",
        is_staff=True,
        is_superuser=True,
    )


def _make_non_admin_user():
    return get_user_model().objects.create_user(
        username="user",
        email="user@example.com",
        password="password123",
    )


def _make_document():
    application = RegistrationApplication.objects.create(
        guardian_email="guardian@example.com",
        claimed_email="guardian@example.com",
    )
    return Document.objects.create(
        application=application,
        kind=Document.Kind.CHILD_IDENTITY,
        file=SimpleUploadedFile("id.png", b"file-bytes", content_type="image/png"),
        original_filename="id.png",
        content_type="image/png",
        file_size=10,
    )


@override_settings(PRIVATE_DOCUMENTS_ROOT="/tmp/test-private-uploads")
def test_document_file_uses_private_storage_root():
    document = _make_document()
    assert "/test-private-uploads/" in document.file.path


def test_preview_redirects_anonymous_user_to_admin_login():
    client = Client()
    document = _make_document()
    response = client.get(reverse("documents:admin-document-preview", args=[document.pk]))
    assert response.status_code == 302
    assert reverse("admin:login") in response["Location"]


def test_preview_returns_404_for_logged_in_non_admin():
    client = Client()
    user = _make_non_admin_user()
    client.force_login(user)
    document = _make_document()
    response = client.get(reverse("documents:admin-document-preview", args=[document.pk]))
    assert response.status_code == 404
```

- [ ] **Step 2: Add admin preview/download success tests and admin-page link test**

```python
def test_preview_returns_inline_response_for_admin():
    client = Client()
    admin = _make_admin_user()
    client.force_login(admin)
    document = _make_document()

    response = client.get(reverse("documents:admin-document-preview", args=[document.pk]))

    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("inline;")


def test_download_returns_attachment_response_for_admin():
    client = Client()
    admin = _make_admin_user()
    client.force_login(admin)
    document = _make_document()

    response = client.get(reverse("documents:admin-document-download", args=[document.pk]))

    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment;")


def test_document_admin_change_page_shows_preview_and_download_links():
    client = Client()
    admin = _make_admin_user()
    client.force_login(admin)
    document = _make_document()

    response = client.get(reverse("admin:documents_document_change", args=[document.pk]))

    assert response.status_code == 200
    content = response.content.decode()
    assert reverse("documents:admin-document-preview", args=[document.pk]) in content
    assert reverse("documents:admin-document-download", args=[document.pk]) in content
```

- [ ] **Step 3: Add soft-delete and no-storage-url assertions**

```python
def test_soft_deleted_document_returns_404_for_admin():
    client = Client()
    admin = _make_admin_user()
    client.force_login(admin)
    document = _make_document()
    document.deleted_at = timezone.now()
    document.save(update_fields=["deleted_at", "updated_at"])

    response = client.get(reverse("documents:admin-document-preview", args=[document.pk]))

    assert response.status_code == 404


def test_admin_download_streams_file_without_storage_redirect():
    client = Client()
    admin = _make_admin_user()
    client.force_login(admin)
    document = _make_document()

    response = client.get(reverse("documents:admin-document-download", args=[document.pk]))

    assert response.status_code == 200
    assert response.get("Location") is None
    assert response.streaming is True
    assert b"".join(response.streaming_content) == b"file-bytes"
```

- [ ] **Step 4: Run targeted tests to verify red phase**

Run:
```bash
uv run pytest tests/documents/test_admin_document_access.py -q
```

Expected:
- FAIL with missing module/import/URL/admin registration errors because storage, services, views, and admin wiring do not exist yet.

- [ ] **Step 5: Do not commit**

User has not requested a git commit. Keep changes uncommitted.

### Task 2: Implement private document storage configuration

**Files:**
- Create: `apps/documents/storage.py`
- Modify: `fk_cesis_mms/settings.py`
- Modify: `apps/documents/models.py`
- Create: `apps/documents/migrations/0003_private_document_storage.py`
- Test: `tests/documents/test_admin_document_access.py::test_document_file_uses_private_storage_root`

- [ ] **Step 1: Add private storage setting**

Add to `fk_cesis_mms/settings.py` near `MEDIA_ROOT`:

```python
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "uploads"
PRIVATE_DOCUMENTS_ROOT = BASE_DIR / "private-uploads"
```

- [ ] **Step 2: Create dedicated storage class**

Create `apps/documents/storage.py`:

```python
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateDocumentStorage(FileSystemStorage):
    @property
    def base_location(self) -> str:
        return str(Path(settings.PRIVATE_DOCUMENTS_ROOT))

    @property
    def location(self) -> str:
        return self.base_location


def private_document_old_root() -> Path:
    return Path(settings.MEDIA_ROOT)


def private_document_new_root() -> Path:
    return Path(settings.PRIVATE_DOCUMENTS_ROOT)
```

- [ ] **Step 3: Bind `Document.file` to the private storage**

Update `apps/documents/models.py`:

```python
from apps.documents.storage import PrivateDocumentStorage

private_document_storage = PrivateDocumentStorage()


class Document(TimeStampedModel):
    ...
    file = models.FileField(
        upload_to="private/child-identity/",
        storage=private_document_storage,
    )
```

- [ ] **Step 4: Create migration that alters field and copies existing files**

Create `apps/documents/migrations/0003_private_document_storage.py`:

```python
from pathlib import Path
import shutil

from django.conf import settings
from django.db import migrations, models

from apps.documents.storage import PrivateDocumentStorage


def copy_existing_document_files(apps, schema_editor):
    Document = apps.get_model("documents", "Document")
    old_root = Path(settings.MEDIA_ROOT)
    new_root = Path(settings.PRIVATE_DOCUMENTS_ROOT)
    new_root.mkdir(parents=True, exist_ok=True)

    for document in Document.objects.exclude(file=""):
        relative_name = document.file.name
        source = old_root / relative_name
        destination = new_root / relative_name
        if destination.exists() or not source.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


class Migration(migrations.Migration):
    dependencies = [("documents", "0002_initial")]

    operations = [
        migrations.AlterField(
            model_name="document",
            name="file",
            field=models.FileField(
                upload_to="private/child-identity/",
                storage=PrivateDocumentStorage(),
            ),
        ),
        migrations.RunPython(copy_existing_document_files, migrations.RunPython.noop),
    ]
```

If Django cannot serialize the storage import cleanly in migration, move the storage instantiation into a deconstructible class exactly as above and regenerate until the migration imports only stable module paths.

- [ ] **Step 5: Run storage-root test**

Run:
```bash
uv run pytest tests/documents/test_admin_document_access.py::test_document_file_uses_private_storage_root -q
```

Expected:
- PASS

- [ ] **Step 6: Do not commit**

User has not requested a git commit. Keep changes uncommitted.

### Task 3: Implement service-gated preview/download responses

**Files:**
- Create: `apps/documents/services.py`
- Test: `tests/documents/test_admin_document_access.py::test_preview_returns_404_for_logged_in_non_admin`
- Test: `tests/documents/test_admin_document_access.py::test_soft_deleted_document_returns_404_for_admin`

- [ ] **Step 1: Create authorization and response helpers**

Create `apps/documents/services.py`:

```python
from django.http import FileResponse, Http404

from apps.documents.models import Document


def get_admin_accessible_document(*, document_id: int, user) -> Document:
    if not user.is_authenticated or not user.is_staff:
        raise Http404

    document = Document.objects.filter(
        pk=document_id,
        deleted_at__isnull=True,
    ).exclude(file="").first()
    if document is None:
        raise Http404
    return document


def build_document_response(*, document: Document, disposition: str) -> FileResponse:
    if disposition not in {"inline", "attachment"}:
        raise ValueError("disposition must be inline or attachment")

    document.file.open("rb")
    response = FileResponse(
        document.file,
        as_attachment=disposition == "attachment",
        filename=document.original_filename,
        content_type=document.content_type or "application/octet-stream",
    )
    if disposition == "inline":
        response.headers["Content-Disposition"] = (
            f'inline; filename="{document.original_filename}"'
        )
    return response
```

- [ ] **Step 2: Run service-focused tests**

Run:
```bash
uv run pytest \
  tests/documents/test_admin_document_access.py::test_preview_returns_404_for_logged_in_non_admin \
  tests/documents/test_admin_document_access.py::test_soft_deleted_document_returns_404_for_admin -q
```

Expected:
- still FAIL because views/URLs are not wired yet, but failures should no longer be about missing services.

- [ ] **Step 3: Do not commit**

User has not requested a git commit. Keep changes uncommitted.

### Task 4: Implement protected views and URLs

**Files:**
- Create: `apps/documents/views.py`
- Create: `apps/documents/urls.py`
- Modify: `fk_cesis_mms/urls.py`
- Test: `tests/documents/test_admin_document_access.py::test_preview_redirects_anonymous_user_to_admin_login`
- Test: `tests/documents/test_admin_document_access.py::test_preview_returns_inline_response_for_admin`
- Test: `tests/documents/test_admin_document_access.py::test_download_returns_attachment_response_for_admin`

- [ ] **Step 1: Create protected views**

Create `apps/documents/views.py`:

```python
from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

from apps.documents.services import build_document_response, get_admin_accessible_document


def admin_document_preview(request: HttpRequest, document_id: int) -> HttpResponse:
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), reverse("admin:login"))
    document = get_admin_accessible_document(document_id=document_id, user=request.user)
    return build_document_response(document=document, disposition="inline")


def admin_document_download(request: HttpRequest, document_id: int) -> HttpResponse:
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), reverse("admin:login"))
    document = get_admin_accessible_document(document_id=document_id, user=request.user)
    return build_document_response(document=document, disposition="attachment")
```

- [ ] **Step 2: Add named URL routes**

Create `apps/documents/urls.py`:

```python
from django.urls import path

from apps.documents import views

app_name = "documents"

urlpatterns = [
    path("<int:document_id>/preview/", views.admin_document_preview, name="admin-document-preview"),
    path("<int:document_id>/download/", views.admin_document_download, name="admin-document-download"),
]
```

- [ ] **Step 3: Mount protected routes before admin catch-all**

Update `fk_cesis_mms/urls.py`:

```python
urlpatterns = [
    path("admin/documents/", include("apps.documents.urls")),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.registrations.urls")),
]
```

- [ ] **Step 4: Run endpoint tests**

Run:
```bash
uv run pytest \
  tests/documents/test_admin_document_access.py::test_preview_redirects_anonymous_user_to_admin_login \
  tests/documents/test_admin_document_access.py::test_preview_returns_inline_response_for_admin \
  tests/documents/test_admin_document_access.py::test_download_returns_attachment_response_for_admin -q
```

Expected:
- PASS

- [ ] **Step 5: Run no-storage-url and non-admin tests**

Run:
```bash
uv run pytest \
  tests/documents/test_admin_document_access.py::test_preview_returns_404_for_logged_in_non_admin \
  tests/documents/test_admin_document_access.py::test_admin_download_streams_file_without_storage_redirect -q
```

Expected:
- PASS

- [ ] **Step 6: Do not commit**

User has not requested a git commit. Keep changes uncommitted.

### Task 5: Register `Document` in Django admin with preview/download links

**Files:**
- Create: `apps/documents/admin.py`
- Test: `tests/documents/test_admin_document_access.py::test_document_admin_change_page_shows_preview_and_download_links`

- [ ] **Step 1: Register a focused `DocumentAdmin`**

Create `apps/documents/admin.py`:

```python
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from apps.documents.models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "application",
        "kind",
        "uploaded_by_parent_at",
        "access_links",
    )
    readonly_fields = (
        "application",
        "kind",
        "original_filename",
        "content_type",
        "file_size",
        "ocr_status",
        "uploaded_by_parent_at",
        "deleted_at",
        "access_links",
    )
    fields = readonly_fields

    def access_links(self, obj: Document) -> str:
        if not obj.file:
            return "—"
        preview_url = reverse("documents:admin-document-preview", args=[obj.pk])
        download_url = reverse("documents:admin-document-download", args=[obj.pk])
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Preview</a> | '
            '<a href="{}">Download</a>',
            preview_url,
            download_url,
        )

    access_links.short_description = "Access"
```

- [ ] **Step 2: Run admin-link test**

Run:
```bash
uv run pytest tests/documents/test_admin_document_access.py::test_document_admin_change_page_shows_preview_and_download_links -q
```

Expected:
- PASS

- [ ] **Step 3: Do not commit**

User has not requested a git commit. Keep changes uncommitted.

### Task 6: Cover migration safety and update docs

**Files:**
- Modify: `tests/documents/test_admin_document_access.py`
- Modify: `docs/milestones.md`
- Modify: `AGENTS.md`
- Modify: `README.md` (only if needed)

- [ ] **Step 1: Add a focused test or helper-level assertion for private path stability**

Extend `tests/documents/test_admin_document_access.py` with one more assertion around saved file names:

```python
def test_document_keeps_relative_name_under_private_storage_root():
    document = _make_document()
    assert document.file.name.startswith("private/child-identity/")
```

This protects the migration assumption that database file names do not need rewriting.

- [ ] **Step 2: Manually verify migration-copy behavior in local dev database if any existing documents are present**

Run:
```bash
uv run python manage.py migrate
```

Then inspect one existing `Document` from Django shell:

```bash
uv run python manage.py shell -c "from apps.documents.models import Document; d = Document.objects.exclude(file='').first(); print(d.file.name if d else 'no-docs'); print(d.file.storage.location if d else 'no-docs')"
```

Expected:
- migration succeeds
- storage location prints `.../private-uploads`
- existing document row still has same relative file name

- [ ] **Step 3: Update milestone and project guide docs**

Apply these content updates after code is green:

`docs/milestones.md`
```md
- **Current milestone focus:** `M2` registration intake is substantially implemented ... remaining `M1` deliverables still need implementation (background jobs, audit baseline); private document access controls are now implemented.
```

`AGENTS.md`
```md
- `apps/documents` now uses a dedicated private storage root and admin-only backend endpoints for preview/download.
```

Only touch `README.md` if it already documents uploads/media behavior; if not, skip README to avoid scope creep.

- [ ] **Step 4: Run targeted document test file again**

Run:
```bash
uv run pytest tests/documents/test_admin_document_access.py -q
```

Expected:
- PASS

- [ ] **Step 5: Do not commit**

User has not requested a git commit. Keep changes uncommitted.

### Task 7: Final verification

**Files:**
- No new files
- Verify all modified files from Tasks 1–6

- [ ] **Step 1: Run full test suite**

Run:
```bash
uv run pytest -q
```

Expected:
- PASS

- [ ] **Step 2: Run lint**

Run:
```bash
uv run ruff check .
```

Expected:
- PASS

- [ ] **Step 3: Run type checks**

Run:
```bash
uv run mypy .
```

Expected:
- PASS

- [ ] **Step 4: Generate diff URL for review**

Run critique filtered to changed files, for example:

```bash
bunx critique --web "Add private admin document access" \
  --filter "apps/documents/*.py" \
  --filter "apps/documents/migrations/*.py" \
  --filter "fk_cesis_mms/settings.py" \
  --filter "fk_cesis_mms/urls.py" \
  --filter "tests/documents/test_admin_document_access.py" \
  --filter "docs/milestones.md" \
  --filter "AGENTS.md" \
  --filter "README.md"
```

Expected:
- critique prints a shareable diff URL for user review

- [ ] **Step 5: Do not commit**

User has not requested a git commit. Keep changes uncommitted.

---

## 7. Self-review against spec

### Spec coverage
- private storage root: covered in Task 2
- admin-only protected endpoints: covered in Tasks 3–4
- preview/download through Django admin: covered in Task 5
- anonymous redirect + non-admin `404`: covered in Tasks 1 and 4
- no direct public URLs: covered in Tasks 3–5 and final diff review
- audit hook seam: covered in design decision 1.3 and service structure in Task 3

### Placeholder scan
- Removed generic “add validation” phrasing; each task names exact files, code shape, and commands.
- Commit steps replaced with explicit “Do not commit” because user has not requested a commit.

### Type consistency
- Route names use `documents:admin-document-preview` / `documents:admin-document-download` consistently.
- Service API uses `get_admin_accessible_document` and `build_document_response` consistently across tasks.
- Private storage root name stays `PRIVATE_DOCUMENTS_ROOT` in settings, storage, tests, and docs.
