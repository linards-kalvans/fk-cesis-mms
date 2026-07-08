"""Template tags for analytics injection (P10).

`{% analytics_browser %}` renders the parent-only analytics partial. It is
the only sanctioned entry point: it short-circuits to an empty string when
the configured provider is not properly set up or the browser channel is
disabled, so consumers can include the tag unconditionally.

When the request is in context (the common case for the parent base
template), the tag also reads the pending referral code from the session
so the browser tracker can attach `referral_code` to early events before
the application exists server-side. The value is sanitised through
`sanitize_referral_code`; an empty result is omitted from the partial so
no bootstrap script is emitted.
"""

from __future__ import annotations

from django import template

from apps.analytics.config import browser_template_context
from apps.analytics.sanitize import sanitize_referral_code

register = template.Library()


@register.inclusion_tag("analytics/browser.html", takes_context=True)
def analytics_browser(context: template.Context) -> dict[str, object]:
    ctx = browser_template_context()
    request = context.get("request")
    if request is not None:
        referral = sanitize_referral_code(
            request.session.get("registration_referral_code", "")
        )
        if referral:
            ctx["analytics_referral_code"] = referral
    return ctx
