from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from billing import mpesa
from billing.models import FollowUpTask, MpesaTransaction, Payment, ReminderLog
from billing.reminders import run_reminders
from billing.services import account_summary, add_months, month_start
from communications.models import Notification

from .base import BaseTestCase


def callback(txn, code=0, receipt="QWE123ABC", amount=None):
    cb = {"MerchantRequestID": "m", "CheckoutRequestID": txn.checkout_request_id, "ResultCode": code,
          "ResultDesc": "ok"}
    if code == 0:
        cb["CallbackMetadata"] = {"Item": [{"Name": "Amount", "Value": float(amount or txn.amount)},
                                           {"Name": "MpesaReceiptNumber", "Value": receipt},
                                           {"Name": "PhoneNumber", "Value": 254712345678}]}
    return {"Body": {"stkCallback": cb}}


class MpesaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.tenant, self.tenancy = self.make_tenant("Mpesa", self.u1, charge_deposit=False)
        self.login(self.tenant.user)

    def stk(self, amount="20000"):
        r = self.client.post("/api/portal/payments/mpesa/", {"phone": "0712345678", "amount": amount}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return MpesaTransaction.objects.get(pk=r.data["id"])

    def test_initiating_stk_does_not_record_payment(self):
        txn = self.stk()
        self.assertEqual(txn.status, "pending")
        self.assertTrue(txn.is_simulated)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(account_summary(self.tenancy).balance, Decimal("20000"))

    def test_simulated_success_records_one_verified_payment(self):
        txn = self.stk()
        r = self.client.post(f"/api/portal/payments/mpesa/{txn.pk}/simulate/", {"outcome": "success"}, format="json")
        self.assertEqual(r.data["status"], "success")
        p = Payment.objects.get()
        self.assertEqual((p.status, p.method, p.is_simulated), ("verified", "mpesa_simulated", True))
        self.assertTrue(p.receipt_number)
        self.assertEqual(account_summary(self.tenancy).balance, 0)
        # Simulating again changes nothing
        self.client.post(f"/api/portal/payments/mpesa/{txn.pk}/simulate/", {"outcome": "success"}, format="json")
        self.assertEqual(Payment.objects.count(), 1)

    def test_cancelled_payment_creates_nothing(self):
        txn = self.stk()
        r = self.client.post(f"/api/portal/payments/mpesa/{txn.pk}/simulate/", {"outcome": "cancel"}, format="json")
        self.assertEqual(r.data["status"], "cancelled")
        self.assertEqual(Payment.objects.count(), 0)

    def test_tenant_cannot_touch_another_tenants_transaction(self):
        txn = self.stk()
        other, _ = self.make_tenant("Other", self.u2)
        self.login(other.user)
        self.assertEqual(self.client.get(f"/api/portal/payments/mpesa/{txn.pk}/").status_code, 404)
        r = self.client.post(f"/api/portal/payments/mpesa/{txn.pk}/simulate/", {"outcome": "success"}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_invalid_phone_rejected(self):
        r = self.client.post("/api/portal/payments/mpesa/", {"phone": "12345", "amount": "100"}, format="json")
        self.assertEqual(r.status_code, 400)


@override_settings(MPESA={**__import__("django.conf").conf.settings.MPESA, "MODE": "sandbox",
                          "CALLBACK_TOKEN": "secret-token-123", "ALLOWED_CALLBACK_IPS": []})
class MpesaCallbackTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.tenant, self.tenancy = self.make_tenant("Cb", self.u1, charge_deposit=False)
        self.txn = MpesaTransaction.objects.create(tenancy=self.tenancy, phone="254712345678",
                                                   amount=Decimal("20000"), account_reference="A1",
                                                   checkout_request_id="ws_CO_1")
        self.url = "/api/payments/mpesa/callback/secret-token-123/"
        patcher = mock.patch.object(mpesa, "query_stk_status", return_value=("0", "confirmed"))
        self.query = patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, payload, url=None):
        return APIClient().post(url or self.url, payload, format="json")

    def test_bad_token_rejected(self):
        r = self.post(callback(self.txn), url="/api/payments/mpesa/callback/wrong/")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Payment.objects.count(), 0)

    def test_success_callback_and_duplicates_are_idempotent(self):
        for _ in range(3):
            r = self.post(callback(self.txn))
            self.assertEqual(r.status_code, 200)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, "success")
        self.assertEqual(self.txn.callback_count, 3)
        self.assertEqual(Payment.objects.count(), 1)
        p = Payment.objects.get()
        self.assertEqual((p.method, p.is_simulated, p.mpesa_receipt), ("mpesa", False, "QWE123ABC"))

    def test_same_receipt_on_another_transaction_not_double_counted(self):
        self.post(callback(self.txn))
        txn2 = MpesaTransaction.objects.create(tenancy=self.tenancy, phone="254712345678", amount=Decimal("20000"),
                                               account_reference="A1", checkout_request_id="ws_CO_2")
        self.post(callback(txn2, receipt="QWE123ABC"))
        self.assertEqual(Payment.objects.count(), 1)
        txn2.refresh_from_db()
        self.assertEqual(txn2.status, "failed")
        self.assertIn("already applied", txn2.result_desc)

    def test_unconfirmed_by_query_is_not_credited(self):
        self.query.return_value = ("1", "failed")
        self.post(callback(self.txn))
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, "failed")
        self.assertEqual(Payment.objects.count(), 0)

    def test_query_unavailable_keeps_pending(self):
        self.query.return_value = (None, "network")
        self.post(callback(self.txn))
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, "pending")
        self.assertEqual(Payment.objects.count(), 0)

    def test_amount_mismatch_flagged_for_review(self):
        self.post(callback(self.txn, amount=1))
        p = Payment.objects.get()
        self.assertEqual(p.status, "pending")
        self.assertIn("mismatch", p.notes)

    def test_failed_callback(self):
        self.post(callback(self.txn, code=2001))
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, "failed")
        self.assertEqual(Payment.objects.count(), 0)

    def test_late_success_after_timeout_is_still_credited(self):
        self.txn.status = "timeout"
        self.txn.save()
        self.post(callback(self.txn))
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, "success")
        self.assertEqual(Payment.objects.count(), 1)

    def test_unknown_checkout_ignored(self):
        fake = MpesaTransaction(checkout_request_id="nope", amount=Decimal("1"))
        r = self.post(callback(fake))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Payment.objects.count(), 0)


class ReminderTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.start = add_months(month_start(date.today()), -1)
        self.tenant, self.tenancy = self.make_tenant("Remy", self.u1, start=self.start, charge_deposit=False,
                                                     grace_days=2)
        self.due = add_months(self.start, 1).replace(day=5)  # current month due date
        # first month paid
        self.pay(self.tenancy, "20000", paid_on=self.start)

    def run_at(self, d):
        with self.captureOnCommitCallbacks(execute=True):
            return run_reminders(d)

    def test_upcoming_due_and_overdue_sequence(self):
        self.assertEqual(self.run_at(self.due - timedelta(days=3)), 1)
        self.assertEqual(self.run_at(self.due), 1)
        self.assertEqual(self.run_at(self.due + timedelta(days=3)), 1)
        kinds = list(ReminderLog.objects.order_by("created_at").values_list("kind", flat=True))
        self.assertEqual(kinds, ["rent_upcoming", "rent_due", "rent_overdue"])
        self.assertTrue(Notification.objects.filter(template_key="rent_overdue", tenant=self.tenant).exists())

    def test_no_duplicates_when_run_repeatedly(self):
        self.run_at(self.due)
        self.run_at(self.due)
        self.run_at(self.due)
        self.assertEqual(ReminderLog.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(template_key="rent_due", channel="in_app").count(), 1)

    def test_reminders_stop_once_paid(self):
        self.run_at(self.due)
        self.pay(self.tenancy, "20000")
        self.assertEqual(self.run_at(self.due + timedelta(days=3)), 0)
        self.assertEqual(self.run_at(self.due + timedelta(days=10)), 0)

    def test_escalation_creates_management_follow_up(self):
        self.run_at(self.due + timedelta(days=10))
        self.assertTrue(FollowUpTask.objects.filter(tenancy=self.tenancy).exists())
        self.assertTrue(Notification.objects.filter(user=self.manager, template_key="staff_alert").exists())

    def test_disabled_reminders(self):
        self.tenancy.reminders_enabled = False
        self.tenancy.save()
        self.assertEqual(self.run_at(self.due), 0)
