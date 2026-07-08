# Analytics (P10) — Public-site analytics + registration funnel

*Added 2026-07-08. Provider adapter ships with `stub` (no-op), `plausible`, and `umami` modes.*

## Platform selection

| Platform | GDPR/privacy | Funnel/events | Ops burden | Verdict |
|---|---|---|---|---|
| **Plausible** | Self-hosted or cloud; no cookies by default; IP minimisation configurable; DPA available. | Pageviews, referrers, top pages, custom events, event properties, server-side events, referral segmentation. | One script tag + optional server API calls. No custom stack. | **Selected** |
| Umami | Self-hosted; privacy-focused; custom browser events and `/api/send`. | Similar event model to Plausible. | Comparable complexity. | Fallback if Plausible is rejected. |
| Matomo | Mature, feature-rich, self-hosted. | Powerful but requires more configuration. | Heavier ops burden than needed for this milestone. | Too heavy for P10. |
| PostHog | Powerful funnels, session replay, experiments. | Broad product-analytics platform. | Requires disabling autocapture, session replay, and extra features to reach privacy parity. | Too broad unless explicitly scoped down. |

**Decision:** Plausible was the default first choice, but self-hosted Umami is also supported because the club already runs it. The app code hides provider specifics behind a small adapter in `apps/analytics/providers.py`, so replacement stays cheap.

## Configuration

All settings are environment variables. Defaults are safe for development (disabled or stubbed).

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANALYTICS_PROVIDER` | No | `stub` | `stub` (no-op), `plausible`, or `umami`. |
| `ANALYTICS_BROWSER_ENABLED` | No | `false` | Render analytics script on parent pages. |
| `ANALYTICS_SERVER_ENABLED` | No | `false` | Emit server-side milestone events. |
| `ANALYTICS_DOMAIN` | No | `""` | Plausible site domain (e.g. `mms.fkcesis.lv`). |
| `ANALYTICS_SITE_ID` | No | `""` | Umami website UUID. Required only for `ANALYTICS_PROVIDER=umami`. |
| `ANALYTICS_API_URL` | No | `""` | Provider base URL (e.g. `https://plausible.io` or `https://umami.example.com`). |
| `ANALYTICS_API_KEY` | No | `""` | Not used by Plausible (server events use no auth). Reserved for future providers. |
| `ANALYTICS_TIMEOUT_SECONDS` | No | `2` | HTTP timeout for server-side event POSTs. |

Enablement steps:

1. Add the site in Plausible or Umami.
2. For Plausible, set `ANALYTICS_DOMAIN` to the site domain. For Umami, set `ANALYTICS_SITE_ID` to the website UUID.
3. Set the matching provider config in the production `.env`.
4. Restart the web process. Browser analytics activates immediately; server events activate on the next request.

Plausible example:

```env
ANALYTICS_PROVIDER=plausible
ANALYTICS_BROWSER_ENABLED=true
ANALYTICS_SERVER_ENABLED=true
ANALYTICS_DOMAIN=mms.fkcesis.lv
ANALYTICS_API_URL=https://plausible.io
```

Umami example:

```env
ANALYTICS_PROVIDER=umami
ANALYTICS_BROWSER_ENABLED=true
ANALYTICS_SERVER_ENABLED=true
ANALYTICS_API_URL=https://umami.example.com
ANALYTICS_SITE_ID=your-umami-website-uuid
```

**Production enablement requires provider setup + dashboard smoke.** Do not flip the flags to `true` without first verifying that pageviews and at least one server event appear in the provider dashboard.

## Event catalog

### Browser events

Triggered by `data-analytics-event` and `data-analytics-impression` attributes on parent-facing templates. Admin pages never render these attributes.

| Event name | Where emitted | Purpose |
|---|---|---|
| `portal_visit` | `/portal/` (impression) | Parent enters the portal. |
| `cta_start_registration` | `/portal/` + `/register/` CTA buttons | Parent clicks "Start registration". |
| `cta_continue_application` | `/portal/` application card CTA | Parent opens an existing application. |
| `cta_new_application` | `/portal/` empty-state CTA | Parent clicks "Start new registration" from empty portal. |
| `cta_submit_application` | `/applications/<id>/` review step submit button | Parent submits the application. |
| `portal_empty_state_shown` | `/portal/` when no applications exist (impression) | Portal shows the empty-state card. |
| `portal_error_state_shown` | `/portal/` when an error occurs (impression) | Portal shows the error-state card. |
| `application_validation_error_summary_shown` | `/applications/<id>/` on validation failure (impression) | Application workspace shows the error summary. |

### Server events

Emitted by Django milestone helpers in `apps/analytics/services.py` when `ANALYTICS_SERVER_ENABLED=true`.

| Event name | Where emitted | Purpose |
|---|---|---|
| `registration_start` | New application creation after verified parent access | Parent begins a new application. |
| `email_verified` | Successful one-time email verification | Parent's email is verified. |
| `application_submitted` | Application enters `submitted` state | Parent submits the application. |

### Safe event properties

Only the following property keys are allowed in any analytics payload (enforced by `apps/analytics/sanitize.py`):

| Property | Allowed values | Where used |
|---|---|---|
| `page_area` | `registration`, `portal`, `application` | All events |
| `event_source` | Fixed enum per event (e.g. `new_application`, `email_verification`, `submit`, `hero`, `application_card`, `empty_state`, `check_other_email`, `review_step`) | All events |
| `application_status` | `draft`, `submitted`, `approved`, `rejected`, `fix_requested` | `cta_submit_application`, `cta_continue_application` |
| `referral_code` | Sanitized `?ref=...` value (see below) | Server milestone events and early browser events before application creation |
| `error_kind` | `validation_summary`, `empty_state`, `error_state` | Error/empty-state impressions |

### Forbidden data

Analytics payloads must never include:

- Names, email addresses, phone numbers, personal IDs
- Document metadata or document filenames
- Free-text form values
- Model primary keys for `Guardian`, `ParentAccount`, `Member`, or `RegistrationApplication`

The server-side `sanitize_event_props()` function enforces an allowlist — any property not in the allowed set is silently dropped. The browser tracker never reads form values or user objects.

## Referral code

Referral codes enter the system only through a URL query parameter:

```
/register/?ref=coach-a
```

Rules:

- Sanitize to lowercase ASCII letters (`a-z`), digits (`0-9`), dash (`-`), and underscore (`_`).
- Trim whitespace.
- Cap length at 64 characters.
- Invalid codes are silently ignored (empty string).
- The sanitized code is stored in the session (`registration_referral_code`) until a `RegistrationApplication` is created.
- On application creation, the code is persisted on `RegistrationApplication.referral_code`.
- The code is sent as the `referral_code` property on server events (`registration_start`, `email_verified`, `application_submitted`) and bootstrapped into the browser tracker via `window.fkAnalyticsBaseProps`.

The first slice does not add referral-code admin list filters, export columns, or a Django report. Analytics dashboard segmentation is the reporting surface.

## Privacy / GDPR posture

### Hosting

- Plausible can be self-hosted (recommended for data residency) or used via plausible.io (EU-based). Self-hosting puts full data control in the club's hands.
- The app never sends personal data to the analytics provider.

### Cookies

- Plausible's default mode is **cookie-free** — no tracking cookies are set. The `defer` script tag records pageviews via the HTTP referer header.
- If the provider is changed to one that uses cookies, a consent banner must be added before production enablement.

### IP handling

- Plausible's default mode does **not** store full IP addresses. The implementation sends `X-Forwarded-For` for accurate geo data, but the provider's IP-minimisation setting must be enabled in Plausible configuration.
- **Verify this setting in the provider dashboard before production enablement.**

### Retention

- Retention is controlled in the analytics provider dashboard, not in this application.
- Default Plausible retention is 365 days. Adjust to match the club's data-retention policy.
- **Set retention in the provider dashboard before production enablement.**

### DPA / self-host responsibility

- If using plausible.io: they provide a DPA. Review before enabling.
- If self-hosting: the club is the data controller and processor. Document the server location and access controls.

### Consent / notice implications

- Because Plausible operates in cookie-free mode with no personal data collection, GDPR consent is generally not required for the analytics script.
- However, Latvian/EU interpretation may vary. Add a brief notice in the privacy policy stating that aggregate, cookie-free analytics are collected for service improvement.
- **Legal review of the privacy-policy notice is recommended before production enablement.**

## Production checklist

Before enabling analytics in production:

- [ ] Analytics platform is deployed (self-hosted or cloud) and the site is added.
- [ ] `ANALYTICS_PROVIDER=plausible` is set in production `.env`.
- [ ] `ANALYTICS_DOMAIN` and `ANALYTICS_API_URL` are set to valid values.
- [ ] `ANALYTICS_BROWSER_ENABLED=true` — verify pageviews appear in the dashboard.
- [ ] `ANALYTICS_SERVER_ENABLED=true` — verify at least one server event appears.
- [ ] IP minimisation is enabled in the provider dashboard.
- [ ] Retention period is set to match the club's data-retention policy.
- [ ] Privacy policy is updated with a brief analytics notice.
- [ ] Admin pages (`/admin/...`) do **not** render analytics scripts (verified by inspection).

## Administration

- Admin pages (`/admin/...`) never render analytics scripts and never emit analytics events.
- There is **no Django dashboard or reporting UI** in P10. All reporting lives in the analytics provider's native dashboard.
- No analytics models are stored in the Django database. The only persistence is `RegistrationApplication.referral_code` (max 64 chars, sanitized).

## Error handling

- Provider failures (HTTP errors, timeouts) are logged as warnings and swallowed. They never raise into parent-facing views.
- Missing or invalid provider config disables analytics silently (the browser script is a no-op `window.plausible = function(){}`).
- Server-side event POSTs use a short timeout (`ANALYTICS_TIMEOUT_SECONDS`, default 2s).

## Files

| File | Purpose |
|---|---|
| `apps/analytics/config.py` | Env-driven settings helpers (`analytics_browser_configured`, `analytics_server_configured`). |
| `apps/analytics/providers.py` | Provider boundary: `send_event(name, props, request)`. Dispatches on `ANALYTICS_PROVIDER`. |
| `apps/analytics/services.py` | `track_event()` + milestone helpers (`track_registration_start`, `track_email_verified`, `track_application_submitted`). |
| `apps/analytics/sanitize.py` | Referral-code sanitizer + event-property allowlist. |
| `apps/analytics/templatetags/analytics_tags.py` | `{% analytics_browser %}` template tag. |
| `templates/analytics/browser.html` | Browser script partial (provider script + stub + tracker JS). |
| `static/js/analytics_events.js` | Declarative event tracker (click + impression via `data-analytics-*` attributes). |
