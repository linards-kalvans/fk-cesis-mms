# P2 Audit and P3 OCR Provider Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Audit whether P2 is actually complete in the repository, compare `tiny-IDP` with AWS OCR/document options for Latvian passport and ID-card handling, and update project planning docs with evidence-backed conclusions.

**Architecture:** This work is a documentation-and-evidence slice, not a product-code slice. The implementation gathers proof from current code/tests/docs, gathers provider facts from official provider sources, records the comparison in a dedicated decision memo, and then updates milestone/spec documents so project planning reflects verified reality.

**Tech Stack:** Django repo docs, pytest evidence, git history for context, official provider documentation via web fetch, markdown planning docs.

---

## 1. Design decisions

### 1.1 Audit before recommendation
- Do the P2 audit first.
- Why: P3 planning depends on whether P2 is fully complete or still has blocking UX/security/document-state gaps.

### 1.2 Research-only P3 slice
- Do not modify application code, models, migrations, or dependencies in this plan.
- Why: user approved a research-first decision slice whose success condition is recommendation + docs truth, not OCR implementation.

### 1.3 Official-source provider comparison
- Use only official docs/pricing/compliance pages for `tiny-IDP` and AWS options unless repo already contains prior validated evidence.
- Why: recommendation must be defensible and cannot rely on hearsay for GDPR/EU posture.

### 1.4 AWS comparison is service-family based
- Compare the best-fit AWS document/OCR path, not only Textract.
- Why: user explicitly asked for any AWS document intelligence alternative that fits best.

### 1.5 Documentation becomes source of truth
- Save final provider comparison as a new spec/research document, then align `docs/milestones.md` and canonical product spec wording.
- Why: current milestone doc contains stale baseline text and future work should not rely on outdated assumptions.

---

## 2. File-by-file plan

### Files to read as evidence
- `docs/milestones.md` — current milestone language, P2/P3 acceptance, stale wording to correct.
- `docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md` — canonical product direction and OCR/security constraints.
- `docs/superpowers/specs/2026-05-11-p2-parent-visual-system-and-registration-ux-design.md` — P2 intended design baseline.
- `docs/superpowers/specs/2026-05-15-style-guide-application-design.md` — latest visual-system intent.
- `AGENTS.md` — authoritative status summary and scope boundaries.
- `apps/documents/models.py` — current document state and OCR-related fields.
- `apps/documents/views.py` and `apps/documents/admin.py` — current admin/protected access posture.
- `apps/registrations/forms.py`, `apps/registrations/presentation.py`, `apps/registrations/views.py` — current parent UX, document cards, source badges, editable/read-only flow.
- `tests/registrations/test_parent_visual_pages.py` — visual/UX regression evidence.
- `tests/registrations/test_document_state_presentation.py` — document-state UX evidence.
- `tests/registrations/test_ocr_source_presentation.py` — OCR/source badge evidence.
- `tests/documents/test_admin_document_access.py` — private document access evidence.

### Files to create
- `docs/superpowers/specs/2026-05-15-p3-ocr-provider-review.md` — decision memo with rubric, evidence, recommendation, fallback, and open risks.

### Files to modify
- `docs/milestones.md` — mark actual P2 status, correct stale baseline lines, refine P3 wording based on research result.
- `docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md` — only if canonical OCR/provider wording or P2/P3 status statements are now inaccurate.
- `docs/superpowers/specs/2026-05-15-p2-audit-and-p3-ocr-provider-review-design.md` — only if minor status note needs to reflect plan completion; otherwise leave unchanged.

### Files not to modify
- application code under `apps/`
- tests under `tests/`
- `pyproject.toml`
- migrations

---

## 3. Test strategy

### What to verify
- P2 acceptance claims against current code/tests/docs.
- Existing tests that prove current P2 behavior still pass.
- Documentation updates match audited evidence and provider findings.

### Commands to run
- `uv run pytest tests/registrations/test_parent_visual_pages.py -q`
- `uv run pytest tests/registrations/test_document_state_presentation.py -q`
- `uv run pytest tests/registrations/test_ocr_source_presentation.py -q`
- `uv run pytest tests/documents/test_admin_document_access.py -q`
- If audit suggests wider regression risk: `uv run pytest -q`

### What NOT to test
- No new OCR behavior tests, because this plan does not implement OCR.
- No brittle screenshot/assertion additions.
- No synthetic provider mocks inside product code.

### Verification evidence to capture in final summary
- Which targeted tests passed.
- Which P2 acceptance items are fully met versus partial.
- Which provider facts came from which official URLs.

---

## 4. Acceptance criteria per unit

### Unit A — P2 audit complete
- Every P2 acceptance item has `met`, `partial`, or `missing`.
- Each status includes concrete evidence from code/tests/docs.
- Any remaining P2 gaps are explicitly named, not implied.

### Unit B — P3 provider review complete
- `tiny-IDP` and best-fit AWS option(s) are compared.
- Comparison covers GDPR/EU posture, Latvian passport fit, Latvian ID-card fit, security fit, integration complexity, cost/free tier, and operational risk.
- Recommendation is explicit: primary provider, fallback provider, or justified no-decision.

### Unit C — docs aligned
- `docs/milestones.md` no longer contains stale wording that conflicts with audited reality.
- Canonical product spec is updated only where wording is materially stale.
- Decision memo is saved under `docs/superpowers/specs/` and linked or referenced from milestone/spec text where useful.

---

## 5. Documentation scope

Create or update only docs needed for truthful planning:
- provider comparison memo
- milestone status wording
- canonical OCR-direction wording if research changes or narrows recommendation

Do not create ADRs, README changes, or implementation docs yet.

---

## 6. Task breakdown

### Task 1: Build P2 acceptance audit matrix

**Files:**
- Read: `docs/milestones.md`
- Read: `AGENTS.md`
- Read: `docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md`
- Read: `docs/superpowers/specs/2026-05-11-p2-parent-visual-system-and-registration-ux-design.md`
- Read: `docs/superpowers/specs/2026-05-15-style-guide-application-design.md`
- Read: `apps/registrations/forms.py`
- Read: `apps/registrations/presentation.py`
- Read: `apps/registrations/views.py`
- Read: `apps/documents/models.py`
- Read: `apps/documents/admin.py`
- Read: `apps/documents/views.py`
- Read: `tests/registrations/test_parent_visual_pages.py`
- Read: `tests/registrations/test_document_state_presentation.py`
- Read: `tests/registrations/test_ocr_source_presentation.py`
- Read: `tests/documents/test_admin_document_access.py`

- [ ] **Step 1: Extract P2 acceptance checklist into working notes**

Create a temporary checklist outside the repo notes if needed, using this exact structure:

```text
1. Style guide applied on parent-facing flow
2. Guardian-email entry redesigned
3. Existing-guardian chooser/dashboard redesigned
4. Registration form redesigned
5. Document-upload UX clearer
6. OCR-prefill review UX clear
7. Validation UX improved
8. Parent portal / registration list matches visual system
9. No workflow regression
10. Tests cover critical workflow/state behavior
11. Public visual implementation easy to refine
```

- [ ] **Step 2: Map each checklist item to evidence files before making judgments**

Use file notes like:

```text
1 -> tests/registrations/test_parent_visual_pages.py, templates/..., style docs
5 -> templates/parent_ui/includes/document_card.html, tests/registrations/test_document_state_presentation.py
6 -> apps/registrations/presentation.py, tests/registrations/test_ocr_source_presentation.py
```

- [ ] **Step 3: Read mapped files and assign provisional status**

Use this status template exactly:

```text
P2.<n> <criterion>
Status: met|partial|missing
Evidence:
- <file path>: <fact>
- <file path>: <fact>
Risk/Gap:
- <only if partial or missing>
```

- [ ] **Step 4: Run targeted tests that support P2 status claims**

Run:

```bash
uv run pytest tests/registrations/test_parent_visual_pages.py -q && uv run pytest tests/registrations/test_document_state_presentation.py -q && uv run pytest tests/registrations/test_ocr_source_presentation.py -q && uv run pytest tests/documents/test_admin_document_access.py -q
```

Expected:

```text
All selected suites pass.
```

- [ ] **Step 5: Reconcile provisional status with test output**

If a criterion was marked `met` but only docs support it and no code/test proof exists, downgrade to `partial`.

- [ ] **Step 6: Record final P2 audit table in working draft**

Use this exact table shape in the final memo or notes:

```markdown
| Criterion | Status | Evidence | Gap/Implication |
|---|---|---|---|
| P2.1 Style guide applied | met | `...` | — |
| P2.6 OCR-prefill review UX clear | partial | `...` | No real OCR values yet; only source badge cues exist |
```

### Task 2: Research tiny-IDP and AWS OCR options

**Files:**
- Create: `docs/superpowers/specs/2026-05-15-p3-ocr-provider-review.md`
- Reference: `docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md`
- Reference: `docs/milestones.md`

- [ ] **Step 1: Identify exact provider/service candidates**

Working list must include at minimum:

```text
- tiny-IDP
- AWS Textract
- AWS IDP-adjacent alternatives if more appropriate for Latvian identity documents
```

If AWS has no better fit than Textract, explicitly state that.

- [ ] **Step 2: Gather official-source evidence for each candidate**

Collect URLs for:

```text
- product overview
- pricing or free tier page
- compliance / GDPR / data residency page
- feature page relevant to passports/identity docs/forms
```

- [ ] **Step 3: Fill comparison rubric with facts only**

Use this exact section template in the new memo:

```markdown
## <Provider or Service>
- **GDPR / EU posture:**
- **Latvian passport fit:**
- **Latvian ID card fit:**
- **Sensitive metadata handling fit:**
- **Integration shape in this repo:**
- **Cost / free tier:**
- **Operational risk / lock-in:**
- **Official sources:**
  - <URL>
```

- [ ] **Step 4: Write explicit recommendation logic**

Use this exact structure:

```markdown
## Recommendation
- **Primary provider:** <name or cannot recommend yet>
- **Fallback provider:** <name or none yet>
- **Why this wins now:**
  - ...
- **Why rejected / deferred alternatives lost:**
  - ...
- **Open risks before implementation:**
  - ...
```

- [ ] **Step 5: Save decision memo**

The memo must also contain a short top summary:

```markdown
# P3 OCR Provider Review

**Decision status:** recommended | no-decision
**Primary recommendation:** <...>
**Scope tested:** documentary research only, no live OCR benchmark
```

### Task 3: Update milestone and canonical docs

**Files:**
- Modify: `docs/milestones.md`
- Modify if needed: `docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md`
- Reference: `docs/superpowers/specs/2026-05-15-p3-ocr-provider-review.md`

- [ ] **Step 1: Remove or correct stale P2/P3 wording in `docs/milestones.md`**

Specifically review lines/sections that still describe pre-P1 behavior or pre-P2 assumptions, and replace them with audited reality.

- [ ] **Step 2: Update P2 status text to match audit result**

Use wording like one of these, depending on evidence:

```markdown
### P2 — Visual system + registration UX redesign
**Status:** complete
```

or

```markdown
### P2 — Visual system + registration UX redesign
**Status:** partial

Remaining gaps:
- ...
```

- [ ] **Step 3: Update P3 wording to reflect provider research outcome**

Add explicit provider direction, for example:

```markdown
- preferred OCR direction after 2026-05-15 review: `<provider>`
- fallback direction: `<provider>`
- live sample-document validation still required before implementation sign-off
```

- [ ] **Step 4: Update canonical product spec only where it is stale**

Allowed update examples:

```markdown
- change preferred OCR direction wording if research changed recommendation
- add note that provider choice is provisional pending Latvian sample validation
- correct milestone-status-style wording that conflicts with audited reality
```

Do not broaden scope.

- [ ] **Step 5: Re-read updated docs for internal consistency**

Check that:

```text
milestones P2 status == audit table
milestones P3 direction == provider memo
canonical spec wording does not contradict either one
```

### Task 4: Final verification and delivery

**Files:**
- Verify: all touched markdown files

- [ ] **Step 1: Run targeted tests again if doc changes relied on those behaviors**

Run:

```bash
uv run pytest tests/registrations/test_parent_visual_pages.py -q && uv run pytest tests/registrations/test_document_state_presentation.py -q && uv run pytest tests/registrations/test_ocr_source_presentation.py -q && uv run pytest tests/documents/test_admin_document_access.py -q
```

Expected:

```text
Pass; doc-only work did not change behavior.
```

- [ ] **Step 2: Optionally run full project verification if audit confidence requires it**

Run only if targeted suites are insufficient:

```bash
uv run pytest -q && uv run ruff check . && uv run mypy .
```

Expected:

```text
All green, or failures pre-exist and are called out explicitly.
```

- [ ] **Step 3: Prepare final user summary**

Summary must include:

```text
- P2 audit result
- strongest evidence for any partial/missing items
- primary OCR recommendation
- fallback / no-decision caveat
- docs changed
- verification commands run and outcomes
```

- [ ] **Step 4: Generate critique diff URL for changed docs**

Run a filtered critique command covering only changed docs, for example:

```bash
bunx critique --web "Audit P2 and document P3 OCR provider direction" --filter "docs/milestones.md" --filter "docs/superpowers/specs/2026-05-15-p3-ocr-provider-review.md" --filter "docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md"
```

Share the produced URL in the final message.

---

## 7. Self-review checklist

- Spec coverage: this plan covers P2 audit, provider comparison, and docs updates.
- Placeholder scan: no `TODO`/`TBD` placeholders remain.
- Scope check: no implementation, migration, or dependency work included.
- Consistency check: all output files and recommendation formats are named explicitly.
