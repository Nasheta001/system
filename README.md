# Property Management Platform

A multi-property management platform for a Kenyan landlord or property-management company, with three
experiences that share one Django backend and database:

| Experience | URL | Who |
|---|---|---|
| Public website | `/`, `/properties`, `/properties/:slug`, `/apply/:unitId`, `/application-status`, `/about`, `/privacy` | Prospective tenants |
| Sign-in | `/login` → `/tenant/login` or `/management/login` | Tenants, or landlords / management |
| Management dashboard | `/management/...` | Administrators, landlords, property managers, caretakers |
| Tenant portal | `/tenant/...` | Current tenants (mobile-first) |

**Accounts are invitation-only.** There is no public registration. The first administrator is created once
(`/account/setup` while no administrator exists, or `manage.py createsuperuser`); administrators invite staff,
and staff invite tenants who have a current tenancy. Invitations are single-use, expire after 72 hours and
can be revoked. Ending a tenant's last tenancy or deactivating an account ends its sessions immediately.
See [docs/SECURITY.md](docs/SECURITY.md#accounts-invitations-and-access).

**Stack:** Angular 21 (standalone components, signals, zoneless) · Django 5.2 LTS + Django REST Framework ·
PostgreSQL (SQLite fallback for quick trials only) · cookie sessions + CSRF · reportlab PDFs ·
Docker images for production · AWS CloudFormation templates (ECS Fargate, RDS, S3, CloudFront, WAF).

> **Production status:** the AWS deployment is **prepared but not yet deployed or tested in an AWS
> account**. See [docs/AWS_DEPLOYMENT.md](docs/AWS_DEPLOYMENT.md) for what has and hasn't been verified.

---

## 1. Quick start (Windows)

Prerequisites: **Python 3.12+** (tested 3.13.7), **Node.js 20.19+/22+** (tested 22.18), **npm 10**.
PostgreSQL 15+ is recommended (tested target: 17); Redis is **not** required.

```powershell
cd C:\Users\ADMIN\OneDrive\Documents\System
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1          # venv, packages, .env, migrations, demo data, npm install
powershell -ExecutionPolicy Bypass -File scripts\start-backend.ps1  # API on :8000 + background worker
powershell -ExecutionPolicy Bypass -File scripts\start-frontend.ps1 # Angular on :4200 (second window)
```

Open **http://localhost:4200**. The Angular dev server proxies `/api` and `/media` to Django
(`frontend/proxy.conf.json`), so the browser sees one origin and session/CSRF cookies just work.

Without `DATABASE_URL`, setup uses `backend/db.sqlite3` and prints a warning. To switch to PostgreSQL:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-postgres.ps1   # asks for the 'postgres' superuser password
cd backend
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py setup_defaults
.\.venv\Scripts\python.exe manage.py seed_demo
```

### Manual commands (if you prefer not to use the scripts)

```powershell
# backend
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env        # then edit DJANGO_SECRET_KEY, DATABASE_URL, ...
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py setup_defaults
.\.venv\Scripts\python manage.py seed_demo
.\.venv\Scripts\python manage.py runserver 127.0.0.1:8000
.\.venv\Scripts\python manage.py run_worker          # separate window: scheduled jobs every 5 min

# frontend
cd frontend
npm install                   # .npmrc sets legacy-peer-deps (works around an npm 10.9 resolver crash)
npx ng serve
```

### Production-like stack with Docker (PostgreSQL + gunicorn + worker + nginx)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\docker-env.ps1     # generates deploy\docker.env with random secrets (git-ignored)
docker compose up -d --build
docker compose run --rm backend manage seed_demo                   # optional demo data
# open http://localhost:8080   ·   health: http://localhost:8080/api/health/ready/
docker compose run --rm -e TEST_MEDIA_ROOT=/tmp/m -e TEST_PRIVATE_MEDIA_ROOT=/tmp/p backend manage test tests   # tests on PostgreSQL
```

## 2. Demo accounts

All demo people, phone numbers and emails are **fictional** (emails use the reserved `.test` domain).
Password for every demo account: **`Demo@2026!`**

| Role | Email | Sees |
|---|---|---|
| Company administrator | `admin@demo.propman.test` | Everything, incl. staff accounts, settings, audit log |
| Landlord / owner | `landlord@demo.propman.test` | Whole portfolio, finance, reports (not staff accounts) |
| Property manager (Bamburi & Kisauni) | `manager@demo.propman.test` | Bamburi Heights, Kisauni Gardens only |
| Property manager (Nyali, Mwembeni & Nakuru) | `manager.coast@demo.propman.test` | Nyali Breeze, Mwembeni Residences, Milimani Court (Nakuru) only |
| Caretaker | `caretaker@demo.propman.test` | Bamburi Heights only; maintenance and tenant contacts, **no finance** |
| Tenant | `tenant@demo.propman.test` | Own tenancy in Bamburi Heights A3 (tenant portal) |

Other seeded *current* tenants with portal accounts use `firstname.lastname@demo.propman.test`; seeded
former tenants have their portal closed, as in real use. Demo accounts are created directly by the seed
command; real accounts only come from invitations.

**Reset the demo data** (deletes all properties, tenants, payments, uploads and non-superuser users, then reloads):

```powershell
cd backend
.\.venv\Scripts\python.exe manage.py seed_demo --reset
```

It asks you to type `reset`. With `DEBUG=false` it refuses unless you also pass `--yes`, so production data
is not wiped by accident. Never run `--reset` against a database holding real tenants.

### Suggested demo walkthrough

1. **Public site:** search homes → open Bamburi Heights → *Request a viewing* → *Apply* on a unit (note the reference).
2. **Manager** (`manager@`): Applications → review → *Approved* → *Reserve unit* → Reservations → *Move in* (creates the tenancy and emails a portal invitation; with `DEBUG=true` and no email provider the
   link is also shown on screen, labelled *development only*).
3. Tenants → open the new tenant → *Record payment* (saved as **pending**, because managers cannot verify) → sign in as **admin** → Rent & payments → *Verify* → receipt PDF.
4. Announcements → new notice → *Tenants in selected buildings* → Block B → *Publish* → open it to see recipients, delivery and acknowledgement.
5. **Tenant** (`tenant@`): *Pay rent* → simulated M-Pesa prompt → *Approve payment* → balance clears, receipt downloads (marked SIMULATED).
   Or *Send Money to landlord*: pay `+254112157383` from the M-Pesa app and enter the confirmation code →
   the payment stays **pending** until an admin/landlord checks the M-Pesa statement and verifies it.
6. Tenant: Documents → acknowledge house rules / upload a signed agreement → admin verifies under Documents → Signatures.
7. Tenant: Maintenance → report an issue → caretaker updates the status (internal notes stay hidden from the tenant).
8. Reports → arrears, collections by property, occupancy → *Export CSV*. Settings → Channels shows which integrations are live.
9. **Admin:** Staff & access → *Invite staff member* → the invitee opens the link, chooses a password and signs in
   with exactly the invited role and properties. *Revoke* or *Resend* (the old link stops working) pending invitations.
10. Tenants → a tenant → *Move-out*: their portal access and sessions end; payments and ledger stay for staff.

## 3. Project structure

```
System/
├── backend/                     Django project
│   ├── config/                  settings, urls, pagination, safe error handler, upload validators,
│   │                            private storage, property-scoping mixin, scheduled jobs
│   ├── accounts/                users & roles, capabilities, staff, company settings, audit log,
│   │                            management commands (run_worker, setup_defaults, seed_demo)
│   ├── properties/              properties, photos, amenities, ownership history, buildings, unit types, units, public API
│   ├── tenancies/               tenants, tenancies, move-in / notice / move-out / transfer, tenant portal profile & dashboard
│   ├── leasing/                 viewing requests, applications, reservations (locking + expiry)
│   ├── billing/                 charges, payments, ledger maths, M-Pesa Daraja, reminders, receipts/statements (PDF)
│   ├── communications/          announcements, recipients/acknowledgements, notifications, providers, templates
│   ├── documents/               documents, versions, assignments, acknowledgements, signature requests
│   ├── maintenance/             requests, updates (public/internal), attachments
│   ├── reports/                 dashboard metrics, reports + CSV export, "run jobs now"
│   ├── tests/                   142 API/service/security tests
│   ├── Dockerfile               production image (non-root, gunicorn, health check)
│   ├── requirements.txt         pinned versions
│   └── .env.example
├── frontend/                    Angular app
│   ├── src/app/core/            API client, auth state, guards, interceptor, formatting, UI services
│   ├── src/app/shared/          icons, badges, modals, pager, list-state helper
│   ├── src/app/layouts/         public, management (sidebar) and tenant (bottom-nav) layouts
│   └── src/app/pages/           public/, auth/, management/, tenant/
├── deploy/aws/                  CloudFormation: app-stack.yaml (VPC, RDS, S3, ECS, ALB, CloudFront), waf-us-east-1.yaml
├── deploy/docker.env.example    environment template for docker-compose
├── docker-compose.yml           production-like local stack
├── scripts/                     setup, start, PostgreSQL, backup/restore, security scan, e2e_smoke.py, aws/ deploy scripts
└── docs/                        API, integrations, AWS deployment, generic deployment, security & privacy
```

## 4. Tests

```powershell
cd backend;  .\.venv\Scripts\python.exe manage.py test tests      # 142 tests (SQLite)
cd frontend; npx ng test --watch=false                           # 14 tests (Vitest)
cd frontend; npx ng build                                        # production build
powershell -ExecutionPolicy Bypass -File scripts\security-scan.ps1  # pip-audit, npm audit, check --deploy, secret scan
# End-to-end (80 checks) against a running stack with fresh demo data:
$env:BASE="http://localhost:4200"; backend\.venv\Scripts\python.exe scripts\e2e_smoke.py
$env:BASE="http://localhost:8080"; $env:TOKENS="docker"; backend\.venv\Scripts\python.exe scripts\e2e_smoke.py
```

Backend tests cover: authentication and portal separation, role and property permissions, caretaker
restrictions, tenant isolation (IDOR attempts), property create/edit/archive and delete protection, public
listing visibility, applications, reservation conflicts (service lock and database constraint), expiry,
move-in/out, deposit reconciliation, transfers, charges, partial payments, overpayment credit, grace
periods, manual payment verification, M-Pesa simulated and sandbox callbacks (bad token, duplicates, a
reused receipt, amount mismatch, late success after a timeout, unconfirmed query), the reminder sequence,
de-duplication and stopping after payment, invitation-only accounts (expired / reused / revoked /
re-sent invitations, role escalation, unauthorised registration, first-admin setup, ID numbers granting
nothing), session revocation on deactivation and move-out, moved-out tenants, Send Money payment reports, announcement targeting, document access, signature uploads,
maintenance permissions and internal notes, and report/dashboard calculations.

## 5. Integrations at a glance

| Integration | Default | How to activate | Doc |
|---|---|---|---|
| M-Pesa STK Push | **Simulated** (labelled everywhere, payments flagged `is_simulated`) | `MPESA_MODE=sandbox` + Daraja keys + public HTTPS callback (needs a Paybill/Till shortcode) | [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) |
| M-Pesa Send Money to landlord's number | **Active**: `+254112157383` (Settings → Company profile) | Tenant reports the code; staff verify against the M-Pesa statement. No Safaricom API confirms these payments | same |
| Email | Logged only | `NOTIFY_EMAIL_ENABLED=true` + SMTP settings | same |
| SMS (Africa's Talking) | Logged only | `SMS_PROVIDER=africastalking` + API key | same |
| WhatsApp (Meta Cloud API) | Logged only | `WHATSAPP_PROVIDER=meta` + token | same |
| In-app notifications | Active | – | – |
| Bank feeds | **Not integrated** | Bank payments are recorded manually and verified by staff | – |
| E-signatures | Not integrated | Download → sign → upload → staff verify workflow | [docs/SECURITY.md](docs/SECURITY.md) |

Messages on channels without a configured provider are stored with status **Logged only** and never
shown as delivered. *Settings → Channels & notification log* shows the live status.

## 6. More documentation

- [docs/API.md](docs/API.md) – endpoint overview (interactive Swagger UI at `/api/docs/` when `DEBUG=true`)
- [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) – M-Pesa sandbox, SMS, email, WhatsApp, background worker
- [docs/AWS_DEPLOYMENT.md](docs/AWS_DEPLOYMENT.md) – **AWS production deployment**, health checks, M-Pesa on AWS, jobs, logging, backups & recovery
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) – generic single-server deployment (nginx) alternative
- [docs/SECURITY.md](docs/SECURITY.md) – permission model, data protection (Kenya DPA 2019), signatures

## 7. Package versions

Backend (`backend/requirements.txt`): Django 5.2.18 LTS, djangorestframework 3.17.2, gunicorn 26.2.0,
whitenoise 6.12.0, django-storages 1.14.6 + boto3 (S3), cryptography 50.0.2 (field encryption), django-cors-headers 4.9.0,
django-filter 26.2, drf-spectacular 0.30.0, psycopg 3.3.6 (binary), dj-database-url 3.1.2, python-dotenv 1.2.4,
Pillow 12.3.0, reportlab 5.0.1, requests 2.34.2.

Frontend (`frontend/package.json`, locked in `package-lock.json`): Angular 21.2 (core/router/forms/common),
@angular/build 21.2, TypeScript 5.9, RxJS 7.8, Vitest 4.1. No UI framework: the design system is plain SCSS
(`src/styles.scss`).
