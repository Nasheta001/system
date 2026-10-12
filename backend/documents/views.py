import os

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.audit import audit, client_ip
from accounts.permissions import IsTenantUser, StaffCapability, accessible_property_ids, can_access_property
from communications.views import file_download
from config.validators import validate_document_upload
from tenancies.models import Tenant
from tenancies.views import scoped_tenants

from .models import Document, DocumentAcknowledgement, DocumentAssignment, DocumentVersion, SignatureRequest
from .serializers import (
    AssignmentSerializer, DocumentSerializer, PortalDocumentSerializer, SignatureRequestSerializer,
)
from .services import (
    can_edit_document, create_signature_requests, eligible_tenants, notify_document_action, scoped_documents,
    visible_documents_for_tenant,
)


def _add_version(document, f, user, notes=""):
    validate_document_upload(f)
    last = document.versions.order_by("-version").first()
    v = DocumentVersion.objects.create(
        document=document, version=(last.version + 1) if last else 1, file=f,
        original_name=os.path.basename(f.name)[:200], size=f.size, notes=notes, uploaded_by=user,
    )
    document.current_version = v
    document.save(update_fields=["current_version", "updated_at"])
    return v


class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer
    permission_classes = [StaffCapability]
    read_cap = "view_documents"
    write_cap = "manage_documents"
    action_caps = {"download": "view_documents"}
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filterset_fields = ["category", "workflow", "status", "is_library", "property", "tenant"]
    search_fields = ["title", "description"]

    def get_queryset(self):
        return scoped_documents(self.request.user).select_related(
            "property", "tenant", "current_version", "tenancy").prefetch_related(
            "versions__uploaded_by", "assignments__property", "assignments__building", "assignments__tenant")

    def _check_scope(self, data):
        user = self.request.user
        prop = data.get("property")
        tenant = data.get("tenant")
        tenancy = data.get("tenancy")
        if prop and not can_access_property(user, prop.pk):
            raise PermissionDenied("You are not assigned to this property.")
        if tenant and not scoped_tenants(user).filter(pk=tenant.pk).exists():
            raise PermissionDenied("You cannot attach documents to this tenant.")
        if tenancy and not can_access_property(user, tenancy.property_id):
            raise PermissionDenied("You cannot attach documents to this tenancy.")
        if not (prop or tenant or tenancy) and accessible_property_ids(user) is not None:
            raise PermissionDenied("Company-wide documents are managed by portfolio administrators. "
                                   "Choose a property.")

    def _require_edit(self, document):
        if not can_edit_document(self.request.user, document):
            raise PermissionDenied("You cannot change this document.")

    def perform_create(self, serializer):
        self._check_scope(serializer.validated_data)
        f = serializer.validated_data.pop("file")
        notes = serializer.validated_data.pop("version_notes", "")
        with transaction.atomic():
            doc = serializer.save(created_by=self.request.user)
            _add_version(doc, f, self.request.user, notes)
            if doc.tenant_id:
                DocumentAssignment.objects.create(document=doc, scope="tenant", tenant=doc.tenant,
                                                  assigned_by=self.request.user)
        audit(self.request, "document.create", doc, f"Uploaded document '{doc.title}'")

    def perform_update(self, serializer):
        self._require_edit(serializer.instance)
        self._check_scope({k: v for k, v in serializer.validated_data.items() if k in ("property", "tenant", "tenancy")})
        serializer.validated_data.pop("file", None)
        serializer.validated_data.pop("version_notes", None)
        doc = serializer.save()
        audit(self.request, "document.update", doc, f"Updated document details '{doc.title}'")

    def destroy(self, request, *args, **kwargs):
        doc = self.get_object()
        self._require_edit(doc)
        if doc.status != Document.Status.DRAFT or doc.acknowledgements.exists() or doc.signature_requests.exists():
            return Response({"detail": "Approved or acknowledged documents are retained. Archive it instead."},
                            status=409)
        audit(request, "document.delete", doc, f"Deleted draft document '{doc.title}'")
        for v in doc.versions.all():
            v.file.delete(save=False)
        doc.delete()
        return Response(status=204)

    @action(detail=True, methods=["post"], url_path="versions")
    def new_version(self, request, pk=None):
        doc = self.get_object()
        self._require_edit(doc)
        f = request.FILES.get("file")
        if not f:
            raise ValidationError({"file": "Choose a file."})
        v = _add_version(doc, f, request.user, request.data.get("notes", ""))
        # A new version of an approved document goes back to draft until re-approved
        if doc.status == Document.Status.APPROVED:
            doc.status = Document.Status.DRAFT
            doc.save(update_fields=["status"])
        audit(request, "document.version", doc, f"Uploaded version {v.version} of '{doc.title}'")
        return Response(self.get_serializer(doc).data, status=201)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        doc = self.get_object()
        self._require_edit(doc)
        doc.status = Document.Status.APPROVED
        doc.approved_by = request.user
        doc.approved_at = timezone.now()
        doc.save()
        tenants = list(eligible_tenants(doc))
        notify_document_action(doc, tenants)
        if doc.workflow == Document.Workflow.SIGNATURE:
            create_signature_requests(doc, tenants, request.user)
        audit(request, "document.approve", doc, f"Approved '{doc.title}' (v{doc.current_version.version})")
        return Response(self.get_serializer(doc).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        doc = self.get_object()
        self._require_edit(doc)
        doc.status = Document.Status.ARCHIVED
        doc.save(update_fields=["status", "updated_at"])
        audit(request, "document.archive", doc, f"Archived '{doc.title}'")
        return Response(self.get_serializer(doc).data)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        doc = self.get_object()
        self._require_edit(doc)
        s = AssignmentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        ids = accessible_property_ids(request.user)
        if ids is not None:
            if d["scope"] == "all_tenants":
                raise PermissionDenied("Only portfolio administrators can assign to all tenants.")
            pid = (d.get("property").pk if d.get("property") else
                   d["building"].property_id if d.get("building") else None)
            if pid is not None and pid not in ids:
                raise PermissionDenied("You are not assigned to this property.")
            if d.get("tenant") and not scoped_tenants(request.user).filter(pk=d["tenant"].pk).exists():
                raise PermissionDenied("You cannot assign to this tenant.")
        a = s.save(document=doc, assigned_by=request.user)
        if doc.status == Document.Status.APPROVED:
            tenants = list(eligible_tenants(doc))
            notify_document_action(doc, tenants)
            if doc.workflow == Document.Workflow.SIGNATURE:
                create_signature_requests(doc, tenants, request.user, a.due_date)
        audit(request, "document.assign", doc, f"Assigned '{doc.title}' to {AssignmentSerializer(a).data['target']}")
        return Response(self.get_serializer(doc).data, status=201)

    @action(detail=True, methods=["post"], url_path="unassign")
    def unassign(self, request, pk=None):
        doc = self.get_object()
        self._require_edit(doc)
        doc.assignments.filter(pk=request.data.get("assignment")).delete()
        return Response(self.get_serializer(doc).data)

    @action(detail=True, methods=["get"])
    def acknowledgements(self, request, pk=None):
        doc = self.get_object()
        tenants = eligible_tenants(doc)
        ids = accessible_property_ids(request.user)
        if ids is not None:
            tenants = tenants.filter(tenancies__property_id__in=ids).distinct()
        acks = {a.tenant_id: a for a in DocumentAcknowledgement.objects.filter(version=doc.current_version)}
        sigs = {s.tenant_id: s for s in SignatureRequest.objects.filter(version=doc.current_version)
                .exclude(status="cancelled")}
        rows = []
        for t in tenants.order_by("first_name"):
            a, s = acks.get(t.pk), sigs.get(t.pk)
            rows.append({"tenant_id": t.pk, "tenant": t.full_name,
                         "acknowledged_at": a.acknowledged_at if a else None,
                         "signature_status": s.status if s else None, "signature_request_id": s.pk if s else None})
        return Response({"version": doc.current_version.version if doc.current_version else None, "rows": rows})

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        doc = self.get_object()
        vid = request.query_params.get("version")
        v = doc.versions.filter(pk=vid).first() if vid else doc.current_version
        if v is None:
            return Response({"detail": "No file."}, status=404)
        return file_download(v.file, v.original_name)


class SignatureRequestViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = SignatureRequestSerializer
    permission_classes = [StaffCapability]
    read_cap = "view_documents"
    write_cap = "manage_documents"
    action_caps = {"signed_file": "view_documents"}
    filterset_fields = ["status", "document", "tenant"]

    def get_queryset(self):
        qs = SignatureRequest.objects.select_related("document", "tenant", "version")
        ids = accessible_property_ids(self.request.user)
        if ids is not None:
            qs = qs.filter(tenant__tenancies__property_id__in=ids).distinct()
        return qs

    def _review(self, request, status_, notes=""):
        sr = self.get_object()
        if sr.status != SignatureRequest.Status.SUBMITTED:
            raise ValidationError({"detail": "Only submitted signatures can be reviewed."})
        sr.status = status_
        sr.reviewed_by = request.user
        sr.reviewed_at = timezone.now()
        sr.review_notes = notes[:300]
        sr.save()
        audit(request, f"signature.{status_}", sr, f"Signature for '{sr.document.title}' by {sr.tenant.full_name}: {status_}")
        return Response(self.get_serializer(sr).data)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        return self._review(request, SignatureRequest.Status.VERIFIED, request.data.get("notes", ""))

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        notes = str(request.data.get("notes", "")).strip()
        if not notes:
            raise ValidationError({"notes": "Explain what needs to be corrected."})
        return self._review(request, SignatureRequest.Status.REJECTED, notes)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        sr = self.get_object()
        sr.status = SignatureRequest.Status.CANCELLED
        sr.save(update_fields=["status"])
        return Response(self.get_serializer(sr).data)

    @action(detail=True, methods=["get"], url_path="signed-file")
    def signed_file(self, request, pk=None):
        sr = self.get_object()
        if not sr.signed_file:
            return Response({"detail": "No signed file uploaded."}, status=404)
        return file_download(sr.signed_file, f"signed-{sr.document.title[:40]}{os.path.splitext(sr.signed_file.name)[1]}")


# ------------------------------------------------------------------------ tenant portal
class PortalDocumentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = PortalDocumentSerializer
    permission_classes = [IsTenantUser]
    pagination_class = None

    def tenant(self):
        return self.request.user.tenant_profile

    def get_queryset(self):
        return visible_documents_for_tenant(self.tenant()).select_related("current_version").order_by("category", "title")

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        t = self.tenant()
        ctx["acks"] = {a.version_id: a.acknowledged_at for a in DocumentAcknowledgement.objects.filter(tenant=t)}
        ctx["signatures"] = {}
        for s in SignatureRequest.objects.filter(tenant=t).exclude(status="cancelled").order_by("created_at"):
            ctx["signatures"][s.document_id] = s
        return ctx

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        doc = self.get_object()
        v = doc.current_version
        return file_download(v.file, v.original_name)

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        doc = self.get_object()
        if doc.workflow != Document.Workflow.ACKNOWLEDGE:
            raise ValidationError({"detail": "This document does not need acknowledgement."})
        DocumentAcknowledgement.objects.get_or_create(
            version=doc.current_version, tenant=self.tenant(),
            defaults={"document": doc, "user": request.user, "ip_address": client_ip(request)},
        )
        return Response(self.get_serializer(doc).data)


class PortalSignatureUploadView(APIView):
    permission_classes = [IsTenantUser]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        sr = get_object_or_404(SignatureRequest, pk=pk, tenant=request.user.tenant_profile,
                               status__in=["pending", "rejected"])
        f = request.FILES.get("file")
        if not f:
            raise ValidationError({"file": "Choose the signed file to upload."})
        validate_document_upload(f)
        sr.signed_file = f
        sr.status = SignatureRequest.Status.SUBMITTED
        sr.submitted_at = timezone.now()
        sr.save()
        return Response({"detail": "Signed copy uploaded. Management will verify it.", "status": sr.status})
