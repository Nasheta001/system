from rest_framework import serializers

from properties.models import Property, Unit

from .models import RentalApplication, Reservation, ViewingRequest


def _require_consent(value):
    if not value:
        raise serializers.ValidationError("Please accept the privacy notice so we can process your details.")
    return value


class PublicViewingRequestSerializer(serializers.ModelSerializer):
    property = serializers.SlugRelatedField(slug_field="slug", queryset=Property.objects.filter(
        status="active", is_published=True))
    unit = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.all(), required=False, allow_null=True)
    consent_given = serializers.BooleanField(validators=[_require_consent])

    class Meta:
        model = ViewingRequest
        fields = ["property", "unit", "full_name", "phone", "email", "preferred_date", "message", "consent_given"]

    def validate(self, attrs):
        unit = attrs.get("unit")
        if unit and (unit.property_id != attrs["property"].pk or not unit.is_listed):
            raise serializers.ValidationError({"unit": "Unit not found."})
        return attrs


class PublicApplicationSerializer(serializers.ModelSerializer):
    unit = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.filter(
        is_listed=True, is_archived=False, status="available", property__is_published=True,
        property__status="active"), error_messages={"does_not_exist": "This unit is no longer available."})
    consent_given = serializers.BooleanField(validators=[_require_consent])

    class Meta:
        model = RentalApplication
        fields = ["reference", "unit", "full_name", "email", "phone", "occupation", "employer", "household_size",
                  "desired_move_in", "message", "consent_given", "status"]
        read_only_fields = ["reference", "status"]

    def validate(self, attrs):
        dup = RentalApplication.objects.filter(
            unit=attrs["unit"], email__iexact=attrs["email"], status__in=RentalApplication.OPEN_STATUSES
        ).exists()
        if dup:
            raise serializers.ValidationError("You already have an open application for this unit.")
        return attrs


class ApplicationLookupSerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=20)
    email = serializers.EmailField()


class ViewingRequestSerializer(serializers.ModelSerializer):
    property_name = serializers.CharField(source="property.name", read_only=True)
    unit_label = serializers.CharField(source="unit.label", read_only=True, default=None)
    handled_by_name = serializers.CharField(source="handled_by.get_full_name", read_only=True, default=None)

    class Meta:
        model = ViewingRequest
        fields = "__all__"
        read_only_fields = ["property", "unit", "full_name", "phone", "email", "preferred_date", "message",
                            "consent_given", "handled_by", "created_at", "updated_at"]


class ApplicationSerializer(serializers.ModelSerializer):
    property_name = serializers.CharField(source="property.name", read_only=True)
    unit_label = serializers.CharField(source="unit.label", read_only=True)
    unit_status = serializers.CharField(source="unit.status", read_only=True)
    rent_amount = serializers.DecimalField(source="unit.rent_amount", max_digits=12, decimal_places=2,
                                           read_only=True)
    reviewed_by_name = serializers.CharField(source="reviewed_by.get_full_name", read_only=True, default=None)
    active_reservation = serializers.SerializerMethodField()

    class Meta:
        model = RentalApplication
        fields = "__all__"
        read_only_fields = [f.name for f in RentalApplication._meta.fields if f.name not in ("internal_notes",)]

    def get_active_reservation(self, obj):
        r = obj.reservations.filter(status="active").first()
        return {"id": r.pk, "expires_at": r.expires_at} if r else None


class ApplicationStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=RentalApplication.Status.choices)
    applicant_message = serializers.CharField(required=False, allow_blank=True, max_length=500)
    internal_notes = serializers.CharField(required=False, allow_blank=True)


class ReservationSerializer(serializers.ModelSerializer):
    property_name = serializers.CharField(source="property.name", read_only=True)
    unit_label = serializers.CharField(source="unit.label", read_only=True)
    application_reference = serializers.CharField(source="application.reference", read_only=True, default=None)
    tenancy_id = serializers.SerializerMethodField()

    class Meta:
        model = Reservation
        fields = "__all__"
        read_only_fields = ["property", "status", "release_to_status", "reserved_by", "created_at", "closed_at"]

    def get_tenancy_id(self, obj):
        t = getattr(obj, "tenancy", None)
        return t.pk if t else None


class ReserveSerializer(serializers.Serializer):
    unit = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.all(), required=False)
    holder_name = serializers.CharField(max_length=120, required=False)
    holder_phone = serializers.CharField(max_length=20, required=False)
    holder_email = serializers.EmailField(required=False, allow_blank=True)
    expires_at = serializers.DateTimeField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


class ConvertSerializer(serializers.Serializer):
    tenant = serializers.IntegerField(required=False, help_text="Existing tenant id; omit to create from holder")
    first_name = serializers.CharField(required=False, max_length=80)
    last_name = serializers.CharField(required=False, max_length=80, allow_blank=True)
    id_number = serializers.CharField(required=False, allow_blank=True, max_length=30)
    create_portal_account = serializers.BooleanField(default=True)
    start_date = serializers.DateField()
    expected_end_date = serializers.DateField(required=False, allow_null=True)
    monthly_rent = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    deposit_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    rent_due_day = serializers.IntegerField(required=False, min_value=1, max_value=28)
    move_in_inspection_notes = serializers.CharField(required=False, allow_blank=True)
