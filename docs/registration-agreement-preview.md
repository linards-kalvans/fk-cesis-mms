# Registration agreement template preview

## Parent experience

The editable registration wizard (including the legacy invalid-POST fallback)
shows **Līguma paraugs** at the top of **Piekrišana**, above signing/payment
preferences. It lazy-loads when that section becomes visible, displays one page
at a time, and offers previous/next controls and a larger in-page dialog.
Escape closes the dialog and focus returns to the expand button. On narrow
screens the enlarged page can be scrolled horizontally for legible text.

This is the configured **blank template**, not a personalized agreement or a
signing session. Viewing never creates an Agreement, DocuSeal submission, or
email. It adds no acknowledgement field or submission gate. If preview loading
fails, a Latvian error and retry button appear; registration remains usable.
Without JavaScript, an explanatory message is shown instead of a preview.

The approved layout was an inline viewer rather than an expandable disclosure
(easier to miss) or a new/final-review step (too late or an extra step).

## Implementation and operations

- `AGREEMENT_DOCUMENT_MODE` selects the configured backend, defaulting to
  `docuseal`. In local mode the worker renders a blank snapshot using the
  versioned local template; the selected paper/electronic path determines its
  wording. In DocuSeal mode, `AGREEMENT_PROVIDER_MODE`, `DOCUSEAL_API_URL`,
  `DOCUSEAL_API_KEY`, and `DOCUSEAL_TEMPLATE_ID` select the provider template.
  Stub mode shows a synthetic sample, not the live contract. Local preview does
  not contact the provider.
- A running **qcluster** is required. The first viewer request enqueues
  `apps.agreements.template_preview.refresh_template_preview`; HTTP handlers
  do not make outbound provider calls. A temporary pending marker coalesces
  requests best-effort; duplicate read-only jobs are safe.
- In DocuSeal mode the worker reads `GET /templates/{configured_id}` and downloads its
  `documents[].url` PDFs in template order, without creating a submission.
  Blob downloads allow the API origin plus exact origins explicitly configured
  in `DOCUSEAL_TEMPLATE_ALLOWED_ORIGINS` (comma-separated environment setting).
  For an internal `DOCUSEAL_API_URL=http://docuseal:3000/api` and public blob
  links, set `DOCUSEAL_TEMPLATE_ALLOWED_ORIGINS=https://agreements.mplytics.eu`
  on **both web and qcluster**, then restart/redeploy both processes. Keep the
  API internal; do not change DocuSeal's public signing host. Origins include
  scheme, hostname, and effective port (443 for HTTPS / 80 for HTTP); paths,
  credentials, query strings, fragments, and wildcards are rejected. Other
  origins, lookalike hosts, and subdomains are not implicitly trusted. Downloads
  still send no API key and do not follow redirects, including from trusted
  origins. Configure only operator-controlled destinations.
- PyMuPDF renders the PDFs to PNG pages. Limits: 20 MiB total source bytes,
  20 pages total, bounded page dimensions and raster resolution. Encrypted or
  malformed PDFs fail closed. PDFs and provider metadata are not cached.
- Raster pages are cached for **one hour** in
  `PRIVATE_DOCUMENTS_ROOT/agreement-template-preview/`, shared between web
  and worker through the existing private volume. Both processes need write
  access. Identity includes configured backend, selected signing path, and
  template version. DocuSeal keys additionally include provider mode, API URL,
  template ID, and origin allowlist; changed trust settings invalidate cached
  failure markers. Legacy template edits may take up to one hour to appear.
  Cache files are disposable and contain raster pages, not source PDFs or PII.
- The manifest returns 202 while queued, 503 while a failure marker is present,
  and 200 only when pages are ready. Failed fetch/queue/render results are
  suppressed for 60 seconds; pending coalescing lasts 90 seconds. Parent polling
  is bounded and pauses in hidden tabs. A stale job whose backend no longer
  matches worker configuration fails before fetching or rendering; stale image
  versions and invalid page numbers return 404. Backend/version assertions that
  do not match configuration, and invalid signing paths, return 400. A change
  of signing path does not let an older asynchronous response replace the new
  selection. Web and worker must use matching configuration.
- Both the manifest and versioned image routes require an active verified
  parent session and send `Cache-Control: ... no-store`. The blank template is
  shared, not owned by one application. Staff agreement-document access is a
  separate, backend-routed workflow.
- Preview remains separate from agreement creation, signing and billing. The
  local generation rollout and its separate activation prerequisites are
  described in [Local agreement PDFs](local-agreement-pdfs.md).

## Download limitation

Parents receive only raster images; there is **no parent source-PDF endpoint**,
native PDF toolbar, download link, print control, or signing button. The viewer
is hidden in the page's print stylesheet. This is a UI restriction, not DRM:
screenshots, saving image responses, or deliberate browser tooling cannot be
prevented for content delivered to a browser.

## Verification (2026-10-31)

- Full local suite: **2897 passed, 2 skipped**. The two existing correction
  serialization tests require PostgreSQL and are skipped by the SQLite lane.
- Ruff, mypy, migration drift, JavaScript syntax, and whitespace checks passed.
- Isolated real-Chrome check at desktop and 390 px: page navigation, enlarged
  dialog, Escape/focus return, normal-page overflow, error/retry recovery, and
  zero JavaScript page errors. Production partial/CSS/JS with mocked template
  responses; this is not a live provider/end-to-end registration acceptance.
- Live DocuSeal response/contract rendering and deployed shared-volume/worker
  acceptance remain pending. No deployment, email, or provider mutation was run.

## Local acceptance (2026-10-31)

The user accepted the local instance and authorized committing/pushing to `dev`.
The LAN instance used a migrated SQLite snapshot (original database unchanged),
web + qcluster, the configured DocuSeal/SMTP providers, and disabled scheduled
jobs. Health and registration entry returned HTTP 200. This records user local
acceptance, not an independently observed live-provider contract test or deployed
environment sign-off. Deployment/shared-volume acceptance remains pending.

## Split-origin deployment fix (2026-10-31)

Deployment diagnosis identified the internal API/public blob-origin mismatch:
the previous API-only guard rejected legitimate public template URLs and the
preview returned 503. The fix adds the explicit origin setting above rather
than accepting arbitrary URLs or changing DocuSeal's signing host.

Regression coverage reproduces the internal API/public blob combination through
PDF rendering and the parent manifest/image endpoints with mocked provider HTTP.
It also checks origin lookalikes, ports, credentials, invalid configuration, and
failure-cache invalidation. Full local suite after the fix: **2915 passed,
2 existing PostgreSQL-only skips**; ruff, mypy, migration and whitespace checks
passed. The deployed environment still needs the new setting, updated web/worker
processes, and a real manifest-200 plus image-200/browser-render acceptance check
(202 alone only means queued).
