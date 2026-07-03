# LAN Acceptance Test — P6 Guardian Identity, Slice A

**Date:** 2026-06-10
**Build under test:** `dev` branch, Slice A commits `2cd0395..5b3bad5` (migrations `members/0004`, `registrations/0009`).
**Environment:** LAN baseline — `http://192.168.3.245:8000`.
**Scope:** Full chain — guardian dedup core **plus** the billing payoff (sibling discount) **plus** Invoice Ninja push (one client per parent).
**Data state:** Fresh-start wipe (Django DB + Invoice Ninja).
**Spec:** `docs/superpowers/specs/2026-06-09-p6-canonical-guardian-identity-design.md`.
**Plan:** `docs/superpowers/plans/2026-06-09-p6-guardian-identity-slice-a.md`.

## What Slice A changes (and what it deliberately does NOT)

- **Behind the scenes:** one canonical `Guardian` per verified parent email, resolved when a registration is initiated and reused at approval. A parent's children now share one `Guardian` → sibling discount applies → one Invoice Ninja client per parent.
- **No visible parent-UI change yet:** the parent still types/edits guardian fields on each application (the denormalized `guardian_*` columns are retained this slice). Field-locking + propagation is **Slice B/C** — do **not** expect locked guardian fields here.
- The proof of Slice A therefore lives in **Django admin + billing + Invoice Ninja**, not in the parent form.

---

## Preconditions (fresh-start setup)

Record the exact value/observation in the right-hand column as you go.

| # | Precondition | How | Observed |
|---|---|---|---|
| P0 | Slice A code deployed to 192.168.3.245 | Push `dev` (CI builds `:dev`, server auto-pulls) **or** deploy the `dev` build to the LAN host; confirm `members/0004` + `registrations/0009` applied (`manage.py showmigrations`) | |
| P1 | Django DB wiped & re-migrated | Drop/recreate the app DB, run `migrate` from zero (no data migration exists — fresh schema only) | |
| P2 | Invoice Ninja data wiped | Clear IN clients/products/invoices for the test scope; since the Django DB is wiped, all `external_*` ids are gone too | |
| P3 | `qcluster` worker restarted | django-q2 has **no hot-reload** — restart it after the new build so push/sync tasks run the Slice A code | |
| P4 | Active `MembershipPlan` exists | Admin → Billing → create one active plan: `annual_amount=300.00`, `sibling_discount_percent=50.00`, an installment count + first month, `is_active=True` | |
| P5 | Invoice Ninja configured (live) | `INVOICE_PROVIDER_MODE=invoiceninja`, valid `X-Api-Token`/URL pointing at the real IN instance used in the P6 close-out | |
| P6 | OTP delivery works | Confirm you can receive the one-time code at the test guardian email (SMTP or console backend visible) | |
| P7 | (Optional) A `TrainingGroup` exists | For exercising group assignment at approval | |

**Test guardian email:** use a single fresh address for the whole run, e.g. `lan-dedup-2026-06-10@<your-domain>`. Both children below register under this one email.

---

## Acceptance scenarios

### A. Parent flow — Child #1 end-to-end (no regression)
1. Open `/register/`, enter the test guardian email, request the code.
2. Enter the OTP at `/register/verify/`; land on `/portal/` (empty chooser).
3. Click start new registration → redirected to `/applications/<id>/` workspace (step 1, documents).
4. Tick the personal-data consent; upload **guardian ID** (OCR spinner → "Dokumenta apstrāde pabeigta…" toast), **member ID**, **member portrait**.
5. Advance the wizard; fill guardian fields (or accept OCR prefill), child #1 data, kit sizes, payment mode, signing preference.
6. Submit ("Iesniegt pieteikumu").

**Expected:** flow completes with no errors; OCR reaches a terminal state; application is `submitted`.
**Result:** ☐ PASS ☐ FAIL — notes:

### B. Parent flow — Child #2, same parent
1. From `/portal/`, start another new registration (same verified session).
2. Observe guardian fields are **prefilled** from the prior app (they remain **editable** — that is correct for Slice A).
3. Enter a **different** child's data; upload member ID + portrait (guardian ID may be reused automatically).
4. On submit, the **"Nepiemērot Līgumā noteiktās atlaides - Vēlos atbalstīt klubu"** decision is required (a prior non-rejected application exists). **Leave it unticked** (do NOT opt out — so the sibling discount applies).
5. Submit.

**Expected:** second application submits; the opt-out/support-club choice is enforced before submit.
**Result:** ☐ PASS ☐ FAIL — notes:

### C. Guardian dedup — CORE acceptance
1. Django admin → Members → **Guardians**. Filter/search the test email.
2. **Before approval:** confirm there is exactly **one** `Guardian` row linked to this parent account (it was resolved at initiation of Child #1 and reused for Child #2).
3. Admin review → approve **both** applications ("Apstiprināt"; assign a training group if testing P7).
4. **After approving both:** re-check Guardians.

**Expected:** still exactly **one** `Guardian` for the account; **two** `Member`s linked to it (the guardian's members list shows both children). No second guardian was created at approval.
**Result:** ☐ PASS ☐ FAIL — observed guardian count: ___ / member count: ___

### D. Idempotent re-approval
1. Confirm the approved application's review screen offers no re-approve (early-return), or re-POST approve via admin if reachable.

**Expected:** no duplicate `Guardian`, `Member`, or `Agreement` is created by a repeat approval.
**Result:** ☐ PASS ☐ FAIL — notes:

### E. Sibling discount — PAYOFF
1. Drive each child's agreement to **signed** (electronic via DocuSeal, or mark the paper path signed) so the signing signal auto-creates a DRAFT `BillingRecord` per child.
2. Admin → Billing → **BillingRecords**: open both.

**Expected:** Child #1 (earliest-created member) = **full price 300.00**, `is_full_price` true; Child #2 = **discounted to 150.00** (50% sibling discount, `discount_amount` 150.00). The discount only appears because both members share one guardian.
**Result:** ☐ PASS ☐ FAIL — child#1 final: ___ / child#2 final: ___

### F. One Invoice Ninja client — PAYOFF
1. Confirm both BillingRecords; run the admin action **"Izrakstīt rēķinus (Invoice Ninja)"**; let `qcluster` push.
2. In Invoice Ninja, locate the guardian's client.

**Expected:** exactly **one** IN client for the guardian; **both** children's invoice streams sit under that single client (not two clients). Child #2's lines carry the sibling-discount note. Re-running the push is idempotent (no duplicate clients/invoices).
**Result:** ☐ PASS ☐ FAIL — IN client count for guardian: ___

### G. Guardian profile refresh (latest-wins — expected for Slice A)
1. Note the guardian name/phone/address you entered on Child #2's application.
2. Admin → Guardians → open the single guardian row.

**Expected:** the profile reflects the **most recently approved** application's guardian data (latest-wins). This is intended for Slice A; field-locking + controlled propagation arrives in Slice C. Confirm nothing is blank/garbled.
**Result:** ☐ PASS ☐ FAIL — notes:

### H. Abandoned draft is benign (edge)
1. Start a third registration and abandon it (don't submit).

**Expected:** a `Guardian` may exist with no members — harmless (no billing fires); `/portal/` and the chooser still work; starting/continuing registrations is unaffected.
**Result:** ☐ PASS ☐ FAIL — notes:

---

## Recording results

- Capture any defect with the scenario letter, exact step, and observed-vs-expected. Live runs in this project have repeatedly surfaced stub-hidden integration bugs (P3 tiny-IDP, P6 Invoice Ninja) — treat any surprise as a real finding, not noise.
- On a clean pass, record the outcome (pass/fail per scenario + date + the build SHA) in `AGENTS.md` under the Slice A entry, matching the existing LAN-verification record style.
- Any bug found here is fixed before merging/pushing `dev` onward.

---

## Results — run 2026-06-10 (build `dev` @ `7470d2f`)

Instance: `uv` runserver + qcluster on `0.0.0.0:8000`, SQLite (fresh-start), stub OCR, **live** Invoice Ninja, console email (OTP read from server log).

| # | Scenario | Result | Evidence |
|---|---|---|---|
| A | Child #1 flow (no regression) | ✅ PASS | OTP→verify→workspace→3 uploads (OCR stub)→submit |
| B | Child #2 same parent | ✅ PASS | guardian reused at init; opt-out enforced + left unticked |
| C | Guardian dedup core | ✅ PASS | 1 Guardian (Anna Bērziņa), 2 Members; total guardians in DB = 1 |
| D | Idempotent re-approval | ✅ PASS | re-approve app1 → 0 new guardian/member/agreement |
| E | Sibling discount | ✅ PASS | Jānis €300 full / Pēteris €150 (50%) |
| F | One IN client for both children | ✅ PASS *(after fix)* | initial run created 2 clients + 2 products (concurrency bug); fixed (`2fa6510`,`7470d2f`); re-test → 1 client `7LDdwRb1YK`, 1 product, both invoices under it |
| G | Guardian profile latest-wins | ⚠️ not differentiated | both apps carried identical guardian data; profile correct + populated |
| H | Abandoned draft benign | ✅ PASS | app3 reuses guardian, no new guardian, no billing |

**Headline finding:** scenario F surfaced a high-severity concurrency bug — parallel `push_billing_record` workers duplicated the shared IN client + product. Fixed via `select_for_update`-locked ensure helpers; re-validated. See the AGENTS.md Slice A entry. Gate after fix: 1137 passed, ruff + mypy clean.
