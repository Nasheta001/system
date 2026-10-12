from rest_framework.test import APIClient

from accounts.models import AuditLog

from .base import PASSWORD, BaseTestCase


class AuthenticationTests(BaseTestCase):
    def test_unauthenticated_requests_get_401(self):
        for url in ["/api/properties/", "/api/tenants/", "/api/payments/", "/api/portal/dashboard/"]:
            self.assertEqual(APIClient().get(url).status_code, 401, url)

    def test_login_and_me(self):
        r = self.client.post("/api/auth/login/", {"email": "manager@x.test", "password": PASSWORD,
                                                  "portal": "management"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("view_payments", r.data["capabilities"])
        self.assertEqual([p["id"] for p in r.data["assigned_properties"]], [self.p1.pk])
        self.assertTrue(AuditLog.objects.filter(action="auth.login").exists())

    def test_wrong_password(self):
        r = self.client.post("/api/auth/login/", {"email": "manager@x.test", "password": "nope",
                                                  "portal": "management"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_tenant_cannot_use_management_login_and_vice_versa(self):
        t, _ = self.make_tenant("Tina", self.u1)
        r = self.client.post("/api/auth/login/", {"email": "tina@tenant.test", "password": PASSWORD,
                                                  "portal": "management"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/auth/login/", {"email": "manager@x.test", "password": PASSWORD,
                                                  "portal": "tenant"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/auth/login/", {"email": "tina@tenant.test", "password": PASSWORD,
                                                  "portal": "tenant"}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_deactivated_user_cannot_login(self):
        self.manager.is_active = False
        self.manager.save()
        r = self.client.post("/api/auth/login/", {"email": "manager@x.test", "password": PASSWORD,
                                                  "portal": "management"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_password_reset_does_not_reveal_accounts(self):
        a = self.client.post("/api/auth/password/reset/", {"email": "manager@x.test"}, format="json")
        b = self.client.post("/api/auth/password/reset/", {"email": "nobody@x.test"}, format="json")
        self.assertEqual(a.status_code, 200)
        self.assertEqual(a.data, b.data)

    def test_password_reset_confirm(self):
        from accounts.services import password_reset_link

        link = password_reset_link(self.manager)
        q = dict(part.split("=") for part in link.split("?")[1].split("&"))
        r = self.client.post("/api/auth/password/reset/confirm/",
                             {"uid": q["uid"], "token": q["token"], "new_password": "An0ther-Good-Pass"},
                             format="json")
        self.assertEqual(r.status_code, 200)
        self.manager.refresh_from_db()
        self.assertTrue(self.manager.check_password("An0ther-Good-Pass"))
        # token is single-use
        r = self.client.post("/api/auth/password/reset/confirm/",
                             {"uid": q["uid"], "token": q["token"], "new_password": "Yet-An0ther-Pass"},
                             format="json")
        self.assertEqual(r.status_code, 400)


class RolePermissionTests(BaseTestCase):
    def test_caretaker_sees_only_assigned_properties(self):
        r = self.login(self.caretaker).get("/api/properties/")
        self.assertEqual([p["id"] for p in r.data["results"]], [self.p1.pk])
        self.assertEqual(self.client.get(f"/api/properties/{self.p2.pk}/").status_code, 404)

    def test_caretaker_has_no_financial_access(self):
        self.login(self.caretaker)
        for url in ["/api/payments/", "/api/reports/arrears/", "/api/charges/"]:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        r = self.client.get("/api/dashboard/")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data["financials"])

    def test_caretaker_tenancy_view_hides_financials(self):
        _, tenancy = self.make_tenant("Fin", self.u1)
        r = self.login(self.caretaker).get(f"/api/tenancies/{tenancy.pk}/")
        self.assertEqual(r.status_code, 200)
        for field in ("monthly_rent", "deposit_amount", "account"):
            self.assertNotIn(field, r.data)
        r = self.login(self.manager).get(f"/api/tenancies/{tenancy.pk}/")
        self.assertIn("monthly_rent", r.data)

    def test_caretaker_cannot_edit_property(self):
        r = self.login(self.caretaker).patch(f"/api/properties/{self.p1.pk}/", {"name": "Hacked"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_caretaker_tenant_view_is_reduced(self):
        self.make_tenant("Carl", self.u1)
        r = self.login(self.caretaker).get("/api/tenants/")
        self.assertEqual(r.status_code, 200)
        row = r.data["results"][0]
        self.assertNotIn("id_number", row)
        self.assertNotIn("email", row)

    def test_manager_cannot_reach_other_property(self):
        self.login(self.manager)
        self.assertEqual(self.client.get(f"/api/units/{self.u4.pk}/").status_code, 404)
        r = self.client.post("/api/units/", {"property": self.p2.pk, "unit_type": self.one_bed.pk,
                                             "unit_number": "X9", "rent_amount": "1000"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_manager_cannot_create_properties_or_manage_staff(self):
        self.login(self.manager)
        r = self.client.post("/api/properties/", {"name": "New", "address": "a", "county": "c", "town": "t"},
                             format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get("/api/staff/").status_code, 403)

    def test_admin_invites_staff_with_assignments(self):
        from accounts.models import Invitation
        from accounts.invitations import accept_invitation, hash_token

        self.login(self.admin)
        # Accounts cannot be created directly any more – only by invitation
        r = self.client.post("/api/staff/", {"email": "new@x.test", "role": "caretaker"}, format="json")
        self.assertEqual(r.status_code, 405)
        r = self.client.post("/api/staff-invitations/", {"email": "new@x.test", "first_name": "New",
                                                         "role": "caretaker", "property_ids": [self.p2.pk]},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["property_names"], ["Beta Place"])
        raw = r.data["dev_invite_link"].split("#token=")[1] if "dev_invite_link" in r.data else None
        inv = Invitation.objects.get(pk=r.data["id"])
        if raw is None:  # DEBUG off in tests: issue a known token for the check
            raw = "known-test-token"
            inv.token_hash = hash_token(raw)
            inv.save()
        user, _ = accept_invitation(raw, "An0ther-Str0ng-Pass!")
        self.assertEqual(user.role, "caretaker")
        self.assertEqual(list(user.assignments.values_list("property_id", flat=True)), [self.p2.pk])
        # Invitations never create tenants
        r = self.client.post("/api/staff-invitations/", {"email": "t@x.test", "first_name": "T", "role": "tenant"},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_tenant_cannot_call_staff_endpoints(self):
        t, _ = self.make_tenant("Tess", self.u1)
        self.login(t.user)
        for url in ["/api/properties/", "/api/tenants/", "/api/payments/", "/api/dashboard/", "/api/maintenance/",
                    "/api/announcements/", "/api/documents/"]:
            self.assertIn(self.client.get(url).status_code, (403,), url)
