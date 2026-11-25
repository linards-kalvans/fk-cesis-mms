# Agreement PDF shadow comparisons

## Status and boundaries

This feature creates a **separate, unsigned, comparison-only PDF** after a successful new primary agreement submission. DocuSeal remains authoritative for the agreement and its existing notifications and lifecycle. Never send a shadow PDF to a parent, use it for signing, or upload it as a real or signed agreement. Every shadow page is marked in Latvian as not valid for signing; real forwarded data is not labelled synthetic.

`AGREEMENT_PDF_SHADOW_ENABLED` defaults to `false`. Activation is limited to an explicitly chosen development environment after review; it is not authorized by this document. The existing root database remains unmigrated. Security conditions, signing acceptance, deployment and activation remain unapproved. No automatic backfill or agreement lifecycle, sending, billing or mail change is added by shadowing. The shared primary document-fetch path has been tightened as described below.

The latest 2026-11-25 real-clock PostgreSQL gate passed **2989 tests, with zero failures, errors or skips**, after repairing date-sensitive test fixtures without changing production billing/signing guards. Lint, typing, migration drift and scoped whitespace checks passed. Independent code review approved the changes with deferred minor findings; this is not security risk acceptance or deployment, browser or signing approval. No exact-latest-source image build or scan has been performed. The earlier scan recorded baseline 0C/48H/1 fixable H/C → candidate 0C/51H/0 fixable H/C; four new unfixed Expat HIGH findings remain unresolved, and scan artifacts are unavailable. The earlier candidate offline smoke and 2964-test gate are historical. Current evidence: `docs/acceptance/2026-11-25-shadow-test-repair-and-review.md`; earlier checkpoints: `docs/acceptance/2026-11-25-agreement-pdf-shadow-resume.md` and `docs/acceptance/2026-11-18-agreement-pdf-shadow.md`.

## How it works

After the primary job saves a successful DocuSeal submission, best-effort forwarding captures the exact field map used for that POST and its signing path. A private shadow row stores that snapshot and the original submission ID; the queue receives only the shadow row ID. A forwarding, queue, rendering or storage failure must not change the primary result. Older agreements are not scanned or backfilled.

The worker renders the frozen snapshot with WeasyPrint 70, native Pango and HarfBuzz, and local DejaVu fonts. It uses versioned HTML/CSS and an allowlist of local fonts and logo, not external resources. Output is limited to 20 MiB and 20 pages. The row records renderer, Pango, HarfBuzz, template and asset provenance, size and SHA-256. Pending and failed rows retain the sensitive snapshot for retry; successful publication clears it. Ready output is immutable and is not overwritten by retry or duplicate jobs.

Retry uses the original snapshot, not current member data. Preserve the matching template, CSS, logo, fonts and renderer/native versions for outstanding retries. If recorded provenance no longer matches, the job fails with `version_mismatch` instead of silently substituting the current template. Retaining matching assets alone does not guarantee that every environmental difference is captured by provenance.

Paper comparisons intentionally omit electronic-signature and timestamp wording present in the current DocuSeal template; they retain a date field and signature lines. Compare accordingly rather than treating those differences as unexpected defects. The local PDF is unsigned even when its electronic-path text describes electronic signing.

## Development setup — planned commands only

Do not run these commands until the chosen development environment, access, security review and activation are explicitly approved. Substitute the placeholders; verify the target database and storage before any migration. Never point these steps at the existing root database or production by accident.

1. In the chosen checkout, install dependencies with `uv sync`. Ensure the local system has the native Pango, HarfBuzz and DejaVu dependencies as well as the Python dependencies. The container installs these and refreshes `zlib1g` for CVE-2026-85091 without a blanket OS upgrade; that intent is not proof of a clean final scan.
2. Configure an **isolated, explicitly chosen dev database** and private storage using that environment's configuration. Review `DATABASE_URL`, provider mode, email settings and the actual `PRIVATE_DOCUMENTS_ROOT` before proceeding. The default private root is `private-uploads/` under the application base directory.
3. Only on the approved dev target, plan to apply migration `agreements/0008_agreement_pdf_shadow` along with any prerequisite migrations:

   ```sh
   # Run only after verifying this placeholder resolves to the chosen dev database.
   DATABASE_URL='<CHOSEN_DEV_DATABASE_URL>' uv run python manage.py migrate
   ```

4. After review and explicit activation approval, set `AGREEMENT_PDF_SHADOW_ENABLED=true` in **both** web and qcluster environments. They must use the same chosen database and private volume. Provision the private directory for the service owner: restrict access to the intended web/worker identity, deny public serving, and use owner-only permissions (the container creates its private root with mode `0700` and app ownership). Apply equivalent access controls to database and backups.
5. Start both processes in the approved environment, with identical flag, database, provider and private-storage configuration. Example commands, in separate terminals:

   ```sh
   # The environment must already contain the approved dev settings.
   uv run python manage.py runserver <APPROVED_DEV_BIND_ADDRESS>:<PORT>
   uv run python manage.py qcluster
   ```

   Follow the deployment environment's established exposure and process-management rules. Do not place credentials in command history or documentation. Generating a primary submission may invoke the configured provider and its normal notification behavior; use only an explicitly authorized dev scenario.

## Staff inspection and recovery

Active staff can open `/admin/agreements/agreementpdfshadow/` and inspect the read-only list and detail. The detail shows status, signing path, saved submission ID, provenance and file metadata, not the snapshot. It provides paired private original/local preview and download links when the local PDF is ready. The original is fetched using the row's saved submission ID, not the agreement's later current ID. A stored nonsecret fingerprint of the provider mode and canonical API base must match the current configuration; missing or mismatched identity refuses the fetch. API keys, URL userinfo and query strings are not stored. The primary iframe may still appear on a mismatch but returns 404. Access is proxied, audited and served with private/no-store headers; no public storage or provider URL is exposed by these links. Inline comparisons permit same-origin framing; attachments retain the default DENY policy.

Both the existing primary admin download and the shadow original use the shared signed-document stream. Metadata and blob requests reject redirects, and the selected blob must have the configured API origin. Split-origin signed/original blobs therefore fail closed. `DOCUSEAL_TEMPLATE_ALLOWED_ORIGINS` applies only to blank template documents; it does not authorize signed or original blobs. There is no signed-blob allowlist. If a deployment returns public blob URLs on a different origin from its internal API, establish and review a future origin policy and validate it with the provider before use; do not assume the template allowlist resolves this limitation.

Inspect the fields, layout, page markings and expected paper differences in an authorized private session. The snapshot and both PDFs may contain real personal IDs, names, addresses and contact information. Do not copy them into logs, tickets, screenshots or public sharing channels; handle downloads and backups under the same controls as private agreement data.

For a failed row, or a pending row unchanged for more than five minutes, the detail offers retry when the flag is enabled and a snapshot exists. Use the admin retry button, which submits a CSRF-protected POST. Retry schedules only the local comparison; it does **not** resend the primary agreement. Investigate generic `queue_failed`, `render_failed`, `version_mismatch` or `disabled` status without logging sensitive content. A ready row cannot be retried.

To stop new forwarding and queued rendering, set `AGREEMENT_PDF_SHADOW_ENABLED=false` on both web and qcluster and restart or reload both processes through the environment's normal process manager. A worker that observes the disabled flag marks pending work it executes as failed; disabling is not a retroactive cancellation of a job that has already completed. Existing ready comparisons remain readable. Re-enabling and retrying require renewed authorization and matching provenance.

## Cleanup and retention

Shadow rows belong to their agreement and are deleted by cascade when that agreement is deleted. Deleting a shadow row schedules deletion of its private file after the database transaction commits; file deletion failure is logged and requires operator investigation. This is not an automatic age-based prune, and no unrelated document, database-backup or audit retention policy is changed. Coordinate any authorized cleanup with the data owner and existing private-data procedures; do not delete agreements merely to remove comparisons.
