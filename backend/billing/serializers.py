import re
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from tenancies.models import Tenancy

from .models import Charge, FollowUpTask, MpesaTransaction, Payment, ReminderSchedule, ReminderStep


class PaymentSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenancy.tenant.full_name", read_only=True)
    tenant_id = serializers.IntegerField(source="tenancy.tenant_id", read_only=True)
    unit_label = serializers.CharField(source="tenancy.unit.label", read_only=True)
    property_name = serializers.CharField(source="property.name", read_only=True)
    method_label = serializers.CharField(source="get_method_display", read_only=True)
    recorded_by_name = serializers.CharField(source="recorded_by.get_full_name", read_only=True, default=None)
    verified_by_name = serializers.CharField(source="verified_by.get_full_name", read_only=True, default=None)

    class Meta:
        model = Payment
        fields = "__all__"
        read_only_fields = ["property", "status", "source", "is_simulated", "mpesa_receipt", "receipt_number",
                            "recorded_by", "verified_by", "verified_at", "rejection_reason", "created_at",
                            "currency"]


class ManualPaymentSerializer(serializers.ModelSerializer):
    mark_verified = serializers.BooleanField(default=False, write_only=True)

    class Meta:
        model = Payment
        fields = ["tenancy", "amount", "method", "reference", "paid_on", "notes", "mark_verified"]

    def validate_method(self, value):
        if value in (Payment.Method.MPESA, Payment.Method.MPESA_SIMULATED):
            raise serializers.ValidationError(
                "STK payments are recorded automatically. Use 'M-Pesa (recorded manually)' for paybill payments "
                "received outside the portal.")
        return value

    def validate(self, attrs):
        if attrs["method"] != Payment.Method.CASH and not attrs.get("reference"):
            raise serializers.ValidationError({"reference": "A reference is required for non-cash payments."})
        if attrs.get("reference") and Payment.objects.filter(
            method=attrs["method"], reference__iexact=attrs["reference"]
        ).exclude(status=Payment.Status.REJECTED).exists():
            raise serializers.ValidationError({"reference": "A payment with this reference is already recorded."})
        mpesa_methods = (Payment.Method.MPESA_MANUAL, Payment.Method.MPESA_PHONE)
        ref = attrs.get("reference", "").strip()
        if attrs["method"] in mpesa_methods and ref and (
            Payment.objects.filter(reference__iexact=ref).exclude(status=Payment.Status.REJECTED).exists()
            or Payment.objects.filter(mpesa_receipt__iexact=ref).exists()
        ):
            raise serializers.ValidationError(
                {"reference": "This M-Pesa code is already recorded (possibly reported by the tenant). "
                              "Verify the existing payment instead."})
        return attrs


class ChargeSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = Charge
        fields = "__all__"
        read_only_fields = ["property", "voided", "void_reason", "created_by", "created_at", "period"]

    def validate_kind(self, value):
        if value == Charge.Kind.RENT:
            raise serializers.ValidationError("Rent is charged automatically from the tenancy schedule.")
        return value


class MpesaTransactionSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenancy.tenant.full_name", read_only=True)
    unit_label = serializers.CharField(source="tenancy.unit.label", read_only=True)
    receipt_number = serializers.CharField(source="payment.receipt_number", read_only=True, default=None)

    class Meta:
        model = MpesaTransaction
        exclude = ["raw_callback"]


class PortalTransactionSerializer(serializers.ModelSerializer):
    receipt_number = serializers.CharField(source="payment.receipt_number", read_only=True, default=None)
    payment_id = serializers.IntegerField(source="payment.id", read_only=True, default=None)

    class Meta:
        model = MpesaTransaction
        fields = ["id", "phone", "amount", "status", "result_desc", "is_simulated", "created_at", "completed_at",
                  "receipt_number", "payment_id"]


class ReminderStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReminderStep
        fields = ["id", "offset_days", "kind", "alert_management", "custom_message"]


class ReminderScheduleSerializer(serializers.ModelSerializer):
    steps = ReminderStepSerializer(many=True)

    class Meta:
        model = ReminderSchedule
        fields = ["id", "name", "is_default", "steps"]

    def validate_steps(self, steps):
        offsets = [s["offset_days"] for s in steps]
        if len(offsets) != len(set(offsets)):
            raise serializers.ValidationError("Each step needs a different day offset.")
        for s in steps:
            if s["kind"] == ReminderStep.Kind.OVERDUE and s["offset_days"] <= 0:
                raise serializers.ValidationError("Overdue reminders must be after the due date.")
            if s["kind"] == ReminderStep.Kind.UPCOMING and s["offset_days"] >= 0:
                raise serializers.ValidationError("Upcoming reminders must be before the due date.")
        return steps

    def _save_steps(self, schedule, steps):
        schedule.steps.all().delete()
        for s in steps:
            ReminderStep.objects.create(schedule=schedule, **s)
        if schedule.is_default:
            ReminderSchedule.objects.exclude(pk=schedule.pk).update(is_default=False)

    def create(self, validated):
        steps = validated.pop("steps")
        schedule = ReminderSchedule.objects.create(**validated)
        self._save_steps(schedule, steps)
        return schedule

    def update(self, instance, validated):
        steps = validated.pop("steps", None)
        for k, v in validated.items():
            setattr(instance, k, v)
        instance.save()
        if steps is not None:
            self._save_steps(instance, steps)
        return instance


class FollowUpSerializer(serializers.ModelSerializer):
    property_name = serializers.CharField(source="property.name", read_only=True)
    tenant_id = serializers.IntegerField(source="tenancy.tenant_id", read_only=True, default=None)

    class Meta:
        model = FollowUpTask
        fields = "__all__"
        read_only_fields = ["property", "tenancy", "title", "details", "created_at", "closed_by", "closed_at"]


MPESA_CODE_RE = re.compile(r"^[A-Z0-9]{10}$")


class PhonePaymentReportSerializer(serializers.Serializer):
    """A tenant tells us they sent rent with M-Pesa Send Money. This only
    creates a PENDING payment; it changes no balance until staff verify it."""

    mpesa_code = serializers.CharField(max_length=20)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("1"),
                                      max_value=Decimal("250000"))
    paid_on = serializers.DateField()
    sender_phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    tenancy = serializers.PrimaryKeyRelatedField(queryset=Tenancy.objects.all(), required=False)

    def validate_mpesa_code(self, value):
        code = re.sub(r"\s", "", value).upper()
        if not MPESA_CODE_RE.match(code):
            raise serializers.ValidationError("Enter the 10-character M-Pesa transaction code, e.g. SGH7XK2LQP.")
        return code

    def validate_paid_on(self, value):
        today = timezone.localdate()
        if value > today:
            raise serializers.ValidationError("The payment date cannot be in the future.")
        if value < today - timedelta(days=60):
            raise serializers.ValidationError("For payments older than 60 days, please contact the office.")
        return value

    def validate_sender_phone(self, value):
        if not value:
            return ""
        from .mpesa import MpesaError, normalize_phone

        try:
            return normalize_phone(value)
        except MpesaError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class StkRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)
    tenancy = serializers.PrimaryKeyRelatedField(queryset=Tenancy.objects.all(), required=False)
