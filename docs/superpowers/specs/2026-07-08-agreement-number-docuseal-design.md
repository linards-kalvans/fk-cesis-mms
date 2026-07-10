# Agreement number for DocuSeal payload

Date: 2026-07-08
Status: Approved for planning

## Problem

DocuSeal agreement submissions need a stable `agreement_number` field. The number must identify the generated agreement, not the DocuSeal submission attempt, so retries and sync actions must not change it.

## Goals

- Generate an immutable agreement number for every `Agreement` row.
- Use format `{PREFIX}-{YEAR}-{SEQUENCE}`.
- Read `PREFIX` from config with default `FKC`.
- Use the calendar year when the agreement is generated.
- Use a global sequence per calendar year across all agreements.
- Left-pad sequence to 3 digits through `999`; allow `1000+` without failure.
- Send the stored number to DocuSeal as readonly field `agreement_number`.
- Backfill existing agreements.

## Non-goals

- No admin UI for editing agreement numbers.
- No historical renumbering when `AGREEMENT_NUMBER_PREFIX` changes later.
- No separate yearly sequence table unless concurrency needs exceed the current low-volume agreement workflow.
- No parent-portal display unless an existing screen already naturally renders all agreement fields.

## Design decisions

### Store number on `Agreement`

Add `Agreement.agreement_number` as a unique stored string.

Why: agreement number must be immutable, audit-friendly, available for paper/electronic agreements, and stable across DocuSeal retries. Computing it at DocuSeal send time would make retry behavior fragile and leave paper agreements without a canonical number.

### Number format

Format is:

```text
{AGREEMENT_NUMBER_PREFIX}-{generated_year}-{sequence:03d}
```

Examples:

```text
FKC-2026-001
FKC-2026-999
FKC-2026-1000
```

The sequence is zero-padded to at least 3 digits. If a year exceeds 999 agreements, the sequence expands to 4+ digits instead of failing.

### Config

Add setting:

```python
AGREEMENT_NUMBER_PREFIX = os.environ.get("AGREEMENT_NUMBER_PREFIX") or "FKC"
```

Runtime generation uses this setting. Historical rows keep whatever prefix they were assigned when generated.

### Generation point

Generate the number when `create_agreement_for_member()` creates a new `Agreement` row. Reused current agreements keep their existing number.

Use `generated_at.year` as the year component. Existing `generated_at` remains the source of truth for when the agreement was generated.

### Concurrency model

Keep this simple: no sequence table.

Generation runs in `transaction.atomic()` and assigns the next sequence for the target year. `agreement_number` has a unique constraint. If a concurrent creation races and hits a duplicate number, retry number assignment in a small bounded loop.

Why: agreement generation is low-volume staff/admin workflow. A dedicated sequence table is more code and schema for little benefit now. The unique constraint is the real safety net.

### Backfill

Add migration that assigns agreement numbers to existing rows.

Rules:

- Use prefix `FKC` in the migration, not runtime env, so history is deterministic.
- Group by `generated_at.year`.
- Order within year by `generated_at`, then `id`.
- Assign sequence starting at 1 per year.

After backfill, enforce uniqueness on `agreement_number`.

### DocuSeal payload

Update `apps/integrations/docuseal.py::_build_field_payload()` to include:

```python
"agreement_number": agreement.agreement_number
```

DocuSeal submission already converts field payload entries into readonly fields. `agreement_number` follows that existing path.

If an agreement somehow has a blank number, the provider should fail loud rather than submit incomplete legal metadata. Normal service and migration paths should prevent blank values.

## Data flow

```text
approve/regenerate/material amendment
        |
        v
create_agreement_for_member()
        |
        v
Agreement(generated_at, agreement_number)
        |
        v
mark_agreement_sent()
        |
        v
create_agreement_submission job
        |
        v
DocuSeal payload includes readonly agreement_number
```

## Acceptance criteria

1. Creating a new agreement stores `agreement_number` like `FKC-2026-001`.
2. Sequence is global per generated calendar year, across all members.
3. Sequence pads to 3 digits through `999` and expands to `1000` if needed.
4. Existing agreements are backfilled deterministically by `generated_at`, `id` within year.
5. `AGREEMENT_NUMBER_PREFIX` controls newly generated numbers and defaults to `FKC`.
6. Re-sending/retrying DocuSeal does not change `agreement_number`.
7. DocuSeal submission payload includes readonly field `agreement_number`.
8. Duplicate number races are prevented by DB uniqueness and bounded retry.

## Test strategy

- Model/service tests for number generation on new agreement creation.
- Service tests for idempotent current-agreement reuse preserving existing number.
- Prefix override test with `override_settings(AGREEMENT_NUMBER_PREFIX="TEST")`.
- Sequence formatting tests for `001`, `999`, `1000`.
- Migration/backfill test using the repo's existing historical migration-test pattern; if no reusable pattern exists, add one focused migration test for this migration only.
- DocuSeal provider payload test asserting `agreement_number` appears in submitter readonly fields.
- Concurrency can be covered by unique constraint + retry unit test using a forced duplicate path; no heavy threaded integration test.

## Documentation scope

- Add env setting to `.env.example` if agreement settings are listed there.
- Update project status docs only if milestone tracker needs this feature recorded after implementation.
