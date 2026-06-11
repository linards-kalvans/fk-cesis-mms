# LAN Acceptance Test — P6 Guardian Identity, Slices B1 + B2

**Date:** 2026-06-11
**Build under test:** `dev` branch through `cf9bad4` (B1 read-through + B2 column drop, migration `registrations/0010`).
**Scope:** B1/B2 are **internal refactors** — guardian data displays/persists exactly as before, now sourced from the `Guardian`/`ParentAccount` instead of the dropped `guardian_*` columns. Functional correctness is covered by the test suite (1149 passed) + Slice A's LAN acceptance. This checklist covers only what is genuinely new or deploy-sensitive.

## Most important — deploy check (not a browser test)

**B2 migration `0010` is lossy on pre-existing data.** It drops the five `guardian_*` columns with **no data migration**. Rows created before B1 landed hold guardian data only in those columns (their `Guardian` profile was never populated), so after `0010` runs the read accessors return `""` — that data is gone. The design assumed a **fresh-start wipe** at cutover, and the test DB is fresh SQLite so tests cannot surface this.

| # | Check | How | Result |
|---|---|---|---|
| D1 | `:dev` Postgres state before deploy | Confirm the `:dev` DB was wiped at the guardian-identity cutover, OR that any pre-B1 application rows are disposable test data | |
| D2 | Migration `0010` applies cleanly on the deployed Postgres | After the `:dev` auto-pull, `manage.py showmigrations registrations` shows `0010` applied; the `web`/`qcluster` containers start healthy; `/healthz` 200 | |
| D3 | Post-migration spot check | In Django admin on `:dev`, open a couple of applications + guardians — guardian name/email/phone/address render (non-empty for rows created after B1) | |

## New observable behavior — propagation (browser)

| # | Scenario | Steps | Expected | Result |
|---|---|---|---|---|
| P1 | Guardian edit propagates across a parent's applications | As a verified parent with **two** applications (two children), edit a guardian field (e.g. name/phone) on application A and save; open application B's workspace and `/portal/` | Application B shows the **edited** guardian value (both read through the one shared `Guardian`) | |
| P2 | Propagation into admin + agreement views | In admin review detail for both children, and on each child's agreement display | Both reflect the edited guardian value | |

## Repoint spot-checks (browser)

| # | Check | Steps | Expected | Result |
|---|---|---|---|---|
| R1 | Admin search by parent email | Django admin → Registration applications → search the parent's email | The parent's applications are found (search now uses `parent_account__email`) | |
| R2 | Admin search by guardian name | Same, search the guardian's surname | Found (search now uses `guardian__full_name`) | |
| R3 | No display regression | Walk `/register/` → verify → `/portal/` → workspace; and an admin review detail | Guardian name/email/phone/address render correctly everywhere — identical to pre-B1/B2 | |

## Explicitly NOT re-tested (unchanged by B1/B2)

- Parent registration flow, OCR, document upload, wizard gating — unchanged; covered by Slice A acceptance + tests.
- Guardian dedup (one guardian / two members), sibling discount (€300/€150), Invoice Ninja one-client-per-parent — billing is untouched by B1/B2; covered by Slice A's LAN acceptance.
- Unverified/claimed-email draft guardian persistence — intentionally retired in B2 (drafts hold only `claimed_email`); not reachable from the live UI (all registration is verified-first), so nothing to test in the browser.

## Recording results

Record pass/fail per row + the build SHA in `AGENTS.md` under the Slice B2 entry. Treat any surprise as a real finding (the live-validation lesson from P3/P6/Slice A).
