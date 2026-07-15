# DocuSeal Agreement PDF Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a staff-only Family hub link that opens the DocuSeal agreement PDF for unsigned or signed agreements.

**Architecture:** Reuse the existing agreement-platform boundary. Add a read-only documents API call, then expose it through a Guardian admin proxy endpoint that checks staff access and family ownership before redirecting to DocuSeal's document URL. Render the link only when the agreement has a DocuSeal submission id.

**Tech Stack:** Django 5 admin, Python 3.12+, pytest/pytest-django, existing `requests` DocuSeal provider, existing Family hub templates.

---

## Design decisions

1. **Use a Django admin proxy endpoint.**
   - Why: agreement PDFs contain personal data. The app must verify staff access and agreement ownership before exposing any DocuSeal URL.
   - Flow: staff clicks Family hub link → Django admin view checks permission + `Agreement.member.guardian` → provider fetches documents → view redirects to the selected document URL.

2. **Redirect instead of streaming.**
   - Why: DocuSeal already returns a document URL; redirect is the smallest safe path and avoids file buffering/timeout code. Staff still passed through the app authorization gate first.

3. **No persistence.**
   - Why: the document may change from partially filled to final signed. Fetching live from DocuSeal avoids stale cached URLs and needs no migration.

4. **Choose PDF first.**
   - Why: the desired artifact is agreement PDF. If DocuSeal returns documents without `application/pdf`, fall back to the first returned document rather than failing a valid submission.

## File-by-file plan

- Modify `apps/integrations/agreement_platform.py`
  - Add `DocumentResult` dataclass.
  - Add `_stub_documents(external_id: str) -> list[DocumentResult]`.
  - Add `list_submission_documents(external_id: str) -> list[DocumentResult]` dispatching to stub/docuseal.

- Modify `apps/integrations/docuseal.py`
  - Import `DocumentResult`.
  - Add `list_submission_documents(external_id: str) -> list[DocumentResult]`.
  - Call `GET {api_url}/submissions/{external_id}/documents`.
  - Parse `payload["documents"]` into `DocumentResult` rows, skipping rows without `url`.

- Modify `apps/members/admin.py`
  - Import `agreement_platform` and `HttpResponseRedirect` if needed.
  - Add admin URL `"<int:guardian_id>/family-hub/agreement/<int:agreement_id>/docuseal-document/"` named `members_guardian_docuseal_document`.
  - Add view `family_hub_docuseal_document_view(request, guardian_id, agreement_id)`:
    - require `has_change_permission`.
    - load Guardian.
    - load Agreement through `_get_guardian_agreement` to enforce ownership.
    - require `agreement.external_id`; if missing, message error and redirect back.
    - call `agreement_platform.list_submission_documents(agreement.external_id)`.
    - choose first PDF by `content_type == "application/pdf"`, else first doc.
    - if no docs, message error and redirect back.
    - redirect to selected `doc.url`.
    - catch `AgreementPlatformError`, message Latvian error, redirect back.

- Modify `templates/admin/members/guardian/family_hub.html`
  - In the Līgumi lane, render a link when `child.agreement.external_id` exists:
    - text: `Lejupielādēt līguma PDF no DocuSeal`
    - href: new admin URL with `guardian.pk` and `child.agreement.pk`
    - target can be omitted; endpoint redirects.

- Modify `tests/integrations/test_docuseal_provider.py`
  - Add provider test for documents endpoint parsing.

- Modify `tests/admin_hub/test_family_hub_page.py`
  - Add link-visible test when agreement has `external_id`.
  - Add link-hidden test when agreement has no `external_id`.

- Modify `tests/admin_hub/test_family_hub_actions.py`
  - Add endpoint redirect test with patched `agreement_platform.list_submission_documents`.
  - Add cross-family 404 test.
  - Add no-documents redirect-with-message test.

## Test strategy

- Use existing pytest + pytest-django tests.
- Patch provider boundary in admin tests; do not hit real DocuSeal.
- Provider test monkeypatches `apps.integrations.docuseal.requests.request`, matching existing style.
- Do not test browser download behavior; endpoint redirect is enough.
- Do not test streaming because streaming is out of scope.

## Acceptance criteria per unit

- Provider boundary:
  - `agreement_platform.list_submission_documents("abc")` returns a stub PDF in stub mode.
  - `docuseal.list_submission_documents("1001")` calls `/submissions/1001/documents` with `X-Auth-Token` and parses returned documents.

- Admin endpoint:
  - staff request for own Guardian agreement redirects to selected DocuSeal document URL.
  - cross-family request returns 404.
  - missing `external_id` redirects back with an error message.
  - empty documents list redirects back with an error message.

- Family hub template:
  - link appears only when `child.agreement.external_id` is truthy.
  - link URL points at the new admin proxy endpoint.

## Documentation scope

- Update `docs/admin-hub.md` with one sentence under the agreement lane: staff can download/open the current DocuSeal agreement PDF through the hub.
- Update P11 line in `docs/milestones.md` after full verification count is known.

---

## Task 1: Provider boundary and DocuSeal documents call

**Files:**
- Modify: `apps/integrations/agreement_platform.py`
- Modify: `apps/integrations/docuseal.py`
- Test: `tests/integrations/test_docuseal_provider.py`

- [ ] **Step 1: Add failing provider test**

Add to `tests/integrations/test_docuseal_provider.py`:

```python
def test_list_submission_documents_parses_pdf_documents(docuseal_settings, monkeypatch):
    captured = {}

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        return _mock_response(
            200,
            {
                "documents": [
                    {
                        "id": "doc_1",
                        "filename": "agreement.pdf",
                        "url": "https://sign.example/files/agreement.pdf",
                        "content_type": "application/pdf",
                    }
                ]
            },
        )

    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request",
        fake_request,
    )

    docs = docuseal.list_submission_documents("1001")

    assert captured["method"] == "GET"
    assert captured["url"] == "https://sign.example/api/submissions/1001/documents"
    assert captured["headers"]["X-Auth-Token"] == "secret-key"
    assert len(docs) == 1
    assert docs[0].filename == "agreement.pdf"
    assert docs[0].url == "https://sign.example/files/agreement.pdf"
    assert docs[0].content_type == "application/pdf"
```

- [ ] **Step 2: Run red test**

Run:

```bash
uv run pytest tests/integrations/test_docuseal_provider.py::test_list_submission_documents_parses_pdf_documents -q
```

Expected: fail because `docuseal.list_submission_documents` does not exist.

- [ ] **Step 3: Implement boundary**

In `apps/integrations/agreement_platform.py`, add after `SubmissionResult`:

```python
@dataclass(frozen=True)
class DocumentResult:
    filename: str
    url: str
    content_type: str
```

Add stub helper near `_stub_sync`:

```python
def _stub_documents(external_id: str) -> list[DocumentResult]:
    return [
        DocumentResult(
            filename=f"agreement-{external_id}.pdf",
            url=f"https://stub.invalid/{external_id}/agreement.pdf",
            content_type="application/pdf",
        )
    ]
```

Add public dispatcher near `archive_submission`:

```python
def list_submission_documents(external_id: str) -> list[DocumentResult]:
    mode = _mode()
    if mode == "stub":
        return _stub_documents(external_id)
    if mode == "docuseal":
        from apps.integrations import docuseal

        return docuseal.list_submission_documents(external_id)
    raise AgreementPlatformConfigError(f"unknown agreement provider mode: {mode}")
```

- [ ] **Step 4: Implement DocuSeal call**

In `apps/integrations/docuseal.py`, import `DocumentResult` from `apps.integrations.agreement_platform`.

Add after `sync_submission`:

```python
def list_submission_documents(external_id: str) -> list[DocumentResult]:
    api_url, api_key, _ = _require_config()
    resp = _request("GET", f"{api_url}/submissions/{external_id}/documents", api_key)
    payload = resp.json()
    documents = payload.get("documents") if isinstance(payload, dict) else []
    results: list[DocumentResult] = []
    for item in documents or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", ""))
        if not url:
            continue
        results.append(
            DocumentResult(
                filename=str(item.get("filename", "")),
                url=url,
                content_type=str(item.get("content_type", "")),
            )
        )
    return results
```

- [ ] **Step 5: Run provider tests**

Run:

```bash
uv run pytest tests/integrations/test_docuseal_provider.py -q
```

Expected: pass.

## Task 2: Admin proxy endpoint

**Files:**
- Modify: `apps/members/admin.py`
- Test: `tests/admin_hub/test_family_hub_actions.py`

- [ ] **Step 1: Add failing admin endpoint tests**

Add to `tests/admin_hub/test_family_hub_actions.py`:

```python
def _docuseal_document_url(guardian, agreement):
    return reverse(
        "admin:members_guardian_docuseal_document",
        args=[guardian.pk, agreement.pk],
    )


def test_docuseal_document_endpoint_redirects_to_pdf(
    staff_client, approved_application, monkeypatch,
):
    from apps.agreements.models import Agreement
    from apps.integrations.agreement_platform import DocumentResult

    agreement = Agreement.objects.get(
        member=approved_application.approved_member,
        is_current=True,
    )
    agreement.external_id = "1001"
    agreement.save(update_fields=["external_id", "updated_at"])

    monkeypatch.setattr(
        "apps.members.admin.agreement_platform.list_submission_documents",
        lambda external_id: [
            DocumentResult(
                filename="agreement.pdf",
                url="https://sign.example/files/agreement.pdf",
                content_type="application/pdf",
            )
        ],
    )

    response = staff_client.get(_docuseal_document_url(approved_application.guardian, agreement))

    assert response.status_code == 302
    assert response["Location"] == "https://sign.example/files/agreement.pdf"


def test_docuseal_document_endpoint_rejects_cross_family(
    staff_client, approved_application, other_parent_account,
):
    from apps.agreements.models import Agreement
    from apps.members.services import resolve_guardian_for_account

    agreement = Agreement.objects.get(
        member=approved_application.approved_member,
        is_current=True,
    )
    other_guardian = resolve_guardian_for_account(other_parent_account)

    response = staff_client.get(_docuseal_document_url(other_guardian, agreement))

    assert response.status_code == 404


def test_docuseal_document_endpoint_redirects_back_when_no_documents(
    staff_client, approved_application, monkeypatch,
):
    from apps.agreements.models import Agreement

    agreement = Agreement.objects.get(
        member=approved_application.approved_member,
        is_current=True,
    )
    agreement.external_id = "1001"
    agreement.save(update_fields=["external_id", "updated_at"])
    monkeypatch.setattr(
        "apps.members.admin.agreement_platform.list_submission_documents",
        lambda external_id: [],
    )

    response = staff_client.get(_docuseal_document_url(approved_application.guardian, agreement), follow=True)

    assert response.status_code == 200
    assert "DocuSeal dokuments nav atrasts" in response.content.decode()
```

- [ ] **Step 2: Run red tests**

Run:

```bash
uv run pytest tests/admin_hub/test_family_hub_actions.py::test_docuseal_document_endpoint_redirects_to_pdf tests/admin_hub/test_family_hub_actions.py::test_docuseal_document_endpoint_rejects_cross_family tests/admin_hub/test_family_hub_actions.py::test_docuseal_document_endpoint_redirects_back_when_no_documents -q
```

Expected: fail because route/import does not exist.

- [ ] **Step 3: Implement route and view**

In `apps/members/admin.py`, add imports:

```python
from django.http import Http404, HttpResponseRedirect
from apps.integrations import agreement_platform
```

Keep existing `Http404` import; only add `HttpResponseRedirect` and `agreement_platform`.

Add URL in `get_urls()` before action route:

```python
path(
    "<int:guardian_id>/family-hub/agreement/<int:agreement_id>/docuseal-document/",
    self.admin_site.admin_view(self.family_hub_docuseal_document_view),
    name="members_guardian_docuseal_document",
),
```

Add view after `family_hub_view`:

```python
    def family_hub_docuseal_document_view(self, request, guardian_id, agreement_id):
        if not self.has_change_permission(request):
            raise PermissionDenied
        guardian = get_object_or_404(
            Guardian.objects.select_related("parent_account"), pk=guardian_id
        )
        agreement = self._get_guardian_agreement(guardian, agreement_id)
        if not agreement.external_id:
            self.message_user(
                request,
                "DocuSeal sūtījums vēl nav izveidots.",
                level=messages.ERROR,
            )
            return self._family_hub_redirect(guardian.pk)
        try:
            documents = agreement_platform.list_submission_documents(agreement.external_id)
        except agreement_platform.AgreementPlatformError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return self._family_hub_redirect(guardian.pk)
        selected = next(
            (doc for doc in documents if doc.content_type == "application/pdf"),
            documents[0] if documents else None,
        )
        if selected is None:
            self.message_user(
                request,
                "DocuSeal dokuments nav atrasts.",
                level=messages.ERROR,
            )
            return self._family_hub_redirect(guardian.pk)
        return HttpResponseRedirect(selected.url)
```

- [ ] **Step 4: Run admin endpoint tests**

Run:

```bash
uv run pytest tests/admin_hub/test_family_hub_actions.py::test_docuseal_document_endpoint_redirects_to_pdf tests/admin_hub/test_family_hub_actions.py::test_docuseal_document_endpoint_rejects_cross_family tests/admin_hub/test_family_hub_actions.py::test_docuseal_document_endpoint_redirects_back_when_no_documents -q
```

Expected: pass.

## Task 3: Family hub link and docs

**Files:**
- Modify: `templates/admin/members/guardian/family_hub.html`
- Modify: `docs/admin-hub.md`
- Test: `tests/admin_hub/test_family_hub_page.py`

- [ ] **Step 1: Add failing hub link tests**

Add to `tests/admin_hub/test_family_hub_page.py`:

```python
def test_hub_shows_docuseal_pdf_link_when_external_id_exists(
    staff_client, approved_application,
):
    from apps.agreements.models import Agreement

    agreement = Agreement.objects.get(
        member=approved_application.approved_member,
        is_current=True,
    )
    agreement.external_id = "1001"
    agreement.save(update_fields=["external_id", "updated_at"])

    response = staff_client.get(_hub_url(approved_application.guardian))
    html = response.content.decode()

    assert "Lejupielādēt līguma PDF no DocuSeal" in html
    assert reverse(
        "admin:members_guardian_docuseal_document",
        args=[approved_application.guardian.pk, agreement.pk],
    ) in html


def test_hub_hides_docuseal_pdf_link_without_external_id(
    staff_client, approved_application,
):
    from apps.agreements.models import Agreement

    agreement = Agreement.objects.get(
        member=approved_application.approved_member,
        is_current=True,
    )
    agreement.external_id = ""
    agreement.save(update_fields=["external_id", "updated_at"])

    response = staff_client.get(_hub_url(approved_application.guardian))
    html = response.content.decode()

    assert "Lejupielādēt līguma PDF no DocuSeal" not in html
```

- [ ] **Step 2: Run red hub link tests**

Run:

```bash
uv run pytest tests/admin_hub/test_family_hub_page.py::test_hub_shows_docuseal_pdf_link_when_external_id_exists tests/admin_hub/test_family_hub_page.py::test_hub_hides_docuseal_pdf_link_without_external_id -q
```

Expected: first test fails because link is absent.

- [ ] **Step 3: Add template link**

In `templates/admin/members/guardian/family_hub.html`, after the DocuSeal sync/retry block and before signed amendment actions, add:

```django
    {% if child.agreement.external_id %}
      <p>
        <a href="{% url 'admin:members_guardian_docuseal_document' guardian.pk child.agreement.pk %}">
          Lejupielādēt līguma PDF no DocuSeal
        </a>
      </p>
    {% endif %}
```

- [ ] **Step 4: Update admin docs**

In `docs/admin-hub.md`, under the DocuSeal failure paragraph, add:

```markdown
When DocuSeal has created a submission, the Līgumi lane also shows **Lejupielādēt
līguma PDF no DocuSeal**. Before signing, this opens the partially filled agreement
PDF from DocuSeal; after completion, DocuSeal returns the final signed PDF.
```

- [ ] **Step 5: Run hub tests**

Run:

```bash
uv run pytest tests/admin_hub/test_family_hub_page.py -q
```

Expected: pass.

## Task 4: Final verification

**Files:**
- Verify only; no implementation edits unless failures point to the files above.

- [ ] **Step 1: Run targeted tests**

Run:

```bash
uv run pytest tests/integrations/test_docuseal_provider.py tests/admin_hub -q
```

Expected: pass.

- [ ] **Step 2: Run full gate**

Run:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check
```

Expected:
- all tests pass
- ruff clean
- mypy clean
- no migrations detected

- [ ] **Step 3: Update milestone count**

If full pytest count changed, update `docs/milestones.md` P11 verification count to the new number.

- [ ] **Step 4: Produce filtered diff URL**

Run:

```bash
bunx critique --web "DocuSeal agreement PDF download" \
  --filter "apps/integrations/agreement_platform.py" \
  --filter "apps/integrations/docuseal.py" \
  --filter "apps/members/admin.py" \
  --filter "templates/admin/members/guardian/family_hub.html" \
  --filter "tests/integrations/test_docuseal_provider.py" \
  --filter "tests/admin_hub/test_family_hub_page.py" \
  --filter "tests/admin_hub/test_family_hub_actions.py" \
  --filter "docs/admin-hub.md" \
  --filter "docs/milestones.md" \
  --filter "docs/superpowers/specs/2026-07-09-docuseal-agreement-pdf-download-design.md" \
  --filter "docs/superpowers/plans/2026-07-09-docuseal-agreement-pdf-download.md"
```

Expected: critique URL printed.

## Self-review

- Spec coverage: provider call, admin proxy, Family hub link, access control, no persistence, docs, and no migrations are covered.
- Placeholder scan: no TBD/TODO/fill-in placeholders.
- Type consistency: `DocumentResult`, `list_submission_documents`, URL name `members_guardian_docuseal_document`, and template link are consistent across tasks.
