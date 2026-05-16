# P2 Audit and P3 OCR Provider Review Design

**Date:** 2026-05-15  
**Status:** Draft for user review  
**Scope:** Review whether P2 is actually complete in current repository state, then perform a research-first provider comparison for P3 OCR direction.

---

## 1. Goal

This session has two goals:

1. audit current project state against P2 acceptance criteria and determine what is truly complete versus partial or missing;
2. produce a research-backed recommendation for the P3 OCR direction before any implementation planning begins.

This session does **not** implement OCR, add dependencies, write migrations, or start provider integration work.

---

## 2. Confirmed requirements

### 2.1 Desired outputs

The session should produce:

- a P2 audit table with explicit status per acceptance item;
- a provider decision memo comparing `tiny-IDP` and relevant AWS document/OCR options;
- updates to `docs/milestones.md` and any canonical planning/spec text that no longer matches reality.

### 2.2 P3 research scope

The provider review must:

- compare `tiny-IDP` with AWS document/OCR alternatives;
- optimize for Latvian passport and Latvian ID card support in MVP;
- prioritize **GDPR / EU posture first**;
- use a balanced overall score as second priority.

### 2.3 Out of scope

This session does not include:

- OCR implementation;
- SDK wiring;
- background job implementation;
- schema changes;
- manual benchmark runs on sample identity documents;
- legal advice.

---

## 3. Review and decision method

### 3.1 P2 audit method

Each P2 acceptance item will be marked using one of three states:

- **met** — clearly satisfied by current code, tests, and project docs;
- **partial** — mostly present, but an explicit gap or risk still blocks clean acceptance;
- **missing** — not implemented or unsupported by evidence.

Evidence may come from:

- repository code;
- repository tests;
- current project docs;
- recent commits only as supporting context, not sole proof.

### 3.2 Provider comparison method

The P3 provider comparison will score or describe each option against this rubric:

1. GDPR / EU posture;
2. Latvian passport fit;
3. Latvian ID card fit;
4. security fit for sensitive extracted metadata;
5. integration complexity in current Django architecture;
6. cost / free-tier practicality;
7. operational risk and lock-in.

Official provider documentation, pricing pages, and compliance/security pages are valid evidence sources.

### 3.3 Recommendation rules

- GDPR / EU posture may veto a cheaper or easier provider.
- If compliance posture is unclear, the result may be **cannot recommend yet**.
- If options are otherwise close, prefer:
  - cleaner adapter boundary;
  - lower sensitive-data exposure;
  - better deterministic testing and stub story.

---

## 4. Architecture and output shape

The work is split into three bounded deliverables.

### 4.1 Deliverable A — P2 audit

Output format:

- acceptance criterion;
- status (`met`, `partial`, `missing`);
- evidence;
- short implication if not fully met.

Purpose:

- establish truthful current milestone status;
- prevent planning P3 on false assumptions.

### 4.2 Deliverable B — P3 provider decision memo

Output format:

- compared providers/services;
- strengths;
- weaknesses;
- compliance caveats;
- recommended primary provider;
- fallback provider if needed;
- open risks to resolve before build.

Purpose:

- choose the likely OCR direction before implementation planning;
- preserve a clean adapter-based architecture in `apps/integrations`.

### 4.3 Deliverable C — Documentation updates

Files expected to change:

- `docs/milestones.md`;
- canonical product/planning docs only where current wording is stale or inaccurate.

Purpose:

- align project planning docs with audited truth;
- document chosen P3 research direction and any narrowed scope.

---

## 5. Constraints and boundaries

### 5.1 Security and privacy

Because OCR output contains sensitive identity metadata, all research and recommendations must assume the same security posture as raw private identity documents.

That means recommendations must fit this architecture:

- no public OCR payload exposure;
- private server-side processing only;
- adapter boundary around external providers;
- future retry/background-job support;
- redact sensitive payloads from logs and operational traces.

### 5.2 Verification boundary

This session does not claim provider accuracy for Latvian documents unless official documentation or clearly cited evidence supports it.

No live production-quality claim should be made without later sample-document validation.

---

## 6. Proposed execution flow

```text
1. Audit P2 acceptance criteria
   -> inspect code, tests, docs
   -> mark met / partial / missing

2. Research OCR providers
   -> review tiny-IDP
   -> review AWS document/OCR options
   -> compare with GDPR-first rubric

3. Produce decision memo
   -> recommend provider or no-decision
   -> capture open risks and next checks

4. Update docs
   -> milestones
   -> canonical spec wording where stale
```

---

## 7. Success criteria

This design is successful when the session produces all of the following:

1. P2 has an explicit audit result with evidence.
2. P3 has a provider recommendation or justified no-decision.
3. Project docs are updated to reflect verified current truth rather than optimistic target wording.

---

## 8. Not part of this design

The following are intentionally deferred to later phases:

- full P3 implementation plan;
- TDD test plan for OCR integration;
- provider SDK selection at code level;
- exact document-field mapping implementation details;
- admin OCR retry UI design details.

Those belong only after this audit and provider-review design is approved and documented.
