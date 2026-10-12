from rest_framework import serializers

from .models import MaintenanceAttachment, MaintenanceRequest, MaintenanceUpdate


class UpdateSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceUpdate
        fields = ["id", "author_name", "message", "is_internal", "status_from", "status_to", "created_at"]

    def get_author_name(self, obj):
        if not obj.author:
            return "System"
        if obj.author.is_tenant:
            return obj.author.get_full_name() or "Tenant"
        return obj.author.get_full_name() or "Management"


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaintenanceAttachment
        fields = ["id", "original_name", "is_internal", "uploaded_at"]


class MaintenanceSerializer(serializers.ModelSerializer):
    property_name = serializers.CharField(source="property.name", read_only=True)
    unit_label = serializers.CharField(source="unit.label", read_only=True, default=None)
    tenant_name = serializers.CharField(source="tenant.full_name", read_only=True, default=None)
    tenant_phone = serializers.CharField(source="tenant.phone", read_only=True, default=None)
    assigned_to_name = serializers.CharField(source="assigned_to.get_full_name", read_only=True, default=None)
    updates = UpdateSerializer(many=True, read_only=True)
    attachments = AttachmentSerializer(many=True, read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = MaintenanceRequest
        fields = ["id", "reference", "property", "property_name", "unit", "unit_label", "tenant", "tenant_name",
                  "tenant_phone", "title", "description", "category", "urgency", "status", "status_label",
                  "assigned_to", "assigned_to_name", "resolution_notes", "completed_at", "closed_at", "created_at",
                  "updated_at", "updates", "attachments"]
        read_only_fields = ["reference", "status", "completed_at", "closed_at", "created_at", "updated_at"]

    def validate(self, attrs):
        prop = attrs.get("property") or getattr(self.instance, "property", None)
        unit = attrs.get("unit")
        if unit and prop and unit.property_id != prop.pk:
            raise serializers.ValidationError({"unit": "Unit must belong to the property."})
        if self.instance and "property" in attrs and attrs["property"] != self.instance.property:
            raise serializers.ValidationError({"property": "Property cannot be changed."})
        return attrs


class StatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=MaintenanceRequest.Status.choices)
    message = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    is_internal = serializers.BooleanField(default=False)
    resolution_notes = serializers.CharField(required=False, allow_blank=True)


class NoteSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=4000)
    is_internal = serializers.BooleanField(default=True)


class PortalMaintenanceSerializer(serializers.ModelSerializer):
    """Tenant view: no internal notes, no internal attachments, no staff assignment details."""

    property_name = serializers.CharField(source="property.name", read_only=True)
    unit_label = serializers.CharField(source="unit.label", read_only=True, default=None)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    updates = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceRequest
        fields = ["id", "reference", "property_name", "unit_label", "title", "description", "category", "urgency",
                  "status", "status_label", "resolution_notes", "created_at", "updated_at", "completed_at",
                  "updates", "attachments"]
        read_only_fields = ["reference", "status", "resolution_notes", "completed_at"]

    def get_updates(self, obj):
        return UpdateSerializer([u for u in obj.updates.all() if not u.is_internal], many=True).data

    def get_attachments(self, obj):
        return AttachmentSerializer([a for a in obj.attachments.all() if not a.is_internal], many=True).data
