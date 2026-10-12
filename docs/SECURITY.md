# Security, permissions and data protection

## Permission model

Every sensitive endpoint checks permissions **on the server**. Hidden buttons in Angular are only a convenience.

| Capability | Admin | Landlord | Manager | Caretaker | Tenant |
|---|:-:|:-:|:-:|:-:|:-:|
| View properties / units | ✔ all | ✔ all | ✔ assigned | ✔ assigned | – |
| Create / delete properties | ✔ | ✔ | – | – | – |
| Edit properties, units, photos | ✔ | ✔ | ✔ assigned | – | – |
| Tenants (full record) | ✔ | ✔ | ✔ assigned | contacts only, current tenants | own profile |
| Payments: view / record | ✔ | ✔ | ✔ assigned | – | own |
| Payments: verify / reject | ✔ | ✔ | – (segregation of duties) | – | – |
| Applications & reservations | ✔ | ✔ | ✔ assigned | – | – |
| Announcements | ✔ incl. whole portfolio | ✔ incl. whole portfolio | ✔ assigned properties | read | received only |
| Documents | ✔ | ✔ | ✔ assigned | read | assigned & own |
| Maintenance | ✔ | ✔ | ✔ assigned | ✔ assigned | own requests |
| Reports | ✔ | ✔ | ✔ assigned (no portfolio-wide totals) | – | – |
| Staff accounts | ✔ | – | – | – | – |
| Company settings, templates, audit log | ✔ | ✔ | – | – | – |

Implementation: `accounts/permissions.py` (capabilities, `accessible_property_ids`), `config/mixins.py`
(property-scoped querysets and write checks), plus per-view checks. Objects outside a user's scope return
**404**. Tenant endpoints always derive the tenant from the session, so changing an ID in a URL or request
body cannot reach another tenant's data (covered by `tests/test_comms_docs_isolation.py`).

## Accounts, invitations and access

**There is no public registration.** Login endpoints authenticate only; nothing creates an account from a
form on the website. Accounts come from exactly three places:

| Path | Who | Rules |
|---|---|---|
| First-time setup (`/account/setup`, `POST /api/auth/setup/`) | The first company administrator | Works **only while no active administrator exists**. With `DEBUG=false` it also requires `SETUP_TOKEN` (compared in constant time); with no token set, it is disabled and you use `manage.py createsuperuser` on the server. Concurrent attempts are serialised with a row lock. |
| Staff invitation (`/management/staff`, `POST /api/staff-invitations/`) | Administrators only (`manage_staff`) | Role (admin, landlord, manager or caretaker only, never tenant), name and property assignments are stored **in the invitation**. On acceptance the account gets exactly those values; role, email or superuser flags sent with the acceptance are ignored. Existing emails cannot be invited. |
| Tenant invitation (tenant page → *Invite to tenant portal*, or *Register tenant* / *Move in*) | Staff with `manage_tenants` for that property | Only for an existing tenant record with an email, no login yet, and a **current tenancy** (active or notice). Eligibility is checked again at acceptance, so if the tenancy ended or the record changed in the meantime the link no longer works. Knowing a name, phone or **ID number grants nothing**: only the emailed token can activate an account. |

Invitation tokens are 256-bit random values. Only their SHA-256 hash is stored. The link puts the token in
the URL **fragment** (`/account/accept-invite#token=…`), which browsers never send to servers or proxies,
so it does not appear in access logs. The page removes it from the address bar and posts it in the request
body. Invitations are **single-use** and **expire** after `INVITATION_TTL_HOURS` (default 72). Administrators
can **revoke** them, and *Resend* issues a new token and disables the old link. Check and accept endpoints
are rate-limited (`THROTTLE_INVITATION`, default 20/hour per IP), setup to 5/hour.

Invitations are delivered through the normal notification system (email; tenants also get an SMS pointing
to the email, with no link in it). Stored copies of secret links are redacted in the notification-log API
when `DEBUG=false`, and replaced in the database once a real provider has sent them. **Development only:** with `DEBUG=true` the
invite API also returns the link (`dev_invite_link`), shown in a yellow box labelled *Development only*,
so the flow can be tested without an email provider. It is never returned with `DEBUG=false`.

**Ending access**

| Event | What happens | Kept |
|---|---|---|
| Staff account deactivated | `is_active=false`, **all its server sessions deleted**, open invitations for that email revoked, password links refused | Audit log, records they created |
| Tenant portal access disabled by staff | Same as above for the tenant's login | Everything |
| Tenant's last current tenancy ends (move-out) | Open invitations revoked, login deactivated, sessions deleted. Even if a login were re-activated, every portal endpoint requires a current tenancy, so a former tenant gets 403. Password reset does nothing for them. | Tenancy, charges, payments, receipts, documents, maintenance history (visible to staff) |
| Tenant transferred to another unit | Access continues (they still have a current tenancy) | Both tenancies |

Staff can only re-enable portal access for a tenant who has a current tenancy again.

## Security hardening checklist

Each item says what is implemented and how it is verified. "Test" refers to the backend suite
(`backend/tests/`, 142 tests, run on SQLite and on PostgreSQL 17 in the production Docker image).

| Item | Implementation | Verified by |
|---|---|---|
| Hide API keys | No key or credential is ever sent to Angular; the browser only receives the public Turnstile *site* key. Provider keys live in `.env` locally and in AWS Secrets Manager in production, injected at container start. AWS access uses IAM task roles, so no AWS keys exist. | Secret scan in `scripts/security-scan.ps1`; `.dockerignore` keeps `.env` out of images |
| Purge Git secrets | The project is **not a Git repository yet**, so there is no history to purge. `.gitignore` excludes `.env`, `deploy/docker.env`, keys and data folders; the scan flags secret-looking strings and tracked secret files. After `git init`, run the scan before the first commit. If a secret is ever committed, **rotate it first**, then rewrite history (`git filter-repo`). | `security-scan.ps1` (passes) |
| "Use public DB key" | Not applicable: that is a Supabase/Firebase pattern where the browser talks to the database directly. Here the browser never touches PostgreSQL; only the API does, with credentials from Secrets Manager, over TLS, from private subnets. | Architecture (RDS not publicly accessible) |
| Enable row-level security | Row-level access is enforced in the **API layer** on every query: property scoping for staff, tenant-from-session for the portal. Objects outside scope return 404. PostgreSQL RLS policies are **not** enabled; see the note below. | Isolation/IDOR tests, caretaker and manager scope tests |
| Encrypt sensitive data | National ID numbers are encrypted in the application (Fernet: AES + HMAC) before storage, with key rotation (`reencrypt_fields`). Everything else is encrypted at rest by RDS (KMS) and S3 (SSE), and in transit by TLS everywhere (`rds.force_ssl`, HTTPS-only buckets). | `test_id_number_encrypted_at_rest`, key-rotation test |
| Enforce server-side auth | Every endpoint defaults to `IsAuthenticated`; capabilities and property scope are checked server-side. Angular guards are cosmetic only. Accounts are invitation-only (see above). Tenant endpoints also require a current tenancy. | 401/403 tests, tenant-calls-staff-API tests, `test_invitations_access.py` |
| Lock record access | Scoped querysets (`config/mixins.py`), portal endpoints filtered by the session tenant, foreign IDs → 404. Concurrent writes use `SELECT … FOR UPDATE` row locks and unique constraints (reservations, payments, receipts). | Isolation tests, reservation-conflict tests |
| Block field tampering | Serializers whitelist writable fields: status, receipt numbers, simulation flags, verification, superuser and role-escalation fields are read-only or ignored. Invitation acceptance takes role, email and assignments only from the stored invitation. The tenant profile cannot change name, email or notes. Maintenance property and unit come from the tenancy, not the request. | `InputAndTamperingTests` |
| Secure session cookies | HttpOnly, SameSite=Lax, Secure and the `__Host-` prefix when `SECURE_HTTPS=true`; the CSRF cookie is Secure. Staff sessions last 12 h, tenants 30 days, and logout invalidates the server session. Deactivation and move-out delete all of the user's sessions. | Settings; `check --deploy` clean |
| Rate limit login | Per-IP throttle (10/min; invitations 20/hour; setup 5/hour) **plus** per-account lock-out (5 failures → 15 min, identical for unknown emails), plus a WAF rate rule on `/api/auth/` in AWS. The cache is shared across containers (`CACHE_BACKEND=db`). | `LoginLockoutTests` |
| Add bot protection | Honeypot field on every public form and on password reset; optional Cloudflare Turnstile verified server-side (fails closed); AWS WAF managed rules, IP reputation and optional Bot Control (M-Pesa callbacks exempted). | `BotProtectionTests`; live check against Cloudflare's test keys |
| Parameterise queries | Only the Django ORM is used: no raw SQL, `.extra()` or string-built queries anywhere (checked by search). WAF SQLi rules add an outer layer. | Code search |
| Validate all input | DRF serializers with types, lengths and choices; model validators (phone format, positive amounts, due day 1–28); business-rule checks in services; email normalisation. | Validation tests |
| Escape user content | Angular escapes all interpolation and never uses `innerHTML`. User text in PDFs is XML-escaped. Notification templates use safe `{placeholder}` substitution (no `str.format` attribute access). CSV exports neutralise formulas. Emails are plain text. | PDF and template-injection tests |
| Restrict file uploads | Extension allow-list plus magic-byte check, 10 MB limit, max 10 files per request, image decode check with a decompression-bomb limit. Photos are **re-encoded** (EXIF/GPS and appended payloads stripped) and renamed to random names. Private files are outside the web root or in a private bucket. | Upload tests |
| Trim API responses | Role-specific serializers (caretakers get no finance, no ID numbers). The raw M-Pesa callback is never returned. Secret reset links are redacted in the notification log. Errors are generic. JSON-only renderer in production (no browsable API); API docs are admin-only when `DEBUG=false`. | Caretaker and redaction tests |
| Add security headers | API: CSP `default-src 'none'`, `Cache-Control: no-store`, nosniff, `X-Frame-Options: DENY`, Referrer-Policy, COOP, CORP and Permissions-Policy. SPA: strict CSP (no inline scripts; Angular's critical-CSS inlining is disabled for this), HSTS, frame denial, Permissions-Policy, via CloudFront (AWS) or nginx (Docker). | Header test; browser run with a CSP-violation listener: 0 violations |
| Force HTTPS | CloudFront redirect-to-https, HTTPS-only API behaviour, TLS 1.2+ policies, Django `SECURE_SSL_REDIRECT` and HSTS, origin verification header so the ALB can't be used directly. | `check --deploy` clean; origin-verify test |
| Scan dependencies | `pip-audit` and `npm audit` in `scripts/security-scan.ps1`; ECR scan-on-push for image OS packages. The audit found 2 advisories in DRF 3.16.1, now **upgraded to 3.17.2**. | Current result: 0 known vulnerabilities (Python and npm) |

### Why PostgreSQL row-level security is not enabled (yet)

Django connects as one database role, so PostgreSQL RLS would need every request to set a session variable
(the current user and their property scope), plus policies on ~20 tables that duplicate the permission model
in SQL. The background worker and migrations would need separate bypass roles. Done half-way, it gives a
false sense of security and can break features silently. Done properly, it is a project of its own, best
built and tested on PostgreSQL in staging. The current protection (scoped querysets on every endpoint,
covered by isolation tests, with the database unreachable from the internet) is the standard and
sufficient control for this architecture. RLS remains a reasonable defence-in-depth extension later.

## Other controls

- Passwords hashed with Django's PBKDF2. Minimum length 10, plus common-password and similarity checks.
- CSRF protection on every authenticated unsafe request (`X-XSRF-TOKEN` header).
- Additional rate limits: password reset 5/hour, public forms 20/hour, M-Pesa requests 10/min.
- Password reset never reveals whether an email exists. Links are single-use and expire after 3 days.
- The real client IP is taken only from trusted proxies (`NUM_PROXIES`), so rate limits, the audit log and
  the M-Pesa IP allow-list cannot be fooled with a forged `X-Forwarded-For`.
- CSV exports contain only data the user can access.
- Audit log of logins, lock-outs, staff and tenant changes, payments, voids, verifications, publications
  and settings.
- Financial history is never deleted: properties and units with history can only be archived; charges are
  voided with a reason rather than deleted; former tenants' records are kept but hidden from caretakers.
- Containers run as a non-root user, use a slim, freshly patched base image, and contain no secrets.

## Kenya Data Protection Act, 2019 – practical notes

The platform supports compliance; the company remains the data controller and should obtain legal advice.

- **Lawful basis and notice:** public forms require explicit consent, and a privacy notice is editable under
  *Settings → Company profile* and published at `/privacy`. Staff record that tenants were informed when
  registering them (`data_consent_at`).
- **Minimisation:** public applications collect only contact and basic suitability information. National ID
  is entered by staff only, and caretakers never see it.
- **Access control:** least-privilege roles and property scoping, as above.
- **Retention:** tenancy and financial records should be kept as long as tax and legal obligations require
  (commonly 7 years in Kenya). Define a schedule for deleting old rejected applications and viewing requests
  (for example after 12 months); these can be removed via Django admin.
- **Data subject requests:** staff can export a tenant's statement and payment history (PDF/CSV) and correct
  records. Deletion requests must be weighed against legal retention duties.
- **Registration:** check whether the company must register with the Office of the Data Protection
  Commissioner (ODPC) as a data controller or processor.
- **Breach response:** keep the audit log and server logs, and notify the ODPC within 72 hours where required.
- **Messages:** SMS and WhatsApp content is kept minimal, because phones may be shared.

## Electronic signatures

The system does **not** create legally binding electronic signatures. The built-in workflow is:
download → sign by hand (or with the tenant's own recognised e-signature tool) → upload the signed copy →
staff verify it. Under the Kenya Information and Communications Act, advanced electronic signatures
require a licensed certification service provider. Integrating such a provider is a separate project.
The `SignatureRequest` model already has `method=provider`, `provider` and `provider_reference` fields for it.
