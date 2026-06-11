# LAN Acceptance Test — P6 Guardian Identity, Slice C

**Date:** 2026-06-11
**Build under test:** `dev` branch (locked-profile UX + admin-initiated email change; code-only, no migrations).
**Scope:** Closes design-spec acceptance items **#4** (locked profile + propagation) and **#6** (admin email change). Functional correctness of the underlying read-through is covered by the suite (1169 passed) + Slices A/B LAN acceptance. This checklist covers only the genuinely new, browser-observable behavior.

## How to run

Local `uv` instance bound to all interfaces + qcluster, console email backend so OTP codes appear in server logs:

```
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend uv run python manage.py runserver 0.0.0.0:8000 --noreload
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend uv run python manage.py qcluster
```

Drive via browser against `http://192.168.3.245:8000`. Staff/admin checks use Django admin (`/admin/`).

## Checks

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| L1 | Lock + unlock | As a returning parent (one prior populated registration), open a new application workspace → guardian step | Guardian name / PID / phone / address render **read-only**; the verified email is **read-only**. Clicking **"Rediģēt vecāka datus"** makes the four profile fields editable (email stays read-only); the toggle hides. Edit the name + save (auto-save). | |
| L2 | Propagation | After the L1 edit, open the parent's **other** application workspace + `/portal/` | Both show the **edited** guardian value (one shared `Guardian`). | |
| L3 | First registration unlocked | As a brand-new parent, start the first application → guardian step | Guardian profile fields are **editable**, no unlock toggle; verified email is read-only. | |
| L4 | Admin email change | Django admin → Parent accounts → change a parent's email and save. Then check admin → Guardians, and the parent's application display. Also try setting an email already owned by another account. | The change saves; the linked **Guardian.email** updates to match; the parent's applications display the **new** verified email (read-through). Setting an email owned by another account is **rejected** (admin unique validation). | |

## Explicitly NOT re-tested (unchanged by Slice C)

- Dedup (one Guardian / two members), sibling discount, Invoice Ninja one-client-per-parent — billing untouched; covered by Slice A's LAN acceptance.
- Read-through display on portal / workspace / admin / DocuSeal payload — covered by Slice B1/B2 acceptance + the suite.
- Parent registration flow, OCR, document upload, wizard gating — unchanged.

## Results — run YYYY-MM-DD

PENDING — to be filled in during the LAN acceptance session.

## Recording results

Record pass/fail per row + build SHA here and add the sign-off line to the AGENTS.md Slice C entry. Treat any surprise as a real finding (the live-validation lesson from P3 / P6 / Slice A).
