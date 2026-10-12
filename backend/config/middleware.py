import hmac
import time

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse

HEALTH_PATH = "/api/health/"
READY_PATH = "/api/health/ready/"
WORKER_HEARTBEAT_KEY = "worker:last_run"


def readiness():
    """Checks the dependencies a web task needs. Returns (ok, details).
    Details contain only coarse statuses – no versions, hosts or errors."""
    checks = {}
    try:
        connection.ensure_connection()
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        checks["database"] = "ok"
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        checks["migrations"] = "ok" if not pending else "pending"
    except Exception:  # noqa: BLE001
        checks["database"] = "error"
    try:
        cache.set("health:probe", "1", 10)
        checks["cache"] = "ok" if cache.get("health:probe") == "1" else "error"
    except Exception:  # noqa: BLE001
        checks["cache"] = "error"
    last = cache.get(WORKER_HEARTBEAT_KEY) if checks.get("cache") == "ok" else None
    # Informational only: the web tier is healthy even if the worker is late.
    checks["worker"] = "ok" if last and time.time() - last < 15 * 60 else "stale"
    ok = checks.get("database") == "ok" and checks.get("migrations") == "ok" and checks["cache"] == "ok"
    return ok, checks


class HealthCheckMiddleware:
    """Serves /api/health/ (liveness) and /api/health/ready/ (readiness)
    before ALLOWED_HOSTS, HTTPS redirect and origin checks, because load
    balancer probes connect directly to the container over HTTP."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == HEALTH_PATH:
            return JsonResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})
        if request.path == READY_PATH:
            ok, checks = readiness()
            return JsonResponse({"status": "ok" if ok else "unavailable", "checks": checks},
                                status=200 if ok else 503, headers={"Cache-Control": "no-store"})
        return self.get_response(request)


class OriginVerifyMiddleware:
    """Rejects requests that did not come through CloudFront (which adds the
    secret X-Origin-Verify header), so WAF/rate limits cannot be bypassed by
    calling the load balancer directly."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.secret = settings.ORIGIN_VERIFY_SECRET

    def __call__(self, request):
        if self.secret:
            supplied = request.META.get("HTTP_X_ORIGIN_VERIFY", "")
            if not hmac.compare_digest(supplied, self.secret):
                return JsonResponse({"detail": "Forbidden."}, status=403)
        return self.get_response(request)


class SecurityHeadersMiddleware:
    """Extra headers on every response; strict CSP and no-store for API JSON."""

    API_EXEMPT = ("/api/docs/", "/api/schema/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        response.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        path = request.path
        if path.startswith("/api/") and not path.startswith(self.API_EXEMPT):
            response.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            # Private data must never be stored by browsers, CloudFront or proxies.
            response.setdefault("Cache-Control", "no-store")
        return response
