# syntax=docker/dockerfile:1
# Production image for the Django API, worker and one-off management tasks.
#   docker build -t propman-backend ./backend
# Secrets are NEVER baked into the image: they are injected at runtime
# (ECS task definition "secrets" from AWS Secrets Manager, or an env file locally).

FROM python:3.13-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /venv && /venv/bin/pip install --upgrade pip && /venv/bin/pip install -r requirements.txt

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/venv/bin:$PATH" \
    DJANGO_DEBUG=false \
    LOG_FORMAT=json
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin app \
    && mkdir -p /app /data/media /data/private_media \
    && chown -R app:app /data
WORKDIR /app
COPY --from=build /venv /venv
COPY --chown=app:app . .
# Static files (Django admin, API docs) are collected at build time and served by WhiteNoise.
# The placeholder values below exist only for this build step and are not kept in the image environment.
RUN DJANGO_SECRET_KEY=collectstatic-only FIELD_ENCRYPTION_KEYS=collectstatic-only \
    python manage.py collectstatic --noinput \
    && chmod +x /app/docker-entrypoint.sh
ENV MEDIA_ROOT=/data/media PRIVATE_MEDIA_ROOT=/data/private_media
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health/', timeout=4).status == 200 else 1)"
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["web"]
