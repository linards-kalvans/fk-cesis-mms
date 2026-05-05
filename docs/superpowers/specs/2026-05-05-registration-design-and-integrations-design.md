# Registration Design and Integrations Design

**Date:** 2026-05-05
**Status:** Approved — split into build-now and research-now tracks
**Reference:** Brainstorming outcome approved by project owner

## Scope Split

Work is divided into two tracks with different execution modes:

| Track | Mode | Description |
|---|---|---|
| **Build now** | Implementation | Whole-app visual system and registration form redesign, with major parent-flow changes allowed. |
| **Research now** | Spikes / evaluation | ID document extraction vendor shortlist + architecture, agreement generation/signing module concept, club countersign order best practice, signed agreement secure delivery to parent, SMTP/email provider strategy for scale. |

Research-track outcomes feed directly into subsequent implementation plans. Build-now work proceeds in parallel once the visual system direction is established.

---

## 1. Visual System Design

### Design Tokens and Direction

The canonical visual source of truth for this repository is now `style-guide/`. The files `style-guide/FK Cesis.pdf`, `style-guide/background-1.jpeg`, `style-guide/tokens.md`, and `style-guide/tokens.css` supersede exploratory values from `design-template.html` whenever they conflict.

- **Tone:** Calm, centered, trustworthy. The parent experience should feel like filling out a form at a quiet desk — not a frantic checklist.
- **Palette:** Primary brand blue `#0f0851` and brand red `#ce1c20` from the style guide. Additional supporting colors may be derived later, but must not contradict `style-guide/`.
- **Typography:** Brand display font is `Anton`. Supporting body font stack can be chosen during implementation planning, but `Anton` remains the canonical brand/type direction.
- **Spacing scale:** 4px base unit. Section gaps 24–32px. Card padding 16–24px.
- **Components:** Reusable Django template tags for form fields, buttons, alerts, and card containers. Consistent border-radius (4–6px), subtle shadows on cards.

### Asset Handling

- Binary visual reference files under `style-guide/` must be tracked with Git LFS.
- Any future PDFs or raster image assets added to `style-guide/` should continue using LFS-backed tracking.

### Parent Flow Layout

- **Full-width centered layout** on all parent-facing pages. Max-width 640px for forms.
- **Club logo** displayed hero-style on parent entry screens (register, login, magic-link verify). Logo at ~120px width, centered above page heading.
- **Single-column form stack.** No sidebars. Progress indicator (step 1 of 3) at top of multi-step forms.
- **Navigation:** Minimal — only "Back to registration" and "Need help" links. No global nav bar for anonymous/parent pages.

### Admin Shell Layout

- **Denser shell.** Wider content area, sidebar nav for admin sections (applications, members, billing, documents, settings).
- **Club logo** displayed at shell level (sidebar header or top-left corner), smaller (~48px) than parent hero placement.
- **Table-first design** for queues and lists. Bulk action checkboxes, inline status badges, filter bar at top.
- **Modal overlays** for quick-view detail (no full-page navigation for simple lookups).

### Logo Placement Strategy

| Context | Placement | Size | Purpose |
|---|---|---|---|
| Parent entry screens (register, login, verify) | Centered hero above heading | ~120px | Brand warmth, trust signal |
| Admin shell (sidebar or header) | Top-left, compact | ~48px | Persistent brand presence |
| Email templates | Top-left of header | ~80px | Recognizability |

---

## 2. Registration Form Redesign

### Goals

- Reduce perceived effort: group fields into logical sections with clear headings.
- Eliminate dead ends: every page has a visible save-draft or continue button.
- Clarify next steps: after submission, show a confirmation screen with expected timeline.

### Allowed Flow Changes

Major parent-flow changes are permitted in this redesign:

- **Anonymous-to-parent linking:** An anonymous draft can be linked to a `ParentAccount` on first login without losing draft data.
- **Multi-step vs single-page:** Evaluate both. Multi-step with progress indicator preferred if sections are clearly separable (child info, guardian info, documents).
- **Document upload:** Move from a separate page to an inline section within the application form. Drag-and-drop zone with file-type validation and progress indicator.
- **Birth date:** Continue using native `<input type="date">`. Validate against reasonable age ranges (3–16 years).
- **Error handling:** Inline field-level errors with red borders and helper text. Summary error list at top of page.

### Not Changing

- Draft/submit state machine remains intact.
- Magic-link auth flow unchanged at protocol level.
- `/register/` remains accessible without login.

---

## 3. ID Document Extraction — Research Track

### Architecture (Provider-Agnostic)

- **Interface layer:** Define a `DocumentExtractor` protocol (Python ABC or Protocol) with methods: `extract_text(doc: Document) -> ExtractionResult`, `extract_fields(doc: Document) -> Dict[str, str]`.
- **Adapter pattern:** Each vendor gets an adapter implementing the protocol. The service layer calls the protocol, not a concrete vendor.
- **Background job:** Extraction runs asynchronously via Celery/Django-Q. Status stored on `Document` model (`pending`, `processing`, `extracted`, `failed`).
- **Human correction UI:** Admin can review extracted fields and correct them before the data feeds into the application. Extraction is **non-blocking** — application submission is not blocked by extraction success/failure.
- **Storage:** Original document remains in private storage. Extracted data stored as JSON on the `Document` model or a dedicated `DocumentExtraction` model.

### GDPR / EU Compliance — Mandatory

- Any vendor must support EU data residency (data processed and stored within EU/EEA).
- Vendor must provide a Data Processing Agreement (DPA) compliant with GDPR Article 28.
- No training of vendor models on client data.
- Data retention: extraction results must be deletable on document deletion.
- Prefer self-hosted or EU-cloud-native solutions.

### Shortlist Classes

| Class | Examples | Notes |
|---|---|---|
| **Low-cost focused API** | `tiny-idp` or similar niche ID/OCR vendors | Explicitly research first because low cost matters, but viability, EU compliance, and Latvian ID support must be validated. |
| **Self-hosted / on-prem** | Tesseract + custom OCR, PaddleOCR, EasyOCR | Full data control, requires maintenance, may need model tuning for Latvian ID cards. |
| **EU-cloud API** | Microsoft Azure AI Document Intelligence (EU data center), Google Document AI (EU), AWS Textract (EU regions) | Managed service, strong EU compliance documentation, per-page pricing. |
| **Specialized Latvian ID** | Research whether any Latvian vendors offer OCR tuned for `personas kods` extraction | Niche — may not exist; fallback to low-cost or general EU-cloud OCR. |

### Evaluation Criteria

1. **GDPR/EU compliance** (pass/fail gate)
2. **Accuracy on Latvian ID cards** — accuracy of `personas kods`, name, date of birth extraction
3. **Latvian language support** — OCR accuracy on Latvian text
4. **Cost model** — per-page vs subscription; estimate at 50–200 documents/month and peak-period sensitivity
5. **API maturity** — SDK quality, retry support, async response
6. **Self-hosted option** — available and practical for data sovereignty
7. **Cheap-enough MVP fit** — total operating cost remains reasonable for club-scale usage without enterprise lock-in

### Acceptance Outcome

- One recommended vendor with justification, or a decision to proceed with self-hosted OCR.
- Architecture document showing adapter integration points.
- Estimated monthly cost at current and projected volume.

---

## 4. Agreement Generation and Signing — Research Track

### Flow Timing

Agreements are generated and sent for signing **after admin approval** of a registration application. The sequence:

1. Admin approves application → member record created.
2. Membership agreement document is generated (PDF).
3. Agreement is sent to parent for electronic signature.
4. Club countersigns (or countersigns automatically).
5. Fully signed agreement is delivered to parent and archived.

### Configurable Signing Order

- Signing order must be configurable per agreement type (membership, liability waiver, photo release).
- Default order: parent signs first, then club countersigns.
- Admin can override order per-application if needed (e.g., club countersigns first for urgent placements).

### Club Countersign Options

| Option | Description | Pros | Cons |
|---|---|---|---|
| **Automatic countersign** | Club countersigns programmatically after parent signs, using a stored digital certificate. | Fast, no manual step. | Requires certificate management; legal weight may vary by jurisdiction. |
| **Admin countersign** | Admin reviews and clicks "countersign" in admin UI. | Human oversight. | Adds friction; admin must remember to act. |
| **Hybrid** | Auto-countersign by default, with admin override/review queue. | Best of both. | More complex implementation. |

Recommended: **Hybrid approach** — auto-countersign with admin review queue for exceptions.

### Secure Storage and Delivery — Vendor Requirement

The chosen e-signature solution **must provide secure document storage and delivery out of the box**:

- Stored agreements must be tamper-evident (audit trail, hash verification).
- Access to signed agreements must be role-restricted (admin + parent of relevant member).
- Export capability (PDF download) must be available.
- Retention policy must be configurable (minimum 5 years per Latvian law considerations).

### Parent Delivery Options

- **Email attachment** — signed PDF attached to email. Simple, universally accessible.
- **Secure portal/download link** — parent logs in to receive a time-limited download link. More control over access.
- **Both** — recommended. Email with link; attachment if parent prefers. Delivery preference stored on `ParentAccount` or per-agreement.

### Self-Hosted vs SaaS Security Evaluation Principle

Self-hosted deployment is **not assumed to be more secure by default**. For this project, self-hosted services may run in separate infrastructure projects with their own deployment and operations workflows (for example, Ansible-managed environments). FK Cēsis MMS should integrate with those services through stable APIs and keep coupling loose enough that a managed SaaS or a self-hosted equivalent can be swapped later.

Evaluate self-hosted and managed options separately on:

- GDPR / EU data residency and DPA terms
- real-world security controls
- patching and upgrade burden
- key / certificate management burden
- backup and disaster recovery posture
- auditability and tamper evidence
- network exposure and isolation
- team operational maturity to run the service safely
- API quality and portability for loose integration

Internal-only Docker Compose or Kubernetes networking improves isolation, but does not by itself prove a stronger overall security posture.

### Vendor Shortlist

| Vendor | Type | EU Data Residency | Self-Hosted | Open Source | Notes |
|---|---|---|---|---|---|
| **DocuSeal** | SaaS | Yes (EU) | Yes | Yes | Open-source, self-hostable, EU-focused, eIDAS-compliant. |
| **Documenso** | SaaS | Yes (EU) | Yes | Yes | Open-source DocuSign alternative, active development, EU data centers. |
| **OpenSign** | SaaS | Varies | Yes | Yes | Open-source, eIDAS-compliant, self-hostable. |
| **DocuSign** | SaaS | Yes | No | No | Market leader, mature, expensive. |
| **HelloSign / Dropbox Sign** | SaaS | Yes | No | No | Integrated with Dropbox ecosystem. |

Recommended research focus: **DocuSeal, Documenso, OpenSign** (open-source, self-hostable, EU-compliant).

### Acceptance Outcome

- Recommended vendor with justification (cost, compliance, self-host feasibility).
- Signed-off flow diagram showing all states from approval to delivery.
- Configurable signing order design (data model + admin UI concept).
- Delivery preference storage design (parent-level default + per-agreement override).

---

## 5. SMTP / Email Provider — Research Track

### Gmail Limits Risk

- **Free Gmail:** 500 emails/day limit. Easily exceeded at scale.
- **Gmail with Google Workspace:** 2,000 emails/day for standard accounts. Still limited for bulk notifications.
- **Throttling:** Gmail may flag sudden volume spikes as spam.
- **Deliverability:** Transactional emails from Gmail IPs have lower reputation than dedicated transactional providers.
- **Current use case:** Magic-link auth emails, submission confirmations, agreement delivery. Volume is moderate but growing with membership.

### Evaluation Criteria

1. **Daily send limit** — must support projected volume (estimate 50–200 emails/day at steady state, spikes during registration periods).
2. **Deliverability** — inbox placement rate, warm-up support, dedicated IPs available.
3. **EU data residency** — preferred for GDPR alignment.
4. **Pricing** — free tier sufficient for MVP? Predictable cost at scale?
5. **API quality** — REST/API vs SMTP, SDK availability, webhook support for delivery tracking.
6. **Template support** — hosted templates or send HTML inline.
7. **Analytics** — open/click tracking, bounce/drop reporting.

### Deployment / Integration Principle

Email and signing infrastructure may be operated outside this repository in separate deployment projects. This Django app should therefore:

- integrate through provider APIs or SMTP interfaces, not vendor-specific deep coupling
- isolate provider-specific logic in adapters under `apps/integrations`
- keep configuration external so switching between SaaS and self-hosted options does not require domain-model rewrites
- avoid assuming this repo owns service deployment, patching, or lifecycle management

### Candidate Providers

| Provider | Free Tier | Paid Starting | EU Residency | API Quality | Notes |
|---|---|---|---|---|---|
| **Brevo (Sendinblue)** | 300/day | €25/mo | EU (France) | Good | EU-based, SMTP + REST API. |
| **Mailgun** | 5,000/mo | $35/mo | US/EU | Excellent | Industry standard, strong API. |
| **SendGrid (Twilio)** | 100/day | $14.95/mo | US/EU | Excellent | Mature, widely used. |
| **Postmark** | 100/day | $10/mo | US/EU | Excellent | Transactional-focused, highest deliverability. |
| **Resend** | 3,000/mo | $20/mo | US | Good | Modern API, developer-friendly. |
| **Self-hosted Postfix/Mailcow** | Free | Infra cost | Full control | SMTP only | Full data control, requires maintenance. |

### Acceptance Outcome

- Recommended provider with justification.
- Fallback plan if primary provider has outage (secondary provider or queue-based retry).
- Email template architecture decision (hosted vs inline HTML in Django templates).

---

## Summary of Outcomes

| Track | Output | Feeds Into |
|---|---|---|
| **Build now** | Visual system (tokens, components, layouts), redesigned registration form | Implementation in git worktree |
| **Research: ID extraction** | Vendor recommendation + architecture doc | M1/M3 integration work |
| **Research: Agreements** | Vendor recommendation + flow diagram + data model | M3 post-approval workflow |
| **Research: SMTP/email** | Provider recommendation + template architecture | M2/M3 notification infrastructure |

Research-track outcomes are due before corresponding implementation work begins. Build-now visual system work can proceed in parallel.
