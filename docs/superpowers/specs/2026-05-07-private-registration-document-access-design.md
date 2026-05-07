# Private Registration Document Access Design

**Date:** 2026-05-07
**Status:** Approved — security baseline design for registration document access
**Reference:** Brainstorming outcome approved by project owner
**Related:** `docs/milestones.md`, `docs/superpowers/specs/2026-05-05-parent-identity-verification-design.md`

---

## 1. Problem Statement

Registration identity documents are currently stored on local disk via Django `FileField`, under a path rooted at `MEDIA_ROOT`. The application does not currently expose `/media/` routes, but the storage layout still carries a future footgun:

1. **Storage ambiguity:** Documents live under a conventional media root (`uploads/`) that could later be mapped by a web server or template usage mistake.
2. **Access-path gap:** There is no dedicated, protected backend endpoint for admin preview/download of registration documents.
3. **Security-policy gap:** A `private/` filename prefix is not a security boundary. Only authenticated backend access checks can protect files.

This slice must establish a clear private-document policy before more admin and parent features are built on top.

---

## 2. Approved Scope

### In Scope

- Move registration document storage to a clearly private storage location/configuration
- Expose registration documents only through protected backend endpoints
- Restrict first-slice access to admins only
- Integrate document preview/download links into Django admin
- Support both inline preview and download from the same authorization path
- Redirect anonymous users to admin login
- Return `404` to authenticated non-admin users to avoid file-existence leakage
- Leave a clean hook for future audit logging

### Out of Scope

- Parent document access
- Audit event implementation
- New custom admin operations UI outside Django admin
- OCR pipeline changes
- Private object storage migration (S3, MinIO, etc.)
- Broader member/document authorization model beyond registration documents

---

## 3. Approved Access Model

Only admins may access registration documents in this slice.

| Requester | Result |
|---|---|
| Anonymous user | Redirect to admin login |
| Logged-in non-admin user | Return `404` |
| Admin user | Allow preview/download |

### Core Rules

1. **No public document URLs.** Registration documents must never be linked via `document.file.url` or any direct storage URL.
2. **Backend-only file serving.** Every preview/download request must pass through a Django view that performs authorization.
3. **No file-existence leak.** Authenticated users without admin permission receive `404`, regardless of whether the document exists.
4. **Preview and download share the same permission gate.** They differ only by response headers (`inline` vs `attachment`).
5. **Storage location and access path are both part of security.** It is not enough to add protected views while leaving documents in an ambiguous publicly mappable location.

---

## 4. Storage Design

### Target Policy

Registration documents move to a clearly private root, separate from any conventional public/static/media path.

```text
project/
├─ static/                 public assets
├─ uploads/                generic non-sensitive media if ever needed
└─ private-uploads/        registration identity documents, backend-only
```

The exact filesystem path can remain local-disk for now, but it must be configured as private-only by project policy and never mapped to a public URL.

### Storage Rules

- `Document.file` uses a private storage root
- Django templates/admin must not use `document.file.url`
- Web server or Django URL configuration must not expose the private root directly
- Future migration to object storage must preserve the same authorization model: protected backend access first, storage adapter second

### Why This Shape

- Prevents accidental exposure through later `/media/` routing or reverse proxy config
- Makes the public/private distinction visible in project configuration
- Keeps future storage-backend migration independent from access-control logic

---

## 5. Architecture

```text
Django admin
   -> Preview / Download links
   -> protected document endpoints
   -> documents access service
   -> private file storage root
```

### Responsibilities by Layer

#### Django admin
- Show read-only preview/download links for registration documents
- Never render direct file URLs

#### Document views
- Accept document ID and action (`preview`, `download`)
- Redirect anonymous users to admin login
- Delegate document lookup/authorization to service layer
- Stream file response on success

#### Document service layer
- Centralize admin-only authorization decision
- Return not-found-style failure for authenticated non-admin users
- Build file response metadata consistently for preview/download
- Provide clean seam for future audit-event insertion

#### Storage layer
- Read bytes from private storage location only after authorization succeeds
- Remain opaque to callers; no caller should depend on storage path format

---

## 6. Proposed Application Units

### `apps/documents/services.py`

Expected responsibilities:

- `get_admin_accessible_document(document_id, user) -> Document`
- `build_document_response(document, disposition) -> FileResponse`

Behavior:
- Anonymous callers are not resolved here; view handles login redirect first
- Authenticated non-admin callers trigger not-found-style failure
- Admin callers receive the active `Document`
- `disposition` controls `Content-Disposition` header: `inline` for preview, `attachment` for download

### `apps/documents/views.py`

Expected responsibilities:

- `admin_document_preview(request, document_id)`
- `admin_document_download(request, document_id)`

Behavior:
- If anonymous: redirect to Django admin login page
- Otherwise: call service layer for authorization + document fetch
- On success: return streamed file response with safe filename and stored content type

### URL configuration

Add protected application routes for preview/download. These are backend endpoints, not storage URLs. Exact route names can follow existing project conventions, but they must be stable enough for Django admin link generation.

### Django admin integration

Add read-only admin links for each document:
- **Preview**
- **Download**

These links appear only when a stored file exists.

---

## 7. Error Handling and Security Behavior

### Anonymous requests
- Redirect to admin login page
- Preserve expected Django admin login UX

### Authenticated non-admin requests
- Return `404`
- Do not distinguish between “missing document” and “forbidden document”

### Missing or deleted documents
- Return `404`
- Treat soft-deleted documents as unavailable

### File response behavior
- `preview` uses `Content-Disposition: inline`
- `download` uses `Content-Disposition: attachment`
- Both use same auth path and same underlying file stream

### Logging/audit seam
This slice does not implement audit events yet, but the service/view boundary must make later insertion straightforward, for example:
- audit on successful preview/download
- audit on denied access attempts if policy later requires it

---

## 8. Test Strategy

### What to test

1. Anonymous request to preview endpoint
   - receives redirect to admin login

2. Anonymous request to download endpoint
   - receives redirect to admin login

3. Authenticated non-admin request to preview/download
   - receives `404`

4. Admin request to preview
   - receives `200`
   - response uses `Content-Disposition: inline`

5. Admin request to download
   - receives `200`
   - response uses `Content-Disposition: attachment`

6. Successful admin response streams file through backend
   - no redirect to storage URL
   - no direct storage-path leakage in response body

7. Django admin integration
   - admin page shows Preview/Download links for document records where file exists

8. Storage configuration behavior
   - document uploads resolve under private storage location, not generic public media path

### What not to test

- Browser-native rendering of PDFs/images
- Storage backend internals beyond project-owned configuration
- Future parent-access behavior
- Audit event payloads
- Future object storage adapters

---

## 9. Acceptance Criteria

- [ ] Registration document files are stored in a clearly private storage location/configuration
- [ ] Registration documents are never exposed through direct public URLs
- [ ] Admin users can preview documents through protected backend endpoint
- [ ] Admin users can download documents through protected backend endpoint
- [ ] Anonymous users are redirected to admin login when hitting preview/download endpoints
- [ ] Logged-in non-admin users receive `404` for preview/download endpoints
- [ ] Preview and download differ only by response disposition, not permission logic
- [ ] Django admin exposes preview/download actions without revealing storage paths
- [ ] Design leaves a clean future hook for audit logging

---

## 10. Incremental Implementation Order

1. Introduce private storage root/config for registration documents
2. Update `Document.file` usage/config to target private storage policy
3. Add document access service for admin authorization + response construction
4. Add protected preview/download views and URLs
5. Integrate links into Django admin
6. Add tests covering anonymous, non-admin, and admin flows
7. Verify no direct storage URL usage remains in admin/templates for registration documents

---

## 11. Future Extensions

- Add audited access events at service/view boundary
- Expand authorization from admin-only to verified parent + admin where policy allows
- Move private storage to object store or separate infra-managed service without changing endpoint contract
- Introduce document deletion/revocation controls with audit trail
