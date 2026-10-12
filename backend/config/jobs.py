"""Scheduled jobs. Run by `python manage.py run_worker` (loop) or
`python manage.py run_worker --once` (e.g. from Windows Task Scheduler).
Every job is idempotent, so running them more often than needed is safe."""
import logging

from django.utils import timezone

logger = logging.getLogger("jobs")


def run_all_jobs():
    from billing.mpesa import reconcile_pending
    from billing.reminders import run_reminders
    from billing.services import generate_all_charges
    from communications.services import publish_scheduled_announcements, retry_failed
    from leasing.services import expire_reservations

    results = {}
    for name, fn in [
        ("rent_charges_created", generate_all_charges),
        ("reservations_expired", expire_reservations),
        ("announcements_published", publish_scheduled_announcements),
        ("reminders_sent", run_reminders),
        ("mpesa_reconciled", reconcile_pending),
        ("notifications_retried", retry_failed),
    ]:
        try:
            results[name] = fn()
        except Exception as exc:  # noqa: BLE001 - one failing job must not stop the others
            logger.exception("Job %s failed", name)
            results[name] = f"error: {exc}"
    results["ran_at"] = timezone.now().isoformat()
    import time

    from django.core.cache import cache

    from .middleware import WORKER_HEARTBEAT_KEY

    cache.set(WORKER_HEARTBEAT_KEY, time.time(), None)  # reported by /api/health/ready/
    logger.info("Jobs complete: %s", results)
    return results
