# Production deployment (single server)

> For AWS, use [AWS_DEPLOYMENT.md](AWS_DEPLOYMENT.md) instead (containers, RDS, S3, CloudFront). This page describes a
> simpler alternative on one Linux/Windows server. Production now also requires `FIELD_ENCRYPTION_KEYS`
> (see `backend/.env.example`), and `CACHE_BACKEND=db` if you run more than one process.

The recommended layout is a single Linux or Windows server with a reverse proxy (nginx or IIS/Caddy)
serving the built Angular files, proxying `/api/` to Django (gunicorn or waitress), and serving `/media/`
(public property photos only). Private files (`PRIVATE_MEDIA_ROOT`) must **never** be exposed by the web
server; Django streams them after checking permissions.

## 1. Backend

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt gunicorn   # or: pip install waitress on Windows
```

`backend/.env` (production values):
```
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=<50+ random characters>
DJANGO_ALLOWED_HOSTS=yourdomain.co.ke
CSRF_TRUSTED_ORIGINS=https://yourdomain.co.ke
FRONTEND_URL=https://yourdomain.co.ke
SECURE_HTTPS=true                       # secure cookies, HSTS, HTTPS redirect
DATABASE_URL=postgres://propman:<password>@localhost:5432/propman
MEDIA_ROOT=/srv/propman/media
PRIVATE_MEDIA_ROOT=/srv/propman/private_media
MPESA_MODE=production                   # see INTEGRATIONS.md
```

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py setup_defaults
.venv/bin/python manage.py collectstatic --noinput     # Django admin assets
.venv/bin/python manage.py createsuperuser             # first administrator (role=admin)
.venv/bin/gunicorn config.wsgi:application -b 127.0.0.1:8000 -w 3
# Windows: .venv\Scripts\waitress-serve --listen=127.0.0.1:8000 config.wsgi:application
```

Run the worker as a service (`python manage.py run_worker`) or schedule `run_worker --once` every 5 minutes.
**Do not** run `seed_demo` on a production database.

## 2. Frontend

```bash
cd frontend
npm ci
npx ng build            # output: frontend/dist/frontend/browser
```

## 3. nginx example

```nginx
server {
    listen 443 ssl http2;
    server_name yourdomain.co.ke;
    ssl_certificate     /etc/letsencrypt/live/yourdomain.co.ke/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.co.ke/privkey.pem;
    client_max_body_size 12m;

    root /srv/propman/frontend/dist/frontend/browser;
    location / { try_files $uri $uri/ /index.html; }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location /django-admin/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; proxy_set_header X-Forwarded-Proto $scheme; }
    location /static/ { alias /srv/propman/backend/staticfiles/; }
    location /media/  { alias /srv/propman/media/; add_header X-Content-Type-Options nosniff; }
    # private_media is intentionally NOT exposed
}
server { listen 80; server_name yourdomain.co.ke; return 301 https://$host$request_uri; }
```

Use Let's Encrypt (certbot) for free TLS certificates. Serving the frontend and API from one origin avoids
CORS entirely. If they must live on different domains, set `CORS_ALLOWED_ORIGINS` and
`CSRF_TRUSTED_ORIGINS`, and configure cookies for cross-site use.

## 4. Backups and restore

- **Database:** daily `pg_dump -F c` (see `scripts/backup.ps1` on Windows; on Linux use cron with
  `pg_dump -Fc -f /backups/propman-$(date +%F).dump propman`).
- **Files:** back up both `MEDIA_ROOT` and `PRIVATE_MEDIA_ROOT`. Private documents are as important as the database.
- Keep at least 30 days, store an **encrypted off-site copy**, and **test a restore** at least monthly:
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\restore.ps1 -BackupDir backups\<timestamp>
  ```
  (on Linux: `pg_restore --clean --if-exists --no-owner -d propman file.dump`).
- Restore into a staging database first, run `python manage.py check` and log in, then switch over.

## 5. Operational checklist

- [ ] `DEBUG=false`, strong `DJANGO_SECRET_KEY`, HTTPS with `SECURE_HTTPS=true`
- [ ] PostgreSQL user limited to the application database; firewall blocks port 5432 externally
- [ ] Worker running; check *Settings → Channels & notification log* for failures
- [ ] Email/SMS providers configured and verified with a test tenant
- [ ] M-Pesa in `production` mode with IP allow-list; a small live test payment reconciled
- [ ] Demo accounts removed; real administrator created; staff assigned to properties
- [ ] Company profile, privacy notice and FAQ updated (Settings → Company profile)
- [ ] Backups scheduled and a restore tested
- [ ] Log monitoring (gunicorn / Django logs) and uptime monitoring in place
