import os

from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from accounts.audit import audit
from accounts.models import Role
from accounts.permissions import IsTenantUser, can_access_property
from communications.views import file_download
from config.mixins import PropertyScopedMixin
from config.validators import validate_document_upload

from .models import MaintenanceAttachment, MaintenanceRequest, MaintenanceUpdate
from .serializers import (
    MaintenanceSerializer, NoteSerializer, PortalMaintenanceSerializer, StatusChangeSerializer,
)


def _notify_tenant(req, message=""):
    from communications.services import notify_tenant

    if not req.tenant_id:
        return
    transaction.on_commit(lambda: notify_tenant(
        req.tenant, "maintenance_update",
        {"reference": req.reference, "title": req.title, "status": req.get_status_display(), "message": message},
        link=f"/tenant/maintenance/{req.pk}", channels=["in_app", "email", "sms"],
        dedupe=f"mr:{req.pk}:{req.status}:{req.updated_at.timestamp():.0f}", related=("MaintenanceRequest", req.pk),
    ))


def _save_attachment(req, f, user, internal):
    if not f:
        raise ValidationError({"file": "Choose a file."})
    validate_document_upload(f)
    return MaintenanceAttachment.objects.create(request=req, file=f, original_name=os.path.basename(f.name)[:200],
                                                is_internal=internal, uploaded_by=user)


class MaintenanceViewSet(PropertyScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                         mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = MaintenanceSerializer
    read_cap = "view_maintenance"
    write_cap = "manage_maintenance"
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    filterset_fields = ["status", "urgency", "category", "property", "assigned_to", "tenant"]
    search_fields = ["reference", "title", "description", "unit__unit_number", "tenant__first_name",
                     "tenant__last_name"]
    ordering_fields = ["created_at", "urgency", "status", "updated_at"]

    def get_queryset(self):
        qs = MaintenanceRequest.objects.select_related(
            "property", "unit", "unit__building", "tenant", "assigned_to").prefetch_related(
            Prefetch("updates", queryset=MaintenanceUpdate.objects.select_related("author")), "attachments")
        if self.request.query_params.get("open") == "true":
            qs = qs.filter(status__in=MaintenanceRequest.OPEN_STATUSES)
        if self.request.query_params.get("mine") == "true":
            qs = qs.filter(assigned_to=self.request.user)
        return self.scope(qs)

    def perform_create(self, serializer):
        self.check_target(serializer)
        req = serializer.save(reported_by=self.request.user)
        if req.tenant_id is None and req.unit_id:
            t = req.unit.tenancies.filter(status__in=["active", "notice"]).first()
            if t:
                req.tenant_id, req.tenancy_id = t.tenant_id, t.pk
                req.save(update_fields=["tenant", "tenancy"])
        audit(self.request, "maintenance.create", req, f"Logged maintenance request {req.reference}")

    def perform_update(self, serializer):
        assignee = serializer.validated_data.get("assigned_to")
        if assignee and (assignee.role == Role.TENANT or not (
            assignee.has_portfolio_access or assignee.assignments.filter(property=serializer.instance.property).exists()
        )):
            raise ValidationError({"assigned_to": "Assign to a staff member who covers this property."})
        req = super().perform_update(serializer)
        if assignee and req.status in ("submitted", "reviewed"):
            prev = req.status
            req.status = MaintenanceRequest.Status.ASSIGNED
            req.save(update_fields=["status", "updated_at"])
            MaintenanceUpdate.objects.create(request=req, author=self.request.user, status_from=prev,
                                             status_to=req.status, message=f"Assigned to {assignee.get_full_name()}",
                                             is_internal=True)
            _notify_tenant(req, "A team member has been assigned to your request.")

    @action(detail=True, methods=["post"], url_path="status")
    def change_status(self, request, pk=None):
        req = self.get_object()
        s = StatusChangeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        prev = req.status
        req.status = d["status"]
        now = timezone.now()
        if req.status == "completed":
            req.completed_at = req.completed_at or now
        if req.status == "closed":
            req.closed_at = now
        if "resolution_notes" in d:
            req.resolution_notes = d["resolution_notes"]
        req.save()
        MaintenanceUpdate.objects.create(request=req, author=request.user, status_from=prev, status_to=req.status,
                                         message=d.get("message", ""), is_internal=d["is_internal"])
        if prev != req.status and not d["is_internal"]:
            _notify_tenant(req, d.get("message", ""))
        audit(request, "maintenance.status", req, f"{req.reference}: {prev} → {req.status}")
        return Response(self.get_serializer(req).data)

    @action(detail=True, methods=["post"])
    def note(self, request, pk=None):
        req = self.get_object()
        s = NoteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        MaintenanceUpdate.objects.create(request=req, author=request.user, **s.validated_data)
        if not s.validated_data["is_internal"]:
            _notify_tenant(req, s.validated_data["message"][:300])
        req.save(update_fields=["updated_at"])
        return Response(self.get_serializer(req).data)

    @action(detail=True, methods=["post"], url_path="attachments")
    def add_attachment(self, request, pk=None):
        req = self.get_object()
        internal = str(request.data.get("is_internal", "false")).lower() == "true"
        _save_attachment(req, request.FILES.get("file"), request.user, internal)
        return Response(self.get_serializer(req).data, status=201)

    @action(detail=True, methods=["get"], url_path=r"attachments/(?P<att_id>\d+)")
    def download_attachment(self, request, pk=None, att_id=None):
        req = self.get_object()
        att = get_object_or_404(req.attachments, pk=att_id)
        return file_download(att.file, att.original_name)


class PortalMaintenanceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                               viewsets.GenericViewSet):
    serializer_class = PortalMaintenanceSerializer
    permission_classes = [IsTenantUser]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        return MaintenanceRequest.objects.filter(tenant=self.request.user.tenant_profile).select_related(
            "property", "unit", "unit__building").prefetch_related(
            Prefetch("updates", queryset=MaintenanceUpdate.objects.select_related("author")), "attachments")

    def perform_create(self, serializer):
        tenant = self.request.user.tenant_profile
        tenancy = tenant.current_tenancy()
        if tenancy is None:
            raise ValidationError({"detail": "You need an active tenancy to submit maintenance requests."})
        with transaction.atomic():
            req = serializer.save(tenant=tenant, tenancy=tenancy, property=tenancy.property, unit=tenancy.unit,
                                  reported_by=self.request.user)
            f = self.request.FILES.get("file")
            if f:
                _save_attachment(req, f, self.request.user, False)
        from accounts.models import User
        from communications.services import notify_user

        staff = User.objects.filter(is_active=True, role__in=[Role.MANAGER, Role.CARETAKER],
                                    assignments__property=tenancy.property).distinct()
        for u in staff:
            transaction.on_commit(lambda u=u: notify_user(
                u, "staff_alert", {"title": f"New maintenance request {req.reference}",
                                   "message": f"{req.title} – {tenancy.unit.label}, {tenancy.property.name} "
                                              f"({req.get_urgency_display()})"},
                link=f"/management/maintenance/{req.pk}", channels=("in_app",), dedupe=f"mrnew:{req.pk}:{u.pk}"))

    @action(detail=True, methods=["post"])
    def comment(self, request, pk=None):
        req = self.get_object()
        msg = str(request.data.get("message", "")).strip()
        if not msg:
            raise ValidationError({"message": "Write a message."})
        if req.status in ("closed", "cancelled"):
            raise ValidationError({"detail": "This request is closed."})
        MaintenanceUpdate.objects.create(request=req, author=request.user, message=msg[:4000], is_internal=False)
        req.save(update_fields=["updated_at"])
        return Response(self.get_serializer(req).data)

    @action(detail=True, methods=["post"], url_path="attachments")
    def add_attachment(self, request, pk=None):
        req = self.get_object()
        _save_attachment(req, request.FILES.get("file"), request.user, False)
        return Response(self.get_serializer(req).data, status=201)

    @action(detail=True, methods=["get"], url_path=r"attachments/(?P<att_id>\d+)")
    def download_attachment(self, request, pk=None, att_id=None):
        req = self.get_object()
        att = get_object_or_404(req.attachments, pk=att_id, is_internal=False)
        return file_download(att.file, att.original_name)
