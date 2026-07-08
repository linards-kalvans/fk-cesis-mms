# P10 — Public-site analytics + registration funnel

*Design spec. Status: approved for written review. Date: 2026-07-08.*

## 1. Problem

The Django app has no product analytics for the parent entry, registration, or portal flow.
Staff cannot see whether parents reach the registration start page, complete email verification,
submit applications, or encounter confusing empty/error states. Today, diagnosing drop-off means
reading logs, waiting for support messages, or manually testing the flow.

P10 adds privacy-aware aggregate analytics for the Django app's parent-facing surfaces only. It
must help staff answer basic funnel and portal-usage questions without tracking admin work or
collecting personal data.

## 2. Goals

- Select an analytics platform through a short comparison against privacy/GDPR posture,
  funnel/event capability, and operational burden.
- Show public/parent traffic stats in the selected platform's native dashboard:
  visits, page views, referrers, and top pages.
- Show aggregate registration funnel milestones:
  registration start, verified access, and application submitted.
- Show aggregate parent-portal operational usage:
  portal visits, key CTA usage, empty states, error states, and validation-error summary views.
- Support referral-code attribution from a URL query parameter (`?ref=...`).
- Store the sanitized referral code on `RegistrationApplication` for future reporting.
- Keep the first slice small: use the native analytics dashboard, not a custom Django dashboard.

## 3. Non-goals

- No analytics for a separate marketing/public website outside this Django app.
- No Django admin tracking.
- No Google Analytics, Meta Pixel, ad pixels, or retargeting tools.
- No per-user behaviour profiling.
- No session replay, heatmaps, surveys, or product-experiment tooling in the first slice.
- No custom BI warehouse or bespoke analytics dashboard.
- No parent invoice visibility or billing UI changes.
- No admin/reporting UI for referral codes in the first slice.

## 4. Platform comparison and selection

P10 compares four options before final implementation:

1. **Plausible** — recommended first candidate. Privacy-first web analytics, native referrer and
   top-page reporting, custom events, event properties, and server-side event API support.
2. **Umami** — strong fallback. Privacy-focused, self-host-friendly, custom browser events and
   `/api/send` server-side events.
3. **Matomo** — mature but likely heavier than needed for this milestone.
4. **PostHog** — powerful funnels and product analytics, but too broad unless all autocapture,
   session replay, and extra product features are explicitly disabled.

Decision criteria:

- **GDPR/privacy:** EU/self-host option, DPA/config path, cookie/IP handling, retention controls,
  and whether the default mode is acceptable for parent-facing youth-sports registration.
- **Funnel/event power:** pageviews, referrers, top pages, custom events, event properties,
  server-side events, and referral-code segmentation.
- **Ops burden:** simplest viable setup with no custom analytics stack.

Default design is a small **Plausible-first adapter**. If the comparison rejects Plausible, Umami
is the preferred fallback. The app code should hide provider specifics behind a small adapter so
provider replacement stays cheap.

## 5. Scope: pages and events

### 5.1 Instrumented pages

Analytics is limited to parent-facing Django pages:

- `/register/`
- `/register/verify/`
- `/portal/`
- `/applications/new/`
- `/applications/<id>/`

Admin URLs must never render analytics scripts and must never emit analytics events.

### 5.2 Browser-tracked events

When browser analytics is enabled, the platform script records pageviews and normal referrer/top-page
stats. A small local script adds declarative tracking for fixed parent-flow events:

- `portal_visit`
- `cta_start_registration`
- `cta_continue_application`
- `cta_new_application`
- `cta_submit_application`
- `portal_empty_state_shown`
- `portal_error_state_shown`
- `application_validation_error_summary_shown`

Browser events use fixed event names and fixed safe properties only. They must not read form values.

### 5.3 Server-tracked events

When server analytics is enabled, Django emits reliable milestone events:

- `registration_start` — when a verified parent starts a new application.
- `email_verified` — when one-time email verification succeeds.
- `application_submitted` — when an application successfully enters submitted state.

Server event failures are logged and swallowed. Analytics can never block registration or portal use.

## 6. Referral-code attribution

Referral code enters the system only through a URL query parameter:

```text
/register/?ref=coach-a
```

Rules:

- Accept only a sanitized code: lowercase ASCII letters, numbers, dash, underscore.
- Trim whitespace.
- Cap length at a small fixed limit, e.g. 64 characters.
- Ignore invalid codes rather than raising user-facing errors.
- Carry the sanitized code in the session until application creation.
- Persist it on `RegistrationApplication.referral_code`.
- Include it as a safe analytics property named `referral_code` where supported.

The first slice does not add referral-code admin list filters, export columns, or a Django report.
Analytics dashboard segmentation is the reporting surface.

## 7. Privacy and PII guardrails

Analytics payloads must never include:

- names
- email addresses
- phone numbers
- personal IDs
- document metadata
- document filenames
- uploaded file names
- free-text form values
- model primary keys for `Guardian`, `ParentAccount`, `Member`, or `RegistrationApplication`

Use an allowlist-based sanitizer for event properties. Allowed first-slice properties:

- `page_area` — fixed enum such as `registration`, `portal`, `application`
- `event_source` — fixed enum for button/section source
- `application_status` — fixed enum when needed
- `referral_code` — sanitized as described above
- `error_kind` — fixed enum such as `validation_summary`, `empty_state`, `error_state`

All other properties are dropped before sending. This is simpler and safer than trying to detect PII.

## 8. Architecture

### 8.1 New app boundary

Add `apps/analytics/` with:

- `config.py` — settings/env parsing helpers.
- `services.py` — `track_event(name, props=None, request=None)` and milestone helpers.
- `providers.py` or `provider_<name>.py` — selected provider implementation.
- `sanitize.py` — referral-code sanitizer and event-property allowlist.

No analytics models are needed. The only schema change is `RegistrationApplication.referral_code`.

### 8.2 Template integration

Add a small parent-facing template partial, included from parent base templates only when
`ANALYTICS_BROWSER_ENABLED=true` and provider settings are valid.

The partial:

- renders the provider script for parent pages only;
- configures the site/domain id;
- exposes only a minimal JS event function;
- does not render on admin pages.

### 8.3 JavaScript integration

Add a small static script that listens for clicks or initial page-state markers on elements with
`data-analytics-event` attributes.

Rules:

- Event names come from fixed template literals, not user input.
- Optional properties come from fixed `data-analytics-*` attributes, not form values.
- Missing provider function is a no-op.

### 8.4 Server integration

Django views/services call milestone helpers at stable business points:

- successful email verification;
- successful new-application creation;
- successful application submission.

Server-side provider calls should have short timeouts and fail closed with logging only.

## 9. Configuration

Use separate feature flags:

- `ANALYTICS_BROWSER_ENABLED` — controls browser script and browser events.
- `ANALYTICS_SERVER_ENABLED` — controls server-side event emission.

Provider settings:

- `ANALYTICS_PROVIDER` — e.g. `plausible`, `umami`, or `stub` for tests.
- `ANALYTICS_SITE_ID` or `ANALYTICS_DOMAIN` — provider-specific site identifier.
- `ANALYTICS_API_URL` — provider endpoint when needed.
- `ANALYTICS_API_KEY` — only if server-side events require authentication.

Defaults should be safe for development and tests: disabled or stubbed, no external calls.

## 10. Data flow

```text
/register/?ref=coach-a
  -> sanitize ref
  -> store in session
  -> browser pageview/event if browser flag enabled

verified parent starts application
  -> create RegistrationApplication(referral_code=session ref)
  -> server emits registration_start if server flag enabled

email verification succeeds
  -> server emits email_verified if server flag enabled

application submit succeeds
  -> server emits application_submitted if server flag enabled

portal renders empty/error state or CTA clicked
  -> browser emits fixed event if browser flag enabled
```

## 11. Error handling

- Missing provider config disables analytics and logs a configuration warning.
- Provider request failures never raise into parent-facing views.
- Server-side event requests use short timeouts.
- Browser event errors are ignored.
- Invalid referral codes are ignored.

## 12. Testing strategy

Tests cover:

- browser script is not rendered when disabled;
- browser script renders on parent pages when enabled;
- browser script never renders on admin pages;
- fixed `data-analytics-event` hooks render on CTA/empty/error-state elements;
- `track_event` drops non-allowlisted properties;
- `track_event` never sends PII-like arbitrary props;
- analytics provider failures do not block registration flow;
- server milestone helpers are called for registration start, email verification, and application submission when enabled;
- no server events are sent when disabled;
- referral code sanitization;
- referral code session carry from `/register/?ref=...` to new application;
- `RegistrationApplication.referral_code` persistence;
- admin pages remain untracked.

Test files can be grouped under `tests/analytics/` plus a few focused registration/portal template tests where existing fixtures are easier to reuse.

## 13. Documentation scope

Create `docs/analytics.md` with:

- selected platform and comparison result;
- provider/env configuration;
- feature-flag enablement steps;
- event catalog;
- referral-code rules;
- privacy/GDPR posture: hosting model, cookie use, IP handling, retention, DPA/self-host responsibility;
- production checklist;
- explicit note that admin tracking and PII payloads are forbidden.

Update `.env.example` with analytics flags and provider settings.

Rename the existing family admin hub spec from P10 to P11 so current docs match milestone numbering.

## 14. Acceptance criteria

P10 is complete when all of the following are true:

1. A documented platform comparison selects the analytics provider.
2. Native analytics dashboard shows visits, page views, referrers, and top pages for parent-facing Django pages.
3. Registration funnel events are visible in aggregate:
   `registration_start` → `email_verified` → `application_submitted`.
4. Parent portal operations events are visible in aggregate:
   portal visits, key CTA usage, empty states, error states, validation-summary views.
5. `?ref=...` referral code is sanitized, stored on `RegistrationApplication`, and available as an analytics event property.
6. No admin pages render analytics scripts or emit analytics events.
7. Analytics payloads contain no PII and only allowlisted properties.
8. Browser and server analytics can be enabled independently.
9. Analytics failures do not break registration, verification, submission, or portal rendering.
10. `docs/analytics.md` documents GDPR/privacy posture before production enablement.
11. Existing family admin hub design file is renamed/relabelled as P11.
