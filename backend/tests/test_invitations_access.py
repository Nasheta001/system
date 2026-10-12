"""Invitation-only accounts, initial setup, revocation and moved-out tenants,
plus the Send Money rent workflow for the landlord's phone number."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.sessions.models import Session
from django.core import mail
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts import invitations
from accounts.models import CompanySettings, Invitation, Role, User
from billing.models import Payment
from billing.services import account_summary
from communications.models import Notification
from tenancies.models import Tenant
from tenancies.services import complete_move_out

from .base import PASSWORD, BaseTestCase

NEW_PASSWORD = "Fresh-Str0ng-Pass!"
FIXTURE_SETUP = "fixture-" + "setup-value"  # test-only value, not a real secret


def with_token(inv, raw="tok-" + "x" * 20):
    """Give an invitation a known token (the real one is only emailed)."""
    inv.token_hash = invitations.hash_token(raw)
    inv.save(update_fields=["token_hash"])
    return raw


class RegistrationLockdownTests(BaseTestCase):
    def test_no_public_registration_endpoints(self):
        anon = APIClient()
        for url in ["/api/auth/register/", "/api/auth/signup/", "/api/register/"]:
            self.assertEqual(anon.post(url, {"email": "x@x.test", "password": NEW_PASSWORD}).status_code, 404, url)
        self.assertEqual(anon.post("/api/staff/", {"email": "x@x.test", "role": "admin"}).status_code, 401)
        self.assertEqual(anon.post("/api/staff-invitations/", {"email": "x@x.test", "role": "admin",
                                                               "first_name": "X"}).status_code, 401)

    def test_only_administrators_can_invite_staff(self):
        body = {"email": "boss@x.test", "first_name": "Boss", "role": "admin"}
        t, _ = self.make_tenant("Tia", self.u1)
        for user in (self.landlord, self.manager, self.caretaker, t.user):
            r = self.login(user).post("/api/staff-invitations/", body, format="json")
            self.assertEqual(r.status_code, 403, user.role)
        self.assertFalse(Invitation.objects.exists())
        r = self.login(self.admin).post("/api/staff-invitations/", body, format="json")
        self.assertEqual(r.status_code, 201)

    def test_login_never_creates_accounts(self):
        r = APIClient().post("/api/auth/login/", {"email": "nobody@x.test", "password": NEW_PASSWORD,
                                                  "portal": "management"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(User.objects.filter(email="nobody@x.test").exists())


class InitialSetupTests(BaseTestCase):
    def body(self, **kw):
        return {"email": "first@x.test", "first_name": "First", "password": NEW_PASSWORD, **kw}

    def test_setup_refused_when_an_administrator_exists(self):
        with override_settings(DEBUG=True):
            r = APIClient().get("/api/auth/setup/")
            self.assertFalse(r.data["setup_required"])
            r = APIClient().post("/api/auth/setup/", self.body(), format="json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(User.objects.filter(email="first@x.test").exists())

    def test_setup_needs_token_in_production_and_runs_once(self):
        User.objects.filter(role=Role.ADMIN).update(is_active=False)
        with override_settings(DEBUG=False, SETUP_TOKEN=""):
            self.assertEqual(APIClient().post("/api/auth/setup/", self.body(), format="json").status_code, 403)
        with override_settings(DEBUG=False, SETUP_TOKEN=FIXTURE_SETUP):
            self.assertTrue(APIClient().get("/api/auth/setup/").data["available"])
            r = APIClient().post("/api/auth/setup/", self.body(setup_token="wrong"), format="json")
            self.assertEqual(r.status_code, 403)
            r = APIClient().post("/api/auth/setup/", self.body(setup_token=FIXTURE_SETUP), format="json")
            self.assertEqual(r.status_code, 201, r.data)
            again = APIClient().post("/api/auth/setup/", self.body(email="second@x.test",
                                                                  setup_token=FIXTURE_SETUP), format="json")
            self.assertEqual(again.status_code, 403)
        u = User.objects.get(email="first@x.test")
        self.assertEqual(u.role, Role.ADMIN)
        self.assertFalse(User.objects.filter(email="second@x.test").exists())


class StaffInvitationTests(BaseTestCase):
    def invite(self, **kw):
        body = {"email": "new.manager@x.test", "first_name": "Nia", "role": "manager",
                "property_ids": [self.p1.pk], **kw}
        r = self.login(self.admin).post("/api/staff-invitations/", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return Invitation.objects.get(pk=r.data["id"])

    def accept(self, raw, password=NEW_PASSWORD, **extra):
        return APIClient().post("/api/auth/invitations/accept/", {"token": raw, "password": password, **extra},
                                format="json")

    def test_token_is_hashed_and_email_sent(self):
        inv = self.invite()
        self.assertEqual(len(inv.token_hash), 64)
        n = Notification.objects.get(template_key="staff_invite", to_address="new.manager@x.test")
        self.assertIn("/account/accept-invite#token=", n.body)
        raw = n.body.split("#token=")[1].split()[0]
        self.assertEqual(invitations.hash_token(raw), inv.token_hash)
        self.assertEqual(APIClient().post("/api/auth/invitations/check/", {"token": raw}).status_code, 200)

    def test_accept_creates_account_with_invited_role_only(self):
        raw = with_token(self.invite())
        r = self.accept(raw, role="admin", email="evil@x.test", is_superuser=True)
        self.assertEqual(r.status_code, 201, r.data)
        u = User.objects.get(email="new.manager@x.test")
        self.assertEqual(u.role, Role.MANAGER)
        self.assertFalse(u.is_superuser or u.is_staff)
        self.assertFalse(User.objects.filter(email="evil@x.test").exists())
        self.assertEqual(set(u.assignments.values_list("property_id", flat=True)), {self.p1.pk})
        login = APIClient().post("/api/auth/login/", {"email": u.email, "password": NEW_PASSWORD,
                                                      "portal": "management"}, format="json")
        self.assertEqual(login.status_code, 200)

    def test_invitation_is_single_use(self):
        raw = with_token(self.invite())
        self.assertEqual(self.accept(raw).status_code, 201)
        self.assertEqual(self.accept(raw, password="Other-Str0ng-Pass!").status_code, 400)
        self.assertEqual(APIClient().post("/api/auth/invitations/check/", {"token": raw}).status_code, 400)

    def test_expired_invitation_is_rejected(self):
        inv = self.invite()
        raw = with_token(inv)
        inv.expires_at = timezone.now() - timedelta(minutes=1)
        inv.save()
        self.assertEqual(self.accept(raw).status_code, 400)
        self.assertFalse(User.objects.filter(email=inv.email).exists())

    def test_revoked_invitation_is_rejected(self):
        inv = self.invite()
        raw = with_token(inv)
        self.assertEqual(self.client.post(f"/api/staff-invitations/{inv.pk}/revoke/").status_code, 200)
        self.assertEqual(self.accept(raw).status_code, 400)

    def test_resend_disables_previous_link(self):
        inv = self.invite()
        old = with_token(inv)
        r = self.client.post(f"/api/staff-invitations/{inv.pk}/resend/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.accept(old).status_code, 400)
        inv.refresh_from_db()
        self.assertEqual(inv.sent_count, 2)

    def test_weak_password_keeps_invitation_open(self):
        raw = with_token(self.invite())
        r = self.accept(raw, password="password")
        self.assertEqual(r.status_code, 400)
        self.assertIn("password", r.data)
        self.assertEqual(self.accept(raw).status_code, 201)

    def test_existing_email_cannot_be_invited(self):
        r = self.login(self.admin).post("/api/staff-invitations/", {"email": self.manager.email, "first_name": "M",
                                                                    "role": "admin"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_dev_link_only_when_debug(self):
        r = self.login(self.admin).post("/api/staff-invitations/", {"email": "a@x.test", "first_name": "A",
                                                                    "role": "caretaker"}, format="json")
        self.assertNotIn("dev_invite_link", r.data)
        with override_settings(DEBUG=True):
            r = self.client.post("/api/staff-invitations/", {"email": "b@x.test", "first_name": "B",
                                                             "role": "caretaker"}, format="json")
        self.assertIn("#token=", r.data["dev_invite_link"])
        # The notification log never shows the secret link outside DEBUG
        rows = self.client.get("/api/notification-log/", {"template_key": "staff_invite"}).data
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        self.assertTrue(rows)
        for n in rows:
            self.assertNotIn("#token=", n["body"])


class StaffDeactivationTests(BaseTestCase):
    def test_deactivation_ends_sessions_immediately(self):
        mgr = APIClient()
        mgr.force_login(self.manager)
        self.assertEqual(mgr.get("/api/properties/").status_code, 200)
        self.login(self.admin).post(f"/api/staff/{self.manager.pk}/deactivate/")
        self.assertIn(mgr.get("/api/properties/").status_code, (401, 403))
        uid = str(self.manager.pk)
        self.assertFalse(any(s.get_decoded().get("_auth_user_id") == uid for s in Session.objects.all()))
        r = APIClient().post("/api/auth/login/", {"email": self.manager.email, "password": PASSWORD,
                                                  "portal": "management"}, format="json")
        self.assertEqual(r.status_code, 400)


class TenantInvitationTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.tenant, self.tenancy = self.make_tenant("Wanjiru", self.u1, portal=False)

    def invite(self, user=None):
        return self.login(user or self.manager).post(f"/api/tenants/{self.tenant.pk}/portal-account/")

    def test_invitation_requires_current_tenancy(self):
        loose = Tenant.objects.create(first_name="No", last_name="Unit", email="nounit@x.test", phone="0712000000",
                                      created_by=self.manager)
        r = self.login(self.manager).post(f"/api/tenants/{loose.pk}/portal-account/")
        self.assertIn(r.status_code, (400, 404))
        self.assertFalse(Invitation.objects.filter(tenant=loose).exists())
        r = self.client.post("/api/tenants/", {"first_name": "Z", "last_name": "Z", "phone": "0712000001",
                                               "email": "z@x.test", "create_portal_account": True}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("create_portal_account", r.data)

    def test_manager_cannot_invite_tenant_of_other_property(self):
        r = self.invite(self.manager2)
        self.assertEqual(r.status_code, 404)
        self.assertFalse(Invitation.objects.exists())

    def test_accept_links_login_to_tenant_record(self):
        self.assertEqual(self.invite().status_code, 201)
        inv = Invitation.objects.get(tenant=self.tenant)
        self.assertEqual(inv.tenancy, self.tenancy)
        raw = with_token(inv)
        r = APIClient().post("/api/auth/invitations/accept/", {"token": raw, "password": NEW_PASSWORD},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["portal"], "tenant")
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.user.role, Role.TENANT)
        c = APIClient()
        r = c.post("/api/auth/login/", {"email": self.tenant.email, "password": NEW_PASSWORD, "portal": "tenant"},
                   format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.get("/api/portal/dashboard/").status_code, 200)

    def test_id_number_alone_grants_nothing(self):
        self.tenant.id_number = "12345678"
        self.tenant.save()
        self.invite()
        anon = APIClient()
        for body in [{"id_number": "12345678", "email": self.tenant.email, "password": NEW_PASSWORD},
                     {"token": "12345678", "password": NEW_PASSWORD}]:
            self.assertEqual(anon.post("/api/auth/invitations/accept/", body, format="json").status_code, 400)
        self.assertEqual(anon.post("/api/auth/invitations/check/", {"token": "12345678"}).status_code, 400)
        self.tenant.refresh_from_db()
        self.assertIsNone(self.tenant.user)

    def test_revoked_tenant_invitation_fails(self):
        self.invite()
        raw = with_token(Invitation.objects.get(tenant=self.tenant))
        self.assertEqual(self.client.post(f"/api/tenants/{self.tenant.pk}/portal-invite/revoke/").status_code, 200)
        r = APIClient().post("/api/auth/invitations/accept/", {"token": raw, "password": NEW_PASSWORD},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_invitation_dies_when_tenancy_ends_before_acceptance(self):
        self.invite()
        inv = Invitation.objects.get(tenant=self.tenant)
        raw = with_token(inv)
        complete_move_out(self.tenancy, actual_move_out=date.today(), notify=False)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "revoked")
        r = APIClient().post("/api/auth/invitations/accept/", {"token": raw, "password": NEW_PASSWORD},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(User.objects.filter(email=self.tenant.email).exists())


class MovedOutTenantTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.tenant, self.tenancy = self.make_tenant("Otieno", self.u1, charge_deposit=False)
        self.pay(self.tenancy, "5000")
        self.portal = APIClient()
        self.portal.force_login(self.tenant.user)
        self.assertEqual(self.portal.get("/api/portal/account/").status_code, 200)
        complete_move_out(self.tenancy, actual_move_out=date.today(), notify=False)
        self.tenant.user.refresh_from_db()

    def test_sessions_revoked_and_login_blocked(self):
        self.assertFalse(self.tenant.user.is_active)
        self.assertIn(self.portal.get("/api/portal/account/").status_code, (401, 403))
        r = APIClient().post("/api/auth/login/", {"email": self.tenant.email, "password": PASSWORD,
                                                  "portal": "tenant"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_reactivated_login_without_tenancy_still_blocked(self):
        User.objects.filter(pk=self.tenant.user_id).update(is_active=True)
        c = APIClient()
        r = c.post("/api/auth/login/", {"email": self.tenant.email, "password": PASSWORD, "portal": "tenant"},
                   format="json")
        self.assertEqual(r.status_code, 403)
        c.force_login(self.tenant.user)
        for url in ["/api/portal/account/", "/api/portal/dashboard/", "/api/portal/documents/",
                    "/api/portal/maintenance/"]:
            self.assertEqual(c.get(url).status_code, 403, url)
        mail.outbox.clear()
        APIClient().post("/api/auth/password/reset/", {"email": self.tenant.email})
        self.assertFalse(Notification.objects.filter(template_key="password_reset",
                                                     to_address=self.tenant.email).exists())

    def test_staff_cannot_reenable_without_tenancy(self):
        r = self.login(self.manager).post(f"/api/tenants/{self.tenant.pk}/portal-access/", {"enabled": True})
        self.assertEqual(r.status_code, 400)

    def test_history_preserved_for_staff(self):
        self.assertEqual(Payment.objects.filter(tenancy=self.tenancy).count(), 1)
        r = self.login(self.manager).get(f"/api/tenancies/{self.tenancy.pk}/ledger/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["rows"])
        self.assertEqual(self.client.get(f"/api/tenants/{self.tenant.pk}/").data["status"], "former")


class PhoneRentPaymentTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ta, self.tenancy = self.make_tenant("Amina", self.u1, charge_deposit=False)
        self.tb, self.tenancy_b = self.make_tenant("Baraka", self.u4, charge_deposit=False)

    def report(self, user, **kw):
        body = {"mpesa_code": "SGH7XK2LQP", "amount": "5000", "paid_on": str(date.today()), **kw}
        return self.login(user).post("/api/portal/payments/phone-report/", body, format="json")

    def test_landlord_number_configured(self):
        c = CompanySettings.load()
        self.assertEqual(c.rent_receiving_phone, "+254112157383")
        self.assertTrue(c.rent_phone_payments_enabled)
        data = self.login(self.ta.user).get("/api/portal/account/").data
        self.assertEqual(data["send_money"], {"enabled": True, "phone": "+254112157383", "name": ""})
        # The number is not published on the public website API
        self.assertNotIn("112157383", str(APIClient().get("/api/public/company/").data))

    def test_report_is_pending_until_staff_verify(self):
        before = account_summary(self.tenancy).balance
        r = self.report(self.ta.user, mpesa_code="sgh7 xk2lqp")
        self.assertEqual(r.status_code, 201, r.data)
        p = Payment.objects.get(pk=r.data["id"])
        self.assertEqual((p.status, p.method, p.source, p.reference), ("pending", "mpesa_phone", "tenant", "SGH7XK2LQP"))
        self.assertIsNone(p.receipt_number)
        self.assertEqual(account_summary(self.tenancy).balance, before)
        # Caretakers and managers cannot verify; administrators can
        self.assertEqual(self.login(self.manager).post(f"/api/payments/{p.pk}/verify/").status_code, 403)
        r = self.login(self.admin).post(f"/api/payments/{p.pk}/verify/")
        self.assertEqual(r.data["status"], "verified")
        self.assertEqual(account_summary(self.tenancy).balance, before - Decimal("5000"))

    def test_duplicate_and_invalid_codes_rejected(self):
        self.assertEqual(self.report(self.ta.user).status_code, 201)
        self.assertEqual(self.report(self.tb.user).status_code, 400)  # same code by another tenant
        self.assertEqual(self.report(self.ta.user, mpesa_code="12").status_code, 400)
        future = str(date.today() + timedelta(days=1))
        self.assertEqual(self.report(self.ta.user, mpesa_code="SGH7XK2LQ9", paid_on=future).status_code, 400)
        r = self.login(self.admin).post("/api/payments/", {"tenancy": self.tenancy.pk, "amount": "5000",
                                                           "method": "mpesa_manual", "reference": "SGH7XK2LQP",
                                                           "paid_on": str(date.today())}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_tenant_cannot_report_against_another_tenancy(self):
        r = self.report(self.ta.user, tenancy=self.tenancy_b.pk)
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Payment.objects.filter(tenancy=self.tenancy_b).exists())

    def test_disabled_when_not_configured(self):
        CompanySettings.objects.filter(pk=1).update(rent_phone_payments_enabled=False)
        self.assertEqual(self.report(self.ta.user).status_code, 400)
        self.assertFalse(self.login(self.ta.user).get("/api/portal/account/").data["send_money"]["enabled"])

    def test_settings_validate_receiving_number(self):
        self.login(self.admin)
        r = self.client.patch("/api/settings/company/", {"rent_receiving_phone": "0112 157 383"}, format="json")
        self.assertEqual(r.data["rent_receiving_phone"], "+254112157383")
        r = self.client.patch("/api/settings/company/", {"rent_receiving_phone": "12345"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.login(self.manager).patch("/api/settings/company/", {"rent_receiving_phone": "+254700000000"},
                                           format="json")
        self.assertEqual(r.status_code, 403)
