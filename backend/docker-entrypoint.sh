#!/bin/sh
# Container entrypoint.
#   web       - gunicorn API server (default)
#   worker    - scheduled jobs loop (rent charges, reminders, expiry, retries)
#   jobs-once - run the scheduled jobs once and exit (for EventBridge Scheduler)
#   migrate   - apply migrations, create the cache table and default data
#   manage …  - any Django management command, e.g. "manage createsuperuser"
set -e

case "$1" in
  web)
    exec gunicorn config.wsgi:application \
      --bind "0.0.0.0:${PORT:-8000}" \
      --workers "${GUNICORN_WORKERS:-3}" \
      --threads "${GUNICORN_THREADS:-2}" \
      --timeout "${GUNICORN_TIMEOUT:-60}" \
      --max-requests 1000 --max-requests-jitter 100 \
      --access-logfile - --error-logfile -
    ;;
  worker)
    exec python manage.py run_worker --interval "${WORKER_INTERVAL:-300}"
    ;;
  jobs-once)
    exec python manage.py run_worker --once
    ;;
  migrate)
    python manage.py migrate --noinput
    python manage.py createcachetable
    exec python manage.py setup_defaults
    ;;
  manage)
    shift
    exec python manage.py "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
