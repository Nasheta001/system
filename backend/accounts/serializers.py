from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from properties.models import Property

from .models import AuditLog, CompanySettings, Invitation, PropertyAssignment, STAFF_ROLES, User
from .permissions import accessible_property_ids, capabilities


class AssignedPropertySerializer(serializers.ModelSerializer):
    class Meta:
        model = Property
        fields = ["id", "name", "town"]


class MeSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="get_full_name")
    capabilities = serializers.SerializerMethodField()
    assigned_properties = serializers.SerializerMethodField()
    portfolio_access = serializers.BooleanField(source="has_portfolio_access")
    tenant_id = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "full_name", "phone", "role", "capabilities",
                  "assigned_properties", "portfolio_access", "tenant_id", "must_change_password"]

    def get_capabilities(self, obj):
        return sorted(capabilities(obj))

    def get_assigned_properties(self, obj):
        ids = accessible_property_ids(obj)
        qs = Property.objects.filter(status="active")
        if ids is not None:
            qs = qs.filter(id__in=ids)
        if obj.is_tenant:
            return []
        return AssignedPropertySerializer(qs.order_by("name"), many=True).data

    def get_tenant_id(self, obj):
        return getattr(getattr(obj, "tenant_profile", None), "id", None)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False)
    portal = serializers.ChoiceField(choices=["management", "tenant"])
    remember = serializers.BooleanField(default=True)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False)
    new_password = serializers.CharField(trim_whitespace=False)

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError({"current_password": "Current password is incorrect."})
        validate_password(attrs["new_password"], user)
        return attrs


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(trim_whitespace=False)


class StaffSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="get_full_name", read_only=True)
    property_ids = serializers.PrimaryKeyRelatedField(
        source="assigned_property_ids", many=True, queryset=Property.objects.all(), required=False, write_only=True
    )
    assigned_properties = serializers.SerializerMethodField()
    job_title = serializers.CharField(source="staff_profile.job_title", required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "full_name", "phone", "role", "is_active", "job_title",
                  "property_ids", "assigned_properties", "last_login", "date_joined"]
        read_only_fields = ["is_active", "last_login", "date_joined"]

    def get_assigned_properties(self, obj):
        return [{"id": a.property_id, "name": a.property.name, "is_primary_contact": a.is_primary_contact}
                for a in obj.assignments.select_related("property").all()]

    def validate_role(self, value):
        if value not in STAFF_ROLES:
            raise serializers.ValidationError("Choose a staff role.")
        return value

    def validate_email(self, value):
        value = value.lower().strip()
        qs = User.objects.filter(email__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def _apply_related(self, user, props, profile):
        from .models import StaffProfile

        request = self.context["request"]
        if profile is not None:
            sp, _ = StaffProfile.objects.get_or_create(user=user)
            sp.job_title = profile.get("job_title", sp.job_title)
            sp.save()
        if props is not None:
            keep = {p.pk for p in props}
            user.assignments.exclude(property_id__in=keep).delete()
            for p in props:
                PropertyAssignment.objects.get_or_create(user=user, property=p, defaults={"assigned_by": request.user})

    def update(self, instance, validated):
        props = validated.pop("assigned_property_ids", None)
        profile = validated.pop("staff_profile", None)
        for k, v in validated.items():
            setattr(instance, k, v)
        instance.save()
        self._apply_related(instance, props, profile)
        return instance


class StaffOptionSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="get_full_name")

    class Meta:
        model = User
        fields = ["id", "full_name", "role", "email"]


class CompanySettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanySettings
        exclude = ["id"]

    def validate_rent_receiving_phone(self, value):
        value = (value or "").strip()
        if not value:
            return ""
        from billing.mpesa import MpesaError, normalize_phone

        try:
            return "+" + normalize_phone(value)
        except MpesaError as exc:
            raise serializers.ValidationError("Enter a Safaricom number, e.g. +254712345678.") from exc

    def validate(self, attrs):
        phone = attrs.get("rent_receiving_phone", getattr(self.instance, "rent_receiving_phone", ""))
        if attrs.get("rent_phone_payments_enabled") and not phone:
            raise serializers.ValidationError(
                {"rent_receiving_phone": "Set the receiving number before enabling phone payments."})
        return attrs

    def validate_faq(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("FAQ must be a list.")
        for item in value:
            if not isinstance(item, dict) or not item.get("question") or not item.get("answer"):
                raise serializers.ValidationError("Each FAQ item needs a question and an answer.")
        return [{"question": str(i["question"])[:300], "answer": str(i["answer"])[:2000]} for i in value]


class PublicCompanySerializer(serializers.ModelSerializer):
    turnstile_site_key = serializers.SerializerMethodField()

    class Meta:
        model = CompanySettings
        fields = ["name", "tagline", "about", "phone", "whatsapp", "email", "address", "currency", "faq",
                  "privacy_notice", "turnstile_site_key"]

    def get_turnstile_site_key(self, obj):
        from django.conf import settings

        return settings.TURNSTILE_SITE_KEY or None


class InvitationSerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    property_names = serializers.SerializerMethodField()

    class Meta:
        model = Invitation
        fields = ["id", "kind", "email", "first_name", "last_name", "phone", "role", "role_label", "job_title",
                  "property_ids", "property_names", "tenant", "tenancy", "status", "expires_at", "created_at",
                  "created_by_name", "sent_count", "accepted_at", "revoked_at", "revoke_reason"]
        read_only_fields = fields

    def get_created_by_name(self, obj):
        return str(obj.created_by) if obj.created_by else "System"

    def get_property_names(self, obj):
        if not obj.property_ids:
            return []
        return list(Property.objects.filter(pk__in=obj.property_ids).order_by("name").values_list("name", flat=True))


class StaffInvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True,
                                  validators=User._meta.get_field("phone").validators)
    role = serializers.ChoiceField(choices=sorted(STAFF_ROLES))
    job_title = serializers.CharField(max_length=100, required=False, allow_blank=True)
    property_ids = serializers.PrimaryKeyRelatedField(many=True, queryset=Property.objects.all(), required=False)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value


class AcceptInvitationSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=200)
    password = serializers.CharField(trim_whitespace=False, max_length=128)


class InitialSetupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    password = serializers.CharField(trim_whitespace=False, max_length=128)
    setup_token = serializers.CharField(required=False, allow_blank=True, max_length=200)

    def validate_email(self, value):
        return value.strip().lower()


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()
    property_name = serializers.CharField(source="property.name", default=None)

    class Meta:
        model = AuditLog
        fields = ["id", "actor", "actor_name", "action", "object_type", "object_id", "summary", "changes",
                  "property", "property_name", "ip_address", "created_at"]

    def get_actor_name(self, obj):
        return str(obj.actor) if obj.actor else "System"
