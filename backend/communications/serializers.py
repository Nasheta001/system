import os

from rest_framework import serializers

from accounts.models import Role, User
from accounts.permissions import accessible_property_ids
from properties.models import Building, Property
from tenancies.models import Tenant

from .models import Announcement, AnnouncementAttachment, AnnouncementRecipient, Notification, NotificationTemplate


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnnouncementAttachment
        fields = ["id", "original_name", "uploaded_at"]


class AnnouncementSerializer(serializers.ModelSerializer):
    property_ids = serializers.PrimaryKeyRelatedField(source="properties", many=True, required=False,
                                                      queryset=Property.objects.all())
    building_ids = serializers.PrimaryKeyRelatedField(source="buildings", many=True, required=False,
                                                      queryset=Building.objects.all())
    tenant_ids = serializers.PrimaryKeyRelatedField(source="tenants", many=True, required=False,
                                                    queryset=Tenant.objects.all())
    staff_ids = serializers.PrimaryKeyRelatedField(source="staff", many=True, required=False,
                                                   queryset=User.objects.exclude(role=Role.TENANT))
    property_names = serializers.SerializerMethodField()
    author_name = serializers.CharField(source="author.get_full_name", read_only=True, default=None)
    attachments = AttachmentSerializer(many=True, read_only=True)
    stats = serializers.SerializerMethodField()
    related_document_title = serializers.CharField(source="related_document.title", read_only=True, default=None)

    class Meta:
        model = Announcement
        fields = ["id", "title", "body", "priority", "status", "audience", "property_ids", "building_ids",
                  "tenant_ids", "staff_ids", "property_names", "requires_acknowledgement", "action_text",
                  "related_document", "related_document_title", "send_email", "send_sms", "send_whatsapp",
                  "publish_at", "expires_at", "published_at", "is_template", "author", "author_name", "attachments",
                  "stats", "created_at", "updated_at"]
        read_only_fields = ["status", "published_at", "author", "created_at", "updated_at"]

    def get_property_names(self, obj):
        return [p.name for p in obj.properties.all()]

    def get_stats(self, obj):
        recs = list(obj.recipients.all()) if obj.status in ("published", "archived") else []
        return {"recipients": len(recs), "opened": sum(1 for r in recs if r.opened_at),
                "acknowledged": sum(1 for r in recs if r.acknowledged_at)}

    def validate(self, attrs):
        user = self.context["request"].user
        ids = accessible_property_ids(user)
        audience = attrs.get("audience", getattr(self.instance, "audience", None))
        props = attrs.get("properties", None)
        buildings = attrs.get("buildings", None)
        tenants = attrs.get("tenants", None)
        staff = attrs.get("staff", None)
        if ids is not None:
            if audience == Announcement.Audience.ALL_TENANTS:
                raise serializers.ValidationError({"audience": "Only portfolio administrators can message all tenants."})
            if props and any(p.pk not in ids for p in props):
                raise serializers.ValidationError({"property_ids": "You can only target your assigned properties."})
            if buildings and any(b.property_id not in ids for b in buildings):
                raise serializers.ValidationError({"building_ids": "You can only target your assigned buildings."})
            if tenants:
                allowed = set(Tenant.objects.filter(tenancies__property_id__in=ids).values_list("id", flat=True))
                if any(t.pk not in allowed for t in tenants):
                    raise serializers.ValidationError({"tenant_ids": "You can only message tenants in your properties."})
        if not self.partial or "audience" in attrs:
            need = {
                Announcement.Audience.PROPERTIES: ("properties", props, "property_ids"),
                Announcement.Audience.BUILDINGS: ("buildings", buildings, "building_ids"),
                Announcement.Audience.TENANTS: ("tenants", tenants, "tenant_ids"),
                Announcement.Audience.STAFF: ("staff", staff, "staff_ids"),
            }.get(audience)
            if need and not need[1] and not (self.instance and getattr(self.instance, need[0]).exists()):
                raise serializers.ValidationError({need[2]: "Select at least one recipient for this audience."})
        exp, pub = attrs.get("expires_at"), attrs.get("publish_at")
        if exp and pub and exp <= pub:
            raise serializers.ValidationError({"expires_at": "Expiry must be after the publication date."})
        return attrs


class RecipientSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    property_name = serializers.CharField(source="property.name", read_only=True, default=None)
    deliveries = serializers.SerializerMethodField()

    class Meta:
        model = AnnouncementRecipient
        fields = ["id", "tenant", "user", "name", "property_name", "delivered_at", "opened_at", "acknowledged_at",
                  "deliveries"]

    def get_name(self, obj):
        return obj.tenant.full_name if obj.tenant else str(obj.user)

    def get_deliveries(self, obj):
        notes = self.context.get("deliveries", {}).get((obj.tenant_id, obj.user_id), [])
        return [{"channel": n.channel, "status": n.status, "error": n.last_error} for n in notes]


class TemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationTemplate
        fields = ["id", "key", "name", "subject", "body", "short_body", "is_active", "updated_at"]
        read_only_fields = ["key"]


class NotificationSerializer(serializers.ModelSerializer):
    recipient = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ["id", "channel", "to_address", "recipient", "template_key", "subject", "body", "link", "status",
                  "attempts", "last_error", "sent_at", "read_at", "created_at", "related_type", "related_id"]

    def to_representation(self, instance):
        from django.conf import settings

        from .services import SECRET_LINK_TEMPLATES, redact_secret_links

        data = super().to_representation(instance)
        if instance.template_key in SECRET_LINK_TEMPLATES and not settings.DEBUG:
            data["body"] = redact_secret_links(data["body"])
        return data

    def get_recipient(self, obj):
        if obj.tenant_id:
            return obj.tenant.full_name
        if obj.user_id:
            return str(obj.user)
        return obj.to_address


class InAppNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "subject", "body", "link", "read_at", "created_at", "template_key"]


class PortalAnnouncementSerializer(serializers.ModelSerializer):
    title = serializers.CharField(source="announcement.title")
    body = serializers.CharField(source="announcement.body")
    priority = serializers.CharField(source="announcement.priority")
    published_at = serializers.DateTimeField(source="announcement.published_at")
    requires_acknowledgement = serializers.BooleanField(source="announcement.requires_acknowledgement")
    action_text = serializers.CharField(source="announcement.action_text")
    related_document = serializers.IntegerField(source="announcement.related_document_id", default=None)
    attachments = serializers.SerializerMethodField()
    announcement_id = serializers.IntegerField(source="announcement.id")

    class Meta:
        model = AnnouncementRecipient
        fields = ["id", "announcement_id", "title", "body", "priority", "published_at", "requires_acknowledgement",
                  "action_text", "related_document", "attachments", "opened_at", "acknowledged_at"]

    def get_attachments(self, obj):
        return AttachmentSerializer(obj.announcement.attachments.all(), many=True).data


def attachment_name(f):
    return os.path.basename(f.name)[:200]
