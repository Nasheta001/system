from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError

from billing.models import Charge, Payment
from billing.services import account_summary, add_months, generate_charges_for_tenancy, month_start
from tenancies.services import complete_move_out, give_notice, move_in, transfer

from .base import BaseTestCase


class LedgerTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.today = date.today()
        self.start = add_months(month_start(self.today), -2)  # three rent months incl. current
        self.tenant, self.tenancy = self.make_tenant("Lee", self.u1, start=self.start, charge_deposit=False,
                                                     grace_days=5)

    def test_charges_generated_once_per_month(self):
        rents = self.tenancy.charges.filter(kind="rent")
        self.assertEqual(rents.count(), 3)
        self.assertEqual(generate_charges_for_tenancy(self.tenancy), 0)  # idempotent
        self.assertEqual(rents.count(), 3)

    def test_deposit_charge_created_when_configured(self):
        _, t = self.make_tenant("Dee", self.u2, start=self.today)
        self.assertEqual(t.charges.filter(kind="deposit").count(), 1)

    def test_full_and_partial_payments(self):
        s = account_summary(self.tenancy)
        self.assertEqual(s.balance, Decimal("60000"))
        self.pay(self.tenancy, "20000")
        self.pay(self.tenancy, "5000")
        s = account_summary(self.tenancy)
        self.assertEqual(s.total_paid, Decimal("25000"))
        self.assertEqual(s.balance, Decimal("35000"))

    def test_pending_and_rejected_payments_do_not_reduce_balance(self):
        self.pay(self.tenancy, "20000", status="pending")
        self.pay(self.tenancy, "20000", status="rejected")
        s = account_summary(self.tenancy)
        self.assertEqual(s.balance, Decimal("60000"))
        self.assertEqual(s.pending_payments, Decimal("20000"))

    def test_overpayment_becomes_credit(self):
        self.pay(self.tenancy, "70000")
        s = account_summary(self.tenancy)
        self.assertEqual(s.balance, Decimal("-10000"))
        self.assertEqual(s.status, "credit")
        self.assertEqual(s.overdue_amount, 0)

    def test_overdue_respects_grace_period_and_allocates_oldest_first(self):
        first_due = self.start.replace(day=5)
        # As of 3 days after first due date: not overdue yet (grace 5)
        s = account_summary(self.tenancy, as_of=first_due + timedelta(days=3))
        self.assertEqual(s.overdue_amount, 0)
        self.assertEqual(s.status, "due")
        # Pay 30,000: first month covered, second partly
        self.pay(self.tenancy, "30000")
        second_due = add_months(self.start, 1).replace(day=5)
        s = account_summary(self.tenancy, as_of=second_due + timedelta(days=6))
        self.assertEqual(s.overdue_amount, Decimal("10000"))
        self.assertEqual(s.overdue_since, second_due)

    def test_settled_balance_is_not_overdue(self):
        self.pay(self.tenancy, "60000")
        s = account_summary(self.tenancy)
        self.assertEqual(s.overdue_amount, 0)
        self.assertEqual(s.balance, 0)
        self.assertEqual(s.status, "paid")

    def test_credit_adjustment_reduces_balance(self):
        Charge.objects.create(tenancy=self.tenancy, property=self.p1, kind="credit", amount=Decimal("1500"),
                              due_date=self.today, description="Goodwill")
        self.assertEqual(account_summary(self.tenancy).balance, Decimal("58500"))

    def test_move_out_with_deposit_reconciliation(self):
        _, t = self.make_tenant("Mo", self.u2, start=month_start(self.today))
        # deposit 20000 + rent 20000 charged; deposit paid only
        self.pay(t, "20000")
        give_notice(t, self.today, self.today + timedelta(days=1))
        t = complete_move_out(t, actual_move_out=self.today, deposit_deductions=Decimal("3000"),
                              apply_deposit_to_balance=True, notify=False)
        self.assertEqual(t.status, "ended")
        self.assertEqual(t.deposit_applied_to_balance, Decimal("17000"))
        self.assertEqual(t.deposit_refund_amount, Decimal("0"))
        self.assertEqual(account_summary(t).balance, Decimal("3000"))
        self.u2.refresh_from_db()
        self.assertEqual(self.u2.status, "available")
        self.assertEqual(Payment.objects.filter(tenancy=t).count(), 1)  # history preserved

    def test_transfer_carries_balance(self):
        new = transfer(self.tenancy, self.u3.pk, self.today)
        self.tenancy.refresh_from_db()
        self.assertEqual(self.tenancy.status, "ended")
        self.assertEqual(account_summary(self.tenancy, self.today).balance, 0)
        self.assertEqual(account_summary(new).balance, Decimal("60000"))  # brought forward; month not billed twice
        self.u1.refresh_from_db()
        self.u3.refresh_from_db()
        self.assertEqual((self.u1.status, self.u3.status), ("available", "occupied"))

    def test_unit_cannot_have_two_current_tenancies(self):
        from tenancies.models import Tenant

        other = Tenant.objects.create(first_name="Two", last_name="X", phone="1")
        with self.assertRaises(ValidationError):
            move_in(other, self.u1.pk, self.today, notify=False)


class ManualPaymentApiTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        _, self.tenancy = self.make_tenant("Pat", self.u1, charge_deposit=False)

    def payload(self, **kw):
        return {"tenancy": self.tenancy.pk, "amount": "15000", "method": "bank", "reference": "BNK1",
                "paid_on": str(date.today()), **kw}

    def test_manager_records_pending_payment_and_admin_verifies(self):
        self.login(self.manager)
        r = self.client.post("/api/payments/", self.payload(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "pending")
        self.assertIsNone(r.data["receipt_number"])
        r = self.client.post("/api/payments/", self.payload(reference="BNK2", mark_verified=True), format="json")
        self.assertEqual(r.status_code, 403)
        pid = Payment.objects.get(reference="BNK1").pk
        self.assertEqual(self.client.post(f"/api/payments/{pid}/verify/").status_code, 403)
        self.login(self.admin)
        r = self.client.post(f"/api/payments/{pid}/verify/")
        self.assertEqual(r.data["status"], "verified")
        self.assertTrue(r.data["receipt_number"].startswith("RCT-"))
        self.assertEqual(r.data["recorded_by"], self.manager.pk)
        r = self.client.get(f"/api/payments/{pid}/receipt/")
        self.assertEqual(r["Content-Type"], "application/pdf")

    def test_duplicate_reference_rejected(self):
        self.login(self.admin)
        self.client.post("/api/payments/", self.payload(), format="json")
        r = self.client.post("/api/payments/", self.payload(), format="json")
        self.assertEqual(r.status_code, 400)

    def test_manual_entry_cannot_claim_stk(self):
        r = self.login(self.admin).post("/api/payments/", self.payload(method="mpesa"), format="json")
        self.assertEqual(r.status_code, 400)

    def test_manager_cannot_record_for_other_property(self):
        _, other = self.make_tenant("Far", self.u4)
        r = self.login(self.manager).post("/api/payments/", self.payload(tenancy=other.pk), format="json")
        self.assertEqual(r.status_code, 403)

    def test_verified_payment_notifies_tenant(self):
        from communications.models import Notification

        self.login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post("/api/payments/", self.payload(mark_verified=True), format="json")
        n = Notification.objects.filter(template_key="payment_received", channel="in_app").first()
        self.assertIsNotNone(n)
        self.assertEqual(n.status, "delivered")
        sms = Notification.objects.get(template_key="payment_received", channel="sms")
        self.assertEqual(sms.status, "logged")  # provider not configured: never claimed as delivered
