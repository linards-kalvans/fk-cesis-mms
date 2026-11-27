# WeasyPrint Slice A — local verification, 2026-11-26

## Status and scope

Slice A is implemented and reviewed in the linked worktree based on `da0d414`.
This record captures local verification, not deployment or activation readiness,
authenticated browser acceptance, or release acceptance. No deployment or
activation is authorized by this record. The existing DocuSeal backend remains
the default; local generation must be explicitly selected for new agreements.
Historical rows retain their backend, and shadow PDFs remain comparison-only.

Staff explicitly prepare an immutable private local PDF from a frozen snapshot.
Paper and eParaksts handover are manual; upload alone does not confirm signing or
establish signature validity. Existing signing and billing guards remain in
force. The operator workflow, failure handling and cutoff conditions are described
in [local agreement PDFs](../local-agreement-pdfs.md). Slice B historical
preservation and Slice C integration disable are not delivered by this record.

## Verification evidence

- Isolated PostgreSQL 18 baseline: **2989 passed**, 1253 warnings.
- Final isolated PostgreSQL 18 suite: **3273 passed**, zero failures or skips,
  1364 warnings, in 341.79 seconds.
- Targeted PostgreSQL concurrency run: **4 passed**, 95 deselected, 2 warnings.
- Full ruff, mypy (532 files), `makemigrations --check`, and tracked diff checks
  were clean.
- Automated Node checks and headless Chromium with stubbed fetch exercised both
  paths. These are not authenticated browser or manual signing acceptance.
- Independent task and domain/security reviews approved the implementation after
  fixes. Review approval is not security risk acceptance or release approval.

These results are reported implementation evidence, not a test rerun for this
documentation update. They do not establish behavior in a deployed environment.

## Open gates and follow-up

Before any proposed activation, the following remain open:

1. Build and scan the exact release image; assess findings and obtain any required
   security risk acceptance. Verify runtime compatibility, non-root operation,
   and encryption in that exact image. Earlier image evidence does not establish
   these properties for this source.
2. Obtain an authorized blank source, compare both document paths against it, and
   obtain the club document owner's approval. Template development and automated
   rendering do not substitute for legal or owner approval.
3. Complete authenticated browser acceptance and manual paper and eParaksts
   handover, upload, and confirmation acceptance using authorized representative
   data. Stubbed browser checks are not evidence of those workflows in production.
4. Before any separately authorized DocuSeal cutoff, inventory legacy records and
   in-flight work; obtain data-owner dispositions for ambiguous no-ID cases;
   refresh the inventory; quiesce old web and worker processes and reconcile
   queued, running, retrying, and uncertain jobs. Obtain the required deployment,
   activation, and cutoff approvals. An absent external ID does not prove that a
   remote submission does not exist.

Additional follow-up remains for a minor UI affordance mismatch, recovery from
SMTP notice delivery failure, and operational reconciliation of stuck or failed
snapshots and orphan private files. Treat snapshots and files as sensitive; do not
delete uncertain files without an authorized, verified reconciliation. No new
retention period or automatic purge is established here.

No staging, commit, live operation, or changes to the original checkout were
performed for this documentation update.
