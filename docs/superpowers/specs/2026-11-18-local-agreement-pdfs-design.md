# Local agreement PDFs — migration design

## Status and intent

User approved fixed-width revision 2 samples and proceeding with the next technical
checks/planning. This does not approve security risks, prove signing, or authorize
deployment/DocuSeal retirement.
This records proposed production choices, not an implemented/released feature.
Prerequisite evidence and remaining security/manual-signing/review gates:
`docs/acceptance/2026-11-18-weasyprint-feasibility.md`.

Replace DocuSeal generation for **new agreements** with reviewed Django templates
and WeasyPrint 70.0. Current signing remains manual eParaksts or paper, followed by
existing PDF/edoc upload and explicit staff confirmation. Future browser eParaksts
integration is separate; it must consume issued PDF bytes rather than own layout.

## Confirmed document contract

- DejaVu Sans body; DejaVu Sans Mono Bold for every inserted/repeated value.
- Preserve approved wording, including 50 EUR base fee and existing reduction /
  amendment provisions. Do not insert each family's computed discount into 4.1.
- Paper omits electronic-signature footer, timestamp header, and electronic /
  last-signer-timestamp sentences of the final 7.5 clause. Retain its general
  Latvian-language sentence, ordinary blank date field, and handwritten signature
  spaces. Electronic variant retains the approved provisions.
- No automatic correction of duplicate numbering, payment terms or other legal
  text. No prototype TEST markings or diagnostic alphabet in real documents.
- Production template contains reviewed clauses directly; never extract legal text
  from a PDF at runtime. Freeze a template version (`v1-2026-11`) with the document.
  A version identifies immutable HTML, CSS, fonts and logo bytes. Any content/asset
  change creates a new version, never an in-place edit. Keep old versions available
  while pending/failed jobs reference them. A missing/mismatched version fails
  explicitly; retries must never substitute the current version.

## Alternatives and why

WeasyPrint is selected for flowing legal text/print CSS and existing Django stack.
Chromium adds unnecessary browser runtime; ReportLab requires more programmatic
layout; fixed PDF overlays constrain long values; DOCX conversion adds Office
runtime without a confirmed staff Word-editing requirement. Renderer 68.1 was a
spike-only pin and is rejected after security comparison; 70.0 fixes its reported
HIGH advisory. Native dependency findings still require final-image risk review.

## Domain and state (architect proposals)

### Explicit new/legacy routing

Add `Agreement.document_backend`, choices `docuseal` / `local`, migration default
`docuseal`. Historical rows remain legacy, without fetching or regenerating them.
`AGREEMENT_DOCUMENT_MODE` defaults to `docuseal`; only newly created agreements
read it. Production activation is a later configuration change, not this migration.
Material amendments/regenerations create new agreement rows through the same
backend-selection rule; they never overwrite the earlier agreement's artifact.

Why: durable per-row routing avoids reinterpreting old rows when global settings
change. Keep `external_*` fields and legacy integrations during coexistence.

### Separate unsigned document record

Add `GeneratedAgreementDocument`, one-to-one with Agreement, private FileField,
status pending/ready/failed, template version, frozen signing path, temporary
render-input JSON, content hash, size, created/ready timestamps, generic error code.
This record is distinct from existing `Agreement.signed_artifact`.

Why: one durable async job result per agreement, not an artifact-version system.
Snapshot is needed only while pending/failed so retries never read changed guardian
data. On success retain the exact private PDF/version/hash and clear temporary
snapshot data. Snapshot receives the same DB/backup protection as source personal
fields; never log it or expose it through admin forms, audit metadata or exports.

### Generate, then hand over

Proposed staff flow: **Sagatavot PDF → PDF ready → existing handover action →
staff confirms signed**. Generation runs in the background and never marks sent,
signed, or creates billing. Keep existing generated/sent/signed states; show document
pending/failed/ready alongside them rather than adding agreement states.

Why: manual signing does not justify optimistic “sent” or “signed” on render success.
For local rows, handover and signing require ready PDF. Existing billing-plan/month
guards and signing signal remain authoritative. Upload alone still changes no state.

First generation request freezes data/path/version under row lock. Duplicate jobs
may render, but only first successful row-locked publication wins; discard losing
temporary files. Ready artifacts are never regenerated or replaced by downloads,
retries, profile/template edits, signing-path sync or setting changes. A path change
after freezing is refused; staff uses existing void/new-agreement lifecycle instead.
Apply this guard to both staff path setter and application-to-agreement sync writer.
Failed generation keeps its frozen snapshot and offers explicit retry of that input.

Frozen fields: agreement number, signing path, child name/PID/DOB/address, guardian
name/PID/address/email/phone, template version. No OCR payloads, uploaded documents,
training-group details or dynamic billing calculations are added.

## Integration and delivery boundaries

- Keep all staff authorization/ownership guards, same-origin routes and filenames.
  Shared document response serves local stored bytes for local rows and the existing
  DocuSeal proxy for legacy rows. Missing local bytes must not trigger remote fallback
  or on-demand regeneration. Return unavailable/error, not a substitute document.
- Update list/filter conditions currently requiring `external_id` to also include
  ready local artifacts, including historical local rows. Preserve inline/attachment
  validation and audited access without public storage URLs.
- Local rows never enqueue DocuSeal create/sync/archive. Both manual signing paths
  use club-owned handover notifications; electronic local emails must not claim a
  DocuSeal signing link/session. File delivery remains staff-managed in this slice:
  existing staff download plus agreed external handover, no new unsigned-parent
  download endpoint, email attachment, or automatic signing session.
- Parent blank raster preview uses the same versioned template and selected signing
  path, cached separately per backend/version/path. Preserve verified active-parent
  authorization and existing raster-only/no-submission contract. No personal data
  in blank cache; do not run real agreement generation from registration preview.
- No existing signed-artifact upload/replacement or lifecycle/billing semantics
  change except the local-ready precondition on explicit staff signing.

## Rendering and storage safety

Trusted versioned HTML/CSS, Django autoescaping, exact local asset mapping, no
user-controlled HTML/CSS/URLs, no remote fonts/images, no JS. WeasyPrint 70 fetcher
must fail closed on unknown resources. Review/pin font files with license and digest.
Background rendering uses the existing 60-second worker timeout; reject output over
20 MiB or 20 pages. Leave retryable state after crash. Store privately, publish file metadata atomically,
clean orphan temporary files on failure, and delete storage only after DB commit.
PII/document text never enters exception logs. Access audit uses IDs/backend/status.

## Rollout and rollback

1. Additive schema, renderer and tests with mode still legacy.
2. Staff local acceptance using synthetic data; manual eParaksts test; full final
   image scan/reachability review and any required explicit risk acceptance.
3. Explicitly switch new agreements to local; observe generation, handover, upload,
   staff signing, billing and void/amendment paths on the dev server.
4. Turning mode back to legacy affects only future agreements; existing local
   artifacts stay readable. No rollback can delete issued PDFs.
5. Retire DocuSeal only in a separately authorized operator step after inventory,
   pending-session reconciliation and verified preservation of remote historic
   documents. Preservation downloads existing bytes; never regenerates old PDFs.

No infrastructure repository changes, deployment, mass archive, DocuSeal shutdown,
browser eParaksts implementation, signature verification, or release sign-off here.

## Acceptance

New local documents render approved values/wording, are immutable and private;
concurrent retries cannot replace published bytes; old agreements remain unchanged;
paper contains no electronic signing claim; no render/upload triggers billing;
handover/signing guards work; previews/downloads remain authorized and audited;
legacy fallback still works; manual signing and final-image security evidence exist
before promotion. Sample approval alone does not satisfy these production gates.
