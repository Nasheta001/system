from rest_framework import serializers

from accounts.models import User
from properties.models import Unit

from .models import Tenancy, Tenant


class TenancyBriefSerializer(serializers.ModelSerializer):
    unit_label = serializers.CharField(source="unit.label", read_only=True)
    property_name = serializers.CharField(source="property.name", read_only=True)

    class Meta:
        model = Tenancy
        fields = ["id", "unit", "unit_label", "property", "property_name", "start_date", "expected_end_date",
                  "monthly_rent", "status", "planned_move_out", "actual_move_out"]


class TenantListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    current_tenancy = serializers.SerializerMethodField()
    has_portal_account = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()
    account_status = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = ["id", "full_name", "first_name", "last_name", "email", "phone", "status", "current_tenancy",
                  "has_portal_account", "balance", "account_status"]

    def get_current_tenancy(self, obj):
        cur = [t for t in obj.tenancies.all() if t.status in Tenancy.CURRENT_STATUSES]
        return TenancyBriefSerializer(cur[0]).data if cur else None

    def get_has_portal_account(self, obj):
        return obj.user_id is not None

    def _summary(self, obj):
        return self.context.get("summaries", {}).get(obj.pk)

    def get_balance(self, obj):
        s = self._summary(obj)
        return str(s.balance) if s else None

    def get_account_status(self, obj):
        s = self._summary(obj)
        return s.status if s else None


class CaretakerTenantSerializer(serializers.ModelSerializer):
    """Reduced view for caretakers: contact details and unit only."""

    full_name = serializers.CharField(read_only=True)
    current_tenancy = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = ["id", "full_name", "phone", "status", "current_tenancy"]

    def get_current_tenancy(self, obj):
        cur = [t for t in obj.tenancies.all() if t.status in Tenancy.CURRENT_STATUSES]
        return TenancyBriefSerializer(cur[0]).data if cur else None


class TenantSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    tenancies = TenancyBriefSerializer(many=True, read_only=True)
    has_portal_account = serializers.SerializerMethodField()
    portal_active = serializers.SerializerMethodField()
    portal_invitation = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = ["id", "first_name", "last_name", "full_name", "email", "phone", "alternative_phone", "id_number",
                  "occupation", "emergency_contact_name", "emergency_contact_phone",
                  "emergency_contact_relationship", "status", "notify_sms", "notify_email", "notify_whatsapp",
                  "notes", "data_consent_at", "tenancies", "has_portal_account", "portal_active", "portal_invitation",
                  "created_at"]
        read_only_fields = ["status", "created_at"]
        extra_kwargs = {"id_number": {"max_length": 30}}

    def get_has_portal_account(self, obj):
        return obj.user_id is not None

    def get_portal_active(self, obj):
        return bool(obj.user and obj.user.is_active)

    def get_portal_invitation(self, obj):
        inv = obj.invitations.filter(accepted_at__isnull=True, revoked_at__isnull=True).first()
        if inv is None:
            return None
        return {"id": inv.pk, "status": inv.status, "email": inv.email, "expires_at": inv.expires_at,
                "sent_count": inv.sent_count}

    def validate_email(self, value):
        value = (value or "").strip().lower()
        if value:
            qs = Tenant.objects.filter(email__iexact=value)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.filter(status=Tenant.Status.ACTIVE).exists():
                raise serializers.ValidationError("An active tenant with this email already exists.")
        return value


class TenantCreateSerializer(TenantSerializer):
    """Register a tenant and optionally move them in immediately."""

    create_portal_account = serializers.BooleanField(write_only=True, default=True)
    unit = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.all(), write_only=True, required=False,
                                              allow_null=True)
    start_date = serializers.DateField(write_only=True, required=False)
    monthly_rent = serializers.DecimalField(max_digits=12, decimal_places=2, write_only=True, required=False)
    deposit_amount = serializers.DecimalField(max_digits=12, decimal_places=2, write_only=True, required=False)
    rent_due_day = serializers.IntegerField(write_only=True, required=False, min_value=1, max_value=28)
    expected_end_date = serializers.DateField(write_only=True, required=False, allow_null=True)

    class Meta(TenantSerializer.Meta):
        fields = TenantSerializer.Meta.fields + ["create_portal_account", "unit", "start_date", "monthly_rent",
                                                 "deposit_amount", "rent_due_day", "expected_end_date"]

    def validate(self, attrs):
        if attrs.get("create_portal_account") and not attrs.get("email"):
            raise serializers.ValidationError({"email": "An email address is needed for a portal account."})
        if attrs.get("create_portal_account") and not attrs.get("unit"):
            raise serializers.ValidationError({"create_portal_account": (
                "Portal invitations are only sent to tenants with a current tenancy. Choose a unit, or untick "
                "this and invite the tenant after move-in.")})
        if attrs.get("create_portal_account") and User.objects.filter(email__iexact=attrs["email"]).exists():
            raise serializers.ValidationError({"email": "A user account with this email already exists."})
        if attrs.get("unit") and not attrs.get("start_date"):
            raise serializers.ValidationError({"start_date": "Enter the tenancy start date."})
        return attrs


class TenancySerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.full_name", read_only=True)
    unit_label = serializers.CharField(source="unit.label", read_only=True)
    property_name = serializers.CharField(source="property.name", read_only=True)
    reminder_schedule_name = serializers.CharField(source="reminder_schedule.name", read_only=True, default=None)
    account = serializers.SerializerMethodField()

    class Meta:
        model = Tenancy
        fields = "__all__"
        read_only_fields = [
            "tenant", "unit", "property", "reservation", "transferred_from", "status", "start_date", "notice_date",
            "planned_move_out", "actual_move_out", "move_out_inspection_date", "move_out_inspection_notes",
            "deposit_deductions", "deposit_deduction_notes", "deposit_applied_to_balance", "deposit_refund_amount",
            "deposit_reconciled_at", "unit_available_from", "created_by", "created_at", "updated_at",
            "charge_deposit",
        ]

    FINANCIAL_FIELDS = (
        "monthly_rent", "service_charge", "deposit_amount", "deposit_deductions", "deposit_deduction_notes",
        "deposit_applied_to_balance", "deposit_refund_amount", "account", "charge_deposit",
    )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if self.context.get("hide_financials"):
            for f in self.FINANCIAL_FIELDS:
                data.pop(f, None)
        return data

    def get_account(self, obj):
        s = self.context.get("summaries", {}).get(obj.pk)
        if s is None and self.context.get("with_account"):
            from billing.services import account_summary

            s = account_summary(obj)
        return s.as_dict() if s else None


class MoveInSerializer(serializers.Serializer):
    tenant = serializers.PrimaryKeyRelatedField(queryset=Tenant.objects.all())
    unit = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.all())
    start_date = serializers.DateField()
    expected_end_date = serializers.DateField(required=False, allow_null=True)
    monthly_rent = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    service_charge = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    deposit_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    charge_deposit = serializers.BooleanField(default=True)
    rent_due_day = serializers.IntegerField(required=False, min_value=1, max_value=28)
    grace_days = serializers.IntegerField(required=False, min_value=0, max_value=60)
    move_in_inspection_notes = serializers.CharField(required=False, allow_blank=True)


class NoticeSerializer(serializers.Serializer):
    notice_date = serializers.DateField()
    planned_move_out = serializers.DateField()


class MoveOutSerializer(serializers.Serializer):
    actual_move_out = serializers.DateField()
    inspection_date = serializers.DateField(required=False, allow_null=True)
    inspection_notes = serializers.CharField(required=False, allow_blank=True)
    deposit_deductions = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)
    deduction_notes = serializers.CharField(required=False, allow_blank=True)
    apply_deposit_to_balance = serializers.BooleanField(default=True)
    unit_status_after = serializers.ChoiceField(choices=["available", "maintenance", "unavailable"],
                                                default="available")
    unit_available_from = serializers.DateField(required=False, allow_null=True)


class TransferSerializer(serializers.Serializer):
    unit = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.all())
    transfer_date = serializers.DateField()
    monthly_rent = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)


class PortalProfileSerializer(serializers.ModelSerializer):
    """What a tenant may see and edit about themselves (no staff notes)."""

    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Tenant
        fields = ["id", "first_name", "last_name", "full_name", "email", "phone", "alternative_phone",
                  "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relationship",
                  "notify_sms", "notify_email", "notify_whatsapp"]
        read_only_fields = ["first_name", "last_name", "email", "phone"]
