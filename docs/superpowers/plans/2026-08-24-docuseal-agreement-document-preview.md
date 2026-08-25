# DocuSeal agreement document preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let staff create, preview, and download generated DocuSeal agreement PDFs for electronic and paper signing paths across Family hub, Registration admin, and Agreement admin.

**Architecture:** The integrations boundary returns a one-use `DocumentStream`; one agreement-layer helper converts it to a `StreamingHttpResponse` with either inline or attachment disposition. Each admin surface only resolves and authorizes its Agreement before calling that helper. Paper and electronic sent transitions both enqueue creation, carrying an explicit DocuSeal `send_email` value.

**Tech Stack:** Python 3.12+, Django 5.x, existing `requests` transport, `StreamingHttpResponse`, pytest/pytest-django, unittest.mock.

---

## Task 1 — Add streamed-document provider boundary

**Files:**
- Modify: `apps/integrations/agreement_platform.py`
- Modify: `apps/integrations/docuseal.py`
- Test: `tests/integrations/test_docuseal_provider.py`
- Test: `tests/integrations/test_agreement_platform_adapter.py`

- [ ] **Step 1: Write failing test**

Add this provider test beside the existing `list_submission_documents` tests:

```python
def test_stream_submission_document_prefers_pdf(docuseal_settings, monkeypatch):
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/documents"):
            return _mock_response(
                200,
                {
                    "documents": [
                        {
                            "filename": "scan.png",
                            "url": "https://sign.example/files/scan.png",
                            "content_type": "image/png",
                        },
                        {
                            "filename": "agreement.pdf",
                            "url": "https://sign.example/files/agreement.pdf",
                            "content_type": "application/pdf",
                        },
                    ]
                },
            )
        response = _mock_response(200)
        response.iter_content.return_value = [b"%PDF-", b"test"]
        return response

    monkeypatch.setattr("apps.integrations.docuseal.requests.request", fake_request)

    stream = docuseal.stream_submission_document("1001")

    assert stream.filename == "agreement.pdf"
    assert b"".join(stream.chunks) == b"%PDF-test"
    assert calls[1] == (
        "GET",
        "https://sign.example/files/agreement.pdf",
        {"stream": True},
    )
```

Also add tests that: select first document when none is a PDF; raise `AgreementPlatformNotFoundError` for an empty list; close the upstream response after consuming chunks; and dispatch a deterministic `%PDF-` stream in stub mode.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integrations/test_docuseal_provider.py::test_stream_submission_document_prefers_pdf -q`

Expected: FAIL because `docuseal.stream_submission_document` does not exist.

- [ ] **Step 3: Write minimal implementation**

In `apps/integrations/agreement_platform.py`, add:

```python
@dataclass(frozen=True)
class DocumentStream:
    filename: str
    content_type: str
    chunks: Iterator[bytes]


def stream_submission_document(external_id: str) -> DocumentStream:
    mode = _mode()
    if mode == "stub":
        return _stub_stream_submission_document(external_id)
    if mode == "docuseal":
        from apps.integrations import docuseal

        return docuseal.stream_submission_document(external_id)
    raise AgreementPlatformConfigError(
        f"unknown agreement provider mode: {mode}"
    )
```

`_stub_stream_submission_document` returns filename `agreement-<external_id>.pdf`, content type `application/pdf`, and an iterator yielding deterministic bytes beginning `%PDF-`.

In `apps/integrations/docuseal.py`, add:

```python
def stream_submission_document(external_id: str) -> DocumentStream:
    api_url, api_key, _ = _require_config()
    documents = list_submission_documents(external_id)
    selected = next(
        (item for item in documents if item.content_type == "application/pdf"),
        documents[0] if documents else None,
    )
    if selected is None:
        raise AgreementPlatformNotFoundError("submission document not found")
    response = _request("GET", selected.url, api_key, stream=True)

    def chunks() -> Iterator[bytes]:
        try:
            yield from response.iter_content(chunk_size=64 * 1024)
        finally:
            response.close()

    return DocumentStream(
        filename=selected.filename,
        content_type=selected.content_type,
        chunks=chunks(),
    )
```

Use existing `_request` so timeout, auth, not-found, and HTTP errors retain their existing `AgreementPlatform*` mapping. `disposition` is deliberately not an integration argument.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integrations/test_docuseal_provider.py tests/integrations/test_agreement_platform_adapter.py -q`

Expected: PASS.

- [ ] **Step 5: Checkpoint**

Confirm PDF-first selection, first-document fallback, response cleanup, stub behavior, and provider dispatch coverage.

## Task 2 — Create submissions for both signing paths

**Files:**
- Modify: `apps/integrations/agreement_platform.py`
- Modify: `apps/integrations/docuseal.py`
- Modify: `apps/integrations/tasks.py`
- Modify: `apps/agreements/services.py`
- Test: `tests/integrations/test_docuseal_provider.py`
- Test: `tests/integrations/test_agreement_tasks.py`
- Test: `tests/agreements/test_agreement_services.py`

- [ ] **Step 1: Write failing test**

Add service tests using the existing agreement fixtures:

```python
def test_mark_sent_enqueues_paper_submission_without_docuseal_email(
    agreement_member, actor, monkeypatch,
):
    from apps.agreements.services import (
        create_agreement_for_member,
        mark_agreement_sent,
    )

    agreement = create_agreement_for_member(agreement_member, signing_path="paper")
    calls: list[tuple[int, bool]] = []
    monkeypatch.setattr(
        "apps.integrations.tasks.enqueue_create_agreement_submission",
        lambda agreement_id, send_email=True: calls.append((agreement_id, send_email)),
    )

    mark_agreement_sent(agreement, actor)

    assert calls == [(agreement.pk, False)]


def test_void_archives_paper_submission(agreement_member, actor, monkeypatch):
    from apps.agreements.services import create_agreement_for_member, void_agreement

    agreement = create_agreement_for_member(agreement_member, signing_path="paper")
    agreement.external_id = "sub-456"
    agreement.save(update_fields=["external_id"])
    archived: list[str] = []
    monkeypatch.setattr(
        "apps.integrations.tasks.enqueue_archive_agreement_submission",
        archived.append,
    )

    void_agreement(agreement, actor, "Test")

    assert archived == ["sub-456"]
```

Add real-provider request-body tests for `send_email=True` and `send_email=False`; add task tests that the queued task passes the supplied boolean to `agreement_platform.create_submission`; add an electronic service-path test expecting `True`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agreements/test_agreement_services.py -q -k "paper_submission or mark_sent_enqueues"`

Expected: FAIL because paper agreements currently do not enqueue submission creation.

- [ ] **Step 3: Write minimal implementation**

Use these compatible signatures:

```python
def create_submission(agreement, send_email: bool = True) -> SubmissionResult: ...

def enqueue_create_agreement_submission(
    agreement_id: int,
    send_email: bool = True,
) -> None: ...

def create_agreement_submission(
    agreement_id: int,
    send_email: bool = True,
) -> None: ...
```

`docuseal.create_submission` adds `"send_email": send_email` to its JSON body. Boundary and task pass the value through unchanged. In `mark_agreement_sent`, enqueue for both signing paths:

```python
send_email = agreement.signing_path == Agreement.SigningPath.ELECTRONIC
enqueue_create_agreement_submission(agreement.id, send_email=send_email)
```

In `void_agreement`, replace the electronic-only archive guard with:

```python
if agreement.external_id:
    enqueue_archive_agreement_submission(agreement.external_id)
```

Do not clear `external_id`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integrations/test_docuseal_provider.py tests/integrations/test_agreement_tasks.py tests/agreements/test_agreement_services.py -q`

Expected: PASS.

- [ ] **Step 5: Checkpoint**

Confirm electronic creation sends DocuSeal email, paper creation suppresses only DocuSeal email, club paper email behavior remains unchanged, and void archives either path.

## Task 3 — Add shared HTTP response and link presentation helpers

**Files:**
- Create: `apps/agreements/document_proxy.py`
- Create: `apps/agreements/presentation.py`
- Test: `tests/agreements/test_document_proxy.py`
- Test: `tests/agreements/test_agreement_admin_document.py`

- [ ] **Step 1: Write failing test**

Add a proxy test:

```python
def test_build_response_sets_inline_disposition(agreement_member, monkeypatch):
    from apps.agreements.services import create_agreement_for_member
    from apps.integrations.agreement_platform import DocumentStream

    agreement = create_agreement_for_member(agreement_member, signing_path="paper")
    agreement.external_id = "sub-1"
    agreement.save(update_fields=["external_id"])
    stream = DocumentStream("test.pdf", "application/pdf", iter([b"%PDF-test"]))
    monkeypatch.setattr(
        "apps.agreements.document_proxy.stream_submission_document",
        lambda external_id: stream,
    )

    response = build_agreement_document_response(agreement, disposition="inline")

    assert response["Content-Disposition"].startswith("inline")
```

In `test_agreement_admin_document.py`, add a presentation test which creates an agreement with `create_agreement_for_member`, sets `external_id`, calls `build_agreement_document_links([agreement], url_builder=...)`, and asserts ordinary dictionary keys and `agreement.get_state_display()` values. Do not use `isinstance` with `TypedDict`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agreements/test_document_proxy.py -q`

Expected: FAIL because `apps.agreements.document_proxy` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `apps/agreements/document_proxy.py`:

```python
def build_agreement_document_response(
    agreement: Agreement,
    *,
    disposition: Literal["inline", "attachment"],
) -> StreamingHttpResponse:
    if disposition not in {"inline", "attachment"}:
        raise Http404
    stream = stream_submission_document(agreement.external_id)
    filename = stream.filename or "līgums.pdf"
    response = StreamingHttpResponse(
        stream.chunks,
        content_type=stream.content_type or "application/pdf",
    )
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return response
```

Create `apps/agreements/presentation.py`:

```python
class AgreementDocumentLink(TypedDict):
    agreement: Agreement
    state_label: str
    signing_path_label: str
    download_url: str


def build_agreement_document_links(
    agreements: Iterable[Agreement],
    *,
    url_builder: Callable[[Agreement], str],
) -> list[AgreementDocumentLink]:
    return [
        {
            "agreement": agreement,
            "state_label": agreement.get_state_display(),
            "signing_path_label": agreement.get_signing_path_display(),
            "download_url": url_builder(agreement),
        }
        for agreement in agreements
    ]
```

Callers filter data; this helper does not.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agreements/test_document_proxy.py tests/agreements/test_agreement_admin_document.py -q`

Expected: PASS.

- [ ] **Step 5: Checkpoint**

Confirm invalid disposition raises `Http404`, response uses `StreamingHttpResponse`, and only same-origin application routes become presentation URLs.

## Task 4 — Refactor Family hub controls and historical list

**Files:**
- Modify: `apps/members/admin.py`
- Modify: `apps/members/family_hub.py`
- Modify: `templates/admin/members/guardian/family_hub.html`
- Create: `templates/admin/_agreement_list.html`
- Test: `tests/admin_hub/test_family_hub_actions.py`
- Test: `tests/admin_hub/test_family_hub_page.py`

- [ ] **Step 1: Write failing test**

Use `approved_application` to avoid hand-building a parent/member:

```python
def test_family_hub_lists_historical_document(approved_application, staff_client):
    from datetime import timedelta
    from apps.agreements.models import Agreement
    from apps.agreements.services import get_current_agreement

    member = approved_application.approved_member
    current = get_current_agreement(member)
    current.external_id = "sub-current"
    current.save(update_fields=["external_id"])
    Agreement.objects.create(
        member=member,
        is_current=False,
        state=Agreement.State.SUPERSEDED,
        external_id="sub-history",
        generated_at=current.generated_at - timedelta(days=1),
    )

    response = staff_client.get(
        reverse("admin:members_guardian_family_hub", args=[member.guardian_id])
    )

    assert "Aizvietots" in response.content.decode()
    assert "Lejupielādēt ģenerēto līgumu" in response.content.decode()
```

Add action tests that the existing `family_hub_docuseal_document_view` calls `build_agreement_document_response`; rejects cross-guardian agreement IDs with 404; preserves `attachment` and `inline`; and rejects `?disposition=invalid` with 404.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/admin_hub/test_family_hub_page.py::test_family_hub_lists_historical_document -q`

Expected: FAIL because the hub exposes only its current agreement.

- [ ] **Step 3: Write minimal implementation**

Keep current Family hub endpoint path and ownership lookup. It must parse `request.GET["disposition"]`, default to `attachment`, reject any other value with `Http404`, then return `build_agreement_document_response(agreement, disposition=disposition)`.

In Family hub context, prefetch each guardian member’s non-empty-id agreements once:

```python
Prefetch(
    "members__agreements",
    queryset=Agreement.objects.exclude(external_id="").order_by("-generated_at", "-pk"),
    to_attr="document_agreements",
)
```

For every child, build `child.all_agreements` by passing `member.document_agreements` to `build_agreement_document_links`. Its URL builder reverses `admin:members_guardian_docuseal_document` with guardian and agreement IDs, then appends `?disposition=attachment`.

Create `templates/admin/_agreement_list.html`. It receives `agreements`; each row renders `state_label`, `signing_path_label`, and a GET `<a href="{{ item.download_url }}">Lejupielādēt ģenerēto līgumu</a>`.

Replace old PDF anchor markup in Family hub with the partial. Do not render a DocuSeal file URL.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/admin_hub/test_family_hub_page.py tests/admin_hub/test_family_hub_actions.py -q`

Expected: PASS.

- [ ] **Step 5: Checkpoint**

Confirm current and superseded agreement controls work, the original endpoint is reused, and no per-child agreement query is introduced.

## Task 5 — Add Registration admin agreement-document route and list

**Files:**
- Modify: `apps/registrations/admin.py`
- Modify: `apps/registrations/admin_panels.py`
- Modify: `templates/registrations/admin/_agreement_module.html`
- Test: `tests/registrations/test_agreement_module_docuseal.py`

- [ ] **Step 1: Write failing test**

Build an unrelated agreement using real helpers:

```python
def test_registration_document_route_rejects_other_members_agreement(
    approved_application, other_parent_account, make_guardian, staff_client,
):
    from apps.agreements.services import create_agreement_for_member
    from apps.members.models import Member

    other_guardian = make_guardian(other_parent_account, full_name="Otrais Vecāks")
    other_member = Member.objects.create(
        full_name="Cits Bērns", guardian=other_guardian
    )
    other_agreement = create_agreement_for_member(other_member, signing_path="paper")
    other_agreement.external_id = "sub-other"
    other_agreement.save(update_fields=["external_id"])

    url = reverse(
        "admin:registrations_registrationapplication_docuseal_document",
        args=[approved_application.pk, other_agreement.pk],
    )
    response = staff_client.get(f"{url}?disposition=attachment")

    assert response.status_code == 404
```

Add a rendering test which applies `external_id` to current agreement, adds `is_current=False` historical agreements with explicit `generated_at`, and asserts their exact model labels (`Sagatavots`, `Nosūtīts parakstīšanai`, `Parakstīts`, `Atcelts`, `Aizvietots`, `Pārtraukts`) and same-origin download links.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_agreement_module_docuseal.py::test_registration_document_route_rejects_other_members_agreement -q`

Expected: FAIL because this URL route does not exist.

- [ ] **Step 3: Write minimal implementation**

Add route:

```python
path(
    "<int:object_id>/agreement/<int:agreement_id>/docuseal-document/",
    self.admin_site.admin_view(self.docuseal_document_view),
    name="registrations_registrationapplication_docuseal_document",
)
```

Implement `docuseal_document_view(self, request, object_id: int, agreement_id: int)`. Require `has_change_permission`; load Application; return 404 if no approved member or if this lookup fails:

```python
agreement = get_object_or_404(
    Agreement,
    pk=agreement_id,
    member_id=application.approved_member_id,
)
```

Require `external_id`; invalid disposition raises `Http404`; valid request delegates to `build_agreement_document_response`.

In `build_review_context`, query every agreement for the approved member with `.exclude(external_id="").order_by("-generated_at", "-pk")`; use `build_agreement_document_links` with the new route’s URL builder. Replace `Atvērt DocuSeal ↗` with the shared partial. Do not render external document URLs.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_agreement_module_docuseal.py -q`

Expected: PASS.

- [ ] **Step 5: Checkpoint**

Confirm a registration cannot retrieve an unrelated agreement, and current plus historical controls list every non-empty external ID.

## Task 6 — Add view-only Agreement admin preview and download

**Files:**
- Modify: `apps/agreements/admin.py`
- Create: `templates/admin/agreements/agreement/change_form.html`
- Create: `static/admin/css/agreement_document.css`
- Test: `tests/agreements/test_agreement_admin_document.py`

- [ ] **Step 1: Write failing test**

```python
def test_agreement_admin_change_page_embeds_document(
    agreement_member, actor, client,
):
    from apps.agreements.services import create_agreement_for_member

    agreement = create_agreement_for_member(agreement_member, signing_path="paper")
    agreement.external_id = "sub-1"
    agreement.save(update_fields=["external_id"])
    client.force_login(actor)

    response = client.get(
        reverse("admin:agreements_agreement_change", args=[agreement.pk])
    )

    assert response.status_code == 200
    assert "disposition=inline" in response.content.decode()
    assert "Lejupielādēt ģenerēto līgumu" in response.content.decode()
```

Add permission tests using `RequestFactory` with `actor`: `has_view_permission` true for active staff, false for anonymous/non-staff; `has_change_permission` remains false. Parametrize the change-page test over all six Agreement states, each in a separate test transaction with one agreement and external ID.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agreements/test_agreement_admin_document.py::test_agreement_admin_change_page_embeds_document -q`

Expected: FAIL because Agreement admin has no staff view permission or custom preview template.

- [ ] **Step 3: Write minimal implementation**

Keep `has_change_permission` false. Add:

```python
def has_view_permission(self, request, obj=None) -> bool:
    return bool(request.user.is_authenticated and request.user.is_staff)
```

Add AgreementAdmin route `<int:object_id>/docuseal-document/`; it checks `has_view_permission`, resolves Agreement, validates disposition, then calls `build_agreement_document_response`.

Set `change_form_template = "admin/agreements/agreement/change_form.html"`. Template extends `admin/change_form.html`; only if object has `external_id`, render iframe source with `?disposition=inline` and `<a class="button">Lejupielādēt ģenerēto līgumu</a>` with `?disposition=attachment`. Add class-scoped iframe styling in `static/admin/css/agreement_document.css`; no inline style attributes.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agreements/test_agreement_admin_document.py -q`

Expected: PASS.

- [ ] **Step 5: Checkpoint**

Confirm Agreement admin remains read-only, preview is inline, download is attachment, and every state with an ID renders controls.

## Task 7 — Complete state, error, and URL-leakage coverage

**Files:**
- Modify: `tests/admin_hub/test_family_hub_page.py`
- Modify: `tests/admin_hub/test_family_hub_actions.py`
- Modify: `tests/registrations/test_agreement_module_docuseal.py`
- Modify: `tests/agreements/test_agreement_admin_document.py`

- [ ] **Step 1: Write failing test**

Parametrize lists with these exact display expectations:

```python
STATE_LABELS = [
    (Agreement.State.GENERATED, "Sagatavots"),
    (Agreement.State.SENT, "Nosūtīts parakstīšanai"),
    (Agreement.State.SIGNED, "Parakstīts"),
    (Agreement.State.VOID, "Atcelts"),
    (Agreement.State.SUPERSEDED, "Aizvietots"),
    (Agreement.State.DISCONTINUED, "Pārtraukts"),
]
```

For Family and Registration, keep one current agreement and add each tested state as `is_current=False` historical agreement with `external_id` and `generated_at=current.generated_at - timedelta(days=offset)`. Assert matching label and common download label. For Agreement admin, mutate one created agreement’s state and external ID per parameterized test.

Add tests that rendered Family/Registration/Agreement HTML contains neither `https://sign.example` nor a raw DocuSeal document URL; endpoints map `AgreementPlatformConfigError`, `AgreementPlatformAuthError`, `AgreementPlatformNotFoundError`, and `AgreementPlatformTransientError` to Latvian admin messages; and invalid disposition gives 404.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/admin_hub/test_family_hub_page.py tests/registrations/test_agreement_module_docuseal.py tests/agreements/test_agreement_admin_document.py -q -k "all_states or url_leakage or invalid_disposition"`

Expected: FAIL until historical presentation and proxy controls are complete.

- [ ] **Step 3: Write minimal implementation**

Add only code required by missing assertions. Error handlers catch `AgreementPlatformError`, call existing Django admin message API with Latvian mapped copy, and redirect to source change/hub page. Do not store, log, or template the DocuSeal URL.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/admin_hub/test_family_hub_page.py tests/admin_hub/test_family_hub_actions.py tests/registrations/test_agreement_module_docuseal.py tests/agreements/test_agreement_admin_document.py -q`

Expected: PASS.

- [ ] **Step 5: Checkpoint**

Confirm all six state labels, every surface, error class, ownership rule, disposition, and URL-non-leakage acceptance criterion has direct coverage.

## Task 8 — Update operator documentation

**Files:**
- Modify: `docs/admin-hub.md`
- Modify: `docs/milestones.md`

- [ ] Document that paper agreements create DocuSeal submissions without DocuSeal email; show where staff finds download controls and Agreement admin preview.
- [ ] Document current and historical agreement controls, including retained documents after void/archive.
- [ ] Update milestone status only after all code validation succeeds.

## Task 9 — Full verification and live acceptance

- [ ] Run `uv run pytest -q`
- [ ] Run `uv run ruff check .`
- [ ] Run `uv run mypy .`
- [ ] Run `uv run python manage.py makemigrations --check`
- [ ] On live DocuSeal, create paper and electronic submissions, confirm `send_email` behavior, preview/download their PDFs, then void one and confirm document retrieval remains available by staff.

Expected: all checks pass; no migrations; live DocuSeal confirms pending and archived document retrieval.

## File-by-file summary

| File | Action |
|---|---|
| `apps/integrations/agreement_platform.py` | `DocumentStream`, stream dispatcher, `send_email` passthrough |
| `apps/integrations/docuseal.py` | streamed fetch and `send_email` request body |
| `apps/integrations/tasks.py` | pass `send_email` through create task |
| `apps/agreements/services.py` | queue both paths; archive any external submission on void |
| `apps/agreements/document_proxy.py` | shared `StreamingHttpResponse` helper |
| `apps/agreements/presentation.py` | same-origin agreement link presentation items |
| `apps/agreements/admin.py` | view-only admin detail, PDF route, preview context |
| `apps/members/{admin,family_hub}.py` | protected Family route and prefetched historical context |
| `apps/registrations/{admin,admin_panels}.py` | protected agreement-id route and historical context |
| `templates/admin/_agreement_list.html` | shared historical download controls |
| `templates/admin/members/guardian/family_hub.html` | replace old redirect link |
| `templates/registrations/admin/_agreement_module.html` | replace `Atvērt DocuSeal ↗` |
| `templates/admin/agreements/agreement/change_form.html` | iframe and download control |
| `static/admin/css/agreement_document.css` | scoped preview styling |
| `tests/agreements/test_document_proxy.py` | proxy unit tests |
| `tests/agreements/test_agreement_admin_document.py` | admin and presentation tests |
| Existing provider, task, service, Family hub, and registration admin test modules | behavior and integration coverage |
| `docs/admin-hub.md`, `docs/milestones.md` | staff guidance and delivered status |
