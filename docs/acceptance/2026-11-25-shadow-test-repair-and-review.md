# Agreement PDF shadow — test repair and independent review, 2026-11-25

## Result and scope

The earlier real-clock PostgreSQL run recorded 26 failures and 55 errors. All 81 were caused by date-fragile test fixtures and were repaired using deterministic test data. No production billing or signing guards were changed, and no tests were dropped or skipped. The final real-clock PostgreSQL gate, without a historical-clock plugin, recorded **2989 tests, zero failures, errors or skips**, in 325.914 seconds at `2026-11-25T14:55:26+02:00`: `/tmp/opencode/fk-shadow-resume/full-final.xml`.

The original suite had 2964 cases. All original test-name groups and parameter counts were preserved; one raw PDF parameter ID is nondeterministic, so the comparison normalized that group. The final suite has 25 additional cases. The earlier `full-fixed.xml` recorded 2978 passes before the signed-document source-fetch follow-up; it is not the final gate.

## Failure diagnosis

On November 25, the day-20 cutoff advances default billing selection into December; the configured December skip advances it to January 2027. For the 2026-start plan, the year guard correctly leaves automatic plan selection empty. Tests for unrelated lifecycle, signing and access behavior had assumed a selected plan, producing failures and setup errors. Fixtures now explicitly assign valid `2026-09` billing intent where preselection is not under test. Two genuine derivation tests pin only the relevant date. Production cutoff, year and signing rules remain intact.

The original 81 affected cases, by module, were:

| Module | Failures and errors |
| --- | ---: |
| `tests/registrations/test_admin_agreement_lifecycle.py` | 26 |
| `tests/agreements/test_lifecycle_services.py` | 15 |
| `tests/admin_hub/test_hub_agreement.py` | 12 |
| `tests/agreements/test_agreement_services.py` | 5 |
| `tests/registrations/test_parent_invoice_visibility.py` | 5 |
| `tests/registrations/test_parent_lifecycle_history.py` | 5 |
| `tests/registrations/test_parent_invoice_proxy.py` | 4 |
| `tests/admin_hub/test_family_hub_actions.py` | 2 |
| `tests/admin_hub/test_family_hub_billing.py` | 1 |
| `tests/admin_hub/test_family_hub_page.py` | 1 |
| `tests/agreements/test_audit_agreement_events.py` | 1 |
| `tests/agreements/test_billing_plan_assignment.py` | 1 |
| `tests/registrations/test_admin_review_agreement_ui.py` | 1 |
| `tests/registrations/test_agreement_admin_polish.py` | 1 |
| `tests/registrations/test_agreement_visibility_parent_surfaces.py` | 1 |
| **Total** | **81** |

## Verification evidence

All paths below are under `/tmp/opencode/fk-shadow-resume/` and are local, potentially ephemeral artifacts.

| Evidence | Result |
| --- | --- |
| `fixture-repair.xml` | 226 focused fixture-repair tests passed |
| Expanded focused gate | 631 passed |
| `review-fixes-green-final.xml` | 42 shadow tests passed |
| `review-fetch-green.xml` | 76 provider and shadow tests passed |
| `full-final.xml` | 2989 passed; 0 failures, errors or skips; 325.914 s |
| `final-ruff.log` | Passed |
| `final-mypy.log` | Passed, 523 source files; existing annotation notes |
| `final-migrations.log` | No changes detected |
| `final-whitespace.log` | Empty for scope `. ':!spikes'` |

The [earlier resume record](2026-11-25-agreement-pdf-shadow-resume.md) retains the original failed run and its diagnostics. Its image smoke and the 2026-11-18 image/scan evidence precede the latest source changes and do not verify the current source. No new exact-source image build or scan was performed. Earlier scan and source-PDF artifacts are missing; native security risk remains open.

## Review fixes and document-fetch boundary

- Inline local and primary comparison PDFs use `SAMEORIGIN` framing; attachments retain the default `DENY` policy.
- The renderer translates the specific WeasyPrint `FatalURLFetchingError` into a normal `RuntimeError` so the worker can persist a failure; it does not catch `BaseException` generally. Native HarfBuzz version is recorded lazily in renderer provenance.
- Primary comparison fetches require the stored nonsecret provider-mode and canonical API-base fingerprint to match the current configuration. Missing or mismatched identity refuses the fetch; API keys, userinfo and query strings are not stored. The real enqueue identity path and positive ready/failed UI states have regression coverage.
- The existing provider-supplied original download path was also hardened. `list_submission_documents` and `stream_submission_document` disable redirects and reject 3xx responses; the selected blob must have the configured API origin before credentials are sent. Metadata and error responses are closed, and admin failures use generic 404 messages without private URLs.

The last change affects both the existing primary admin path and the shadow original stream: **split-origin signed/original blobs fail closed**. `DOCUSEAL_TEMPLATE_ALLOWED_ORIGINS` authorizes blank-template origins only; it does not authorize signed blobs. No new signed-blob allowlist exists. Deployments returning a public blob URL on an origin different from the internal API need an explicit future origin policy and provider acceptance. Agreement lifecycle, sending, mail and billing behavior remain unchanged; document fetching is intentionally tighter.

## Independent review and deferred findings

The reviewer configuration at `/home/linards/.config/opencode/agents/code-reviewer.md` uses `opencode-go/deepseek-v4.1-flash`. Three independent read-only calls succeeded:

1. `ses_ded73ab56ffeOX8kOO6SHu4MA5`: **APPROVED**, with findings.
2. `ses_ded4df4b3ffeXlTxQtVzMDbJgI`: **APPROVED**, verifying fixture repairs and four fixes.
3. `ses_ded398ba8ffezHmOJ473DOtSlo`: **APPROVED** for source-fetch changes, with deferred minor findings.

There was no authentication failure, authentication change or recovery in this turn. Approval is code review approval, not independent security risk acceptance, deployment authorization, activation, or provider/browser acceptance.

Deferred non-blocking findings:

1. The pre-existing `fetch_template_documents` metadata 3xx parsing and response-closure issue is outside the signed-document scope.
2. A malformed URL or port can raise `ValueError` from the existing `_template_document_origin` helper outside the expected `ConfigError` mapping in the original admin document path. It fails closed but may return 500.
3. There is no explicit regression test proving the template allowlist cannot authorize a signed blob. The code does not use that allowlist for signed blobs, and untrusted-origin rejection is tested.
4. On provider identity mismatch, the primary comparison iframe remains visible and returns 404 rather than being hidden with an explanation.

Earlier review suggested repinning the Docker base and its commented contract test. Prior explicit user commits `9bf076b` and `1c9b496` intentionally unpinned them; that decision was not reverted or reclassified as a new task defect. Creating failed rows when provenance is unavailable remains deferred: the current best-effort warning preserves primary success.

## Exact changed source and test files in this turn

Fixture repair (14 files):

```text
tests/support.py
tests/admin_hub/conftest.py
tests/admin_hub/test_hub_agreement.py
tests/agreements/test_agreement_services.py
tests/agreements/test_audit_agreement_events.py
tests/agreements/test_billing_plan_assignment.py
tests/agreements/test_lifecycle_services.py
tests/registrations/test_admin_agreement_lifecycle.py
tests/registrations/test_admin_review_agreement_ui.py
tests/registrations/test_agreement_admin_polish.py
tests/registrations/test_agreement_visibility_parent_surfaces.py
tests/registrations/test_parent_invoice_proxy.py
tests/registrations/test_parent_invoice_visibility.py
tests/registrations/test_parent_lifecycle_history.py
```

Additional regression files:

```text
tests/agreements/test_pdf_shadow.py
tests/integrations/test_docuseal_provider.py
```

Production review-fix files:

```text
apps/agreements/pdf_rendering.py
apps/agreements/shadow.py
apps/agreements/shadow_admin.py
apps/integrations/docuseal.py
```

## Outstanding gates and safety boundaries

Shadowing remains off by default. Root `.env` and database were untouched. No worktree, commit, push, deployment, live provider or mail call, activation or backfill was performed. Existing parent-owned `spikes/` were preserved. Security risk acceptance, exact-current-image build and scan, provider/browser acceptance and authorized activation remain open; no release sign-off is claimed.
