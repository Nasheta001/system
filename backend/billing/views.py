from datetime import timedelta
import logging

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.audit import audit
from accounts.permissions import IsTenantUser, StaffCapability, has_cap, require_property_access
from config.mixins import PropertyScopedMixin
from config.throttles import ScopeThrottle
from tenancies.models import Tenancy
from tenancies.views import scoped_tenancies

from . import mpesa
from .models import Charge, FollowUpTask, MpesaTransaction, Payment, ReminderSchedule
from .pdf import ledger_rows, receipt_pdf, statement_pdf
from .serializers import (
    ChargeSerializer, FollowUpSerializer, ManualPaymentSerializer, MpesaTransactionSerializer, PaymentSerializer,
    PhonePaymentReportSerializer, PortalTransactionSerializer, ReminderScheduleSerializer, StkRequestSerializer,
)
from .services import account_summary, suggested_payment_amount, verify_payment

logger = logging.getLogger(__name__)


def pdf_response(content, filename):
    resp = HttpResponse(content, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp["Cache-Control"] = "private, no-store"
    return resp


def _serialize_ledger(rows):
    return [{**r, "debit": str(r["debit"]) if r["debit"] is not None else None,
             "credit": str(r["credit"]) if r["credit"] is not None else None, "balance": str(r["balance"])}
            for r in rows]


# ------------------------------------------------------------------------ staff
class PaymentViewSet(PropertyScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                     viewsets.GenericViewSet):
    read_cap = "view_payments"
    write_cap = "manage_payments"
    action_caps = {"verify": "verify_payments", "reject": "verify_payments", "receipt": "view_payments"}
    filterset_fields = {"status": ["exact"], "method": ["exact"], "property": ["exact"], "tenancy": ["exact"],
                        "tenancy__tenant": ["exact"], "paid_on": ["gte", "lte"], "is_simulated": ["exact"]}
    search_fields = ["reference", "receipt_number", "tenancy__tenant__first_name", "tenancy__tenant__last_name",
                     "tenancy__unit__unit_number"]
    ordering_fields = ["paid_on", "amount", "created_at"]

    def get_queryset(self):
        return self.scope(Payment.objects.select_related(
            "tenancy__tenant", "tenancy__unit__building", "property", "recorded_by", "verified_by"))

    def get_serializer_class(self):
        return ManualPaymentSerializer if self.action == "create" else PaymentSerializer

    def create(self, request, *args, **kwargs):
        s = ManualPaymentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        tenancy = s.validated_data["tenancy"]
        require_property_access(request.user, tenancy.property_id)
        mark = s.validated_data.pop("mark_verified", False)
        if mark and not has_cap(request.user, "verify_payments"):
            raise PermissionDenied("Your role can record payments but not verify them. An administrator will verify it.")
        with transaction.atomic():
            payment = Payment.objects.create(
                property_id=tenancy.property_id, source=Payment.Source.MANUAL, recorded_by=request.user,
                status=Payment.Status.PENDING, **s.validated_data,
            )
            if mark:
                payment = verify_payment(payment, request.user)
        audit(request, "payment.record", payment,
              f"Recorded {payment.get_method_display()} payment KES {payment.amount} for {tenancy.tenant.full_name}"
              f" ({'verified' if mark else 'pending verification'})")
        return Response(PaymentSerializer(payment).data, status=201)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        payment = self.get_object()
        if payment.status == Payment.Status.REJECTED:
            return Response({"detail": "Rejected payments cannot be verified."}, status=400)
        payment = verify_payment(payment, request.user)
        audit(request, "payment.verify", payment, f"Verified payment {payment.receipt_number}")
        return Response(PaymentSerializer(payment).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        payment = self.get_object()
        if payment.status != Payment.Status.PENDING:
            return Response({"detail": "Only pending payments can be rejected."}, status=400)
        reason = str(request.data.get("reason", "")).strip()
        if not reason:
            return Response({"reason": ["Give a reason for rejecting this payment."]}, status=400)
        payment.status = Payment.Status.REJECTED
        payment.rejection_reason = reason[:255]
        payment.verified_by = request.user
        payment.verified_at = timezone.now()
        payment.save()
        audit(request, "payment.reject", payment, f"Rejected payment {payment.pk}: {reason}")
        return Response(PaymentSerializer(payment).data)

    @action(detail=True, methods=["get"])
    def receipt(self, request, pk=None):
        payment = self.get_object()
        if payment.status != Payment.Status.VERIFIED:
            return Response({"detail": "Receipts are only issued for verified payments."}, status=400)
        return pdf_response(receipt_pdf(payment), f"{payment.receipt_number}.pdf")


class ChargeViewSet(PropertyScopedMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    serializer_class = ChargeSerializer
    read_cap = "view_payments"
    write_cap = "manage_payments"
    filterset_fields = ["tenancy", "kind", "property", "voided"]

    def get_queryset(self):
        return self.scope(Charge.objects.all())

    def perform_create(self, serializer):
        tenancy = serializer.validated_data["tenancy"]
        require_property_access(self.request.user, tenancy.property_id)
        charge = serializer.save(property_id=tenancy.property_id, created_by=self.request.user)
        audit(self.request, "charge.create", charge, f"Added {charge.get_kind_display()} KES {charge.amount}: "
                                                     f"{charge.description} ({tenancy.tenant.full_name})")

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        charge = self.get_object()
        reason = str(request.data.get("reason", "")).strip()
        if not reason:
            return Response({"reason": ["A reason is required."]}, status=400)
        if charge.voided:
            return Response({"detail": "Already voided."}, status=400)
        charge.voided = True
        charge.void_reason = reason[:255]
        charge.save(update_fields=["voided", "void_reason"])
        audit(request, "charge.void", charge, f"Voided charge {charge.description}: {reason}")
        return Response(ChargeSerializer(charge).data)


class TenancyLedgerView(APIView):
    permission_classes = [StaffCapability]
    read_cap = "view_payments"

    def get(self, request, pk):
        tenancy = get_object_or_404(scoped_tenancies(request.user), pk=pk)
        if request.query_params.get("export") == "pdf":
            return pdf_response(statement_pdf(tenancy), f"statement-{tenancy.pk}.pdf")
        return Response({"account": account_summary(tenancy).as_dict(), "rows": _serialize_ledger(ledger_rows(tenancy))})


class MpesaTransactionViewSet(PropertyScopedMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = MpesaTransactionSerializer
    read_cap = "view_payments"
    property_field = "tenancy__property"
    filterset_fields = ["status", "is_simulated", "tenancy"]

    def get_queryset(self):
        return self.scope(MpesaTransaction.objects.select_related("tenancy__tenant", "tenancy__unit", "payment"))


class ReminderScheduleViewSet(viewsets.ModelViewSet):
    serializer_class = ReminderScheduleSerializer
    permission_classes = [StaffCapability]
    read_cap = "view_tenants"
    write_cap = "manage_settings"
    queryset = ReminderSchedule.objects.prefetch_related("steps")
    pagination_class = None

    def perform_create(self, serializer):
        s = serializer.save()
        audit(self.request, "reminders.create", s, f"Created reminder schedule {s.name}")

    def perform_update(self, serializer):
        s = serializer.save()
        audit(self.request, "reminders.update", s, f"Updated reminder schedule {s.name}")

    def destroy(self, request, *args, **kwargs):
        s = self.get_object()
        if s.is_default:
            return Response({"detail": "The default schedule cannot be deleted."}, status=409)
        return super().destroy(request, *args, **kwargs)


class FollowUpViewSet(PropertyScopedMixin, mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = FollowUpSerializer
    read_cap = "view_payments"
    write_cap = "manage_payments"
    filterset_fields = ["status", "property"]

    def get_queryset(self):
        return self.scope(FollowUpTask.objects.select_related("property", "tenancy"))

    def perform_update(self, serializer):
        status_ = serializer.validated_data.get("status")
        extra = {}
        if status_ in (FollowUpTask.Status.DONE, FollowUpTask.Status.DISMISSED):
            extra = {"closed_by": self.request.user, "closed_at": timezone.now()}
        serializer.save(**extra)


class PaymentConfigView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        m = mpesa.mode()
        labels = {
            "disabled": "Online payments disabled",
            "simulated": "SIMULATED – demo mode, no real money moves",
            "sandbox": "Safaricom Daraja sandbox (test money)",
            "production": "Live M-Pesa",
        }
        return Response({"mpesa_mode": m, "label": labels.get(m, m), "is_live": m == "production"})


# ------------------------------------------------------------------------ M-Pesa callback
class MpesaCallbackView(APIView):
    """Receives Daraja STK callbacks. Always answers 200 with ResultCode 0 so
    Safaricom does not retry indefinitely; the outcome is logged and processing
    is idempotent."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, token):
        if not mpesa.verify_callback_request(request, token):
            logger.warning("Rejected M-Pesa callback with invalid token or IP")
            return Response({"ResultCode": 1, "ResultDesc": "Rejected"}, status=403)
        payload = request.data if isinstance(request.data, dict) else {}
        try:
            mpesa.process_stk_callback(payload, simulated=False)
        except Exception:  # noqa: BLE001
            logger.exception("Error processing M-Pesa callback")
        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})


# ------------------------------------------------------------------------ tenant portal
def _portal_tenancies(request):
    return Tenancy.objects.filter(tenant=request.user.tenant_profile).select_related("unit", "unit__building",
                                                                                     "property", "tenant")


class PortalAccountView(APIView):
    permission_classes = [IsTenantUser]

    def get(self, request):
        tenancies = list(_portal_tenancies(request).order_by("-start_date"))
        wanted = request.query_params.get("tenancy")
        tenancy = next((t for t in tenancies if str(t.pk) == wanted), None) if wanted else None
        tenancy = tenancy or next((t for t in tenancies if t.is_current), None) or (tenancies[0] if tenancies else None)
        if tenancy is None:
            return Response({"tenancy": None, "tenancies": []})
        payments = Payment.objects.filter(tenancy=tenancy).exclude(status=Payment.Status.REJECTED)
        return Response({
            "tenancy": {"id": tenancy.pk, "property": tenancy.property.name, "unit": tenancy.unit.label,
                        "status": tenancy.status, "monthly_rent": tenancy.monthly_rent},
            "tenancies": [{"id": t.pk, "label": f"{t.property.name} – {t.unit.label}", "status": t.status}
                          for t in tenancies],
            "account": account_summary(tenancy).as_dict(),
            "suggested_amount": suggested_payment_amount(tenancy) if tenancy.is_current else 0,
            "ledger": _serialize_ledger(ledger_rows(tenancy)),
            "payments": [{"id": p.pk, "amount": p.amount, "paid_on": p.paid_on, "method": p.get_method_display(),
                          "reference": p.reference, "status": p.status, "receipt_number": p.receipt_number,
                          "is_simulated": p.is_simulated} for p in payments],
            "phone": request.user.tenant_profile.phone,
            "send_money": send_money_config(),
        })


def send_money_config():
    """Shown only to signed-in tenants (not on the public site)."""
    from accounts.models import CompanySettings

    c = CompanySettings.load()
    enabled = bool(c.rent_phone_payments_enabled and c.rent_receiving_phone)
    return {"enabled": enabled, "phone": c.rent_receiving_phone if enabled else "",
            "name": c.rent_receiving_name if enabled else ""}


class PortalPhonePaymentReportView(APIView):
    """Tenant reports a Send Money payment to the landlord's number. Creates a
    PENDING payment only; balances and receipts change after staff verify it
    against the M-Pesa statement (this flow has no Daraja confirmation)."""

    permission_classes = [IsTenantUser]
    throttle_classes = [ScopeThrottle]
    throttle_scope = "payments"
    MAX_PENDING = 5

    def get(self, request):
        return Response(send_money_config())

    def post(self, request):
        cfg = send_money_config()
        if not cfg["enabled"]:
            return Response({"detail": "Payments to the landlord's phone number are not enabled."}, status=400)
        s = PhonePaymentReportSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        tenant = request.user.tenant_profile
        qs = Tenancy.objects.filter(tenant=tenant, status__in=Tenancy.CURRENT_STATUSES)
        tenancy = qs.filter(pk=d["tenancy"].pk).first() if d.get("tenancy") else qs.order_by("-start_date").first()
        if tenancy is None:
            return Response({"detail": "You have no active tenancy to pay for."}, status=400)
        code = d["mpesa_code"]
        with transaction.atomic():
            Tenancy.objects.select_for_update().get(pk=tenancy.pk)
            if (Payment.objects.filter(reference__iexact=code).exclude(status=Payment.Status.REJECTED).exists()
                    or Payment.objects.filter(mpesa_receipt__iexact=code).exists()):
                return Response({"mpesa_code": ["This M-Pesa code has already been recorded."]}, status=400)
            if Payment.objects.filter(tenancy=tenancy, source=Payment.Source.TENANT,
                                      status=Payment.Status.PENDING).count() >= self.MAX_PENDING:
                return Response({"detail": "You have several payments awaiting confirmation. Please wait for the "
                                           "office to check them."}, status=429)
            sender = f" from {d['sender_phone']}" if d.get("sender_phone") else ""
            payment = Payment.objects.create(
                tenancy=tenancy, property_id=tenancy.property_id, amount=d["amount"], method=Payment.Method.MPESA_PHONE,
                source=Payment.Source.TENANT, reference=code, paid_on=d["paid_on"], status=Payment.Status.PENDING,
                recorded_by=request.user,
                notes=f"Reported by tenant: Send Money to {cfg['phone']}{sender}. Check the M-Pesa statement "
                      "before verifying.",
            )
        audit(request, "payment.tenant_report", payment,
              f"{tenant.full_name} reported M-Pesa {code} KES {payment.amount} (awaiting verification)",
              property_id=tenancy.property_id)
        _alert_verifiers(payment)
        return Response({"id": payment.pk, "amount": payment.amount, "reference": code, "status": payment.status,
                         "detail": "Thank you. Your payment will appear on your account once the office has "
                                   "confirmed it on the M-Pesa statement."}, status=201)


def _alert_verifiers(payment):
    from accounts.models import PORTFOLIO_ROLES, User
    from communications.services import notify_user

    title = f"Check M-Pesa payment {payment.reference}"
    msg = (f"{payment.tenancy.tenant.full_name} ({payment.tenancy.unit.label}) reports sending KES {payment.amount:,.2f} "
           f"by M-Pesa on {payment.paid_on:%d %b %Y}, code {payment.reference}. Confirm it on the M-Pesa statement, "
           "then verify or reject it under Payments.")
    for u in User.objects.filter(role__in=PORTFOLIO_ROLES, is_active=True):
        notify_user(u, "staff_alert", {"title": title, "message": msg}, link="/management/payments",
                    channels=("in_app",), dedupe=f"phone-pay-{payment.pk}-{u.pk}")


class PortalStkPushView(APIView):
    permission_classes = [IsTenantUser]
    throttle_classes = [ScopeThrottle]
    throttle_scope = "payments"

    def post(self, request):
        s = StkRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        tenant = request.user.tenant_profile
        qs = Tenancy.objects.filter(tenant=tenant, status__in=Tenancy.CURRENT_STATUSES).select_related("unit")
        tenancy = s.validated_data.get("tenancy")
        tenancy = qs.filter(pk=tenancy.pk).first() if tenancy else qs.order_by("-start_date").first()
        if tenancy is None:
            return Response({"detail": "You have no active tenancy to pay for."}, status=400)
        if MpesaTransaction.objects.filter(tenancy=tenancy, status=MpesaTransaction.Status.PENDING,
                                           created_at__gte=timezone.now() - timedelta(minutes=2)).exists():
            return Response({"detail": "A payment request was sent less than 2 minutes ago. Check your phone "
                                       "or wait before trying again."}, status=429)
        try:
            txn = mpesa.initiate_stk_push(tenancy, s.validated_data["phone"], s.validated_data["amount"], request.user)
        except mpesa.MpesaError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(PortalTransactionSerializer(txn).data, status=201)


class PortalTransactionView(APIView):
    permission_classes = [IsTenantUser]

    def get(self, request, pk):
        txn = get_object_or_404(MpesaTransaction, pk=pk, tenancy__tenant=request.user.tenant_profile)
        return Response(PortalTransactionSerializer(txn).data)


class PortalSimulateView(APIView):
    """SIMULATED MODE ONLY: stands in for the customer's action on their phone."""

    permission_classes = [IsTenantUser]

    def post(self, request, pk):
        txn = get_object_or_404(MpesaTransaction, pk=pk, tenancy__tenant=request.user.tenant_profile)
        outcome = request.data.get("outcome")
        if outcome not in ("success", "cancel"):
            return Response({"detail": "outcome must be success or cancel"}, status=400)
        try:
            txn = mpesa.simulate_callback(txn, outcome)
        except mpesa.MpesaError as exc:
            return Response({"detail": str(exc)}, status=400)
        txn.refresh_from_db()
        return Response(PortalTransactionSerializer(txn).data)


class PortalReceiptView(APIView):
    permission_classes = [IsTenantUser]

    def get(self, request, pk):
        payment = get_object_or_404(Payment.objects.select_related("tenancy__tenant", "tenancy__unit", "property"),
                                    pk=pk, tenancy__tenant=request.user.tenant_profile,
                                    status=Payment.Status.VERIFIED)
        return pdf_response(receipt_pdf(payment), f"{payment.receipt_number}.pdf")


class PortalStatementView(APIView):
    permission_classes = [IsTenantUser]

    def get(self, request, pk):
        tenancy = get_object_or_404(_portal_tenancies(request), pk=pk)
        return pdf_response(statement_pdf(tenancy), f"statement-{tenancy.pk}.pdf")
