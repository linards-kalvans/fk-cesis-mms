# DocuSeal agreement document preview — design

Date: 2026-08-24
Status: approved for implementation

## Problem

The DocuSeal integration creates submissions only for electronic-signing agreements. Paper-agreement signing paths never receive a DocuSeal submission, so staff cannot preview or download the generated PDF from any surface. The existing `family_hub_docuseal_document_view` in `GuardianAdmin` redirects to the raw DocuSeal document URL, which exposes the external URL in the browser, prevents inline preview (iframe), and forces a download-only flow.

Additionally, `mark_agreement_sent` enqueues a DocuSeal submission only for the electronic path. Paper-path agreements remain invisible to the DocuSeal platform entirely.

## Scope

### In scope

- **`mark_agreement_sent`** creates a DocuSeal submission for **both** electronic and paper signing paths. Electronic submissions include `send_email=True` (DocuSeal sends the signing email to the guardian). Paper submissions include `send_email=False` (the existing club email handles guardian notification).
- **Download controls** appear for **both** paths and **all** agreement states: `generated`, `sent`, `signed`, `void`, `superseded`, `discontinued` — whenever an agreement has a non-empty `external_id`.
- **Three staff-only UI surfaces:**
  1. Family hub (`/admin/members/guardian/<id>/family-hub/`)
  2. RegistrationApplication admin change page (review panels)
  3. Agreement admin change page (staff-viewable, read-only)
- Family hub and RegistrationApplication UI label: `Lejupielādēt ģenerēto līgumu` (exact text).
- Agreement admin embeds the generated PDF inline (iframe) and provides the same forced-download button.
- **Server-side proxy** — list DocuSeal submission documents via `GET /submissions/{id}/documents`, select `application/pdf` or first usable document, fetch the selected URL server-side with `stream=True`, stream chunks through Django. **Never** expose or persist the DocuSeal URL in HTML or the database. `inline` disposition for iframe, `attachment` disposition for download. No migrations, no PDF storage in Django.
- **Void** archives any existing DocuSeal submission regardless of signing path, while retaining `external_id` so historical controls remain visible.
- **Guardian hub document endpoint** (existing `family_hub_docuseal_document_view`) is **refactored** to use the shared proxy — no parallel second streaming endpoint is created.
- **`Atvērt DocuSeal ↗` is removed** from the registration admin agreement module and the family hub; it is not co-rendered with the download controls.

### Out of scope

- Parent-facing agreement PDF downloads.
- Persisting downloaded PDFs in Django storage.
- New Agreement model fields or migrations.
- Changing the DocuSeal submission flow for void/superseded/discontinued agreements (they keep their existing `external_id`).
- Live DocuSeal instance validation (this is a post-test acceptance step, not a unit-test substitute).

## Architecture

### Data-flow diagram

```
Staff clicks "Lejupielādēt ģenerēto līgumu" (attachment) or iframe loads (inline)
    │
    ▼
Django view (Family hub / Registration admin / Agreement admin)
    │   (staff auth + ownership check)
    │
    ▼
agreement_platform.stream_submission_document(external_id)
    │
    ├── list_submission_documents(external_id)
    │   → GET /submissions/{id}/documents
    │   → parses filename, url, content_type
    │
    ├── select application/pdf first; fallback to first document
    │
    ├── GET the selected document URL (stream=True)
    │   → maps all HTTP/timeout/network errors to AgreementPlatform taxonomy
    │
    ├── DocumentStream(filename, content_type, chunks)
    │   → chunk_iterator always closes the upstream response in finally
    │
    ▼
build_agreement_document_response(agreement, disposition=inline|attachment)
    │   → StreamingHttpResponse with safe fallback "līgums.pdf"
    │   → Content-Type from selected doc (or "application/pdf")
    │   → Content-Disposition: inline/attachment with filename
    │
    ▼
Browser receives streaming response (iframe renders inline; download button triggers attachment)
```

### Component boundaries and contracts

```
apps/integrations/agreement_platform.py
├── DocumentStream(filename: str, content_type: str, chunks: Iterator[bytes])
│   → frozen dataclass: filename, content_type, chunks (chunk iterator)
│
├── stream_submission_document(external_id: str) -> DocumentStream
│   → DocumentStream: dispatcher that delegates to the active provider
│   → stub: returns deterministic `DocumentStream` with `filename="stub.pdf"`, `content_type="application/pdf"`, `chunks=iter([b"%PDF-1.4 stub"])
│   → docuseal: calls `list_submission_documents(external_id)`, selects `application/pdf` first, fetches via `_request("GET", selected.url, api_key, stream=True)`, yields `response.iter_content(chunk_size=64*1024)`, closes in `finally`
│
├── list_submission_documents(external_id) → list[DocumentResult]  (existing)
│
├── create_submission(agreement, send_email: bool = True)  (extended)
│   → passes send_email to the provider
│
└── archive_submission(external_id)  (existing)

apps/integrations/docuseal.py
├── stream_submission_document(external_id: str) -> DocumentStream
│   → calls list_submission_documents(external_id)
│   → selects application/pdf first, fallback to first document
│   → fetches the selected URL via _request("GET", selected.url, api_key, stream=True)
│   → iterator yields response.iter_content(chunk_size=64 * 1024)
│   → calls response.close() in finally
│   → maps all HTTP/timeout/network errors to existing AgreementPlatform taxonomy
│   → stub mode: no HTTP calls; returns deterministic `DocumentStream(filename="stub.pdf", content_type="application/pdf", chunks=iter([b"%PDF-1.4 stub"]))`
│
├── create_submission(agreement, send_email: bool = True)  (extended)
│   → adds "send_email": send_email to the submission body
│
└── list_submission_documents(external_id) → list[DocumentResult]  (existing)

apps/agreements/document_proxy.py (NEW)
├── build_agreement_document_response(agreement: Agreement, *, disposition: Literal["inline", "attachment"]) -> StreamingHttpResponse
│   → StreamingHttpResponse
│   → calls stream_submission_document(external_id) from the platform
│   → sets safe fallback filename "līgums.pdf"
│   → sets Content-Type (from selected doc or "application/pdf")
│   → sets Content-Disposition (inline or attachment with filename)
│   → rejects invalid disposition with Http404

apps/agreements/services.py
├── mark_agreement_sent(agreement, actor)
│   → CURRENT: enqueue DocuSeal only for ELECTRONIC
│   → NEW: enqueue for BOTH paths; pass send_email per path
│
├── void_agreement(agreement, actor, reason)
│   → CURRENT: checks signing_path == ELECTRONIC AND external_id
│   → NEW: checks external_id only (no signing_path gate)
│
└── get_current_agreement(member)
    → unchanged: returns is_current=True only
    → historical agreements require explicit queries

apps/members/admin.py
├── GuardianAdmin.family_hub_docuseal_document_view(request, guardian_id, agreement_id)
│   → CURRENT: lists docs, redirects to selected PDF URL
│   → NEW: calls build_agreement_document_response (shared proxy)
│   → same URL route, refactored implementation
│   → guardian ownership enforced (agreement belongs to selected guardian)

apps/registrations/admin.py
├── RegistrationApplicationAdmin.docuseal_document_view(request, object_id: int, agreement_id: int)
│   → NEW: staff-only GET endpoint
│   → verifies has_change_permission
│   → queries Agreement.objects.get(pk=agreement_id, member_id=application.approved_member_id)
│   → calls build_agreement_document_response (shared proxy)
│   → URL: admin:registrations_registrationapplication_docuseal_document
│   → URL route: <int:object_id>/agreement/<int:agreement_id>/docuseal-document/

apps/agreements/admin.py
├── AgreementAdmin
│   → has_change_permission: stays False (unchanged)
│   → has_view_permission(request, obj=None): returns request.user.is_authenticated and request.user.is_staff (new)
│   → change_form_template: "admin/agreements/agreement/change_form.html" (new)
│   → docuseal_document_view(request, object_id, disposition)
│   → NEW: staff-only GET endpoint
│   → verifies has_view_permission
│   → calls build_agreement_document_response (shared proxy)
│   → URL: admin:agreements_agreement_docuseal_document

apps/members/family_hub.py
├── build_family_hub_context: NEW "all_agreements" key on child rows only
│   → returns all member agreements with external_id (not just current)
│   → each entry: AgreementDocumentLink(agreement, state_label, signing_path_label, download_url)
│
└── build_family_queue_rows: NOT modified (YAGNI — queue UI does not render all_agreements)

apps/registrations/admin_panels.py
├── build_review_context: NEW "agreements" key
│   → returns all approved member agreements with external_id
│   → each entry: AgreementDocumentLink(agreement, state_label, signing_path_label, download_url)
│   → queries use select_related("member") to avoid N+1

apps/agreements/admin.py
├── AgreementAdmin:
│   → docuseal_document_view(request, object_id, disposition)
│   → verifies has_view_permission(request)
│   → queries Agreement.objects.get(pk=object_id)
│   → calls build_agreement_document_response(agreement, disposition=...)
│   → URL: admin:agreements_agreement_docuseal_document

apps/agreements/presentation.py (NEW)
├── AgreementDocumentLink: TypedDict
│   → agreement: Agreement
│   → state_label: str (from agreement.get_state_display())
│   → signing_path_label: str (from agreement.get_signing_path_display())
│   → download_url: str (fully built same-origin download URL)
│
├── build_agreement_document_links(agreements: Iterable[Agreement], *, url_builder: Callable[[Agreement], str]) -> list[AgreementDocumentLink]
│   → returns list[AgreementDocumentLink]
│   → url_builder is a callable that receives (agreement) and returns the download URL
│   → filters nothing — callers pass only agreements with non-empty external_id
│   → called by Family hub context and Registration review context

templates/admin/agreements/agreement/change_form.html (NEW)
├── {% extends "admin/change_form.html" %}
├── Renders iframe (disposition=inline) + download button (disposition=attachment)
├── Uses static/admin/css/agreement_document.css for accessible iframe styling
└── No inline styles

templates/admin/members/guardian/family_hub.html
├── Replaces existing anchor link with GET anchor (disposition=attachment)
├── Label: "Lejupielādēt ģenerēto līgumu" (exact text)
└── Uses GET anchor, not POST form

templates/registrations/admin/_agreement_module.html
├── Replaces "Atvērt DocuSeal ↗" with GET anchor (disposition=attachment)
├── Label: "Lejupielādēt ģenerēto līgumu" (exact text)
└── Uses GET anchor, not POST form

templates/admin/_agreement_list.html (SHARED PARTIAL — app-neutral)
├── Accepts agreements: Iterable[AgreementDocumentLink]
├── Renders each agreement's state label, signing path label, and download link
├── download_url is a fully built same-origin URL (no DocuSeal API URL in HTML)
├── Used from both Family hub and Registration review surfaces
└── No inline styles
```

### Historical context shape

`get_current_agreement(member)` returns only `is_current=True`. Superseded agreements carry `is_current=False`. Existing Family hub and registration module use only the current agreement. This design adds **bounded historical lists** to both surfaces:

- **Family hub child row:** `child.all_agreements` — all agreements for the member where `external_id` is non-empty. Each entry is an `AgreementDocumentLink` carrying `agreement`, `state_label`, `signing_path_label`, and `download_url`. Rendered via the shared `_agreement_list.html` partial so templates do not duplicate markup.
- **Registration review context:** `agreements` — all approved member agreements with `external_id`. Built by `build_review_context` via `build_agreement_document_links`. Rendered via the same `_agreement_list.html` partial.
- **Agreement admin:** handles its own agreement (single row, no list needed).

The partial `templates/admin/_agreement_list.html` (app-neutral, shared across `admin/` surfaces) accepts an `agreements` iterable of `AgreementDocumentLink` items and renders each agreement's state, signing path, and download link. This eliminates per-template markup duplication.

### mark_agreement_sent changes

`mark_agreement_sent` currently enqueues `create_agreement_submission` only when `signing_path == ELECTRONIC`. The change:

1. Always enqueue `create_agreement_submission` regardless of path.
2. Pass `send_email` flag to the task:
   - `send_email=True` for ELECTRONIC (DocuSeal sends signing email to guardian)
   - `send_email=False` for PAPER (club email handles guardian notification)

```python
# AFTER:
from apps.integrations.tasks import enqueue_create_agreement_submission
send_email = agreement.signing_path == Agreement.SigningPath.ELECTRONIC
enqueue_create_agreement_submission(agreement.id, send_email=send_email)
```

The `create_submission` function in `docuseal.py` accepts a `send_email` parameter:

```python
def create_submission(agreement, send_email: bool = True) -> SubmissionResult:
    ...
    body = {
        "template_id": template_int,
        "submitters": [submitter],
        "send_email": send_email,  # NEW
    }
    ...
```

The boundary `agreement_platform.create_submission(agreement)` becomes `agreement_platform.create_submission(agreement, send_email=True)`.

The task chain is:
- `enqueue_create_agreement_submission(agreement_id, send_email=True)` → `async_task("apps.integrations.tasks.create_agreement_submission", agreement_id, send_email)`
- `create_agreement_submission(agreement_id, send_email=True)` → `agreement_platform.create_submission(agreement, send_email=send_email)`

### void_agreement changes

The existing `void_agreement` checks BOTH `signing_path == ELECTRONIC` AND `external_id`:

```python
# CURRENT:
if (
    agreement.signing_path == Agreement.SigningPath.ELECTRONIC
    and agreement.external_id
):
    enqueue_archive_agreement_submission(agreement.external_id)
```

The change removes the signing_path gate:

```python
# NEW:
if agreement.external_id:
    enqueue_archive_agreement_submission(agreement.external_id)
```

This ensures void archives any DocuSeal submission regardless of signing path. The `external_id` is retained on the agreement so historical PDF controls remain visible.

### Document preview endpoints

All three endpoints use **GET anchors** with `?disposition=attachment` or `?disposition=inline`. Invalid disposition deterministically returns `Http404`. No POST forms for file downloads.

**Query filter contract:** Historical agreement lists use `.exclude(external_id="")` (not `external_id__isnull=False`) because the field default is blank string. Ordering is `.order_by("-generated_at", "-pk")` for deterministic results. The family hub prefetches `members__agreements` with a filtered `Prefetch` to avoid per-child queries.

**1. Family hub** — `GuardianAdmin.family_hub_docuseal_document_view(request, guardian_id, agreement_id)`

- Verifies `Guardian.objects.get(pk=guardian_id)`
- Verifies `Agreement.objects.get(pk=agreement_id, member__guardian=guardian)` (ownership)
- Verifies `agreement.external_id` is non-empty
- Calls `build_agreement_document_response(agreement, disposition=...)` (shared proxy)
- URL: `admin:members_guardian_docuseal_document` (same route, refactored implementation)

**2. Registration admin** — `RegistrationApplicationAdmin.docuseal_document_view(request, object_id: int, agreement_id: int)`

- Verifies `has_change_permission(request)`
- Verifies `RegistrationApplication.objects.get(pk=object_id)`
- Queries `Agreement.objects.get(pk=agreement_id, member_id=application.approved_member_id)` — else 404
- Verifies `agreement.external_id` is non-empty
- Calls `build_agreement_document_response(agreement, disposition=...)` (shared proxy)
- URL route: `<int:object_id>/agreement/<int:agreement_id>/docuseal-document/`
- URL name: `admin:registrations_registrationapplication_docuseal_document`

**3. Agreement admin** — `AgreementAdmin.docuseal_document_view(request, object_id, disposition)`

- Verifies `has_view_permission(request)` (new, returns `request.user.is_authenticated and request.user.is_staff`)
- Verifies `Agreement.objects.get(pk=object_id)`
- Verifies `agreement.external_id` is non-empty
- Calls `build_agreement_document_response(agreement, disposition=...)` (shared proxy)
- URL: `admin:agreements_agreement_docuseal_document`

### UI/surface table

| Surface | Label | Disposition | Trigger | Authorization |
|---------|-------|-------------|---------|--------------|
| Family hub (Līgumi section) | `Lejupielādēt ģenerēto līgumu` | `attachment` (GET) | Staff clicks anchor | Guardian ownership (agreement belongs to selected guardian) |
| Registration admin (agreement module) | `Lejupielādēt ģenerēto līgumu` | `attachment` (GET) | Staff clicks anchor | `has_change_permission` on application |
| Agreement admin change page (iframe) | — (auto-rendered) | `inline` (GET) | iframe src loads | `has_view_permission` on Agreement |
| Agreement admin change page (download anchor) | `Lejupielādēt ģenerēto līgumu` | `attachment` (GET) | Staff clicks anchor | `has_view_permission` on Agreement |

### Shared partial contract

The shared partial `templates/admin/_agreement_list.html` is app-neutral and rendered from both Family hub and Registration review surfaces. It accepts `agreements: Iterable[AgreementDocumentLink]` where each item carries:

- `agreement` — the `Agreement` model instance
- `state_label` — Latvian state display string (e.g. "Līgums sagatavots", "Līgums parakstīts ✓")
- `signing_path_label` — Latvian signing path label (e.g. "E-pasts", "Papīra līgums")
- `download_url` — fully built same-origin Django URL (no DocuSeal API URL in HTML)

The partial renders each agreement as a row with state label, signing path label, and a GET anchor to `download_url`. State queries use `.exclude(external_id="")` (not `external_id__isnull=False` — the field default is blank string) with `.order_by("-generated_at", "-pk")` for deterministic ordering.

### Security and error-handling contract

| Error condition | Handling |
|----------------|----------|
| Non-staff accessing any endpoint | 403/404 (Django admin permission denied) |
| Guardian ownership mismatch (Family hub) | 404 (agreement does not belong to selected guardian) |
| Application has no approved member (Registration) | Admin error message + redirect to change page |
| Agreement not found for (object_id, agreement_id) tuple (Registration) | 404 (agreement does not belong to reviewed application) |
| Agreement has no `external_id` | Admin error message + redirect (no DocuSeal submission yet) |
| DocuSeal provider error (config/auth/not-found/transient) | Admin error message + redirect; taxonomy mapped via existing `AgreementPlatformError` hierarchy |
| No usable document in submission list | Admin error message + redirect |
| Invalid `disposition` query parameter | `Http404` (deterministic rejection) |
| Chunk iterator failure during streaming | Django handles the disconnect; upstream response closed in `finally` |

**DocuSeal URL never exposed:** The DocuSeal document URL is fetched server-side and streamed to the browser. It never appears in rendered HTML, is never persisted to the database, and is never logged. The only stored reference is `external_id` (the submission ID), which is insufficient to reconstruct the document URL without the live DocuSeal API call.

### Exception taxonomy

All DocuSeal failures map to the existing taxonomy in `apps/integrations/agreement_platform.py`:

| Exception | Error code | Retryable |
|-----------|-----------|-----------|
| `AgreementPlatformConfigError` | `misconfigured` | No |
| `AgreementPlatformAuthError` | `auth_failed` | No |
| `AgreementPlatformNotFoundError` | `not_found` | No |
| `AgreementPlatformTransientError` | `unavailable` | Yes |

Provider errors surface as admin messages (e.g. "Kļūda: Neizdevās sazināties ar DocuSeal.") and the staff is returned to the originating surface.

### Stream error mechanics

`docuseal.stream_submission_document(external_id)` operates as follows:

1. Calls `list_submission_documents(external_id)` to retrieve the document list.
2. Selects `application/pdf` first; falls back to the first document if no PDF is found.
3. Fetches the selected document URL by calling the existing `_request("GET", selected.url, api_key, stream=True)`.
4. Returns a chunk iterator that yields `response.iter_content(chunk_size=64 * 1024)`.
5. Calls `response.close()` in a `finally` block to ensure the upstream response is always closed.
6. All HTTP/timeout/network errors are mapped to the existing `AgreementPlatform` exception taxonomy via `_request` — no raw `requests.get` usage, no duplicate status mapping.

### State behavior

PDF controls appear when `agreement.external_id` is non-empty. This covers:

| State | `external_id` present? | Controls visible? |
|-------|----------------------|------------------|
| generated | Yes (after submission completes) | Yes |
| sent | Yes | Yes |
| signed | Yes | Yes |
| void | Yes (retained) | Yes |
| superseded | Yes (retained) | Yes |
| discontinued | Yes (retained) | Yes |

If the submission is still pending (no `external_id` yet), controls are hidden.

### Agreement admin view-only permission

`AgreementAdmin.has_change_permission` currently returns `False`. This design adds a new `has_view_permission` method that returns `request.user.is_authenticated and request.user.is_staff`, enabling Django's native view-only change page. The existing `has_change_permission` remains `False` — staff cannot edit or save the agreement through the admin. All fields are already in `readonly_fields`, so the change page is effectively read-only. This is NOT the same as asserting that readonly fields make `has_change_permission` safe — `has_view_permission` is the correct Django hook for view-only access.

## Why these decisions

1. **Paper path gets a DocuSeal submission too.** Staff need to preview generated PDFs for all agreements. Paper agreements need the same PDF generation capability — they just don't need DocuSeal to email the guardian, so `send_email=false`.

2. **Server-side streaming, not redirect.** The existing Family hub endpoint redirects to the DocuSeal URL. The new requirement is inline preview (iframe) on the Agreement admin change page, which requires the content to flow through Django. Streaming is the only way to support both inline preview and forced download from a single server.

3. **Shared proxy, no parallel endpoints.** The existing `family_hub_docuseal_document_view` already lists documents and selects a PDF. Refactoring it to use a shared `build_agreement_document_response` helper avoids duplicating HTTP streaming logic across three admin views. Each admin route only authorizes/resolves its Agreement then delegates to the shared helper.

4. **No URL persistence.** DocuSeal document URLs are time-limited and may change. Fetching on every request avoids stale URLs and prevents leaking them into templates or the database.

5. **No migrations.** The existing `external_id` field on `Agreement` is already populated for paper agreements after this change. No new fields needed.

6. **`has_view_permission` instead of `has_change_permission = True`.** Django's permission model distinguishes view from change. Using `has_view_permission` correctly expresses the intent (staff can view but not edit) without relying on the fragile pattern of "readonly fields make change permission safe."

7. **GET anchors, not POST forms.** File downloads are idempotent reads. Using GET with `?disposition=attachment` is semantically correct and avoids CSRF complexity. Invalid disposition is rejected with `Http404`.

8. **Void archives regardless of signing path.** A voided agreement may have had an electronic submission that should be archived. The signing_path gate is unnecessary — if `external_id` exists, the submission should be archived.

9. **Historical route contract.** Registration admin must select a specific historical agreement by `agreement_id` (not just the current one), so the route accepts both `object_id` and `agreement_id`. The query enforces that the agreement belongs to the reviewed application's member, preserving the ownership invariant.

10. **Shared partial with typed presentation items.** A generic partial cannot know each source route's URL. `AgreementDocumentLink` carries a fully built `download_url` so the partial renders the same-origin link without needing to construct it. Family hub and registration review context each own their URL builder; the partial is agnostic.

11. **Platform function does not accept disposition.** Document fetching is independent of HTTP disposition. `stream_submission_document(external_id)` returns `DocumentStream`; `build_agreement_document_response` applies the disposition. This separation keeps the streaming layer pure.

12. **Stream uses existing `_request`.** `docuseal.stream_submission_document` calls `_request("GET", selected.url, api_key, stream=True)` rather than raw `requests.get`, preserving the existing exception taxonomy and status→error mapping.

## Superseded documents

This design supersedes `docs/superpowers/specs/2026-07-09-docuseal-agreement-pdf-download-design.md` (the original PDF download design dated 2026-07-09). That document covered a redirect-only approach for the Family hub. This design extends the scope to all three surfaces, adds server-side streaming, covers the paper signing path, and introduces the shared proxy pattern. The original document is cited for historical context but is not modified.

## Acceptance criteria

1. `mark_agreement_sent` enqueues a DocuSeal submission for both electronic and paper paths. Electronic submissions include `send_email=true`; paper submissions include `send_email=false`.
2. Family hub shows `Lejupielādēt ģenerēto līgumu` anchor for any agreement with `external_id`, regardless of signing path or state.
3. Registration admin agreement module shows `Lejupielādēt ģenerēto līgumu` anchor for any agreement with `external_id`.
4. Agreement admin change page (staff viewable via `has_view_permission`, read-only) embeds the PDF inline and provides a download button.
5. The anchor on Family hub and registration admin forces a download (attachment disposition).
6. The Agreement admin embed shows the PDF inline (inline disposition). The download anchor provides forced download.
7. The DocuSeal document URL is never rendered in HTML or persisted to the database.
8. Family hub enforces guardian ownership: staff cannot access another guardian's agreement document.
9. Registration admin enforces application ownership: the agreement's member must belong to the reviewed application (queried via `pk=agreement_id, member_id=application.approved_member_id`).
10. Agreement admin enforces staff view permission (`has_view_permission` returns `request.user.is_authenticated and request.user.is_staff`).
11. Voided agreements retain their `external_id` and still show PDF controls.
12. Existing void behavior archives the DocuSeal submission regardless of signing path (the signing_path gate is removed).
13. No migrations are generated.
14. All DocuSeal provider errors map to the existing exception taxonomy and surface as Latvian admin messages.
15. Invalid `disposition` query parameter is deterministically rejected with `Http404`.
16. `Atvērt DocuSeal ↗` is removed from all surfaces; it is not co-rendered with download controls. Download controls use GET anchors, not POST forms.
17. Family hub child rows and registration admin show **all** member agreements with `external_id` (not just current), rendered via a shared `_agreement_list.html` partial. Historical rows use `.exclude(external_id="")` with `.order_by("-generated_at", "-pk")`. Family hub prefetches `members__agreements` with a filtered `Prefetch` to avoid per-child queries.
18. The existing Guardian hub document endpoint is refactored to use the shared proxy (no parallel streaming endpoint).
19. Streaming chunk iterator always closes the upstream response in `finally`.
20. First non-PDF document is a success fallback when no PDF is available — tested only in the provider (`docuseal.py`), not at the ModelAdmin view level.
21. `stream_submission_document` does not accept a `disposition` parameter; disposition is applied only by `build_agreement_document_response`.
22. `docuseal.stream_submission_document` uses existing `_request` for the outbound GET, preserving the exception taxonomy.
23. `AgreementDocumentLink` carries a fully built `download_url` so the shared partial is URL-agnostic.

## Live validation note

Live DocuSeal validation should prove generated and archived/history retrieval behavior. This is a post-test acceptance step, not a unit-test substitute. The stub fixtures cover the happy path and error taxonomy; a live instance validates the end-to-end document listing, PDF selection, and streaming behavior.
