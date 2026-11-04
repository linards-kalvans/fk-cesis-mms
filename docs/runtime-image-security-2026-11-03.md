# Runtime image security remediation — 2026-11-03

## Status and boundaries

**Locally verified candidate, not deployed or published.** Python 3.14 is the
preferred candidate; a same-dependency Python 3.12 comparison image also passes
the image gate and runtime smoke. This is not a claim of zero vulnerabilities or
production acceptance. No commit, push, existing-environment database writes,
credential changes, or infrastructure-repository edits were performed.

Source baseline: application checkout `6137239` plus the focused uncommitted files
listed below. Pre-existing `.claude/settings.local.json` changes are excluded from
the build and were not changed. A clean CI build will have its own identity and
must pass its own gate; the local candidate digest must not be assigned to it.

## Image identities (linux/amd64 only)

| Artifact | Identity |
| --- | --- |
| Recovered baseline registry index | `ghcr.io/linards-kalvans/fk-cesis-mms@sha256:ceb4d768caea42f5eda7714df72881d9516dd7e72fc2812c42b8d90e0a1460f4` |
| Baseline platform manifest actually scanned | `ghcr.io/linards-kalvans/fk-cesis-mms@sha256:2aac195941c60f0bfefa520dbc732b125989d094dd6a1aeab09468ac3300eeeb` |
| Preferred local candidate tag | `fk-cesis-mms:security-py314` |
| Preferred local Docker image/index ID | `sha256:0f06e3f4287c5ad2bb5b692e881f6b297b4788700b0457bb746da241a2e2ccdd` |
| Preferred local platform manifest | `sha256:d46e92796204dfcf6e6cacacfae36e2604c13cb8bc86e1b201ede2e36b362673` |
| Preferred local image config | `sha256:1b3186b171ea10d3c6cf56ed71f2d666cb33fd2fd68913d9793106b29faa9d2f` |
| Python 3.12 comparison tag | `fk-cesis-mms:security-py312` |
| Comparison local Docker image/index ID | `sha256:500615b3217a87519e6c90f9f89a749056b1a607f2e3e8e50752b84a77d42535` |
| Comparison platform manifest | `sha256:68432ad2ca3d2d6085969d69cbb5b6e13035dcc02b73042159f2d80242221296` |
| Comparison image config | `sha256:3c6a6472ad81e05e8faf135196bb863ba1229b9c5fb94ebba9c229eb03b824c3` |

The recovered registry index matches the supplied abbreviated identifier, and a
fresh scan reproduces the supplied counts exactly. The original host JSON and
running-host inspection were not available: this is a scan of the recovered
artifact, not independent confirmation of what a host is running. No rebuilt
image is presented as the deployed baseline.

### Base and runtime versions

* Baseline: Python **3.12.16**, Debian **Bookworm / 12.15** (Trivy OS detection),
  SQLite runtime **3.40.1**. Its first four filesystem layers exactly match
  `python:3.12-slim-bookworm@sha256:623674a14ef93d052bb9b0de4dbf5f28eb578a35263838941cc8aa43213c1487`.
* Python 3.12 comparison uses the reviewed multi-platform index
  `python:3.12.16-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337`.
* Preferred candidate uses
  `python:3.14.10-slim-bookworm@sha256:516b51cb9db2ef061e465c803e50f64361b82cefd91e525b889b967b83e83527`;
  its amd64 base manifest is
  `sha256:47d41ea4947601fd5bc7ed6c00a7b9c1fbb936a7684873908a3c3b4e68ce3c86`.
  Runtime probe: Python **3.14.10**, Bookworm, SQLite **3.40.1**, stdlib OpenSSL
  **3.0.22**. This is the ordinary GIL-enabled build, not free-threaded Python.
* Both builder and runtime take the same digest-pinned `PYTHON_IMAGE` argument.
  Builds used `--pull`; pinning a base does not mean future rebuilds refresh it.
  Subsequent base updates require a deliberate reviewed digest change and scan.
* Builder-only uv **0.9.8** is pinned by index digest in the Dockerfile. It is
  compatible with Python 3.14 and the existing frozen lock workflow.

Python 3.14 was selected for active bugfix maintenance and support through October
2030, versus security-only Python 3.12 through October 2028. Django 6.0 supports
3.14; 3.15 is not in that compatibility table. The project minimum remains 3.12.
See the [Python lifecycle](https://devguide.python.org/versions/) and
[Django compatibility table](https://docs.djangoproject.com/en/6.0/faq/install/#what-python-version-can-i-use-with-django).
No Debian release migration was made, and the interpreter upgrade does not fix
the retained Bookworm SQLite finding.

Native versions are not interchangeable: the candidate stdlib links OpenSSL
**3.0.22**, while the cryptography wheel reports bundled OpenSSL **4.0.3**.
psycopg-binary reports libpq **18.0** (180000), and PyMuPDF reports MuPDF **1.28.2**.
The latter two packages were not upgraded. Zero fixable findings means the pinned
scanner's result, not an assertion that every bundled native implementation has
received exhaustive manual vulnerability analysis.

## Root causes and focused changes

1. Application dependency vulnerabilities, not just an OS base problem:

   | Package | Baseline | Candidate | HIGH/CRITICAL findings cleared |
   | --- | --- | --- | --- |
   | Django | 6.0.4 | 6.0.8 | CVE-2026-15307 |
   | certifi | 2026.4.22 | 2026.10.23 | GHSA-6q48-6c7w-9gw2 |
   | cryptography | 48.0.0 | 50.0.2 | CVE-2026-69247, CVE-2026-69249, GHSA-537c-gmf6-5ccf |
   | sqlparse | 0.5.5 | 0.6.0 | CVE-2026-54284, CVE-2026-59893, CVE-2026-71491 |
   | urllib3 | 2.7.0 | 2.8.0 | CVE-2026-97687, CVE-2026-97689 |

   Only these five locked package versions changed, using targeted `uv lock
   --upgrade-package` requests. `pyproject.toml` raises cryptography's minimum to
   50.0.2 because all its reported fixes require crossing the old major line.
   The application's cryptography usage is Fernet in `apps/documents/ocr.py`;
   no cryptographic format, encryption key, or application API was changed.
   A synthetic token generated by baseline cryptography decrypts successfully
   with the candidate. Existing encryption and integration tests also ran.

2. `curl` was installed only to probe `/healthz`; removing it and its otherwise
   unused dependencies clears eleven HIGH package findings:
   CVE-2026-12064, CVE-2026-6276, CVE-2026-8286, CVE-2026-8458,
   CVE-2026-8927 on **both curl and libcurl4**, plus CVE-2023-2953 on
   **libldap-2.5-0**. The replacement stdlib HTTP probe was exercised through
   Docker's actual health status, not merely a direct endpoint request.

3. `uv run ... collectstatic` implicitly reinstalled the dev group despite the
   preceding `--no-dev` sync. It now uses `.venv/bin/python` directly. Neither
   mypy nor ruff is importable in the final candidate.

4. The initial Python 3.14 image scan detected independently vendored **msgpack
   1.1.2, setuptools 70.3.0 and urllib3 2.7.0** through the base packaging tools'
   inventory, despite the application environment having patched urllib3.
   The unused system **pip and ensurepip** are removed from the final runtime,
   including their bundled inventories. This cleared five intermediate HIGH
   findings; no scanner path exclusions or vulnerability suppressions were used.
   Runtime dependency changes now require rebuilding, not installing in place.

5. `.dockerignore` excludes docs, local worktrees, graph output, local agent and
   browser state, and data mounts. These are not runtime inputs. Required source,
   templates, static assets, native libraries and private-storage directories
   remain. UID/GID **10001**, web/worker commands and mount paths are unchanged.

### Exact changed files

* `Dockerfile`, `.dockerignore`, `compose.yaml` (healthcheck comment only)
* `pyproject.toml`, `uv.lock`
* `.github/workflows/ci.yml`, `scripts/scan-runtime-image.sh`
* `tests/deployment/test_runtime_security_contract.py`
* `README.md`, `AGENTS.md`, `docs/runtime-contract.md`, `docs/milestones.md`, this report

Graphify's generated graph was refreshed using its AST-only update. No business
logic, models, migrations, providers or deployment automation were modified.

## Comparable before/after evidence

Scanner: **Trivy 0.76.1**, container
`aquasec/trivy:0.76.1@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c`.

One database was downloaded and reused with `--skip-db-update` for all comparison
scans; the original recovered image was also rescanned through the new gate.

* DB schema: **2**
* Updated: **2026-11-03 01:30:30.031564361 UTC**
* Downloaded: **2026-11-03 06:22:26.754712976 UTC**
* Next update: **2026-11-04 01:30:30.031564131 UTC**
* `trivy.db` SHA-256:
  `168e781d1371a3bc2bec37ca441e11c91202bce2c4eacefd95c6ed44ce7b5b7b`

| Final runtime artifact | CRITICAL | HIGH | MEDIUM | LOW | UNKNOWN | Fixable HIGH/CRITICAL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Recovered baseline | 3 | 56 | 153 | 163 | 8 | 10 |
| Patched Python 3.12 | 2 | 36 | 117 | 105 | 8 | 0 |
| Preferred Python 3.14 | 2 | 36 | 105 | 89 | 8 | 0 |

Against baseline, the preferred candidate clears **21 package/advisory pairs**
(one CRITICAL, twenty HIGH), retains **38**, and introduces **zero** new
HIGH/CRITICAL pairs. Counts are package findings, not unique CVE counts. Python
3.14's lower MEDIUM/LOW count is an observation, not the justification for the
interpreter upgrade.

### Sanitized critical attribution and applicability

| ID | Package / type / path | Installed | Fixed version | Scan status | Severity source |
| --- | --- | --- | --- | --- | --- |
| CVE-2025-7458 | libsqlite3-0 / debian / OS package DB | 3.40.1-2+deb12u2 | None reported for Bookworm | affected | NVD |
| CVE-2023-45853 | zlib1g / debian / OS package DB | 1:1.2.13.dfsg-1 | None reported for Bookworm zlib | will_not_fix | NVD |
| GHSA-6q48-6c7w-9gw2 | certifi / python-pkg / app/.venv/lib/python3.12/site-packages/certifi-2026.4.22.dist-info/METADATA | 2026.4.22 | 2026.10.18 (scanner); upstream recommends >=2026.10.19 | fixed | GHSA |

* [SQLite distribution advisory](https://security-tracker.debian.org/tracker/CVE-2025-7458):
  Bookworm remains affected; the advisory describes crafted arbitrary SQL as an
  exploitation prerequisite. Production uses PostgreSQL, and a source search
  found only a constant `SELECT 1` cursor execution, not an arbitrary-SQL API.
  This reduces the apparent application exposure but is not proof of immunity.
  SQLite is retained for supported development/management functionality.
* [MiniZip distribution advisory](https://security-tracker.debian.org/tracker/CVE-2023-45853):
  Bookworm zlib does **not** build the vulnerable `contrib/minizip` binary code.
  This is an applicability distinction, not an upstream-version comparison.
  No separate minizip/pyminizip package appeared in the final inventory. This does
  not constitute exhaustive disassembly of every bundled native dependency.
  The finding remains visible; no ignore or VEX waiver was added.
* [certifi upstream advisory](https://github.com/advisories/GHSA-6q48-6c7w-9gw2):
  the vulnerable application copy is from pip, used by Requests. Updating the
  Debian CA package alone would not replace it. Candidate certifi is 2026.10.23.

### Every remaining HIGH/CRITICAL package/advisory group

All rows below are Debian packages, have **no fixed version reported in this DB
for Bookworm**, and remain in the unfiltered report. No exception was created.
Groups expand to the 38 package/advisory pairs reported above.

| Packages (installed versions) | Advisory IDs | Severity / scan status |
| --- | --- | --- |
| bsdutils (1:2.38.1-5+deb12u3); libblkid1, libmount1, libsmartcols1, libuuid1, mount, util-linux, util-linux-extra (2.38.1-5+deb12u3) | CVE-2026-53613, CVE-2026-53615, CVE-2026-78410 on each package | HIGH / affected |
| gzip (1.12-1) | CVE-2026-41992 | HIGH / fix_deferred |
| libacl1 (2.3.1-3) | CVE-2026-54369 | HIGH / fix_deferred |
| libncursesw6, libtinfo6, ncurses-base, ncurses-bin (6.4-4) | CVE-2025-69720 on each package | HIGH / affected |
| libsqlite3-0 (3.40.1-2+deb12u2) | CVE-2025-7458 | CRITICAL / affected |
| libsqlite3-0 (3.40.1-2+deb12u2) | CVE-2026-11822, CVE-2026-11824 | HIGH / fix_deferred |
| libsqlite3-0 (3.40.1-2+deb12u2) | CVE-2026-119373 | HIGH / affected |
| libsystemd0, libudev1 (252.39-1~deb12u2) | CVE-2026-16742 on each package | HIGH / fix_deferred |
| perl-base (5.36.0-7+deb12u4) | CVE-2026-9538 | HIGH / fix_deferred |
| zlib1g (1:1.2.13.dfsg-1) | CVE-2023-45853 | CRITICAL / will_not_fix |

NVD is the supplied severity source for gzip, ncurses, perl and the two critical
rows. Other rows use Debian's feed; where Trivy leaves `SeveritySource` empty,
the sanitized JSON preserves null rather than inventing a source.

Remaining-risk review is assigned operationally to the MMS maintainer, with next
review **2026-11-10**, or sooner if a fix becomes available. This is a follow-up
recommendation, not a signed risk acceptance or an exclusion from CI. If release
policy requires removing all critical findings rather than gating fixable ones,
this candidate is **not accepted for release**; Bookworm/SQLite migration scope
must be revisited explicitly rather than hidden by scanner filtering.

## Verification actually performed

Both final images:

* Built from the pinned bases using the frozen patched lock; scanned the **final
  runtime**, not the builder or just the source tree.
* Fresh, disposable PostgreSQL **18** database, isolated internal Docker network;
  no existing data mount or project `.env` supplied; resources removed afterward.
* `manage.py check`, `migrate --noinput`, `makemigrations --check --dry-run` passed.
* Actual Gunicorn startup, actual Docker healthcheck to healthy, and `/register/`
  HTTP 200 with expected parent UI markup.
* Actual separate django-q2 cluster completed a queued `builtins.sum` task with
  result **6**. Python 3.14 used its default **forkserver** start method.
* PyMuPDF generated/reopened/rasterized a synthetic PDF; psycopg imported and
  connected during migrations; baseline-created synthetic Fernet token decrypted.
* mypy/ruff absent from the runtime. No pip/ensurepip required at startup.

Preferred Python **3.14.10** final image:

* Full PostgreSQL pytest invocation: **2918 passed, 18 skipped**, one pytest-cache
  permission warning from read-only mounted tests. The 18 skips are Node harness
  tests, because Node is intentionally absent from the production image.
* Those exact Node-dependent tests ran separately with the patched dependencies,
  host Python **3.14.4** and Node: **18 passed**, no skips. This is supplementary
  coverage, not a claim that Node was installed or tested in the runtime image.
* Full ruff passed; mypy passed for **514** files (existing untyped-body notes).
* `bash -n` and `git diff --check` passed; four new security contract tests passed
  within the full image suite.
* Gate behavior exercised: vulnerable baseline exits **1**; both patched images
  exit **0**. The initial 3.14 candidate correctly failed on its bundled packaging
  dependencies before their removal. A deliberately empty DB cache with updates
  disabled also produces a nonzero scanner execution error (fails closed).
* After the final documentation edits, deployment/security contract tests were
  rerun: **42 passed**; full ruff/mypy and diff/shell syntax checks passed again.

Two initial full-suite attempts failed because the verification harness first
disabled dotenv loading for tests that intentionally load synthetic `.env` files,
and left django-q synchronous mode unset until after image-level settings caused
early plugin initialization. These were test-harness settings, not application
fixes: the final test process explicitly sets `Q_CLUSTER_SYNC=1` and allows its
synthetic dotenv fixtures. Real worker smoke uses `Q_CLUSTER_SYNC=false`.

OCR, Invoice Ninja and DocuSeal coverage is **stubbed/mocked**, not provider E2E.
Runtime networks blocked outbound traffic, email used locmem, billing auto-send
and analytics were disabled, and scheduler rows were removed only in the fresh
smoke database before starting the worker. No live emails, billing calls or
webhooks were sent. No physical-browser or deployed-environment acceptance was
performed. The 3.12 comparison ran runtime smoke, not a second full pytest suite.

## CI protection and reproduction

The trusted dev/main build job now builds and loads one final **linux/amd64**
image, runs `scripts/scan-runtime-image.sh`, then logs into GHCR and tags/pushes
that exact local image without rebuilding it. PR lint/tests have read-only
permissions; the publishing job does not run on PR events. Registry credentials
are not passed to the scanner, which receives a saved image archive, not the
Docker socket. Scanner, JSON validation or gate errors fail the job.

The scanner container is pinned by digest. Its first scan is unfiltered, with no
repository ignore file or config. Full reports, package/version/status/source
HIGH/CRITICAL tables, summaries, image ID, scanner/DB timestamps and DB hash are
retained as CI artifacts for 30 days, including on a failed gate. The gate then
fails on HIGH/CRITICAL findings with a nonempty fixed version. There are **no
vulnerability exceptions**, no global suppression of unfixed findings, no added
schedule, and no deployment webhook. GitHub execution/publication remains pending.

```bash
docker build --pull --platform linux/amd64 -t fk-cesis-mms:security-py314 .
bash scripts/scan-runtime-image.sh fk-cesis-mms:security-py314 /tmp/mms-scan

# Only when deliberately comparing against an already downloaded DB snapshot:
TRIVY_SKIP_DB_UPDATE=true bash scripts/scan-runtime-image.sh \
  fk-cesis-mms:security-py314 /tmp/mms-scan /path/to/retained-trivy-cache
```

Private local evidence: `/tmp/opencode/mms-image-security/`, with `baseline.json`,
`baseline-gate/`, `py312/`, `py314/`, native/smoke logs and final pytest log.
`high-critical.json` in each scan directory is the sanitized finding table:
ID, package, path, type, installed/fixed versions, status, severity and sources.
Raw image inspection, environment files and host reports must not be published.

## Deployment handoff — no rollout performed

**Both local web and local qcluster use the same exact verified image ID:**

`sha256:0f06e3f4287c5ad2bb5b692e881f6b297b4788700b0457bb746da241a2e2ccdd`

This identifies a locally available image on the verification Docker engine,
**not a published GHCR pull reference**. No candidate registry digest exists yet.
Publication must follow repository dev/main release permissions, after explicit
authorization to commit/push. A CI rebuild must record its own scanned digest and
pass acceptance; never deploy a guessed `ghcr.io/...@<local-index-id>` reference.

The deployment repository currently concatenates repository and tag variables.
Its owner must coordinate full `repository@sha256:...` reference support for
**both web and qcluster**, preserving the existing tag fallback if desired. This
application task did not edit that repository or assume it already accepts
digests. Keep the worker's HTTP healthcheck disabled.

No schema migration, data rewrite, new secret, port, volume or UID/GID change is
introduced by this remediation. Normal application migrations still run at web
startup and must follow the deployment owner's release procedure. Cryptography
crosses a major version with compatibility checked as described above; preserve
the existing encryption key. Python 3.14 changes process-start semantics, and
both processes must be updated together. Do not install packages into the live
runtime; its installers have intentionally been removed.

Rollback: retain the previous accepted image reference and deploy it to both
processes together, using the usual backup/restore and migration-compatibility
checks. This change introduces no migration requiring reversal. Rolling back to
the original vulnerable image restores its known dependency findings. The 3.12
comparison is a locally smoke-tested compatibility fallback, not a separately
published or fully pytest-verified production release.
