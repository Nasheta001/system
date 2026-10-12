"""End-to-end smoke test against a running stack with FRESH demo data.

    BASE=http://localhost:4200 python scripts/e2e_smoke.py                  # dev servers (DEBUG on)
    BASE=http://localhost:8080 TOKENS=docker python scripts/e2e_smoke.py    # Docker stack (DEBUG off)

Run `manage.py seed_demo --reset` first. Needs `requests` (installed in backend/.venv).
Mimics the browser: session cookie + XSRF-TOKEN cookie echoed in X-XSRF-TOKEN.

Invitation tokens are only emailed. With DEBUG on, the API returns a development link. With DEBUG off
(TOKENS=docker) the script reads the logged email from the Docker database, as an administrator would
read the notification log on a server where email delivery is not configured.
"""
import os
import subprocess
import sys
import time
from datetime import date

import requests

BASE = os.environ.get("BASE", "http://localhost:4200")
TOKENS = os.environ.get("TOKENS", "api")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PW = "Demo@2026!"
NEWPW = "Smoke-Invite-Pass-2026!"
results = []


def check(name, cond, info=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info and not cond else ""))


def session():
    s = requests.Session()
    s.get(f"{BASE}/api/auth/csrf/").raise_for_status()
    return s


def unsafe(s, method, url, **kw):
    headers = kw.pop("headers", {})
    headers["X-XSRF-TOKEN"] = s.cookies.get("XSRF-TOKEN", "")
    return s.request(method, f"{BASE}{url}", headers=headers, **kw)


def login(s, email, password, portal):
    return unsafe(s, "POST", "/api/auth/login/", json={"email": email, "password": password, "portal": portal})


def invite_token(response_json, email):
    link = response_json.get("dev_invite_link")
    if link:
        return link.split("#token=")[1]
    if TOKENS != "docker":
        return None
    code = ("from communications.models import Notification as N;"
            f"n=N.objects.filter(to_address='{email}',channel='email',template_key__endswith='_invite').latest('id');"
            "print(n.body.split('#token=')[1].split()[0])")
    out = subprocess.run(["docker", "compose", "exec", "-T", "backend", "python", "manage.py", "shell", "-c", code],
                         capture_output=True, text=True, cwd=ROOT)
    lines = out.stdout.strip().splitlines()
    return lines[-1] if lines else None


# wait for servers
for _ in range(90):
    try:
        if requests.get(f"{BASE}/api/public/company/", timeout=3).status_code == 200:
            break
    except Exception:
        pass
    time.sleep(2)
else:
    print("Servers not reachable")
    sys.exit(1)

# ---------------------------------------------------------------- public
r = requests.get(f"{BASE}/")
check("SPA index served", r.status_code == 200 and "<app-root>" in r.text)
props = requests.get(f"{BASE}/api/public/properties/").json()
check("public listing returns published properties", len(props) >= 4, len(props))
check("unpublished property hidden", all(p["name"] != "Mwembeni Residences" for p in props))
check("demo properties use Mombasa-area names",
      {"Bamburi Heights", "Kisauni Gardens"} <= {p["name"] for p in props}
      and not any(x in str(props) for x in ("Kilimani", "Ruaka", "Kisumu", "Nairobi")))
check("login chooser page served", requests.get(f"{BASE}/login").status_code == 200)
check("landlord number not on public API", "112157383" not in requests.get(f"{BASE}/api/public/company/").text)
detail = requests.get(f"{BASE}/api/public/properties/{props[0]['slug']}/").json()
check("property detail has units & photos", "units" in detail and len(detail["photos"]) > 0)
check("public detail exposes no tenant data", "tenant" not in str(detail).lower())
u = detail["photos"][0]["url"]
photo = requests.get(u if u.startswith("http") else BASE + u)
check("property photo served via /media", photo.status_code == 200 and photo.headers["Content-Type"].startswith("image"))

anon = session()
unit_id = detail["units"][0]["id"]
r = unsafe(anon, "POST", "/api/public/applications/", json={
    "unit": unit_id, "full_name": "Smoke Applicant", "email": "smoke@demo.propman.test", "phone": "0711000000",
    "consent_given": True})
check("public application submitted", r.status_code == 201, r.text[:200])
ref = r.json().get("reference")
r = unsafe(anon, "POST", "/api/public/applications/status/", json={"reference": ref, "email": "smoke@demo.propman.test"})
check("application status lookup", r.status_code == 200 and r.json()["status"] == "pending")
r = unsafe(anon, "POST", "/api/public/viewing-requests/", json={
    "property": props[0]["slug"], "full_name": "Viewer", "phone": "0711000001", "consent_given": True})
check("viewing request submitted", r.status_code == 201, r.text[:200])

# ---------------------------------------------------------------- no public registration
check("no public sign-up endpoint", unsafe(anon, "POST", "/api/auth/register/", json={}).status_code == 404)
check("anonymous cannot invite staff", unsafe(anon, "POST", "/api/staff-invitations/", json={
    "email": "x@demo.propman.test", "first_name": "X", "role": "admin"}).status_code in (401, 403))
setup = requests.get(f"{BASE}/api/auth/setup/").json()
check("initial setup closed (administrator exists)", setup["setup_required"] is False, setup)
check("setup POST refused", unsafe(anon, "POST", "/api/auth/setup/", json={
    "email": "evil@demo.propman.test", "first_name": "E", "password": "Evil-Str0ng-Pass!"}).status_code == 403)

# ---------------------------------------------------------------- CSRF enforcement
s = session()
r = login(s, "admin@demo.propman.test", PW, "management")
check("admin login", r.status_code == 200, r.text[:200])
r = s.post(f"{BASE}/api/properties/", json={"name": "No CSRF", "address": "x", "county": "y", "town": "z"})
check("authenticated POST without CSRF token rejected", r.status_code == 403, r.status_code)

# ---------------------------------------------------------------- management flows
d = s.get(f"{BASE}/api/dashboard/").json()
check("dashboard figures", d["properties"] == 5 and d["units"]["total"] > 20 and d["financials"] is not None, d.get("units"))

r = unsafe(s, "POST", "/api/properties/", json={"name": "Smoke Towers", "address": "1 Smoke Rd", "county": "Mombasa",
                                                 "town": "Mombasa", "neighbourhood": "Bamburi"})
check("create property", r.status_code == 201, r.text[:200])
pid = r.json()["id"]
types = s.get(f"{BASE}/api/unit-types/").json()
r = unsafe(s, "POST", "/api/units/", json={"property": pid, "unit_type": types[2]["id"], "unit_number": "S1",
                                            "rent_amount": "30000", "deposit_amount": "30000", "rent_due_day": 5,
                                            "is_listed": True})
check("create unit", r.status_code == 201, r.text[:200])
uid = r.json()["id"]
check("publish property", unsafe(s, "POST", f"/api/properties/{pid}/publish/").json()["is_published"])
check("new property visible publicly",
      any(p["name"] == "Smoke Towers" for p in requests.get(f"{BASE}/api/public/properties/").json()))

r = unsafe(s, "POST", "/api/tenants/", json={
    "first_name": "Smoke", "last_name": "Tenant", "phone": "0712000999", "email": "smoke.tenant@demo.propman.test",
    "create_portal_account": True, "unit": uid, "start_date": str(date.today().replace(day=1)),
    "notify_sms": True, "notify_email": True})
check("register tenant + move in", r.status_code == 201, r.text[:300])
tid = r.json()["id"]
check("dev link only when DEBUG", ("dev_invite_link" in r.json()) == (TOKENS != "docker"))
smoke_tenant_token = invite_token(r.json(), "smoke.tenant@demo.propman.test")
check("tenant portal invitation issued, no account yet",
      bool(smoke_tenant_token) and s.get(f"{BASE}/api/tenants/{tid}/").json()["has_portal_account"] is False)
ten = s.get(f"{BASE}/api/tenancies/", params={"tenant": tid}).json()["results"][0]
check("unit now occupied", s.get(f"{BASE}/api/units/{uid}/").json()["status"] == "occupied")
check("rent + deposit charged", float(ten["account"]["balance"]) == 60000.0, ten["account"]["balance"])

r = unsafe(s, "POST", "/api/payments/", json={"tenancy": ten["id"], "amount": "25000", "method": "bank",
                                               "reference": "SMOKE-BNK-1", "paid_on": str(date.today()),
                                               "mark_verified": True})
check("record & verify manual payment", r.status_code == 201 and r.json()["status"] == "verified", r.text[:200])
pay_id = r.json()["id"]
rc = s.get(f"{BASE}/api/payments/{pay_id}/receipt/")
check("receipt PDF downloads", rc.status_code == 200 and rc.content[:4] == b"%PDF")
led = s.get(f"{BASE}/api/tenancies/{ten['id']}/ledger/").json()
check("partial payment reflected in balance", float(led["account"]["balance"]) == 35000.0, led["account"]["balance"])

r = unsafe(s, "POST", "/api/announcements/", json={"title": "Smoke notice", "body": "Hello Smoke Towers",
                                                    "audience": "properties", "property_ids": [pid],
                                                    "requires_acknowledgement": True})
check("create announcement", r.status_code == 201, r.text[:200])
ann = unsafe(s, "POST", f"/api/announcements/{r.json()['id']}/publish/").json()
check("announcement targets only that property", ann["stats"]["recipients"] == 1, ann["stats"])

csv = s.get(f"{BASE}/api/reports/arrears/", params={"export": "csv"})
check("arrears CSV export", csv.status_code == 200 and "Smoke Tenant" in csv.content.decode("utf-8-sig"))
check("audit log has entries", s.get(f"{BASE}/api/audit-logs/").json()["count"] > 5)
check("notification log reachable", s.get(f"{BASE}/api/notification-log/").status_code == 200)
jobs = unsafe(s, "POST", "/api/system/run-jobs/").json()
check("scheduled jobs run", "reminders_sent" in jobs, jobs)

# ---------------------------------------------------------------- caretaker restrictions
c = session()
login(c, "caretaker@demo.propman.test", PW, "management")
cprops = c.get(f"{BASE}/api/properties/").json()["results"]
check("caretaker sees only assigned property", [p["name"] for p in cprops] == ["Bamburi Heights"], [p["name"] for p in cprops])
check("caretaker blocked from payments", c.get(f"{BASE}/api/payments/").status_code == 403)
check("caretaker cannot open new property", c.get(f"{BASE}/api/properties/{pid}/").status_code == 404)
check("caretaker cannot invite staff", unsafe(c, "POST", "/api/staff-invitations/", json={
    "email": "y@demo.propman.test", "first_name": "Y", "role": "admin"}).status_code == 403)

# ---------------------------------------------------------------- tenant portal (STK, simulated)
t = session()
r = login(t, "tenant@demo.propman.test", PW, "tenant")
check("tenant login", r.status_code == 200, r.text[:200])
check("tenant cannot use management login",
      login(session(), "tenant@demo.propman.test", PW, "management").status_code == 400)
dash = t.get(f"{BASE}/api/portal/dashboard/").json()
check("tenant dashboard", dash["tenancy"]["unit"].endswith("A3"), dash.get("tenancy"))
bal_before = float(dash["account"]["balance"])
check("demo tenant has outstanding rent", bal_before > 0, bal_before)
r = unsafe(t, "POST", "/api/portal/payments/mpesa/", json={"phone": "0712345678", "amount": str(int(bal_before))})
check("STK push initiated (simulated)", r.status_code == 201 and r.json()["is_simulated"], r.text[:200])
txn = r.json()
check("initiating does not change balance",
      float(t.get(f"{BASE}/api/portal/dashboard/").json()["account"]["balance"]) == bal_before)
r = unsafe(t, "POST", f"/api/portal/payments/mpesa/{txn['id']}/simulate/", json={"outcome": "success"})
check("simulated approval recorded", r.json()["status"] == "success" and r.json()["receipt_number"], r.text[:200])
after = float(t.get(f"{BASE}/api/portal/dashboard/").json()["account"]["balance"])
check("balance cleared after verified payment", after == 0, after)
acc = t.get(f"{BASE}/api/portal/account/").json()
sim = [p for p in acc["payments"] if p["is_simulated"]]
check("payment flagged as simulated", len(sim) == 1)
rc = t.get(f"{BASE}/api/portal/payments/{sim[0]['id']}/receipt/")
check("tenant downloads own receipt", rc.status_code == 200 and rc.content[:4] == b"%PDF")
check("tenant cannot download other tenant's receipt",
      t.get(f"{BASE}/api/portal/payments/{pay_id}/receipt/").status_code == 404)
check("tenant blocked from staff API", t.get(f"{BASE}/api/tenants/").status_code == 403)
docs = t.get(f"{BASE}/api/portal/documents/").json()
check("tenant sees library + own agreement", any("House rules" in x["title"] for x in docs) and any("agreement" in x["title"].lower() for x in docs))
anns = t.get(f"{BASE}/api/portal/announcements/").json()["results"]
check("tenant sees property notices", any("Bamburi" in a["title"] for a in anns))
check("tenant doesn't see Smoke Towers notice", not any(a["title"] == "Smoke notice" for a in anns))
r = unsafe(t, "POST", "/api/portal/maintenance/", data={"title": "Smoke leak", "description": "Testing", "category": "plumbing", "urgency": "normal"})
check("tenant submits maintenance request", r.status_code == 201, r.text[:200])
check("tenant logout", unsafe(t, "POST", "/api/auth/logout/").status_code == 204)
check("session ended", t.get(f"{BASE}/api/portal/dashboard/").status_code == 401)

# ---------------------------------------------------------------- staff invitation lifecycle
r = unsafe(s, "POST", "/api/staff-invitations/", json={"email": "smoke.caretaker@demo.propman.test",
                                                       "first_name": "Smoke", "role": "caretaker",
                                                       "property_ids": [pid]})
check("admin invites caretaker", r.status_code == 201, r.text[:200])
tok = invite_token(r.json(), "smoke.caretaker@demo.propman.test")
check("invitation token valid", unsafe(anon, "POST", "/api/auth/invitations/check/", json={"token": tok}).status_code == 200)
r = unsafe(anon, "POST", "/api/auth/invitations/accept/", json={"token": tok, "password": NEWPW, "role": "admin"})
check("caretaker accepts (role taken from invitation)", r.status_code == 201 and r.json()["role"] == "caretaker", r.text[:200])
check("invitation cannot be reused",
      unsafe(anon, "POST", "/api/auth/invitations/accept/", json={"token": tok, "password": NEWPW}).status_code == 400)
nc = session()
check("invited caretaker signs in", login(nc, "smoke.caretaker@demo.propman.test", NEWPW, "management").status_code == 200)
check("invited caretaker scoped to Smoke Towers",
      [p["name"] for p in nc.get(f"{BASE}/api/properties/").json()["results"]] == ["Smoke Towers"])
r = unsafe(s, "POST", "/api/staff-invitations/", json={"email": "smoke.revoked@demo.propman.test",
                                                       "first_name": "Rev", "role": "manager"})
rtok = invite_token(r.json(), "smoke.revoked@demo.propman.test")
unsafe(s, "POST", f"/api/staff-invitations/{r.json()['id']}/revoke/")
check("revoked invitation rejected",
      unsafe(anon, "POST", "/api/auth/invitations/accept/", json={"token": rtok, "password": NEWPW}).status_code == 400)
staff_id = s.get(f"{BASE}/api/staff/", params={"search": "smoke.caretaker"}).json()["results"][0]["id"]
unsafe(s, "POST", f"/api/staff/{staff_id}/deactivate/")
check("deactivation ends caretaker session", nc.get(f"{BASE}/api/properties/").status_code in (401, 403))
check("deactivated caretaker cannot sign in",
      login(session(), "smoke.caretaker@demo.propman.test", NEWPW, "management").status_code == 400)

# ---------------------------------------------------------------- tenant invitation + Send Money rent
r = unsafe(anon, "POST", "/api/auth/invitations/accept/", json={"token": smoke_tenant_token, "password": NEWPW})
check("tenant accepts portal invitation", r.status_code == 201 and r.json()["portal"] == "tenant", r.text[:200])
st = session()
check("invited tenant signs in", login(st, "smoke.tenant@demo.propman.test", NEWPW, "tenant").status_code == 200)
cfg = st.get(f"{BASE}/api/portal/payments/phone-report/").json()
check("tenant sees landlord's rent number", cfg == {"enabled": True, "phone": "+254112157383", "name": ""}, cfg)
bal = float(st.get(f"{BASE}/api/portal/account/").json()["account"]["balance"])
code = "SMK" + str(int(time.time()))[-7:]
r = unsafe(st, "POST", "/api/portal/payments/phone-report/", json={"mpesa_code": code, "amount": "5000",
                                                                    "paid_on": str(date.today())})
check("tenant reports Send Money payment", r.status_code == 201 and r.json()["status"] == "pending", r.text[:200])
pending_id = r.json().get("id")
check("reported payment does not change balance",
      float(st.get(f"{BASE}/api/portal/account/").json()["account"]["balance"]) == bal)
check("duplicate M-Pesa code rejected", unsafe(st, "POST", "/api/portal/payments/phone-report/", json={
    "mpesa_code": code, "amount": "5000", "paid_on": str(date.today())}).status_code == 400)
v = unsafe(s, "POST", f"/api/payments/{pending_id}/verify/").json()
check("admin verifies against M-Pesa statement", v.get("status") == "verified" and v.get("receipt_number"), v)
check("verified payment reduces balance",
      float(st.get(f"{BASE}/api/portal/account/").json()["account"]["balance"]) == bal - 5000)

# ---------------------------------------------------------------- move-out revokes access
r = unsafe(s, "POST", f"/api/tenancies/{ten['id']}/move-out/", json={"actual_move_out": str(date.today())})
check("move-out completed", r.status_code == 200, r.text[:200])
check("moved-out tenant session revoked", st.get(f"{BASE}/api/portal/account/").status_code in (401, 403))
check("moved-out tenant cannot sign in",
      login(session(), "smoke.tenant@demo.propman.test", NEWPW, "tenant").status_code in (400, 403))
check("history kept for staff", len(s.get(f"{BASE}/api/tenancies/{ten['id']}/ledger/").json()["rows"]) > 0)

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
