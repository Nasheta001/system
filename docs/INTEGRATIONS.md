# Integrations

All credentials are read from `backend/.env` (see `.env.example`). Nothing secret is ever sent to Angular.
**Settings → Channels & notification log** in the dashboard shows which integrations are live.

## Background worker (required for automation)

Scheduled work runs through one management command, with no Redis or Celery needed:

```powershell
cd backend
.\.venv\Scripts\python.exe manage.py run_worker            # loops every 300 s
.\.venv\Scripts\python.exe manage.py run_worker --once     # single run (for Task Scheduler / cron)
```

Each run (all steps are idempotent and safe to repeat):
1. Creates missing monthly rent / service charges (and deposits) for current tenancies.
2. Expires overdue reservations and releases their units.
3. Publishes scheduled announcements.
4. Sends due rent reminders (one per tenancy, due date and step) and creates management follow-ups.
5. Re-queries pending M-Pesa transactions and times out abandoned ones.
6. Retries failed notifications with exponential back-off (up to `NOTIFY_MAX_ATTEMPTS`).

`scripts\start-backend.ps1` starts the worker automatically. In production, use Windows Task Scheduler
(`run_worker --once` every 5 minutes) or a systemd service. Administrators can also press
*Settings → Run scheduled jobs now*.

## M-Pesa Daraja (STK Push)

| `MPESA_MODE` | Behaviour |
|---|---|
| `disabled` | Pay Rent is unavailable; staff record payments manually. |
| `simulated` *(default)* | No external call. The portal shows a **"SIMULATED PHONE"** panel to approve or cancel. Payments are stored with `method=mpesa_simulated` and `is_simulated=true`, and receipts, statements and reports mark them **SIMULATED**. Never use in production. |
| `sandbox` | Safaricom sandbox (`sandbox.safaricom.co.ke`), with test money only. |
| `production` | Live Daraja API. |

### Sandbox setup
1. Create an app on <https://developer.safaricom.co.ke> and note the **Consumer Key/Secret**. For sandbox use
   shortcode `174379` and the test **Passkey** shown in the Daraja simulator.
2. Expose your backend over HTTPS (for local testing, e.g. `ngrok http 8000`).
3. In `backend/.env`:
   ```
   MPESA_MODE=sandbox
   MPESA_CONSUMER_KEY=...
   MPESA_CONSUMER_SECRET=...
   MPESA_SHORTCODE=174379
   MPESA_PASSKEY=...
   MPESA_CALLBACK_BASE_URL=https://<your-ngrok-id>.ngrok-free.app
   MPESA_CALLBACK_TOKEN=<long random string>
   ```
   The callback URL registered with each request is
   `{MPESA_CALLBACK_BASE_URL}/api/payments/mpesa/callback/{MPESA_CALLBACK_TOKEN}/`.
4. Add the ngrok host to `DJANGO_ALLOWED_HOSTS`, restart, and sign in as a tenant → *Pay rent*.

### How a payment becomes "paid"
1. Tenant submits phone and amount → an `MpesaTransaction` is created as **pending**. The balance does not change.
2. Safaricom calls the callback. The request must carry the secret token (constant-time compare) and, if
   `MPESA_ALLOWED_CALLBACK_IPS` is set, come from an allowed IP.
3. The transaction row is locked. Duplicate callbacks are counted and ignored. In sandbox/production, a success
   is **confirmed with the STK Query API** before any money is credited. If the query cannot be reached, the
   transaction stays pending and the worker retries.
4. A **verified** `Payment` is created with the M-Pesa receipt (unique, so one transaction can never be
   recorded twice). An amount mismatch is saved as *pending verification* for staff review.
5. A receipt number is issued and the tenant is notified. A success that arrives after the local timeout is
   still credited, because the money has moved.

Production checklist: switch to `production`, use the paybill/till shortcode and production passkey, set
`MPESA_TRANSACTION_TYPE` (`CustomerPayBillOnline` or `CustomerBuyGoodsOnline`), restrict
`MPESA_ALLOWED_CALLBACK_IPS` to Safaricom's published callback IPs, and complete Safaricom go-live approval.

Bank transfers are **not** detected automatically. Staff record them under *Rent & payments*, and an
administrator or landlord verifies them.

## M-Pesa Send Money to the landlord's phone number (`+254112157383`)

**Configured:** the landlord's designated rent-receiving number is **`+254112157383`**. It is stored in
*Settings → Company profile → Rent by M-Pesa Send Money* (`CompanySettings.rent_receiving_phone`), set by
migration `accounts/0004` (only when the field was empty) and enabled. Admins and landlords can change or
disable it there; the number is validated as a Safaricom MSISDN.

**What this is, and what it is not.** A personal phone number is **not** a Paybill or Till number. Daraja
STK Push and C2B confirmations work only with a business shortcode (`BusinessShortCode`, `PartyB`), so the
system **does not and cannot** send STK prompts to this number, and Safaricom sends the system **no
notification** when money arrives on it. The supported workflow is therefore manual reconciliation:

1. The tenant opens *Pay rent → Send Money to landlord*. The portal shows the number (only to signed-in
   tenants, never on the public website) and how to pay from the M-Pesa app.
2. After paying, the tenant enters the M-Pesa transaction code (10 characters), amount and date. This creates
   a payment with `method=mpesa_phone`, `source=tenant`, status **pending**. The balance, receipts and
   reports do **not** change.
3. Administrators and landlords get an in-app alert. They check the code and amount **on the M-Pesa statement
   or SMS for `+254112157383`**, then *Verify* (receipt issued, balance updated, tenant notified) or *Reject*
   with a reason. Managers can see but not verify (segregation of duties).
4. Safeguards: a code can be recorded only once across all payments (including STK receipts and staff
   entries). Future dates and dates over 60 days old are refused. There are at most 5 pending reports per
   tenancy. Requests are rate-limited, and every report and verification is in the audit log.

Nothing in the system claims that money reached this number. Only a staff member who has checked the
M-Pesa statement can mark it verified.

### Getting automatic M-Pesa confirmation (needs Safaricom setup and credentials)
To have payments confirmed automatically (STK prompt on the tenant's phone, instant receipt), the landlord
needs a **business shortcode** linked to the account where rent should land:

| Option | What to obtain | System settings |
|---|---|---|
| Lipa na M-Pesa **Till** (Buy Goods) | Till number + store number from Safaricom | `MPESA_SHORTCODE=<store/head office number>`, `MPESA_TRANSACTION_TYPE=CustomerBuyGoodsOnline` |
| **Paybill** | Paybill number (account number = unit reference) | `MPESA_SHORTCODE=<paybill>`, `MPESA_TRANSACTION_TYPE=CustomerPayBillOnline` |

Then, for either option: Daraja production app (**consumer key/secret**), the **Lipa na M-Pesa Online
passkey**, Safaricom **go-live approval**, a public HTTPS callback URL, and Safaricom's current callback IP
list for `MPESA_ALLOWED_CALLBACK_IPS`. Pochi la Biashara (a business wallet on a personal number) has
no Daraja API, so it would still need manual verification as above. The Send Money flow can stay enabled
alongside STK as a fallback.

## Email
```
NOTIFY_EMAIL_ENABLED=true
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.yourprovider.com
EMAIL_PORT=587
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
EMAIL_USE_TLS=true
DEFAULT_FROM_EMAIL=Your Company <no-reply@yourdomain.co.ke>
FRONTEND_URL=https://yourdomain.co.ke
```
While `NOTIFY_EMAIL_ENABLED=false`, emails (including invitation and password-reset links) are only written
to the notification log, which administrators can read during development.

## SMS – Africa's Talking
```
SMS_PROVIDER=africastalking
AFRICASTALKING_USERNAME=sandbox          # your username in live mode
AFRICASTALKING_API_KEY=...
AFRICASTALKING_SENDER_ID=                # approved alphanumeric sender ID (optional)
AFRICASTALKING_SANDBOX=true
```
Phone numbers should be stored in international format (`+2547...`) for live delivery.

## WhatsApp – Meta WhatsApp Cloud API
```
WHATSAPP_PROVIDER=meta
WHATSAPP_TOKEN=...
WHATSAPP_PHONE_NUMBER_ID=...
```
Meta only allows free-form messages within 24 hours of the customer's last message. Business-initiated
reminders need **pre-approved message templates**; adapt `MetaWhatsApp.send` in
`backend/communications/providers.py` to send template messages before going live.

## Message content rules
SMS and WhatsApp texts are short alerts with a secure link to the portal. They never contain statements,
full balances history or documents. Wording is editable under *Settings → Message templates*. Reminders
never threaten eviction or add penalties, and they stop automatically once the balance is settled.
