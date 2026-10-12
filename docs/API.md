# API overview

Base path: `/api/`. JSON everywhere except file uploads (multipart) and downloads (PDF/CSV/files).
An interactive OpenAPI (Swagger) explorer is served at **`/api/docs/`** and the raw schema at `/api/schema/`.
Both are open while `DEBUG=true`; with `DEBUG=false` only Django admin users can view them.

## Authentication & CSRF

- Cookie sessions (HttpOnly). Call `GET /api/auth/csrf/` once to receive the `XSRF-TOKEN` cookie, then send
  its value in the `X-XSRF-TOKEN` header on every POST/PATCH/PUT/DELETE. Angular's HttpClient does this
  automatically.
- Unauthenticated requests receive **401**; authenticated users without permission receive **403**.
  Objects outside the user's property scope return **404**, so their existence is not revealed.
- List endpoints are paginated: `?page=`, `?page_size=` (max 500) → `{count, next, previous, results}`.
  Most also support `?search=` and `?ordering=`, plus the filters listed below.

| Method & path | Purpose |
|---|---|
| `POST auth/login/` `{email, password, portal: management\|tenant, remember}` | Sign in (rate-limited: 10/min) |
| `POST auth/logout/` · `GET auth/me/` | Sign out · current user, role, capabilities, assigned properties |
| `POST auth/password/change/` | Change own password |
| `POST auth/password/reset/` · `POST auth/password/reset/confirm/` | Request a reset link · set password with `{uid, token, new_password}` |
| `GET auth/setup/` · `POST auth/setup/` `{email, first_name, last_name, password, setup_token}` | First administrator: only while no administrator exists; needs `SETUP_TOKEN` when `DEBUG=false` (5/hour) |
| `POST auth/invitations/check/` `{token}` · `POST auth/invitations/accept/` `{token, password}` | Validate / accept a single-use invitation (20/hour). Role, email and links come from the invitation |

There is **no registration endpoint**. Accounts are created only by the setup step, `createsuperuser`, or an
accepted invitation.

## Public (no login)

| Method & path | Purpose |
|---|---|
| `GET public/company/` | Branding, contacts, FAQ, privacy notice |
| `GET public/filters/` | Towns, counties and unit types for search |
| `GET public/properties/?town=&county=&min_rent=&max_rent=&bedrooms=&unit_type=&q=&available_only=true` | Published properties with listed vacancies |
| `GET public/properties/{slug}/` | Property detail with listed **available** units only (no tenant data) |
| `POST public/viewing-requests/` | Viewing request (consent required; 20/hour) |
| `POST public/applications/` | Rental application → `{reference}` (does **not** create a tenancy) |
| `POST public/applications/status/` `{reference, email[, withdraw: true]}` | Status lookup / withdraw |
| `GET payment-config/` | Current M-Pesa mode (disabled / simulated / sandbox / production) |
| `POST payments/mpesa/callback/{token}/` | Safaricom STK callback (token-protected, idempotent) |

## Management (staff)

Capabilities by role are defined in `backend/accounts/permissions.py`. Managers and caretakers are always
limited to their assigned properties.

| Resource | Endpoints | Notes |
|---|---|---|
| Dashboard | `GET dashboard/?property=&start=&end=` | All figures computed live |
| Properties | `properties/` CRUD; `POST properties/{id}/publish\|unpublish\|archive\|restore/` | Delete only when it has no units or history (409 otherwise) |
| Buildings, units | `buildings/`, `units/` CRUD; `POST units/{id}/archive\|restore/` | Occupied/reserved status is controlled by workflows only |
| Unit types, amenities | `unit-types/`, `amenities/` | Configurable lists |
| Photos | `property-photos/` (multipart `image`, `property`, `unit`, `is_cover`) | Image type and size validated |
| Ownership history | `ownership-records/` | |
| Tenants | `tenants/` list/create/update; `POST tenants/{id}/portal-account/` (invite, or password link for an existing active login), `POST tenants/{id}/portal-invite/revoke/`, `POST tenants/{id}/portal-access/` `{enabled}` | Create can move the tenant in at the same time (`unit`, `start_date`, …). A portal invitation needs a current tenancy |
| Tenancies | `tenancies/` list/retrieve/patch terms; `POST tenancies/move-in/`, `POST tenancies/{id}/notice\|move-out\|transfer/` | `GET tenancies/{id}/ledger/[?export=pdf]` statement |
| Applications | `applications/`; `POST applications/{id}/set-status/`, `POST applications/{id}/reserve/` | Applicant is emailed on status change |
| Viewing requests | `viewing-requests/` list/patch | |
| Reservations | `reservations/` list/create; `POST reservations/{id}/cancel\|convert/` | One active reservation per unit (DB constraint + row lock) |
| Payments | `payments/` list/create (manual); `POST payments/{id}/verify\|reject/`; `GET payments/{id}/receipt/` | Only admin/landlord can verify; STK methods cannot be entered manually |
| Charges | `charges/` list/create; `POST charges/{id}/void/` | Rent is generated automatically; credits reduce balance |
| M-Pesa requests | `mpesa-transactions/` (read-only) | |
| Reminders | `reminder-schedules/` (steps nested) · `follow-ups/` | |
| Announcements | `announcements/` CRUD; `POST …/publish\|unschedule\|archive\|duplicate/`; `GET …/recipients/`, `GET …/audience-preview/`; `POST …/attachments/` | Published notices are immutable |
| Documents | `documents/` CRUD (multipart `file`); `POST …/versions\|approve\|archive\|assign\|unassign/`; `GET …/acknowledgements/`, `GET …/download/[?version=]` | Files are streamed only after permission checks |
| Signatures | `signature-requests/`; `POST …/verify\|reject\|cancel/`; `GET …/signed-file/` | |
| Maintenance | `maintenance/` list/create/patch; `POST …/status/`, `POST …/note/`, `POST …/attachments/`; `GET …/attachments/{id}/` | `?open=true`, `?mine=true` |
| Reports | `GET reports/` (available list); `GET reports/{name}/?property=&start=&end=[&export=csv]` | Names: rent-collected, collections-by-property, arrears, payment-history, occupancy, moves, maintenance, acknowledgements, applications |
| Staff | `staff/` list/update (no create); `POST staff/{id}/activate\|deactivate\|send-reset/` · `GET staff-options/` | Admin only. Deactivate also ends all sessions |
| Staff invitations | `staff-invitations/` list (`?open=true`) / create `{email, first_name, last_name, phone, role, job_title, property_ids}`; `POST staff-invitations/{id}/revoke\|resend/` | Admin only. `dev_invite_link` is returned only when `DEBUG=true` |
| Settings | `GET/PATCH settings/company/`, `notification-templates/`, `notification-log/` (+ `retry`), `notification-channels/`, `POST system/run-jobs/` | |
| Audit | `audit-logs/` | Read-only |
| Notifications | `GET my-notifications/`, `POST my-notifications/` `{ids}` or `{all: true}` | In-app inbox (staff and tenants) |

## Tenant portal

Every portal endpoint resolves the tenant from the session. IDs in URLs are always checked against that
tenant, and a foreign ID returns 404.

| Method & path | Purpose |
|---|---|
| `GET portal/dashboard/` | Tenancy, balance, recent payments, notices, maintenance, manager contact, pending document actions |
| `GET/PATCH portal/profile/` | Contact preferences and emergency contact (name, email and main phone are read-only) |
| `GET portal/account/?tenancy=` | Ledger, payments, suggested amount |
| `POST portal/payments/mpesa/` `{phone, amount}` | Start STK Push (10/min; one request per 2 minutes) |
| `GET portal/payments/mpesa/{id}/` | Poll status |
| `GET portal/payments/phone-report/` · `POST portal/payments/phone-report/` `{mpesa_code, amount, paid_on, sender_phone?}` | Landlord's Send Money number · report a Send Money payment (creates a **pending** payment for staff to verify) |
| `POST portal/payments/mpesa/{id}/simulate/` `{outcome: success\|cancel}` | **Simulated mode only** |
| `GET portal/payments/{id}/receipt/` · `GET portal/tenancies/{id}/statement/` | PDFs |
| `portal/announcements/` list/retrieve (marks opened); `POST …/{id}/acknowledge/` | Notices |
| `portal/documents/` list; `GET …/{id}/download/`; `POST …/{id}/acknowledge/` | Documents |
| `POST portal/signature-requests/{id}/upload/` | Upload signed copy |
| `portal/maintenance/` list/create (multipart, optional `file`); `POST …/{id}/comment\|attachments/` | Property and unit are taken from the tenancy, never from the request |
