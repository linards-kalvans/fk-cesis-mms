# P2 Remainder Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the remaining parent-facing P2 work so P2 can be marked done without starting P3 implementation.

**Architecture:** Keep the boundary strict: P2 only changes parent presentation, copy, and test coverage. Introduce a presentation-only review-hint source state for editable parent fields, improve document-state clarity in the workspace, and polish typography/CSS readability. Do not add provider adapters, background jobs, secure OCR metadata storage, or any real tiny-IDP integration.

**Tech Stack:** Django templates, Django forms/views, pure presentation helpers in `apps/registrations/presentation.py`, CSS in `static/css/parent_theme.css` + `static/css/parent_pages.css`, pytest + pytest-django, markdown docs.

---

## 1. Design decisions

### 1.1 P2 closes the UX gap, not the extraction gap
- Add a presentation-only field source marker: `review_hint_extracted`.
- Why: this lets parent review/correction UX become real and testable without pretending OCR provider work already exists.

### 1.2 Document-state clarity lives in shared partials
- Improve `document_card.html` and related CSS rather than special-casing one page.
- Why: current parent workspace already uses shared includes; this keeps the design consistent and easier to refine.

### 1.3 Typography polish should be CSS-only unless tests prove otherwise
- Prefer CSS updates in `parent_theme.css` / `parent_pages.css`, not template restructuring.
- Why: the debt is readability/weight/contrast, not architecture.

### 1.4 P3 scope is documentation-only in this plan
- Update planning docs to say P3 uses tiny-IDP only, no AWS fallback.
- Why: user explicitly narrowed future direction and asked for P2-only implementation planning now.

---

## 2. File-by-file plan

### Files to modify
- `apps/registrations/presentation.py`
  - Extend source label mapping with `review_hint_extracted`
  - Add any tiny pure-presentation helper needed for review-hint copy
- `apps/registrations/views.py`
  - Ensure workspace context can expose any review-hint explanation text if the template needs it
- `templates/parent_ui/includes/source_badge.html`
  - Add modifier classes / optional assistive copy hook for review-hint state
- `templates/parent_ui/includes/document_card.html`
  - Strengthen active/empty/replace messaging and make “already uploaded” state unmistakable
- `templates/parent_ui/includes/form_field.html`
  - Show review-hint copy and badge in a way that stays editable and non-misleading
- `templates/registrations/application_workspace.html`
  - Add short copy in document/review sections where needed, without provider claims
- `static/css/parent_theme.css`
  - Refine text color/weight/contrast tokens or shared component rules if needed
- `static/css/parent_pages.css`
  - Polish page-level typography, document-card spacing, review-hint visual treatment
- `tests/registrations/test_document_state_presentation.py`
  - Add assertions for stronger active-state / replace guidance
- `tests/registrations/test_ocr_source_presentation.py`
  - Replace P2-facing OCR wording expectation with review-hint expectation where appropriate, or add coverage for new `review_hint_extracted` path
- `tests/registrations/test_parent_visual_pages.py`
  - Add/adjust assertions for readable parent-facing copy and no-regression hooks if necessary
- `docs/milestones.md`
  - Mark P2 complete after implementation and remove partial wording
  - Remove AWS fallback wording from P3
- `docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md`
  - Keep P2/P3 boundary explicit
  - Remove AWS fallback wording from P3 direction if still present
- `AGENTS.md`
  - Update current status and recent changes if P2 is now complete and P3 is tiny-IDP only

### Files likely not to modify
- `apps/registrations/forms.py` unless template/test changes reveal a small field-helper need
- `apps/documents/*` because admin-side cleanup is out of scope
- any migrations
- any provider/integration code

---

## 3. Test strategy

### What to test
- Parent workspace clearly shows uploaded-vs-missing document state.
- Replace action wording is visible and less confusing.
- Review-hint badge/copy is visible for `review_hint_extracted` and stays editable.
- Existing `manual_only` and `derived_system_filled` behavior still works.
- Parent verified flow and workspace rendering do not regress.

### Targeted test files
- `tests/registrations/test_document_state_presentation.py`
- `tests/registrations/test_ocr_source_presentation.py`
- `tests/registrations/test_parent_visual_pages.py`
- `tests/registrations/test_parent_application_workspace.py` (if coverage is needed for review-step output)

### Verification commands
- `uv run pytest tests/registrations/test_document_state_presentation.py -q`
- `uv run pytest tests/registrations/test_ocr_source_presentation.py -q`
- `uv run pytest tests/registrations/test_parent_visual_pages.py -q`
- `uv run pytest tests/registrations/test_parent_application_workspace.py -q`
- Final full verification: `uv run pytest -q && uv run ruff check . && uv run mypy .`

### What NOT to test
- No pixel-perfect CSS assertions.
- No provider integration tests.
- No OCR-job or secure-metadata tests; those belong to P3.

---

## 4. Acceptance criteria per unit

### Unit A — Typography/readability polished
- Parent page text no longer relies on overly heavy blue treatment for body/help text.
- Headings remain branded, but body/help/error/document hint text is easier to scan.
- Tests prove parent pages still render expected visual structure/copy hooks.

### Unit B — Document-state clarity polished
- Active guardian/member document state is obvious.
- Missing-document state is obvious.
- Replace action copy clearly communicates intent and reduces accidental replacement.

### Unit C — Review/correction cues complete
- `review_hint_extracted` path exists in presentation layer.
- Parent sees a review-oriented badge/copy without any claim of real OCR integration.
- Editable fields remain normal editable form fields.

### Unit D — Docs reflect finished P2 and narrowed P3
- `docs/milestones.md` marks P2 complete.
- P3 wording is tiny-IDP only.
- Product/project docs do not mention AWS fallback as future direction.

---

## 5. Documentation scope

Update only docs required by this completion:
- `docs/milestones.md`
- `docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md`
- `AGENTS.md`

Do not create a new P3 plan here.

---

## 6. Task breakdown

### Task 1: Add failing tests for document clarity and review-hint presentation

**Files:**
- Modify: `tests/registrations/test_document_state_presentation.py`
- Modify: `tests/registrations/test_ocr_source_presentation.py`
- Test: `tests/registrations/test_parent_application_workspace.py`

- [ ] **Step 1: Add failing test for stronger active document guidance**

```python
def test_workspace_shows_active_document_guidance_copy(self):
    client = Client()
    acct, app = _create_workspace_draft_with_guardian_doc()
    _login(client, acct)

    resp = client.get(f"/applications/{app.pk}/")

    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Dokuments jau ir augšupielādēts" in content
    assert "Aizvietojiet tikai tad" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/registrations/test_document_state_presentation.py::TestReplaceActionVisible::test_workspace_shows_active_document_guidance_copy -q
```

Expected:

```text
FAIL
assert 'Dokuments jau ir augšupielādēts' in content
```

- [ ] **Step 3: Add failing test for presentation-only review hint source**

```python
def test_review_hint_label_visible_for_review_hint_source(self):
    acct, app = _create_workspace_draft_with_field_sources("reviewhint@example.com")
    app.field_sources = {"guardian_full_name": "review_hint_extracted"}
    app.save(update_fields=["field_sources"])

    client = Client()
    _login(client, acct)
    resp = client.get(f"/applications/{app.pk}/")

    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Lūdzu, pārbaudiet" in content
```

- [ ] **Step 4: Run test to verify it fails**

Run:

```bash
uv run pytest tests/registrations/test_ocr_source_presentation.py::TestOcrExtractedBadgeVisible::test_review_hint_label_visible_for_review_hint_source -q
```

Expected:

```text
FAIL
assert 'Lūdzu, pārbaudiet' in content
```

- [ ] **Step 5: Add or adjust failing review-step assertion if needed**

```python
def test_review_step_keeps_uploaded_document_filename_visible(client, verified_workspace):
    acct, app = verified_workspace
    _login(client, acct)
    resp = client.get(f"/applications/{app.pk}/")
    assert resp.status_code == 200
    assert "data-review-for=\"id_guardian_identity_document\"" in resp.content.decode()
```

- [ ] **Step 6: Run focused test slice**

Run:

```bash
uv run pytest tests/registrations/test_document_state_presentation.py -q && uv run pytest tests/registrations/test_ocr_source_presentation.py -q
```

Expected:

```text
New assertions fail; existing tests may still pass.
```

- [ ] **Step 7: Commit failing tests**

```bash
git add tests/registrations/test_document_state_presentation.py tests/registrations/test_ocr_source_presentation.py tests/registrations/test_parent_application_workspace.py
git commit -m "test: cover P2 remainder review clarity"
```

### Task 2: Implement presentation-layer review hint and document copy improvements

**Files:**
- Modify: `apps/registrations/presentation.py`
- Modify: `templates/parent_ui/includes/source_badge.html`
- Modify: `templates/parent_ui/includes/document_card.html`
- Modify: `templates/parent_ui/includes/form_field.html`
- Modify: `templates/registrations/application_workspace.html`

- [ ] **Step 1: Add review-hint source mapping in presentation helper**

```python
SOURCE_LABEL_MAP = {
    "ocr_guardian_identity": "Aizpildīts no dokumenta",
    "ocr_member_identity": "Aizpildīts no dokumenta",
    "manual_only": "Ievadījāt jūs",
    "derived_system_filled": "Aizpildīts no pārbaudīta konta",
    "review_hint_extracted": "Lūdzu, pārbaudiet",
}
```

- [ ] **Step 2: Run failing source-presentation test**

Run:

```bash
uv run pytest tests/registrations/test_ocr_source_presentation.py::TestOcrExtractedBadgeVisible::test_review_hint_label_visible_for_review_hint_source -q
```

Expected:

```text
Still FAIL or partial PASS until template/copy is updated.
```

- [ ] **Step 3: Upgrade source badge template to support modifier classes**

```django
<span class="fk-source-badge{% if label == 'Lūdzu, pārbaudiet' %} fk-source-badge--review{% endif %}">{{ label }}</span>
```

- [ ] **Step 4: Improve active document card copy**

```django
{% if document %}
  <p class="fk-document-card__status">Dokuments jau ir augšupielādēts.</p>
  <p class="fk-document-card__filename">{{ document.original_filename }}</p>
  {% if workspace_mode == "editable" %}
    <p class="fk-document-card__hint">
      Aizvietojiet tikai tad, ja vēlaties iesniegt citu failu — esošais aktīvais dokuments tiks nomainīts.
    </p>
    <a href="#{{ document_field_id_map|get_item:kind }}" class="fk-button fk-button--secondary fk-button--small fk-document-card__replace">Aizvietot</a>
  {% endif %}
{% endif %}
```

- [ ] **Step 5: Add non-misleading review copy in form field include or workspace section**

```django
{% if source_label == "Lūdzu, pārbaudiet" %}
  <p class="fk-field-hint fk-field-hint--review">Pārbaudiet šo vērtību un izlabojiet to, ja nepieciešams.</p>
{% endif %}
```

- [ ] **Step 6: Add lightweight document-step explanatory copy in workspace**

```django
<p class="fk-section-note fk-section-note--documents">
  Ja dokuments jau ir pievienots, to nav jāaugšupielādē vēlreiz. Aizvietojiet tikai tad, ja vēlaties iesniegt citu failu.
</p>
```

- [ ] **Step 7: Run focused tests to verify implementation passes**

Run:

```bash
uv run pytest tests/registrations/test_document_state_presentation.py -q && uv run pytest tests/registrations/test_ocr_source_presentation.py -q
```

Expected:

```text
PASS
```

- [ ] **Step 8: Commit minimal presentation implementation**

```bash
git add apps/registrations/presentation.py templates/parent_ui/includes/source_badge.html templates/parent_ui/includes/document_card.html templates/parent_ui/includes/form_field.html templates/registrations/application_workspace.html
git commit -m "feat: clarify parent document and review cues"
```

### Task 3: Polish parent typography and visual readability

**Files:**
- Modify: `static/css/parent_theme.css`
- Modify: `static/css/parent_pages.css`
- Test: `tests/registrations/test_parent_visual_pages.py`

- [ ] **Step 1: Add failing test for new parent copy / review-hint hook if needed**

```python
def test_workspace_contains_review_guidance_copy(client, verified_workspace):
    acct, app = verified_workspace
    _login(client, acct)
    resp = client.get(f"/applications/{app.pk}/")
    assert resp.status_code == 200
    assert "Pārbaudiet šo vērtību" in resp.content.decode()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/registrations/test_parent_visual_pages.py::test_workspace_contains_review_guidance_copy -q
```

Expected:

```text
FAIL
```

- [ ] **Step 3: Reduce overly heavy desktop body/help text treatment in CSS**

```css
.fk-hero-copy p,
.fk-page-subtitle,
.fk-document-card__hint,
.fk-field-hint {
  color: var(--fk-muted);
  font-weight: 500;
  line-height: 1.65;
}

.fk-page-title,
.fk-section-head h2,
.fk-hero-copy h2 {
  letter-spacing: 0.01em;
}
```

- [ ] **Step 4: Add review/document-card visual refinements**

```css
.fk-source-badge--review {
  background: #fff4d6;
  color: #6c5200;
}

.fk-document-card__status {
  margin: 0 0 6px;
  color: var(--fk-blue);
  font-weight: 700;
}
```

- [ ] **Step 5: Run targeted parent visual tests**

Run:

```bash
uv run pytest tests/registrations/test_parent_visual_pages.py -q && uv run pytest tests/registrations/test_parent_application_workspace.py -q
```

Expected:

```text
PASS
```

- [ ] **Step 6: Commit typography polish**

```bash
git add static/css/parent_theme.css static/css/parent_pages.css tests/registrations/test_parent_visual_pages.py tests/registrations/test_parent_application_workspace.py
git commit -m "fix: polish parent readability and review states"
```

### Task 4: Update docs to mark P2 complete and narrow P3 to tiny-IDP only

**Files:**
- Modify: `docs/milestones.md`
- Modify: `docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Add failing doc-consistency check in working notes**

Use this exact checklist before editing docs:

```text
- milestones says P2 partial -> must become complete
- milestones P3 mentions fallback -> must be removed
- product spec P3 mentions fallback -> must be removed
- AGENTS current status/debt must match implemented P2 remainder
```

- [ ] **Step 2: Update milestones P2/P3 wording**

```markdown
### P2 — Visual system + registration UX redesign
**Status:** complete

**Delivered outcome**
- parent-facing typography refined for readability
- active uploaded-document state and replace guidance clarified
- review/correction cues completed at presentation layer without real OCR dependency
```

And remove AWS fallback wording from P3 so it reads as tiny-IDP only plus live validation requirement.

- [ ] **Step 3: Update canonical product spec boundary text**

```markdown
- current preferred service direction: **tiny-IDP**
- provider choice remains provisional only pending live Latvian sample-document validation
```

Do **not** mention AWS fallback.

- [ ] **Step 4: Update AGENTS.md status/debt**

```markdown
- P2 is complete.
- Parent workspace now clearly shows active uploaded-document state and review/correction cues.
- Remove or rewrite debt items that this implementation closes.
- Keep P3 as tiny-IDP-only future direction.
```

- [ ] **Step 5: Run consistency grep/read pass**

Run:

```bash
rg -n "fallback|AWS Textract|P2 partial|visual redesign still pending|review_hint_extracted|tiny-IDP" docs AGENTS.md
```

Expected:

```text
Only intentional tiny-IDP references remain; no stale AWS fallback planning text remains in P3 docs.
```

- [ ] **Step 6: Commit docs**

```bash
git add docs/milestones.md docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md AGENTS.md
git commit -m "docs: mark P2 complete and lock P3 provider"
```

### Task 5: Final verification and completion proof

**Files:**
- Verify: all touched files

- [ ] **Step 1: Run focused P2 verification suite**

Run:

```bash
uv run pytest tests/registrations/test_document_state_presentation.py -q && uv run pytest tests/registrations/test_ocr_source_presentation.py -q && uv run pytest tests/registrations/test_parent_visual_pages.py -q && uv run pytest tests/registrations/test_parent_application_workspace.py -q
```

Expected:

```text
PASS
```

- [ ] **Step 2: Run full required verification**

Run:

```bash
uv run pytest -q && uv run ruff check . && uv run mypy .
```

Expected:

```text
All green.
```

- [ ] **Step 3: Prepare completion summary evidence**

```text
- P2 complete
- document-state clarity improved
- review-hint presentation added without real OCR
- P3 still untouched in code
- docs now tiny-IDP only
- full verification outcomes
```

- [ ] **Step 4: Generate filtered critique diff URL**

Run:

```bash
bunx critique --web "Complete remaining P2 parent-facing UX" --filter "apps/registrations/presentation.py" --filter "templates/parent_ui/includes/source_badge.html" --filter "templates/parent_ui/includes/document_card.html" --filter "templates/parent_ui/includes/form_field.html" --filter "templates/registrations/application_workspace.html" --filter "static/css/parent_theme.css" --filter "static/css/parent_pages.css" --filter "tests/registrations/test_document_state_presentation.py" --filter "tests/registrations/test_ocr_source_presentation.py" --filter "tests/registrations/test_parent_visual_pages.py" --filter "tests/registrations/test_parent_application_workspace.py" --filter "docs/milestones.md" --filter "docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md" --filter "AGENTS.md"
```

Expected:

```text
Preview URL printed.
```

---

## 7. Self-review checklist

- Spec coverage: typography polish, document clarity, review/correction cues, tests, and docs updates are all covered.
- Placeholder scan: no TBD/TODO placeholders remain.
- Scope check: no provider integration, metadata storage, admin OCR controls, or AWS fallback work included.
- Consistency check: `review_hint_extracted` is used consistently as the presentation-only state across tasks.
