"""Middleware helpers for local development/UAT behavior."""


class LocalInsecureCookieMiddleware:
    """Relax secure cookie flags for plain-HTTP local/LAN requests.

    Project settings intentionally keep secure cookie defaults when `SITE_URL`
    points at an HTTPS tunnel. Local LAN UAT still needs forms and session-based
    magic links to work over plain HTTP, so this middleware downgrades cookie
    flags only for non-secure requests.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.is_secure():
            return response

        for cookie_name in ("csrftoken", "sessionid"):
            if cookie_name in response.cookies:
                response.cookies[cookie_name]["secure"] = False
                response.cookies[cookie_name]["samesite"] = "Lax"

        return response
