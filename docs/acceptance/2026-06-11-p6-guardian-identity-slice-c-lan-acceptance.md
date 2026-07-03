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
| L1 | Lock + unlock | As a returning parent (one prior populated registration), open a new application workspace → guardian step | Guardian name / PID / phone / address render **read-only**; the verified email is **read-only**. Clicking **"Rediģēt vecāka datus"** makes the four profile fields editable (email stays read-only); the toggle hides. Edit the name + save (auto-save). | ✅ PASS |
| L2 | Propagation | After the L1 edit, open the parent's **other** application workspace + `/portal/` | Both show the **edited** guardian value (one shared `Guardian`). | ✅ PASS (sibling workspace + portal card) |
| L3 | First registration unlocked | As a brand-new parent, start the first application → guardian step | Guardian profile fields are **editable**, no unlock toggle; verified email is read-only. | ✅ PASS |
| L4 | Admin email change | Django admin → Parent accounts → change a parent's email and save. Then check admin → Guardians, and the parent's application display. Also try setting an email already owned by another account. | The change saves; the linked **Guardian.email** updates to match; the parent's applications display the **new** verified email (read-through). Setting an email owned by another account is **rejected** (admin unique validation). | ✅ PASS |

## Explicitly NOT re-tested (unchanged by Slice C)

- Dedup (one Guardian / two members), sibling discount, Invoice Ninja one-client-per-parent — billing untouched; covered by Slice A's LAN acceptance.
- Read-through display on portal / workspace / admin / DocuSeal payload — covered by Slice B1/B2 acceptance + the suite.
- Parent registration flow, OCR, document upload, wizard gating — unchanged.

## Results — run 2026-06-11 (build `dev` @ `1dd1a93`, local `uv` instance, SQLite, stub OCR, console email)

Driven via Playwright against `http://192.168.3.245:8000`. Magic-link login per parent; Django admin login as a staff superuser for L4. Seed: parent A `returning@example.com` with a populated `Guardian` ("Anna Ozola") + two draft apps (49, 50); parent B `fresh@example.com` with an empty guardian + one draft app (51); `other@example.com` for the collision; staff superuser.

| # | Result | Evidence |
|---|--------|----------|
| L1 | ✅ PASS | App 49 guardian step: all four profile inputs `readonly=true` and prefilled ("Anna Ozola" / "010180-12345" / "+37120000001" / "Rīgas iela 1, Cēsis"); email `readonly=true`; toggle present, label "Rediģēt vecāka datus", note "Vecāka dati ir aizpildīti no Jūsu profila. Lai labotu, nospiediet pogu." After clicking the toggle: the four profile fields `readonly=false`, **email stays `readonly=true`**, toggle hidden. |
| L2 | ✅ PASS | After unlocking app 49, edited name→"Anna Atjaunota" + phone→"+37129999999" and saved via the auto-save AJAX endpoint (200, `saved_at`). App **50** (sibling "Bērns Divi") workspace then shows guardian name "Anna Atjaunota" + phone "+37129999999" — propagated through the shared `Guardian` FK without touching app 50. (**Correction, 2026-06-12:** the `/portal/` *does* surface the guardian name — it is each application card's title (`.fk-app-name`), confirmed rendered + visible. The earlier "portal is member-centric" note here and in the B1/B2 record was an `innerText` measurement artifact, not a real gap.) |
| L3 | ✅ PASS | App 51 (fresh parent, empty guardian, member "Jauns Bērns"): four profile fields `readonly=false`, **no** unlock toggle; email `readonly=true`. |
| L4 | ✅ PASS | Admin changed pk 25 email `returning@example.com`→`returning2@example.com`: afterward `ParentAccount.email`, `Guardian.email` mirror, and `RegistrationApplication(49).guardian_contact_email` all read `returning2@example.com`. Attempting to set pk 25 email to the already-owned `other@example.com` was **rejected** with the form error "Parent account with this Email already exists." (clean validation, **no 500**); the DB was unchanged (`returning2@example.com` retained; `other@example.com` still owned by pk 27). |

**Slice C LAN acceptance: COMPLETE (signed off 2026-06-11).** All four checks pass. Local SQLite test DB was restored to its pre-acceptance state afterward; the deployed `:dev` (Postgres) requires no migration for Slice C (code-only).

## Recording results

Record pass/fail per row + build SHA here and add the sign-off line to the AGENTS.md Slice C entry. Treat any surprise as a real finding (the live-validation lesson from P3 / P6 / Slice A).
