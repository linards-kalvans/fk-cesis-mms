# WeasyPrint rollout and DocuSeal preservation design

## Status and decision

This is a forward-looking design, not authorization to implement, deploy, import, disable an integration, close a session, or shut down a provider. The selected approach generates new agreements locally and preserves existing DocuSeal material in MMS while already-issued signing sessions drain or are deliberately closed.
Integration disable and provider shutdown require separate future authorizations.

The alternative is to leave historical downloads on DocuSeal indefinitely. It avoids an initial import but retains provider availability, credentials, security, backup and operational dependencies for as long as records are needed. The selected approach incurs inventory, verification and private-storage costs but permits a verified offline operating mode without replacing historical documents with copies rendered from current data. Neither approach establishes a retention period.

## Baseline and boundaries

- Use the [local PDF design](2026-11-18-local-agreement-pdfs-design.md) and
  [prior plan](../plans/2026-11-18-local-agreement-pdfs.md) as design baselines,
  not as executable instructions. Shadow forwarding was implemented afterward:
  `apps/agreements/pdf_rendering.py` already exists as a comparison-only renderer,
  and `agreements/0008_agreement_pdf_shadow` is occupied. Reconcile current source,
  dependencies and migration graph before writing a fresh implementation plan.
- Shadow output is unsigned, watermarked comparison material, never an operative
  agreement or evidence of signing. Historical test/image evidence is not current
  deployment approval; see `docs/agreement-pdf-shadow.md` and its acceptance records.
- Preserve the backend chosen for every existing row, including non-current rows,
  drafts and failures with no external ID. A global switch affects only new rows;
  it must not silently reclassify, regenerate or reissue any existing agreement.
- Do not change legal wording, assert signature validity, infer legal retention
  from age, delete provider data, or expand parent access. Staff access to detached
  archives is limited to the permissioned, audited retrieval described below.

## Slice A — local default generation

Agreement services own durable per-row backend selection; registration approval,
normal creation, renewal, material replacement and regeneration all use the same
new-row selection rule. Existing agreement rows remain on their original backend.
An explicit cutoff stops *all* new DocuSeal sessions, including retries and send
actions on legacy rows without an external ID. Already-issued sessions alone may
continue normal sync and completion until closed; prevent queued or racing create
jobs from bypassing the cutoff. Inventory and adjudicate draft, failed and ambiguous
no-ID rows individually with the data owner; do not assume an absent ID proves no
remote submission exists. A replacement, if authorized, is a distinct new row
through the normal lifecycle, never a silent reissue or backend change.
Architect proposal: block send and sign confirmation for unresolved no-ID legacy
rows after cutoff, before mail, state, or billing changes. Preserve existing uploads
as evidence for reconciliation, not as a bypass. Resolve real paper exceptions
through the data owner before cutoff, or explicitly design a separate guarded path.

Staff explicitly requests generation via **Sagatavot PDF**; row creation does not
freeze a draft. Local document services and worker jobs then freeze signing path,
versioned template/assets and required input under lock, render privately, and
publish one immutable PDF with hash and provenance. Retain frozen input for retries;
concurrent jobs cannot replace a ready file. Missing bytes or version mismatch fail
closed without provider fallback or on-demand regeneration. A path change after
freeze requires the existing void/replacement workflow. Rendering does not send,
sign, create billing, or alter an existing document.

Both electronic eParaksts and paper are manual handover paths: staff downloads the
ready PDF, arranges signing externally, uploads a signed PDF or edoc through the
existing private upload, and explicitly confirms signing. Upload alone is not a
signing transition; existing billing-plan/month and signing guards remain in force.
Handover and confirmation for local rows require a ready PDF. Only the existing
authorized signing transition may trigger billing; rendering and archive import do not.
No new unsigned parent download, attachment, automated e-signature or signature
verification is introduced. Start from the reviewed shadow template in a distinct
production version with no comparison markings. Before issuing, compare against
an authorized blank source and have the club's document owner approve both paths;
missing source/approval blocks activation, not template development. Preserve approved
path-specific wording; no silent changes to legal clauses or assets.

Registration owns the blank preview: generate raster-only pages from the reviewed, versioned local template for each applicable path, with no personal data. Preserve active verified-parent authorization, existing preview surface and no-submission contract; it must work without DocuSeal. Cache keys distinguish version and path.

## Slice B — legacy inventory and private archive

The agreement domain owns an inventory covering all legacy rows, including
non-current and historically retained submissions, issued sessions, local uploads,
missing IDs, failures and any provider-only records discoverable during reconciliation.
Record source identity, agreement/submission association, lifecycle and session
status, and discrepancies; ambiguous associations remain exceptions, not guesses.
The data owner adjudicates each missing, inaccessible, ambiguous or unmatched item
and any closure, with reasons and evidence recorded without exposing personal data.
Age alone never excludes an item. Inventory is refreshed during drain and at cutoff.

Replace reliance on the current single-file remote proxy with a private, typed,
multi-artifact archive per submission: preserve each available provider PDF and
available signing evidence separately, including unsigned, signed and unknown types
where actually identifiable. Store exact original bytes, size, cryptographic hash,
source/provider and submission identifiers, type/classification basis, retrieval
time and import provenance. Never modify or replace existing staff-uploaded signed
artifacts; never label an unsigned or unknown file signed merely because it was
imported. Do not claim that a provider record proves a qualified signature.

Provide repeatable bounded dry-run and import batches with stable identifiers,
checkpoint/resume and idempotent publication; report conflicts, failures and
unknowns rather than overwriting artifacts. Compare source inventory to a manifest
of stored files, hashes and classifications, verify bytes after storage, and perform
a final delta after sessions and jobs stop. Reconcile counts and each exception with
the data owner; an unresolved exception blocks disable unless explicitly accepted
by the accountable data owner as a documented, authorized exception. Such acceptance
does not turn missing evidence into preserved evidence or authorize shutdown.

Before retirement, prove with an explicitly authorized deployed-provider/export
exercise that the required available files and evidence can actually be captured;
do not assume a particular API, export format, completeness or access rights.
The existing signed/original fetch rejects redirects and split-origin blobs. Keep
that fail-closed policy: template-origin allowlisting does not authorize signed
blobs. Any different capture method or origin policy needs separate security review
and acceptance; inability to capture is a blocking exception, not a reason to relax
checks silently. Keep source material and provider access intact during import.

Private storage, access controls and audit own preservation: existing authorized
staff surfaces continue to work, with signing evidence staff-only; family access
remains signed-only under existing ownership and authorization checks. No new public
URLs, parent evidence access or cross-family exposure. Serve archived bytes with
private/no-store responses and audited access; unavailable bytes fail closed. Test
backup and restore of database, files, manifest, metadata and hashes together, with
restricted access and a documented recovery owner. Logs and audit metadata exclude
document content, personal identifiers and credentials.

The confirmed decision is to allow ordinary Member and Agreement deletion while
retaining already preserved DocuSeal artifacts independently of live business
rows. Each archive has a durable identity independent of the Member-to-Agreement
cascade and an optional association to the live record that clears on deletion.
Retain only the matching metadata necessary to identify and reconcile the archive;
do not reattach it based on coincidental or reused identifiers. After detachment,
authorized staff can retrieve artifacts through private, permissioned, audited
access; parents have no access to detached archives. Ordinary deletion is not an
archive purge. The data owner must establish an explicit retention and authorized
purge policy; its duration remains undecided.

This decision preserves current business-record deletion rules, including unrelated
constraints; it does not change or authorize current deletion behavior. Reconcile
import/delete races and pre-import inventory gaps with the data owner before
integration disable. A record disappearing before preservation must not be treated
as evidence that its artifacts were archived.

## Slice C — offline disable and operator handoff

Integration owners implement an explicit disabled mode that rejects provider
creation, sync, fetch, archive and retry operations without network access; it must
not fall through to the stub or report simulated success. Web and worker share the
same configuration. Existing local and archived files remain available under their
normal permissions. For a shadow comparison, use only the confirmed original
unsigned primary PDF for the same submission; if missing or ambiguous, show an
unavailable state rather than substituting a signed file. Disable
new forwarding and retries that depend on DocuSeal. Never substitute shadow output
for a primary document or require a live provider for offline comparison access.

Before requesting integration-disable authorization, demonstrate no live sessions
or outstanding provider jobs, including queued, running, retrying and uncertain
jobs; reconcile final signed artifacts and available evidence plus the final delta.
Confirm all exceptions have the required data-owner disposition, restore checks
pass, and offline acceptance covers web and worker, blank preview, authorized
downloads, lifecycle/archive actions, and shadow primary-source behavior. A provider
archive action in disabled mode must fail visibly without a remote call; it must not
pretend success or silently change business state. Define and test any local-only
workflow separately without weakening existing lifecycle guards.

## Rollout, gates and rollback

1. Plan and implement A with legacy default unchanged; review additive migrations,
   current writers and queue races. Deploy only to an explicitly approved target.
2. Gate activation on focused and full regression tests, independent review,
   approved template/source comparison and visual checks, manual paper/eParaksts
   handover and upload/confirm acceptance, and unchanged billing/signing guards.
   Build and scan the exact release image; review native findings and obtain any
   explicit security risk acceptance. Verify web/worker configuration, private
   storage and migrations, provider/browser acceptance and rollback readiness.
3. Separately authorize local-default activation and cutoff. Record boundary and
   inventory; drain issued sessions, prevent new provider sessions, and resolve
   no-ID cases with the data owner. Run B dry-run, bounded imports and reconciliation.
4. After C offline tests and all disable gates, request separate integration-disable
   authorization. Provider shutdown is a later, separately authorized operator
   decision after evidence review; this document schedules neither operation.

Tests must cover every creation route and old backend, cutoff races and no-ID rows,
immutability/retries, preview and access isolation, multipart legacy artifacts,
hash and manifest reconciliation, idempotent import, import/delete races and
pre-import inventory gaps, no billing on render/import, and fail-closed offline
behavior. Acceptance must verify that preserved archives survive Member and Agreement
deletion, detached access remains staff-only and audited, and backup/restore
reconciles detached archives, metadata, files, manifests and hashes. Acceptance uses representative
authorized data and the exact deployed image, not only stubs or prior image scans.

Before disable, rollback may restore the legacy default for *future* rows only if separately authorized and the cutoff is deliberately lifted; existing local rows, issued PDFs, imports and legacy routing never change. After disable, re-enabling provider access requires explicit authorization, configuration/security checks and session/job reconciliation; it is not a substitute for restoring private backups. No rollback deletes issued or preserved files or silently reopens signing sessions.

## Decisions reserved for authorization

Operators and data owner must choose target environments, cutoff time, batch sizes,
session closure and exception policy, artifact completeness criteria, archive and
backup retention, recovery ownership, accepted security risks and activation dates.
Provider capabilities, exact capture mechanism and any separate origin policy remain
unverified. Infrastructure rollout, destructive cleanup, provider shutdown, new
signature verification and legal/retention determinations are outside this design.
