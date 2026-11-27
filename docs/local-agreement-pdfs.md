# Local agreement PDFs: staff and operator guide

This guide describes the Slice A implementation in this worktree, not deployment
or activation approval. Local generation is default-off. Document-owner approval
of both templates, exact-image security and operational gates, and separately
authorized target deployment and activation remain necessary. The shadow PDF is
watermarked comparison material and is never the operative agreement.

## Staff workflow

1. For a current local agreement in `generated` or `sent` state, choose the
   signing path before preparation. In the registration admin, family hub, or
   Admin Hub agreement screen, explicitly request PDF preparation. A running
   qcluster and shared private storage are required. The worker queues after the
   transaction commits; preparation itself does not send, sign, or create billing.
2. Wait for **ready**, then use the authorized staff preview or download. If
   preparation failed, use retry; a pending request can be retried after five
   minutes when its frozen input remains available. Fresh pending and ready files
   are not retryable. A queue failure is recorded as a retryable failure.
3. Hand over the PDF manually for paper signing or the club's eParaksts process.
   Marking it sent records handover and sends a club-owned plain-text notice;
   that email does **not** attach or deliver the unsigned PDF. Local electronic
   handover requires a guardian email and does not silently switch to paper.
4. Upload the returned signed PDF or edoc through the existing signed-artifact
   workflow. Upload alone does not sign the agreement or create billing. After
   checking the artifact, explicitly confirm signing. Confirmation requires the
   readable ready PDF, matching frozen path, signed artifact, and existing active
   billing-plan and first-billing-month guards. Only then does the existing
   signing signal initiate draft billing. Upload is not a claim that an electronic
   signature has been validated.

## Identity, privacy and historical documents

The backend is selected when an agreement row is created and remains attached to
that row. Changing `AGREEMENT_DOCUMENT_MODE` affects future agreements, not
existing rows; its default is `docuseal`. Existing legacy rows retain their
provider references and historical routing. Local rows never fall back to the
provider, including when their file is unavailable. Billing renewal alone does
not create a new agreement.

Preparation freezes the signing path, template version `v1-2026-11`, renderer
provenance, and minimum child and guardian input. Profile changes do not alter a
retry; changing the path after freeze is refused. The pending/failed snapshot
contains sensitive personal data and is cleared on successful publication. It
must not be copied into logs, tickets, audit metadata, or exports. The renderer
checks the pinned template, CSS, font and logo digests; changed or unavailable
assets and mismatched provenance fail closed. A changed legal template requires
a new version, not an in-place edit. Source comparison and document-owner
approval remain activation prerequisites.

The ready PDF is stored privately, with size and SHA-256 checked when read.
Staff routes enforce their own permissions and associations, use private no-store
responses, and record redacted access events. There is no unsigned parent PDF
route. Signed-artifact access remains a separate existing workflow. Protect the
shared volume, backups, downloaded files, and any operational evidence as
sensitive material.

## Failure and reconciliation

- For a failed or stale pending request, investigate worker, queue, storage,
  required input, and version/provenance availability without exposing personal
  data. Correct the underlying issue and use the staff retry; it uses the frozen
  snapshot, not current profile data. Do not alter versioned assets to force a
  retry.
- A ready row whose file is missing, unreadable, or fails size/hash/PDF-header
  checks fails closed for download and lifecycle transitions. Ready rows are not
  regenerated automatically or through retry. Stop the workflow, preserve
  evidence, and arrange authorized restoration of the exact bytes from a trusted
  backup, verifying against the recorded size and digest. Escalate unresolved
  cases for an approved remedy; do not substitute a newly rendered document or
  provider file.
- Publication may leave a file under `agreements/generated/` when the database
  commit outcome is unknown. Restore database access and reconcile the exact
  stored name and SHA-256 against the persisted ready row and storage, accounting
  for in-flight workers and backups. If the outcome or ownership remains
  uncertain, retain the bytes and escalate. Never delete a possible winner based
  on an error log or an incomplete inventory; any later cleanup requires a
  separately authorized, verified procedure.

## Cutoff and rollback: future authorization required

`AGREEMENT_DOCUSEAL_CREATE_ENABLED` defaults to `true`; the legacy default can
continue creating sessions until a separately authorized cutoff. Setting it to
`false` blocks new legacy creates at multiple boundaries and blocks send/sign for
legacy rows without an external ID; already-issued sessions retain their normal
sync/completion path. A missing ID does **not** prove that no remote submission
exists. Neither setting is authorization to deploy, contact a provider, archive,
or shut it down.

Before requesting cutoff, inventory legacy draft, failed, and ambiguous no-ID
rows, including possible remote submissions, paper exceptions, signed uploads,
external references and queued/running/retrying/uncertain jobs. Have the data
owner adjudicate each case; record decisions and evidence without sensitive
content. Refresh the inventory immediately before cutoff, including sessions and
jobs created since the earlier inventory. Leave unresolved no-ID cases blocked,
not silently replaced.

Only after separate target deployment and activation approval: stop new staff
sends; quiesce **all** old web and qcluster processes; drain or reconcile jobs
and in-flight HTTP creates; deploy consistent cutoff-enabled configuration to
web and workers; verify no old processes or new provider sessions remain before
resuming traffic. A configuration change cannot cancel an HTTP request already
in flight. Allow already-issued sessions to sync.

Rollback before provider disable requires separate authorization and another
quiescence and reconciliation. Deliberately lift the cutoff and restore the
legacy default only for future rows. Existing local rows and PDFs remain local
and readable; do not delete artifacts or reopen sessions. Any provider re-enable
after a later disable requires separate authorization, security/configuration
checks and reconciliation. Legacy archive/import, integration disable, provider
shutdown, and retention policy are later decisions, not implemented here.
