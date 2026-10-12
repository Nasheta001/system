import os
from collections import defaultdict

from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.audit import audit
from accounts.permissions import IsStaffMember, IsTenantUser, StaffCapability, accessible_property_ids, has_cap
from config.validators import validate_document_upload

from .models import Announcement, AnnouncementAttachment, AnnouncementRecipient, Notification, NotificationTemplate
from .providers import channel_status
from .serializers import (
    AnnouncementSerializer, InAppNotificationSerializer, NotificationSerializer, PortalAnnouncementSerializer,
    RecipientSerializer, TemplateSerializer,
)
from .services import deliver, publish_announcement, resolve_announcement_audience


def file_download(field, name):
    resp = FileResponse(field.open("rb"), as_attachment=True, filename=name)
    resp["Cache-Control"] = "private, no-store"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


def scoped_announcements(user):
    qs = Announcement.objects.all()
    ids = accessible_property_ids(user)
    if ids is None:
        return qs
    return qs.filter(
        Q(author=user) | Q(properties__in=ids) | Q(buildings__property__in=ids) | Q(staff=user)
    ).distinct()


class AnnouncementViewSet(viewsets.ModelViewSet):
    serializer_class = AnnouncementSerializer
    permission_classes = [StaffCapability]
    read_cap = "view_announcements"
    write_cap = "manage_announcements"
    filterset_fields = ["status", "priority", "audience", "is_template", "properties"]
    search_fields = ["title", "body"]
    ordering_fields = ["created_at", "published_at", "priority"]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        return scoped_announcements(self.request.user).select_related("author", "related_document").prefetch_related(
            "properties", "buildings", "tenants", "staff", "attachments", "recipients")

    def perform_create(self, serializer):
        ann = serializer.save(author=self.request.user)
        audit(self.request, "announcement.create", ann, f"Created announcement '{ann.title}'")

    def perform_update(self, serializer):
        if serializer.instance.status in (Announcement.Status.PUBLISHED, Announcement.Status.ARCHIVED):
            changed = set(serializer.validated_data) - {"expires_at", "is_template"}
            if changed:
                raise PermissionDenied("Published notices cannot be edited. Duplicate it to send a corrected version.")
        ann = serializer.save()
        audit(self.request, "announcement.update", ann, f"Updated announcement '{ann.title}'")

    def destroy(self, request, *args, **kwargs):
        ann = self.get_object()
        if ann.status != Announcement.Status.DRAFT:
            return Response({"detail": "Only drafts can be deleted. Archive published notices instead."}, status=409)
        audit(request, "announcement.delete", ann, f"Deleted draft '{ann.title}'")
        ann.delete()
        return Response(status=204)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        ann = self.get_object()
        if ann.status not in (Announcement.Status.DRAFT, Announcement.Status.SCHEDULED):
            return Response({"detail": "This notice is already published or archived."}, status=400)
        if ann.is_template:
            return Response({"detail": "Templates cannot be published. Use 'Use template' to create a notice."},
                            status=400)
        if ann.publish_at and ann.publish_at > timezone.now():
            ann.status = Announcement.Status.SCHEDULED
            ann.save(update_fields=["status", "updated_at"])
            audit(request, "announcement.schedule", ann, f"Scheduled '{ann.title}' for {ann.publish_at:%Y-%m-%d %H:%M}")
        else:
            ann = publish_announcement(ann, request.user)
            audit(request, "announcement.publish", ann, f"Published '{ann.title}' to {ann.recipients.count()} recipients")
        return Response(self.get_serializer(ann).data)

    @action(detail=True, methods=["post"])
    def unschedule(self, request, pk=None):
        ann = self.get_object()
        if ann.status != Announcement.Status.SCHEDULED:
            return Response({"detail": "Not scheduled."}, status=400)
        ann.status = Announcement.Status.DRAFT
        ann.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(ann).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        ann = self.get_object()
        ann.status = Announcement.Status.ARCHIVED
        ann.save(update_fields=["status", "updated_at"])
        audit(request, "announcement.archive", ann, f"Archived '{ann.title}'")
        return Response(self.get_serializer(ann).data)

    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        src = self.get_object()
        copy = Announcement.objects.create(
            title=src.title if src.is_template else f"{src.title} (copy)", body=src.body, priority=src.priority,
            audience=src.audience, requires_acknowledgement=src.requires_acknowledgement, action_text=src.action_text,
            related_document=src.related_document, send_email=src.send_email, send_sms=src.send_sms,
            send_whatsapp=src.send_whatsapp, author=request.user,
        )
        ids = accessible_property_ids(request.user)
        props = src.properties.all() if ids is None else src.properties.filter(pk__in=ids)
        copy.properties.set(props)
        copy.buildings.set(src.buildings.all() if ids is None else src.buildings.filter(property_id__in=ids))
        copy.tenants.set(src.tenants.all())
        copy.staff.set(src.staff.all())
        if ids is not None and copy.audience == Announcement.Audience.ALL_TENANTS:
            copy.audience = Announcement.Audience.PROPERTIES
            copy.save(update_fields=["audience"])
        return Response(self.get_serializer(copy).data, status=201)

    @action(detail=True, methods=["get"])
    def recipients(self, request, pk=None):
        ann = self.get_object()
        recs = ann.recipients.select_related("tenant", "user", "property").order_by("tenant__first_name")
        deliveries = defaultdict(list)
        for n in Notification.objects.filter(related_type="Announcement", related_id=str(ann.pk)):
            deliveries[(n.tenant_id, None if n.tenant_id else n.user_id)].append(n)
        keyed = {}
        for r in recs:
            keyed[(r.tenant_id, None if r.tenant_id else r.user_id)] = r
        ctx = {"deliveries": {(r.tenant_id, r.user_id): deliveries.get((r.tenant_id, None if r.tenant_id else r.user_id), [])
                              for r in recs}}
        return Response(RecipientSerializer(recs, many=True, context=ctx).data)

    @action(detail=True, methods=["get"], url_path="audience-preview")
    def audience_preview(self, request, pk=None):
        ann = self.get_object()
        tenancies, staff = resolve_announcement_audience(ann)
        return Response({"tenants": len(tenancies), "staff": len(staff),
                         "sample": [t.tenant.full_name for t in tenancies[:10]]})

    @action(detail=True, methods=["post"], url_path="attachments")
    def add_attachment(self, request, pk=None):
        ann = self.get_object()
        f = request.FILES.get("file")
        if not f:
            return Response({"file": ["Choose a file."]}, status=400)
        validate_document_upload(f)
        att = AnnouncementAttachment.objects.create(announcement=ann, file=f, original_name=os.path.basename(f.name)[:200])
        return Response({"id": att.pk, "original_name": att.original_name}, status=201)


class AttachmentDownloadView(APIView):
    """Staff with announcement access or tenants who received the notice."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        att = get_object_or_404(AnnouncementAttachment.objects.select_related("announcement"), pk=pk)
        user = request.user
        allowed = False
        if user.is_tenant and hasattr(user, "tenant_profile"):
            allowed = AnnouncementRecipient.objects.filter(
                announcement=att.announcement, tenant=user.tenant_profile, announcement__status="published"
            ).exists()
        elif has_cap(user, "view_announcements"):
            allowed = scoped_announcements(user).filter(pk=att.announcement_id).exists()
        if not allowed:
            return Response({"detail": "Not found."}, status=404)
        return file_download(att.file, att.original_name)


class TemplateViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = TemplateSerializer
    permission_classes = [StaffCapability]
    read_cap = "manage_settings"
    write_cap = "manage_settings"
    queryset = NotificationTemplate.objects.all()
    pagination_class = None

    def perform_update(self, serializer):
        t = serializer.save()
        audit(self.request, "template.update", t, f"Updated message template {t.key}")


class NotificationLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [StaffCapability]
    read_cap = "view_audit"
    action_caps = {"retry": "manage_settings"}
    filterset_fields = ["channel", "status", "template_key"]
    search_fields = ["to_address", "subject", "tenant__first_name", "tenant__last_name"]

    def get_queryset(self):
        return Notification.objects.select_related("tenant", "user")

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        n = self.get_object()
        if n.status != Notification.Status.FAILED:
            return Response({"detail": "Only failed notifications can be retried."}, status=400)
        n.next_attempt_at = timezone.now()
        deliver(n)
        return Response(self.get_serializer(n).data)


class ChannelStatusView(APIView):
    permission_classes = [IsStaffMember]

    def get(self, request):
        return Response(channel_status())


class MyNotificationsView(APIView):
    """In-app notifications for the signed-in user (staff or tenant)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Notification.objects.filter(user=request.user, channel="in_app").order_by("-created_at")
        return Response({"unread": qs.filter(read_at__isnull=True).count(),
                         "results": InAppNotificationSerializer(qs[:50], many=True).data})

    def post(self, request):
        """Mark notifications as read: {"ids": [...]} or {"all": true}."""
        qs = Notification.objects.filter(user=request.user, channel="in_app", read_at__isnull=True)
        if not request.data.get("all"):
            ids = [i for i in request.data.get("ids", []) if str(i).isdigit()]
            qs = qs.filter(pk__in=ids)
        qs.update(read_at=timezone.now())
        return Response({"detail": "ok"})


class PortalAnnouncementViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = PortalAnnouncementSerializer
    permission_classes = [IsTenantUser]

    def get_queryset(self):
        now = timezone.now()
        return AnnouncementRecipient.objects.filter(
            tenant=self.request.user.tenant_profile, announcement__status="published",
        ).filter(Q(announcement__expires_at__isnull=True) | Q(announcement__expires_at__gt=now)
                 | Q(announcement__requires_acknowledgement=True, acknowledged_at__isnull=True)
                 ).select_related("announcement").prefetch_related("announcement__attachments").order_by(
            "-announcement__published_at")

    def retrieve(self, request, *args, **kwargs):
        rec = self.get_object()
        if not rec.opened_at:
            rec.opened_at = timezone.now()
            rec.save(update_fields=["opened_at"])
        return Response(self.get_serializer(rec).data)

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        rec = self.get_object()
        now = timezone.now()
        rec.opened_at = rec.opened_at or now
        rec.acknowledged_at = rec.acknowledged_at or now
        rec.save(update_fields=["opened_at", "acknowledged_at"])
        return Response(self.get_serializer(rec).data)
