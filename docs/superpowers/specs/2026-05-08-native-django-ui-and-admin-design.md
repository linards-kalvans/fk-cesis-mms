# Native Django UI and Admin Design

**Date:** 2026-05-08  
**Status:** Draft for review  
**Reference:** Brainstorming outcome approved in conversation

## 1. Problem and Goal

FK Cēsis MMS currently has separate UI work for child registration and admin review. This design evaluates and recommends a native Django approach that reduces long-term maintenance while preserving a usable parent experience and a practical staff review workflow.

The target outcome is:

- parent-facing pages stay server-rendered and easy to maintain
- admin review moves onto Django admin as primary shell
- public pages are in Latvian
- public pages reflect FK Cēsis identity with lightweight styling
- custom code is introduced only where stock Django patterns are insufficient

## 2. Confirmed Requirements

### In scope

- all public parent-journey pages
- registration and related parent-facing flows
- balanced Django-admin-based staff review flow
- public Latvian copy
- light FK Cēsis branding plus improved layout
- small workflow or model changes if required for better native Django fit

### Out of scope

- multilingual architecture
- SPA or API-first rewrite
- moving parent/public pages into Django admin
- bespoke frontend framework or heavy JS UI
- major workflow replacement unless native Django fit truly requires it

### Primary constraint

- minimize long-term maintenance

## 3. Recommended Approach

### Recommendation: Option A

Use **custom public Django templates plus Django forms** for all parent-facing pages, and use **Django admin as the primary staff shell** for review operations, with **small custom admin views** only where review actions need explicit workflow handling.

### Why this is recommended

This approach gives the best balance across the project’s priorities:

- lower maintenance than a separate frontend or staff app
- enough control for Latvian public UX and light branding
- strong reuse of Django admin features such as permissions, filters, search, and navigation
- no need to force parent UX into Django admin, where it would feel unnatural
- no need to recreate admin features in custom code

## 4. Architecture and Ownership

### Audience split

Split by audience rather than by technical stack:

```text
Public parent pages
  -> Django forms + custom templates + branded CSS
  -> optimized for trust, clarity, and Latvian copy

Staff/admin pages
  -> Django admin as primary shell
  -> optimized for review speed, filters, permissions, and low maintenance
```

### Public pages owned by native Django templates

The following pages remain server-rendered custom templates backed by Django forms and views:

- registration start page
- registration edit/submit page
- submission confirmation page
- magic-link request page
- magic-link sent page
- verify success/error pages
- parent portal summary and detail pages

### Admin pages owned by Django admin

Django admin should own:

- registration application review queue
- filters and search
- application detail inspection
- workflow actions: approve, reject, request fixes
- admin access to secure document preview/download flows

## 5. Public-Side Design

### Latvian interface strategy

The public interface can be fully Latvian using native Django facilities:

- form labels, help text, and validation messages in forms
- headings, buttons, and explanatory copy in templates
- Latvian copy on all parent-facing pages

Full multilingual infrastructure is not recommended now because current scope is Latvian-only public UI and maintenance minimization is the top constraint.

### FK Cēsis branding strategy

Use a lightweight theme layer built on assets already present in the repository:

- logo partial: `templates/includes/site_logo.html`
- parent shell partial: `templates/includes/parent_shell.html`
- design tokens: `style-guide/tokens.md`, `style-guide/tokens.css`
- public CSS: `static/css/tokens.css`, `static/css/parent.css`

Canonical tokens already available:

- display font: `Anton`
- FK Cēsis blue: `#0f0851`
- FK Cēsis red: `#ce1c20`

### Visual target

The public interface should be lightly branded and structured, not bespoke:

- centered content shell
- logo on key parent entry screens
- grouped form sections in cards or panels
- clearer spacing and button hierarchy
- visible field errors and top-level error summary
- brand treatment in headings and accents

### Typography rule

Use `Anton` only for brand and heading moments. Do not use it as body or form-control text. Body text should remain in a readable sans-serif stack.

### Form rendering approach

Avoid hardcoding every field layout indefinitely. Use a small shared template partial for field rendering that handles:

- label
- form control
- help text
- field errors
- required marker

Pages should still control section order and high-level layout so the UI remains readable and easy to adjust.

## 6. Admin-Side Design

### Core admin structure

`RegistrationApplicationAdmin` should become the main review entry point, using:

- Django admin changelist as review queue
- Django admin change view as inspection screen
- small custom admin object-action views for review actions

### Queue design

Use stock admin changelist strengths:

- list display
- status filters
- search
- ordering
- badges/derived columns
- quick navigation to detail views

### Detail design

Use the change view mostly as a review surface, not as a generic editing form. It should emphasize inspection of submitted data and related objects.

Likely content:

- guardian information
- child information
- submission timestamps and status
- linked parent/member references
- active identity document
- later OCR/extraction status if introduced
- history/audit information where available

Submitted review data should generally be readonly during review, except through explicit review actions.

### Review action design

Review actions should remain explicit domain actions rather than generic save operations.

Recommended actions:

- **Approve**
- **Reject**
- **Request fixes**

These actions should use small admin-protected action forms where necessary:

- approve: optional training-group selection
- reject: required reason
- request fixes: required note to parent

### Admin extension approach

Keep custom admin code inside native Django admin extension points:

- `ModelAdmin.get_urls()` for custom object-action routes
- admin-protected custom views
- admin base templates and styling for consistency
- redirect back to changelist/change view after action completion

This keeps admin workflow native without building a separate staff backoffice.

## 7. Workflow and Model Implications

### Areas to keep unchanged

The following domain behavior should stay intact unless later evidence proves otherwise:

- `RegistrationApplication` state machine
- draft vs submitted behavior
- anonymous `/register/` access
- magic-link authentication flow
- private document storage and secure access
- member/guardian creation on approval

### Small changes likely useful

#### Admin helper methods

Add model or admin helper methods for:

- status badge label
- active document access
- compact parent/child summary display
- action-eligibility guards such as `can_approve`, `can_reject`, `can_request_fix`

#### Review action service boundaries

Review actions should stay as explicit service-layer operations rather than admin-inline business logic. Existing service functions already point in the right direction and should remain the business-rule source of truth.

#### Training-group handling on approval

The current gap where approval leaves training group empty becomes more visible in admin-native review. Recommendation:

- allow approval without a training group for now
- make training-group choice available in the approve action form as an optional field

#### Document replacement visibility

Admin review should prioritize the active document and avoid confusing reviewers with replaced rows during normal review. This may only require helper/query changes rather than schema changes.

#### Audit trail support

As admin review becomes more central, audit value increases. If audit is added now or soon, it should capture:

- acting admin user
- action type
- timestamp
- reason or note

## 8. Implementation Shape

### Public structure

```text
templates/
  base.html
  includes/
    parent_shell.html
    site_logo.html
    form_field.html
    form_errors.html
    button_row.html
  registrations/
    start_registration.html
    edit_registration.html
    submit_success.html
    parent_portal.html
  accounts/
    request_magic_link.html
    magic_link_sent.html
    verify_error.html
    verify_success.html  (if separate)
```

Public logic remains in existing Django app boundaries:

- `apps/registrations/forms.py`
- `apps/registrations/views.py`
- `apps/accounts/views.py`

### Admin structure

Primary admin ownership should live in:

- `apps/registrations/admin.py`
- optionally related admin support in `apps/documents/admin.py`
- optionally related admin support in `apps/members/admin.py`

### Service interaction pattern

Business rules remain in services, not in admin view code:

```text
admin action view
  -> validate action form
  -> call service-layer action
  -> show success/error message
  -> redirect back into admin
```

This preserves testability and lowers coupling.

## 9. Maintainability Rules

To stay aligned with the primary constraint, implementation should follow these rules:

- no parallel frontend framework
- no client-side state management layer
- no duplicated business logic across admin and public views
- no custom admin shell unless proven necessary
- public shared UI should be small template partials, not a large bespoke component system
- use stock Django admin features first, then add small custom extensions only where review workflow needs explicit verbs

## 10. Acceptance Criteria

### Public parent journey

- all parent-facing pages are server-rendered Django templates
- public forms use Django forms for validation and error handling
- public copy is in Latvian
- public pages visibly reflect FK Cēsis identity through logo, colors, spacing, and heading treatment
- layout is cleaner than default raw Django output, with grouped sections, visible errors, and clear action buttons
- no separate frontend stack is required

### Admin review journey

- registration review queue runs primarily through Django admin
- staff can filter, search, inspect, and review applications from Django admin
- approve, reject, and request-fix actions are explicit admin workflow actions
- stock Django admin handles most of the staff experience
- custom admin code exists only where stock admin is insufficient for workflow clarity
- document access remains secure and admin-only

### Architecture and maintenance

- business rules remain in service layer
- public styling is lightweight and template-driven
- admin customization stays inside Django admin extension points where possible
- any model/workflow changes are localized and justified by better native Django fit

## 11. Final Decision

Yes, this is both **possible** and **sensible**.

The best-fit design is:

- **public parent journey:** custom Django templates + Django forms + light FK Cēsis branding
- **staff review journey:** Django admin as primary shell, with explicit custom admin action views for review verbs where needed

This approach minimizes long-term maintenance while still producing a public experience that is Latvian, branded, and more polished than stock default form rendering.