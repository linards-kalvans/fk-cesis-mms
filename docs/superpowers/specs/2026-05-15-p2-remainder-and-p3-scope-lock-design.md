# P2 Remainder and P3 Scope Lock Design

**Date:** 2026-05-15  
**Status:** Draft for user review  
**Scope:** Finish the remaining parent-facing P2 work so P2 can be marked complete, while explicitly keeping P3 implementation untouched and locking P3 direction to tiny-IDP only.

---

## 1. Goal

This design covers the final work needed to complete P2 honestly.

It does **not** implement P3. Instead, it sharpens the boundary:

- **P2** owns parent-facing visual clarity, document-state clarity, and review/correction UX;
- **P3** will later own real tiny-IDP extraction, secure extracted metadata handling, and OCR job orchestration.

---

## 2. Confirmed requirements

### 2.1 In scope

The P2 remainder should include only parent-facing work:

- typography polish;
- clearer active uploaded-document messaging;
- clearer replace/reuse guidance;
- related parent UX polish;
- enough review/correction presentation to mark P2 complete without pretending real OCR already exists.

### 2.2 Out of scope

This design excludes:

- tiny-IDP integration;
- real OCR extraction;
- OCR job orchestration;
- secure extracted metadata persistence;
- admin OCR retry/review controls;
- broader admin-only cleanup.

### 2.3 P3 scope lock

Future P3 direction is now locked to:

- **primary and only provider direction:** `tiny-IDP`
- no AWS fallback in future P3 planning

This session should not prepare provider hooks or implementation scaffolding.

---

## 3. Recommended approach

Three approaches were considered:

1. visual-only closeout;
2. visual closeout plus deterministic review-hint presentation;
3. docs-only reclassification.

The recommended approach is **visual closeout plus deterministic review-hint presentation**.

Why this wins:

- it completes the user-facing review/correction experience honestly;
- it avoids false claims that real OCR exists;
- it lets P2 finish without coupling to P3 provider work;
- it preserves a clean later swap from presentation-only hints to real tiny-IDP-backed extracted values.

---

## 4. Design decisions

### 4.1 Keep P2 and P3 separated by responsibility

P2 should answer: *Can a parent understand document state and safely review/correct suggested-looking values?*

P3 should answer: *Where do suggested values come from, how are they stored securely, and how are OCR jobs run?*

Why:

- this keeps milestone truth clean;
- it avoids sneaking provider work into a visual milestone;
- it makes P2 completion testable with current architecture.

### 4.2 Use presentation-only review hints in P2

Introduce or formalize a presentation-layer source state such as:

- `manual_only`
- `derived_system_filled`
- `review_hint_extracted`

`review_hint_extracted` means:
- the UI should present the value as something the parent should inspect carefully;
- the value remains editable;
- the label/copy must not imply that a real OCR provider already generated it.

Why:

- this closes the current P2 partial around review/correction UX;
- it avoids misleading users about system capabilities;
- it gives P3 a simple replacement path later.

### 4.3 Active-document state must become unmistakable

Parent workspace should clearly distinguish:

- active uploaded document exists;
- no active document uploaded yet;
- replace action is optional and intentional.

Why:

- current debt shows users may re-upload unnecessarily;
- clearer state lowers accidental replacement confusion;
- this is a P2 parent-facing concern, not an admin concern.

### 4.4 Typography polish should target readability, not brand change

Typography work should refine weight, contrast, and hierarchy while keeping current FK Cēsis identity intact.

Why:

- current known issue is desktop text feeling too heavy/thick;
- P2 remainder should improve readability without reopening full visual-system design.

---

## 5. Work areas

### 5.1 Typography polish

Expected outcome:

- headings remain branded and strong;
- body/form text becomes easier to scan on desktop;
- blue-heavy text treatment no longer feels overly thick.

Likely touch points:

- parent page CSS tokens/theme/page rules;
- form/help/error text hierarchy;
- document/review badges if contrast or weight needs refinement.

### 5.2 Existing uploaded-document clarity

Expected outcome:

- parent immediately sees whether guardian/member document is already present;
- current active filename/status is obvious;
- upload vs replace choice is understandable;
- copy reduces unnecessary re-upload.

### 5.3 Review/correction cues

Expected outcome:

- some values can be shown with a “please review” hint;
- parent understands they may change any value;
- hint copy does not claim verified OCR extraction;
- edit flow remains simple and non-threatening.

### 5.4 Tests and proof

Expected outcome:

- P2 completion can be justified with tests and code evidence;
- no workflow regression occurs in verified entry, chooser, draft, save, submit, or ownership protections.

---

## 6. Acceptance target for this P2 remainder

P2 remainder is complete when all of the following are true:

1. Parent-facing typography/readability debt is addressed in current visual shell.
2. Parent workspace clearly shows active uploaded document state for guardian and member documents.
3. Replace/upload actions are understandable and discourage accidental replacement.
4. Parent-facing review/correction cues exist for extracted-looking values without implying real OCR integration.
5. Editable fields remain easy to correct.
6. Existing parent workflow behavior still passes regression checks.
7. Milestone/docs wording can truthfully move P2 from partial to complete.

---

## 7. Documentation impact

When this work is later implemented, docs should be updated so that:

- `docs/milestones.md` marks P2 complete;
- P3 wording is tiny-IDP only;
- product/spec wording preserves the boundary:
  - P2 = review/correction presentation complete
  - P3 = real tiny-IDP extraction and secure metadata pipeline later

---

## 8. Execution shape

```text
P2 remainder implementation
  -> typography polish
  -> document-state clarity polish
  -> review-hint presentation state and copy
  -> regression + presentation tests
  -> docs update to mark P2 complete
```

---

## 9. Success criteria

This design succeeds when it produces a plan that:

1. finishes only the remaining P2 parent-facing work;
2. does not leak into P3 implementation;
3. gives a credible path to mark P2 complete;
4. locks future P3 planning to tiny-IDP only.
