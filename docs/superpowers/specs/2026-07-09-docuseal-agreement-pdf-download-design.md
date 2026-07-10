# DocuSeal agreement PDF download — design

Date: 2026-07-09
Status: approved for planning

## Problem

Staff need a direct way from the Family hub to open/download the DocuSeal-generated agreement PDF before it is signed. DocuSeal exposes the partially filled submission PDF through its documents API. After signing, the same endpoint returns the final signed PDF.

## Scope

In scope:
- Staff-only Django admin proxy for DocuSeal submission documents.
- Family hub link for agreements with a DocuSeal `external_id`.
- Provider boundary method for `GET /submissions/{id}/documents`.
- Tests for provider parsing, admin access control, redirect behavior, and hub visibility.

Out of scope:
- Parent-facing agreement PDF downloads.
- Persisting downloaded PDFs in Django storage.
- New Agreement fields or migrations.
- Streaming DocuSeal files through Django unless redirect proves insufficient.

## Design

Add a small `DocumentResult` dataclass and `list_submission_documents(external_id)` function to the existing agreement-platform boundary. Stub mode returns one deterministic PDF URL. DocuSeal mode calls `GET {DOCUSEAL_API_URL}/submissions/{external_id}/documents` with `X-Auth-Token` and parses the returned `documents` list.

Add a Guardian admin endpoint under the Family hub URL space. It is wrapped by `admin_site.admin_view`, verifies the `Agreement` belongs to the selected `Guardian`, requires `external_id`, asks the provider for submission documents, chooses the first `application/pdf` document (falling back to the first document), and redirects to that document URL. Provider/config/access errors become admin messages and redirect back to the hub.

Add a Family hub link near DocuSeal controls: `Lejupielādēt līguma PDF no DocuSeal`. Render only when `child.agreement.external_id` exists.

## Acceptance criteria

- Staff can click the Family hub link for an electronic agreement with `external_id` and reach the DocuSeal PDF URL.
- Staff cannot use the endpoint to access another Guardian's agreement.
- Hub does not show the link when there is no `external_id`.
- DocuSeal provider calls `/submissions/{id}/documents` and parses `filename`, `url`, and `content_type`.
- No migrations are generated.
