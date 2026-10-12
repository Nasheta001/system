from datetime import date
from io import BytesIO
from unittest import mock

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory, override_settings
from rest_framework.test import APIClient

from accounts.audit import client_ip
from billing.models import Charge, Payment
from communications.models import Notification, NotificationTemplate
from communications.services import notify_tenant, render
from properties.models import PropertyPhoto
from tenancies.models import Tenant

from .base import PASSWORD, BaseTestCase


class HealthAndHeadersTests(BaseTestCase):
    def test_liveness_ignores_host_header(self):
        r = self.client.get("/api/health/", HTTP_HOST="10.0.3.17:8000")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_readiness_checks_database_and_migrations(self):
        r = self.client.get("/api/health/ready/")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["checks"]["database"], "ok")
        self.assertEqual(body["checks"]["migrations"], "ok")
        self.assertNotIn("version", str(body))

    def test_api_security_headers(self):
        r = APIClient().get("/api/public/company/")
        self.assertEqual(r["Content-Security-Policy"], "default-src 'none'; frame-ancestors 'none'")
        self.assertEqual(r["Cache-Control"], "no-store")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertIn("camera=()", r["Permissions-Policy"])

    @override_settings(ORIGIN_VERIFY_SECRET="cf-secret")
    def test_origin_verification(self):
        c = APIClient()
        self.assertEqual(c.get("/api/public/company/").status_code, 403)
        self.assertEqual(c.get("/api/public/company/", HTTP_X_ORIGIN_VERIFY="cf-secret").status_code, 200)
        self.assertEqual(c.get("/api/health/").status_code, 200)

    @override_settings(NUM_PROXIES=2)
    def test_client_ip_ignores_spoofed_forwarded_for(self):
        req = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="6.6.6.6, 41.90.1.2, 130.176.0.1", REMOTE_ADDR="10.0.0.5")
        self.assertEqual(client_ip(req), "41.90.1.2")


class LoginLockoutTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def attempt(self, email, password):
        return APIClient().post("/api/auth/login/", {"email": email, "password": password, "portal": "management"},
                                format="json")

    def test_account_locks_after_repeated_failures(self):
        for _ in range(5):
            self.assertEqual(self.attempt("manager@x.test", "wrong").status_code, 400)
        r = self.attempt("manager@x.test", PASSWORD)  # correct password, but locked
        self.assertEqual(r.status_code, 429)
        self.assertEqual(self.attempt("admin@x.test", PASSWORD).status_code, 200)  # other accounts unaffected

    def test_unknown_email_behaves_identically(self):
        for _ in range(5):
            self.attempt("nobody@x.test", "wrong")
        self.assertEqual(self.attempt("nobody@x.test", "wrong").status_code, 429)

    def test_success_resets_counter(self):
        for _ in range(4):
            self.attempt("manager@x.test", "wrong")
        self.assertEqual(self.attempt("manager@x.test", PASSWORD).status_code, 200)
        for _ in range(4):
            self.attempt("manager@x.test", "wrong")
        self.assertEqual(self.attempt("manager@x.test", PASSWORD).status_code, 200)


class BotProtectionTests(BaseTestCase):
    def payload(self, **kw):
        return {"unit": self.u3.pk, "full_name": "A B", "email": "a@x.test", "phone": "0711111111",
                "consent_given": True, **kw}

    def test_honeypot_rejects_bots(self):
        r = APIClient().post("/api/public/applications/", self.payload(website="http://spam"), format="json")
        self.assertEqual(r.status_code, 400)
        r = APIClient().post("/api/auth/password/reset/", {"email": "a@x.test", "website": "x"}, format="json")
        self.assertEqual(r.status_code, 400)

    @override_settings(TURNSTILE_SECRET_KEY="secret")
    def test_turnstile_required_when_configured(self):
        r = APIClient().post("/api/public/applications/", self.payload(), format="json")
        self.assertEqual(r.status_code, 400)
        with mock.patch("config.bot.requests.post") as post:
            post.return_value.json.return_value = {"success": False}
            r = APIClient().post("/api/public/applications/", self.payload(captcha_token="bad"), format="json")
            self.assertEqual(r.status_code, 400)
            post.return_value.json.return_value = {"success": True}
            r = APIClient().post("/api/public/applications/", self.payload(captcha_token="good"), format="json")
            self.assertEqual(r.status_code, 201)

    @override_settings(TURNSTILE_SECRET_KEY="secret")
    def test_turnstile_fails_closed(self):
        with mock.patch("config.bot.requests.post", side_effect=OSError("down")):
            r = APIClient().post("/api/public/applications/", self.payload(captcha_token="x"), format="json")
        self.assertEqual(r.status_code, 400)


class DataProtectionTests(BaseTestCase):
    def test_id_number_encrypted_at_rest(self):
        t = Tenant.objects.create(first_name="Enc", last_name="T", phone="0712345678", id_number="12345678")
        with connection.cursor() as cur:
            cur.execute("SELECT id_number FROM tenancies_tenant WHERE id = %s", [t.pk])
            raw = cur.fetchone()[0]
        self.assertTrue(raw.startswith("enc1:"))
        self.assertNotIn("12345678", raw)
        self.assertEqual(Tenant.objects.get(pk=t.pk).id_number, "12345678")

    def test_reencrypt_command(self):
        from django.core.management import call_command

        t = Tenant.objects.create(first_name="Rot", last_name="T", phone="0712345678", id_number="A1")
        call_command("reencrypt_fields", stdout=BytesIO() and None)
        self.assertEqual(Tenant.objects.get(pk=t.pk).id_number, "A1")

    def test_secret_links_hidden_in_notification_log(self):
        from accounts.services import send_password_link

        with self.captureOnCommitCallbacks(execute=True):
            send_password_link(self.manager)
        n = Notification.objects.get(template_key="password_reset")
        self.assertIn("reset-password", n.body)  # stored for a logged-only channel (development)
        r = self.login(self.admin).get(f"/api/notification-log/{n.pk}/")
        self.assertNotIn("token=", r.data["body"])
        self.assertIn("[secure link hidden]", r.data["body"])

    def test_templates_cannot_read_object_attributes(self):
        NotificationTemplate.objects.update_or_create(
            key="tenancy_change", defaults={"name": "x", "subject": "{first_name.__class__}",
                                            "body": "{first_name.__class__.__init__.__globals__}", "short_body": "x"})
        subject, body, _ = render("tenancy_change", {"first_name": "Ann"})
        # Expressions are left as inert text, never evaluated
        self.assertNotIn("<class", subject + body)
        self.assertNotIn("__builtins__", body)
        self.assertEqual(subject, "{first_name.__class__}")


class InputAndTamperingTests(BaseTestCase):
    def test_invalid_phone_rejected(self):
        r = self.login(self.manager).post("/api/tenants/", {"first_name": "A", "last_name": "B", "phone": "call me",
                                                            "create_portal_account": False}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("phone", r.data)

    def test_tenant_cannot_change_protected_profile_fields(self):
        t, _ = self.make_tenant("Pro", self.u1)
        self.login(t.user).patch("/api/portal/profile/", {"first_name": "Hacker", "email": "evil@x.test",
                                                          "notes": "x", "status": "former"}, format="json")
        t.refresh_from_db()
        self.assertEqual((t.first_name, t.email, t.notes, t.status), ("Pro", "pro@tenant.test", "", "active"))

    def test_staff_cannot_self_verify_by_tampering(self):
        _, ten = self.make_tenant("Pay", self.u1, charge_deposit=False)
        r = self.login(self.manager).post("/api/payments/", {
            "tenancy": ten.pk, "amount": "100", "method": "cash", "paid_on": str(date.today()),
            "status": "verified", "receipt_number": "FAKE-1", "is_simulated": True}, format="json")
        self.assertEqual(r.status_code, 201)
        p = Payment.objects.get(pk=r.data["id"])
        self.assertEqual((p.status, p.receipt_number, p.is_simulated), ("pending", None, False))

    def test_staff_cannot_grant_superuser(self):
        from accounts.invitations import accept_invitation, hash_token
        from accounts.models import Invitation

        r = self.login(self.admin).post("/api/staff-invitations/", {
            "email": "s@x.test", "first_name": "S", "role": "manager", "is_superuser": True, "is_staff": True},
            format="json")
        self.assertEqual(r.status_code, 201)
        inv = Invitation.objects.get(pk=r.data["id"])
        inv.token_hash = hash_token("tok-super")
        inv.save()
        u, _ = accept_invitation("tok-super", "An0ther-Str0ng-Pass!")
        self.assertFalse(u.is_superuser or u.is_staff)
        # Editing an existing staff member cannot set superuser either
        self.client.patch(f"/api/staff/{u.pk}/", {"is_superuser": True, "is_staff": True}, format="json")
        u.refresh_from_db()
        self.assertFalse(u.is_superuser or u.is_staff)

    def test_pdf_statement_escapes_markup(self):
        _, ten = self.make_tenant("Pdf", self.u1, charge_deposit=False)
        Charge.objects.create(tenancy=ten, property=self.p1, kind="other", amount=1, due_date=date.today(),
                              description="<b>Water & <script>alert(1)</script>")
        r = self.login(self.admin).get(f"/api/tenancies/{ten.pk}/ledger/", {"export": "pdf"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content[:4], b"%PDF")

    def test_photo_upload_strips_metadata_and_renames(self):
        from PIL import Image

        img = Image.new("RGB", (40, 30), "green")
        exif = Image.Exif()
        exif[0x010F] = "SecretCameraMaker"
        buf = BytesIO()
        img.save(buf, "JPEG", exif=exif)
        f = SimpleUploadedFile("my house at 12 Secret St.jpg", buf.getvalue(), content_type="image/jpeg")
        r = self.login(self.manager).post("/api/property-photos/", {"property": self.p1.pk, "image": f},
                                          format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        photo = PropertyPhoto.objects.get()
        self.assertNotIn("Secret", photo.image.name)
        with photo.image.open("rb") as fh:
            data = fh.read()
        self.assertNotIn(b"SecretCameraMaker", data)

    def test_non_image_disguised_as_jpg_rejected(self):
        f = SimpleUploadedFile("x.jpg", b"<?php echo 1; ?>", content_type="image/jpeg")
        r = self.login(self.manager).post("/api/property-photos/", {"property": self.p1.pk, "image": f},
                                          format="multipart")
        self.assertEqual(r.status_code, 400)
