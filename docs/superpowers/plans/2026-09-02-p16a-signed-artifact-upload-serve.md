# P16-A Signed-Agreement Artifact Upload and Serve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let staff attach one private signed PDF or `.edoc` artifact to every Agreement, then safely serve every uploaded artifact to authorized staff and its verified guardian without changing agreement or billing state.

**Architecture:** P16-A adds six artifact fields directly to `Agreement`; it does not create an artifact model, provider adapter, background job, validation result, or artifact version. A synchronous agreement service validates and replaces the private `FileField`, then a pure response helper streams it. Surface-specific views own authorization while sharing that response helper. Registration admin, family hub, and parent portal each list artifacts across all agreements for a member; DocuSeal-generated document paths remain separate.

**Tech Stack:** Python 3.12, Django 5, Django admin, Django `FileField`/`FileResponse`, existing `PrivateDocumentStorage`, pytest-django, django-q2 deliberately unused in this slice.

---

## File structure and contracts

| File | Responsibility |
|---|---|
| `apps/agreements/models.py` | Add one private signed-artifact `FileField` and five metadata fields to existing `Agreement`. |
| `apps/agreements/migrations/0007_p16a_signed_artifact.py` | Add the six `Agreement` columns; depend on `0006_agreement_number`. |
| `apps/core/models.py` + `apps/core/migrations/0009_alter_auditevent_action.py` | Add sole `SIGNED_ARTIFACT_UPLOADED` audit action; operation belongs in redacted metadata. |
| `fk_cesis_mms/settings.py`, `.env.example` | Add `SIGNED_ARTIFACT_MAX_BYTES`, default `20 * 1024 * 1024`. |
| `apps/agreements/services.py` | Add `upload_signed_artifact(agreement, file_upload, actor) -> Agreement`, with validation, replacement safety, and audit write. |
| `apps/agreements/signed_artifact_proxy.py` | New pure private-file `FileResponse` builder; no authorization or provider calls. |
| `apps/registrations/admin_panels.py`, `apps/registrations/admin.py` | Build all-agreement staff context; add registration-admin upload and serve endpoints with application/member ownership guards. |
| `apps/agreements/admin.py` | Add staff view-permission-gated signed-artifact serve endpoint and change-page context. |
| `apps/members/family_hub.py`, `apps/members/admin.py` | Build all-agreement artifact links per child; add guardian-scoped staff proxy route. |
| `apps/registrations/views.py`, `apps/registrations/urls.py` | Build guardian-owned all-agreement artifact groups and add guardian ownership proxy route. |
| `templates/registrations/admin/_signed_artifact_module.html` | New sole upload UI; render every Agreement of source member, newest first. |
| `templates/admin/registrations/registrationapplication/change_form.html` | Include upload module beside current agreement module. |
| `templates/admin/agreements/agreement/change_form.html` | Add signed artifact inline/download panel; leave DocuSeal iframe untouched. |
| `templates/admin/members/guardian/family_hub.html` | Render separate all-agreement signed-artifact cards; do not modify DocuSeal list. |
| `templates/registrations/parent_portal.html` | Render separate per-member signed-artifact cards, newest first; no card when no artifact exists. |
| `tests/agreements/test_signed_artifact_service.py` | Model, validation, replacement, storage cleanup, audit, state/billing isolation tests. |
| `tests/agreements/test_signed_artifact_proxy.py` | Pure response content type/disposition and missing-file tests. |
| `tests/registrations/test_signed_artifact_admin.py` | Registration-admin upload/serve permission and all-agreement panel tests. |
| `tests/agreements/test_signed_artifact_agreement_admin.py` | Read-only Agreement admin presentation and serving tests. |
| `tests/members/test_family_hub_signed_artifacts.py` | Family hub all-agreement listing and guardian-scoped staff proxy tests. |
| `tests/registrations/test_parent_signed_artifacts.py` | Portal grouping/order and guardian ownership proxy tests. |

**Explicit non-files:** Do not alter `apps/documents/models.py`, OCR code, `apps/integrations/*`, django-q tasks, DocuSeal proxy functions, agreement-state services, billing services, or CSS. P16-B owns verification/version/provider work.

## Shared implementation rules

```python
# apps/agreements/models.py
signed_artifact = models.FileField(
    upload_to="agreements/signed/%Y/%m/%d/",
    storage=PrivateDocumentStorage(),
    blank=True,
    default="",
)
signed_artifact_original_filename = models.CharField(max_length=255, blank=True, default="")
signed_artifact_content_type = models.CharField(max_length=255, blank=True, default="")
signed_artifact_file_size = models.PositiveIntegerField(default=0)
signed_artifact_uploaded_at = models.DateTimeField(null=True, blank=True)
signed_artifact_updated_at = models.DateTimeField(null=True, blank=True)
```

```python
# Mandatory service behavior
# 1. Validate suffix/size/PDF content type before storage write.
# 2. Preserve old field name and metadata in local variables.
# 3. Save new file and six Agreement fields inside transaction.atomic().
# 4. Record one SIGNED_ARTIFACT_UPLOADED event with only:
#    {"agreement_id": agreement.pk, "operation": "uploaded" | "replaced"}
# 5. transaction.on_commit deletes old storage object. It never runs if DB save fails.
# 6. There is no enqueue, provider import, agreement state change, or billing write.
```

```python
# Shared response helper contract
def build_signed_artifact_response(
    agreement: Agreement,
    *,
    disposition: Literal["inline", "attachment"],
) -> FileResponse:
    # blank file or invalid disposition -> Http404
    # PDF may be inline for staff; all .edoc responses are forced attachment
    # guardian callers pass attachment only; helper performs no permission check
```

---

### Task 1: Write full P16-A red test suite

**Files:**
- Create: `tests/agreements/test_signed_artifact_service.py`
- Create: `tests/agreements/test_signed_artifact_proxy.py`
- Create: `tests/registrations/test_signed_artifact_admin.py`
- Create: `tests/agreements/test_signed_artifact_agreement_admin.py`
- Create: `tests/members/test_family_hub_signed_artifacts.py`
- Create: `tests/registrations/test_parent_signed_artifacts.py`
- Modify: `tests/agreements/test_agreement_model.py` only if its existing model-field style is the natural home for field-default assertions.

- [ ] **Step 1: Add failing service and model tests.**

```python
def uploaded_file(name: str, body: bytes, content_type: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, body, content_type=content_type)

def test_upload_sets_private_agreement_fields_and_redacted_audit(staff_user, agreement):
    updated = upload_signed_artifact(
        agreement,
        uploaded_file("signed.PDF", b"%PDF-1.7\n", "application/pdf"),
        staff_user,
    )
    updated.refresh_from_db()
    assert updated.signed_artifact.name.startswith("agreements/signed/")
    assert updated.signed_artifact_original_filename == "signed.PDF"
    assert updated.signed_artifact_content_type == "application/pdf"
    assert updated.signed_artifact_file_size == len(b"%PDF-1.7\n")
    event = AuditEvent.objects.get(action=AuditEvent.Action.SIGNED_ARTIFACT_UPLOADED)
    assert event.metadata == {"agreement_id": agreement.pk, "operation": "uploaded"}

def test_upload_does_not_change_state_or_create_billing(staff_user, agreement):
    before_state = agreement.state
    before_records = BillingRecord.objects.count()
    upload_signed_artifact(agreement, uploaded_file("x.pdf", b"%PDF-", "application/pdf"), staff_user)
    agreement.refresh_from_db()
    assert agreement.state == before_state
    assert BillingRecord.objects.count() == before_records
```

Add parametrized failures for unsupported suffix, oversized file under `override_settings(SIGNED_ARTIFACT_MAX_BYTES=4)`, PDF MIME mismatch, and case-insensitive `.PDF` / `.EDOC`. Assert each failure leaves old filename, metadata, storage object, and audit row count unchanged.

Add replacement tests with `django_capture_on_commit_callbacks(execute=True)`: first upload, second upload, assert metadata changes, audit operation is `replaced`, old storage name is absent only after callback execution, and new object remains. Patch Agreement save to raise after new storage write; assert old DB fields and storage object survive and the newly written object is best-effort removed.

- [ ] **Step 2: Add failing pure-proxy tests.**

```python
def test_staff_pdf_can_be_inline(agreement_with_signed_pdf):
    response = build_signed_artifact_response(agreement_with_signed_pdf, disposition="inline")
    assert response["Content-Type"] == "application/pdf"
    assert "inline" in response["Content-Disposition"]

def test_edoc_is_forced_attachment(agreement_with_signed_edoc):
    response = build_signed_artifact_response(agreement_with_signed_edoc, disposition="inline")
    assert "attachment" in response["Content-Disposition"]

def test_blank_artifact_or_unknown_disposition_is_404(agreement):
    with pytest.raises(Http404):
        build_signed_artifact_response(agreement, disposition="attachment")
```

Also assert original filename reaches `Content-Disposition` through Django header utilities, PDF attachment works, and no provider mock is called.

- [ ] **Step 3: Add failing staff-surface tests.**

Test all of these contracts:

```python
def test_registration_admin_upload_accepts_only_source_members_agreement(staff_client, app, other_agreement):
    url = reverse("admin:registrations_registrationapplication_signed_artifact_upload", args=[app.pk, other_agreement.pk])
    response = staff_client.post(url, {"signed_artifact": uploaded_file("x.pdf", b"%PDF-", "application/pdf")})
    assert response.status_code == 404

def test_registration_panel_lists_current_and_historical_agreements_newest_first(...):
    # generated, superseded, voided, and discontinued rows with no artifact
    # must still render upload forms; rows with artifacts additionally render serve links.
    ...
```

Cover registration-admin POST requires change permission, rejects GET to upload endpoint by redirecting safely to change page, reports Latvian `ValueError` text, and never exposes `agreement.signed_artifact.url` in HTML. Cover registration staff PDF inline and `.edoc` attachment behavior, including a foreign agreement 404.

For Agreement admin, assert it remains add/change/delete disabled, staff with view permission sees a signed artifact panel only if file exists, PDF iframe/link uses the named same-origin route, and nonstaff is denied. Do not weaken existing DocuSeal assertions.

- [ ] **Step 4: Add failing family-hub and parent-portal tests.**

```python
def test_parent_portal_lists_every_owned_members_artifact_newest_first(verified_client, parent, agreements):
    response = verified_client.get(reverse("registrations:parent-portal"))
    html = response.content.decode()
    assert html.index("newest.pdf") < html.index("older.edoc")
    assert "foreign.pdf" not in html

def test_parent_signed_artifact_proxy_hides_foreign_agreement(verified_client, foreign_agreement):
    url = reverse("registrations:parent-signed-artifact", args=[foreign_agreement.pk])
    assert verified_client.get(url).status_code == 404
```

Cover no parent session redirects to registration entry, own PDF is attachment (never inline), own `.edoc` is attachment, blank file is 404, portal renders no signed-artifact section when no family agreements have files, and portal has no raw storage URL. For family hub, assert staff route verifies guardian-to-member-to-agreement ownership, lists current/superseded/voided/discontinued artifacts per member newest first, and cannot fetch another guardian's artifact.

- [ ] **Step 5: Run red phase before any business implementation.**

Run:

```bash
uv run pytest -q \
  tests/agreements/test_signed_artifact_service.py \
  tests/agreements/test_signed_artifact_proxy.py \
  tests/registrations/test_signed_artifact_admin.py \
  tests/agreements/test_signed_artifact_agreement_admin.py \
  tests/members/test_family_hub_signed_artifacts.py \
  tests/registrations/test_parent_signed_artifacts.py
```

Expected: fail during collection or assertions because P16-A fields, service, routes, and templates do not exist. Do not implement before this red result is recorded.

---

### Task 2: Add Agreement schema, size configuration, and audit vocabulary

**Files:**
- Modify: `apps/agreements/models.py`
- Create: `apps/agreements/migrations/0007_p16a_signed_artifact.py`
- Modify: `apps/core/models.py`
- Create: `apps/core/migrations/0009_alter_auditevent_action.py`
- Modify: `fk_cesis_mms/settings.py`
- Modify: `.env.example`
- Test: `tests/agreements/test_signed_artifact_service.py`

- [ ] **Step 1: Add Agreement fields with private storage.**

Import `PrivateDocumentStorage` from `apps.documents.storage`, instantiate module-level storage in `apps/agreements/models.py`, and add exactly these fields to `Agreement`:

```python
signed_artifact = models.FileField(
    upload_to="agreements/signed/%Y/%m/%d/",
    storage=private_document_storage,
    blank=True,
    default="",
)
signed_artifact_original_filename = models.CharField(max_length=255, blank=True, default="")
signed_artifact_content_type = models.CharField(max_length=255, blank=True, default="")
signed_artifact_file_size = models.PositiveIntegerField(default=0)
signed_artifact_uploaded_at = models.DateTimeField(null=True, blank=True)
signed_artifact_updated_at = models.DateTimeField(null=True, blank=True)
```

Do not add a history model, validation field, soft delete, version token, provider identifier, or public storage URL.

- [ ] **Step 2: Add settings and audit choice.**

Add next to existing document constraints:

```python
SIGNED_ARTIFACT_MAX_BYTES = int(
    os.environ.get("SIGNED_ARTIFACT_MAX_BYTES", str(20 * 1024 * 1024))
)
```

Add to `.env.example`:

```dotenv
# P16-A signed PDF/.edoc maximum upload size (20 MiB by default).
SIGNED_ARTIFACT_MAX_BYTES=20971520
```

Add one, and only one, audit action:

```python
SIGNED_ARTIFACT_UPLOADED = "signed_artifact_uploaded", "Signed agreement artifact uploaded"
```

Replacement is encoded only by audit metadata `operation="replaced"`; do not add `SIGNED_ARTIFACT_REPLACED`.

- [ ] **Step 3: Generate and inspect migrations.**

Create `0007_p16a_signed_artifact.py` with dependency `("agreements", "0006_agreement_number")` and six `AddField` operations. Create the choices-only Core migration after `0008_alter_auditevent_action.py`. Confirm neither migration imports services, starts a task, calls storage, or performs network I/O.

Run:

```bash
uv run python manage.py makemigrations --check
uv run python manage.py migrate
```

Expected: migration check reports no additional model changes; migration applies locally.

- [ ] **Step 4: Run model/config focused tests.**

Run:

```bash
uv run pytest -q tests/agreements/test_signed_artifact_service.py -k "field or config or audit"
```

Expected: schema/default/audit-choice tests pass; service tests still fail until Task 3.

---

### Task 3: Implement private artifact service and pure file proxy

**Files:**
- Modify: `apps/agreements/services.py`
- Create: `apps/agreements/signed_artifact_proxy.py`
- Test: `tests/agreements/test_signed_artifact_service.py`
- Test: `tests/agreements/test_signed_artifact_proxy.py`

- [ ] **Step 1: Implement candidate validation with fixed Latvian errors.**

Use `Path(file_upload.name).suffix.lower()` and `Path(file_upload.name).name`. Reject unsupported extension with:

```python
"Neatbalstītais faila formāts. Pieņemti tikai PDF vai .edoc faili."
```

Reject a size above `settings.SIGNED_ARTIFACT_MAX_BYTES` with:

```python
"Faila izmērs pārsniedz atļauto robežu."
```

For `.pdf`, reject a present non-PDF browser content type with:

```python
"PDF failam jābūt ar 'application/pdf' tipu."
```

Treat `.edoc` content type as unknown: store `""`, do not assign a MIME type, and do not use it to reject a valid suffix. Raise `ValueError` with these messages. Never log the filename or file bytes.

- [ ] **Step 2: Implement safe upload/replace service.**

Add this public contract in `apps/agreements/services.py`:

```python
def upload_signed_artifact(
    agreement: Agreement,
    file_upload: UploadedFile,
    actor: User,
) -> Agreement:
    """Store or replace Agreement's one private signed artifact."""
```

Implementation sequence:

```python
old_name = agreement.signed_artifact.name
operation = "replaced" if old_name else "uploaded"
now = timezone.now()

with transaction.atomic():
    agreement.signed_artifact.save(safe_filename, file_upload, save=False)
    agreement.signed_artifact_original_filename = safe_filename
    agreement.signed_artifact_content_type = pdf_content_type_or_blank
    agreement.signed_artifact_file_size = file_upload.size
    agreement.signed_artifact_uploaded_at = agreement.signed_artifact_uploaded_at or now
    agreement.signed_artifact_updated_at = now
    agreement.save(update_fields=[...all changed artifact fields..., "updated_at"])
    record_audit_event(
        action=str(AuditEvent.Action.SIGNED_ARTIFACT_UPLOADED),
        actor=actor,
        target=agreement,
        metadata={"agreement_id": agreement.pk, "operation": operation},
    )
    if old_name:
        transaction.on_commit(lambda: agreement.signed_artifact.storage.delete(old_name))
```

Wrap only the new storage-write/database-persist sequence to best-effort delete a newly written storage key on failure, then re-raise. Do not delete `old_name` except inside the `on_commit` callback. Do not import integrations, call `mark_agreement_signed`, or touch billing records.

- [ ] **Step 3: Implement the pure streaming helper.**

`apps/agreements/signed_artifact_proxy.py` must:

```python
def build_signed_artifact_response(agreement, *, disposition):
    if disposition not in {"inline", "attachment"} or not agreement.signed_artifact:
        raise Http404
    is_pdf = agreement.signed_artifact_original_filename.lower().endswith(".pdf")
    as_attachment = disposition == "attachment" or not is_pdf
    agreement.signed_artifact.open("rb")
    return FileResponse(
        agreement.signed_artifact,
        as_attachment=as_attachment,
        filename=agreement.signed_artifact_original_filename,
        content_type="application/pdf" if is_pdf else "application/octet-stream",
    )
```

The helper accepts only an already-authorized Agreement. It must never call `FieldFile.url`, DocuSeal, OCR, billing, or a provider.

- [ ] **Step 4: Run focused green tests.**

Run:

```bash
uv run pytest -q \
  tests/agreements/test_signed_artifact_service.py \
  tests/agreements/test_signed_artifact_proxy.py
```

Expected: all service/proxy tests pass, including replacement-after-commit behavior.

---

### Task 4: Add registration and Agreement admin surfaces

**Files:**
- Modify: `apps/registrations/admin_panels.py`
- Modify: `apps/registrations/admin.py`
- Modify: `apps/agreements/admin.py`
- Create: `templates/registrations/admin/_signed_artifact_module.html`
- Modify: `templates/admin/registrations/registrationapplication/change_form.html`
- Modify: `templates/admin/agreements/agreement/change_form.html`
- Test: `tests/registrations/test_signed_artifact_admin.py`
- Test: `tests/agreements/test_signed_artifact_agreement_admin.py`

- [ ] **Step 1: Supply all source-member Agreements to registration admin.**

Extend `build_review_context()` without changing existing `agreement` or `document_links` behavior:

```python
signed_artifact_agreements = []
if member is not None:
    signed_artifact_agreements = list(
        Agreement.objects.filter(member=member).order_by(
            "-signed_artifact_updated_at", "-generated_at", "-pk"
        )
    )
```

Return it under `signed_artifact_agreements`. It deliberately includes no-file rows so staff can upload to generated, sent, signed, voided, superseded, or discontinued history. Existing DocuSeal `document_links` remains an external-id-only list and is not reused.

- [ ] **Step 2: Add registration admin upload and serve routes.**

Add routes before `super().get_urls()`:

```python
path(
    "<int:object_id>/agreement/<int:agreement_id>/signed-artifact/upload/",
    self.admin_site.admin_view(self.signed_artifact_upload_view),
    name="registrations_registrationapplication_signed_artifact_upload",
),
path(
    "<int:object_id>/agreement/<int:agreement_id>/signed-artifact/",
    self.admin_site.admin_view(self.signed_artifact_view),
    name="registrations_registrationapplication_signed_artifact",
),
```

Both views must first require `has_change_permission(request)`, load the source `RegistrationApplication`, then load `Agreement(pk=agreement_id, member_id=application.approved_member_id)`. A mismatched agreement is 404. Upload accepts POST only; non-POST redirects to change page. On `ValueError`, use `message_user(..., level=messages.ERROR)` and return change page. On success use fixed Latvian success message and redirect. Serve allows `inline|attachment` only, delegates to `build_signed_artifact_response`, and uses `attachment` default.

- [ ] **Step 3: Render sole upload module.**

Create `_signed_artifact_module.html` with an `{% for agreement in signed_artifact_agreements %}` loop. Per row show Agreement state and signing path, then:

```django
<form method="post" enctype="multipart/form-data"
      action="{% url 'admin:registrations_registrationapplication_signed_artifact_upload' original.pk agreement.pk %}">
  {% csrf_token %}
  <input type="file" name="signed_artifact" accept="application/pdf,.pdf,.edoc" required>
  <button type="submit">{% if agreement.signed_artifact %}Aizvietot{% else %}Augšupielādēt{% endif %}</button>
</form>
```

When a file exists, show neutral `Status nav pieejams` and same-origin download/preview links built from the signed-artifact route. Do not render a card or status for an Agreement without a file outside its upload row. Do not show raw storage names, URLs, or validation terms. Include this partial in registration change form before the current agreement lifecycle module.

- [ ] **Step 4: Add Agreement-admin serving panel.**

Add a `get_urls()` route analogous to current DocuSeal route:

```python
path(
    "<int:object_id>/signed-artifact/",
    self.admin_site.admin_view(self.signed_artifact_view),
    name="agreements_agreement_signed_artifact",
)
```

Require `has_view_permission`; missing Agreement/file and invalid disposition are 404. Default to `inline` for staff. Extend change context only with the same-origin route when `agreement.signed_artifact` exists. In change template, add distinct “Parakstītais dokuments” section after existing DocuSeal section: inline PDF iframe, attachment anchor, and `Status nav pieejams`. Do not change the existing generated-DocuSeal iframe or permission methods.

- [ ] **Step 5: Run staff-surface tests.**

Run:

```bash
uv run pytest -q \
  tests/registrations/test_signed_artifact_admin.py \
  tests/agreements/test_signed_artifact_agreement_admin.py \
  tests/agreements/test_agreement_admin_document.py
```

Expected: new staff contracts pass and existing DocuSeal document admin regression remains green.

---

### Task 5: Add family-hub and guardian-portal all-agreement serving

**Files:**
- Modify: `apps/members/family_hub.py`
- Modify: `apps/members/admin.py`
- Modify: `templates/admin/members/guardian/family_hub.html`
- Modify: `apps/registrations/views.py`
- Modify: `apps/registrations/urls.py`
- Modify: `templates/registrations/parent_portal.html`
- Test: `tests/members/test_family_hub_signed_artifacts.py`
- Test: `tests/registrations/test_parent_signed_artifacts.py`

- [ ] **Step 1: Build family-hub artifact links from prefetched all-agreement history.**

Keep existing `_build_member_document_links()` unchanged. Add a dedicated helper that receives the already-prefetched member and returns only `Agreement` rows with non-empty `signed_artifact`, ordered by:

```python
sorted(
    agreements,
    key=lambda agreement: (agreement.signed_artifact_updated_at, agreement.pk),
    reverse=True,
)
```

Each row includes `agreement`, state/signing-path labels, neutral status, and a URL built with `admin:members_guardian_signed_artifact`. Put the resulting `signed_artifact_links` in each `children` context row. It must include historical superseded, voided, and discontinued rows; the existing DocuSeal `document_links` is unchanged.

- [ ] **Step 2: Add family-hub staff proxy route.**

Add:

```python
path(
    "<int:guardian_id>/family-hub/agreement/<int:agreement_id>/signed-artifact/",
    self.admin_site.admin_view(self.family_hub_signed_artifact_view),
    name="members_guardian_signed_artifact",
)
```

Require `has_change_permission`, load Guardian, then use the existing guardian-to-agreement ownership helper or an equivalent `Agreement.objects.get(pk=agreement_id, member__guardian=guardian)`. Foreign/missing/no-file is 404. Default and force `attachment` for family hub; delegate response streaming to the pure helper. Add a separate “Parakstītie dokumenti” list in the family hub template. It must not replace or merge with current DocuSeal list.

- [ ] **Step 3: Build guardian portal groups and parent proxy.**

In `parent_portal`, query only the verified account’s records:

```python
artifact_agreements = (
    Agreement.objects.filter(member__guardian__parent_account=account)
    .exclude(signed_artifact="")
    .select_related("member")
    .order_by("member_id", "-signed_artifact_updated_at", "-pk")
)
```

Build plain template groups `{member_name, artifacts}` and a same-origin URL for each Agreement. Add route:

```python
path(
    "portal/agreements/<int:agreement_id>/signed-artifact/",
    views.open_parent_signed_artifact,
    name="parent-signed-artifact",
)
```

`open_parent_signed_artifact` must redirect an absent session to `start-registration`; otherwise retrieve only `Agreement(pk=agreement_id, member__guardian__parent_account=account)` with a nonempty file and return `build_signed_artifact_response(..., disposition="attachment")`. Foreign, missing, blank artifact, and inline-disposition attempts are 404.

In `parent_portal.html`, add an independent “Parakstītie līgumi” section after application cards and before invoices. Render no section if groups are empty. For each artifact show member name, agreement state, uploaded date, neutral `Status nav pieejams`, and “Lejupielādēt parakstīto līgumu”. Do not show filename, raw URL, provider, validation, or technical error. Preserve current agreement/lifecycle cards and invoice section.

- [ ] **Step 4: Run guardian and family-hub tests.**

Run:

```bash
uv run pytest -q \
  tests/members/test_family_hub_signed_artifacts.py \
  tests/registrations/test_parent_signed_artifacts.py \
  tests/registrations/test_parent_invoice_proxy.py \
  tests/registrations/test_portal_polish.py
```

Expected: all owned historical/current artifacts are listed newest first; no foreign artifact is visible or fetchable; existing invoice and portal presentation stays green.

---

### Task 6: Run integration, migration, style, and documentation gates

**Files:**
- Modify only if verification exposes an implementation defect: files from Tasks 2–5.
- Modify after all code acceptance: `AGENTS.md`, `docs/milestones.md` to record P16-A DEV completion and actual command results. Do not claim LAN sign-off before it happens.

- [ ] **Step 1: Execute P16-A focused regression suite.**

Run:

```bash
uv run pytest -q \
  tests/agreements/test_signed_artifact_service.py \
  tests/agreements/test_signed_artifact_proxy.py \
  tests/registrations/test_signed_artifact_admin.py \
  tests/agreements/test_signed_artifact_agreement_admin.py \
  tests/members/test_family_hub_signed_artifacts.py \
  tests/registrations/test_parent_signed_artifacts.py \
  tests/agreements/test_document_proxy.py \
  tests/agreements/test_agreement_admin_document.py \
  tests/registrations/test_parent_invoice_proxy.py
```

Expected: all selected tests pass.

- [ ] **Step 2: Run full repository verification.**

Run:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check
```

Expected: all commands exit `0`. Stop and fix failures; do not claim completion with skipped or failing checks.

- [ ] **Step 3: Update graph and documentation after acceptance.**

Run:

```bash
graphify update .
```

Then invoke `docs-writer` to update only `AGENTS.md` and `docs/milestones.md` with P16-A’s actual verification evidence and delivery status. Preserve P16-B as blocked until credentials exist. Do not add eParaksts configuration or implementation documentation in P16-A.

- [ ] **Step 4: Do not commit automatically.**

Repository policy requires explicit user instruction before any commit. Present verification output and scoped diff for review first.

---

## Spec coverage self-check

| Approved requirement | Implementing task |
|---|---|
| Direct private fields on Agreement; one artifact | Tasks 1–3 |
| PDF/.edoc, 20 MiB config, safe failures | Tasks 1–3 |
| Save new then commit then delete old | Tasks 1 and 3 |
| No state/billing/provider/background change | Tasks 1 and 3 |
| Redacted audit event | Tasks 1–3 |
| Registration sole upload, every Agreement state | Tasks 1 and 4 |
| Four authorized serve surfaces | Tasks 1, 4, and 5 |
| Staff PDF preview; guardian/.edoc attachment | Tasks 1, 3, 4, and 5 |
| All current and historical artifacts, newest first | Tasks 1, 4, and 5 |
| No raw storage/provider links; ownership 404 | Tasks 1, 3, 4, and 5 |
| P16-B stays absent/blocked | Tasks 2, 3, and 6 |

No implementation action is authorized until this plan is approved.
