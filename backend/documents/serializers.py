from rest_framework import serializers

from .models import Document, DocumentAcknowledgement, DocumentAssignment, DocumentVersion, SignatureRequest


class VersionSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source="uploaded_by.get_full_name", read_only=True, default=None)

    class Meta:
        model = DocumentVersion
        fields = ["id", "version", "original_name", "size", "notes", "uploaded_by_name", "uploaded_at"]


class AssignmentSerializer(serializers.ModelSerializer):
    target = serializers.SerializerMethodField()

    class Meta:
        model = DocumentAssignment
        fields = ["id", "document", "scope", "property", "building", "tenant", "due_date", "target", "assigned_at"]
        read_only_fields = ["document", "assigned_at"]

    def get_target(self, obj):
        if obj.scope == "all_tenants":
            return "All active tenants"
        if obj.scope == "property":
            return obj.property.name if obj.property else ""
        if obj.scope == "building":
            return str(obj.building) if obj.building else ""
        return obj.tenant.full_name if obj.tenant else ""

    def validate(self, attrs):
        scope = attrs["scope"]
        need = {"property": "property", "building": "building", "tenant": "tenant"}.get(scope)
        if need and not attrs.get(need):
            raise serializers.ValidationError({need: "Required for this scope."})
        return attrs


class DocumentSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True, required=False)
    version_notes = serializers.CharField(write_only=True, required=False, allow_blank=True)
    current_version_info = VersionSerializer(source="current_version", read_only=True)
    versions = VersionSerializer(many=True, read_only=True)
    assignments = AssignmentSerializer(many=True, read_only=True)
    property_name = serializers.CharField(source="property.name", read_only=True, default=None)
    tenant_name = serializers.CharField(source="tenant.full_name", read_only=True, default=None)
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    workflow_label = serializers.CharField(source="get_workflow_display", read_only=True)

    class Meta:
        model = Document
        fields = ["id", "title", "description", "category", "category_label", "workflow", "workflow_label", "status",
                  "is_library", "property", "property_name", "tenant", "tenant_name", "tenancy", "current_version",
                  "current_version_info", "versions", "assignments", "file", "version_notes", "approved_at",
                  "created_at", "updated_at"]
        read_only_fields = ["status", "current_version", "approved_at", "created_at", "updated_at"]

    def validate(self, attrs):
        if not self.instance and not attrs.get("file"):
            raise serializers.ValidationError({"file": "Upload the document file."})
        tenancy = attrs.get("tenancy")
        if tenancy and attrs.get("tenant") and tenancy.tenant_id != attrs["tenant"].pk:
            raise serializers.ValidationError({"tenancy": "Tenancy does not belong to the selected tenant."})
        return attrs


class PortalDocumentSerializer(serializers.ModelSerializer):
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    version = serializers.IntegerField(source="current_version.version", read_only=True)
    file_name = serializers.CharField(source="current_version.original_name", read_only=True)
    updated = serializers.DateTimeField(source="current_version.uploaded_at", read_only=True)
    acknowledged_at = serializers.SerializerMethodField()
    signature = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = ["id", "title", "description", "category", "category_label", "workflow", "version", "file_name",
                  "updated", "acknowledged_at", "signature"]

    def get_acknowledged_at(self, obj):
        return self.context.get("acks", {}).get(obj.current_version_id)

    def get_signature(self, obj):
        s = self.context.get("signatures", {}).get(obj.pk)
        if not s:
            return None
        return {"id": s.pk, "status": s.status, "review_notes": s.review_notes, "due_date": s.due_date,
                "submitted_at": s.submitted_at}


class SignatureRequestSerializer(serializers.ModelSerializer):
    document_title = serializers.CharField(source="document.title", read_only=True)
    tenant_name = serializers.CharField(source="tenant.full_name", read_only=True)
    version_number = serializers.IntegerField(source="version.version", read_only=True)
    has_signed_file = serializers.SerializerMethodField()

    class Meta:
        model = SignatureRequest
        exclude = ["signed_file"]

    def get_has_signed_file(self, obj):
        return bool(obj.signed_file)


class AcknowledgementSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentAcknowledgement
        fields = ["id", "tenant", "version", "acknowledged_at"]
