from rest_framework.authentication import SessionAuthentication


class CsrfSessionAuthentication(SessionAuthentication):
    """Session authentication that enforces CSRF for authenticated requests
    (DRF's default behaviour, kept explicit for clarity)."""

    def authenticate_header(self, request):
        # Return 401 (not 403) for unauthenticated requests so the SPA can
        # redirect to the correct login page.
        return 'Session realm="api"'
