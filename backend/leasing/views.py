from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.audit import audit
from accounts.models import User
from accounts.permissions import require_property_access
from accounts import invitations
from config.bot import check_human
from config.mixins import PropertyScopedMixin
from config.throttles import ScopeThrottle
from tenancies.models import Tenant
from tenancies.services import move_in
from tenancies.views import scoped_tenants

from . import services
from .models import RentalApplication, Reservation, ViewingRequest
from .serializers import (
    ApplicationLookupSerializer, ApplicationSerializer, ApplicationStatusSerializer, ConvertSerializer,
    PublicApplicationSerializer, PublicViewingRequestSerializer, ReservationSerializer, ReserveSerializer,
    ViewingRequestSerializer,
)


def _drf(exc):
    return ValidationError(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages})


# ------------------------------------------------------------------------ public
class PublicViewingRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopeThrottle]
    throttle_scope = "public_forms"

    def post(self, request):
        check_human(request)
        s = PublicViewingRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response({"detail": "Thank you. Our team will contact you to confirm the viewing."}, status=201)


class PublicApplicationView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopeThrottle]
    throttle_scope = "public_forms"

    def post(self, request):
        check_human(request)
        s = PublicApplicationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        app = s.save()
        services.notify_applicant(app)
        return Response({"reference": app.reference, "status": app.status,
                         "detail": "Application received. Keep your reference number to check its status."},
                        status=201)


class PublicApplicationStatusView(APIView):
    """Applicants check status with reference + email (both required)."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopeThrottle]
    throttle_scope = "public_forms"

    def _get(self, request):
        s = ApplicationLookupSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return RentalApplication.objects.filter(
            reference__iexact=s.validated_data["reference"].strip(), email__iexact=s.validated_data["email"]
        ).select_related("unit", "property").first()

    def post(self, request):
        app = self._get(request)
        if not app:
            return Response({"detail": "No application matches that reference and email."}, status=404)
        if request.data.get("withdraw"):
            if app.status in (RentalApplication.Status.REJECTED, RentalApplication.Status.WITHDRAWN):
                return Response({"detail": "This application is already closed."}, status=400)
            app = services.set_application_status(app, RentalApplication.Status.WITHDRAWN)
        return Response({
            "reference": app.reference, "status": app.status, "status_label": app.get_status_display(),
            "property": app.property.name, "unit": app.unit.unit_number, "submitted": app.created_at,
            "message": app.applicant_message,
        })


# ------------------------------------------------------------------------ staff
class ViewingRequestViewSet(PropertyScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                            mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = ViewingRequestSerializer
    read_cap = "manage_applications"
    write_cap = "manage_applications"
    filterset_fields = ["status", "property"]
    search_fields = ["full_name", "phone", "email"]

    def get_queryset(self):
        return self.scope(ViewingRequest.objects.select_related("property", "unit", "handled_by"))

    def perform_update(self, serializer):
        serializer.save(handled_by=self.request.user)


class ApplicationViewSet(PropertyScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                         mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = ApplicationSerializer
    read_cap = "manage_applications"
    write_cap = "manage_applications"
    filterset_fields = ["status", "property", "unit"]
    search_fields = ["reference", "full_name", "email", "phone"]
    ordering_fields = ["created_at", "status"]

    def get_queryset(self):
        return self.scope(RentalApplication.objects.select_related("property", "unit", "unit__building",
                                                                   "reviewed_by"))

    @action(detail=True, methods=["post"], url_path="set-status")
    def set_status(self, request, pk=None):
        app = self.get_object()
        s = ApplicationStatusSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            app = services.set_application_status(app, user=request.user, **s.validated_data)
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        audit(request, "application.status", app, f"Application {app.reference} → {app.status}")
        return Response(self.get_serializer(app).data)

    @action(detail=True, methods=["post"])
    def reserve(self, request, pk=None):
        app = self.get_object()
        s = ReserveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            res = services.reserve_unit(
                app.unit_id, holder_name=app.full_name, holder_phone=app.phone, holder_email=app.email,
                application=app, expires_at=s.validated_data.get("expires_at"), user=request.user,
                notes=s.validated_data.get("notes", ""),
            )
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        audit(request, "reservation.create", res, f"Reserved {res.unit} for {res.holder_name} ({app.reference})")
        return Response(ReservationSerializer(res).data, status=201)


class ReservationViewSet(PropertyScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                         viewsets.GenericViewSet):
    serializer_class = ReservationSerializer
    read_cap = "manage_applications"
    write_cap = "manage_applications"
    filterset_fields = ["status", "property", "unit"]
    search_fields = ["holder_name", "holder_phone"]

    def get_queryset(self):
        return self.scope(Reservation.objects.select_related("property", "unit", "unit__building", "application",
                                                             "tenancy"))

    def create(self, request):
        """Direct reservation (e.g. walk-in) without an online application."""
        s = ReserveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        if not d.get("unit") or not d.get("holder_name") or not d.get("holder_phone"):
            raise ValidationError({"detail": "Unit, holder name and phone are required."})
        require_property_access(request.user, d["unit"].property_id)
        try:
            res = services.reserve_unit(d["unit"].pk, holder_name=d["holder_name"], holder_phone=d["holder_phone"],
                                        holder_email=d.get("holder_email", ""), expires_at=d.get("expires_at"),
                                        user=request.user, notes=d.get("notes", ""))
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        audit(request, "reservation.create", res, f"Reserved {res.unit} for {res.holder_name}")
        return Response(ReservationSerializer(res).data, status=201)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        res = self.get_object()
        try:
            res = services.cancel_reservation(res, user=request.user, reason=request.data.get("reason", ""))
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        audit(request, "reservation.cancel", res, f"Cancelled reservation of {res.unit}")
        return Response(ReservationSerializer(res).data)

    @action(detail=True, methods=["post"])
    def convert(self, request, pk=None):
        """Turn an active reservation into a tenancy (the move-in step)."""
        res = self.get_object()
        if res.status != Reservation.Status.ACTIVE:
            raise ValidationError({"detail": "Only active reservations can be converted."})
        s = ConvertSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        try:
            with transaction.atomic():
                if d.get("tenant"):
                    tenant = scoped_tenants(request.user).filter(pk=d["tenant"]).first()
                    if tenant is None:
                        raise PermissionDenied("Tenant not found.")
                else:
                    first = d.get("first_name") or res.holder_name.split(" ")[0]
                    last = d.get("last_name", " ".join(res.holder_name.split(" ")[1:]))
                    tenant = Tenant.objects.create(
                        first_name=first, last_name=last, email=res.holder_email, phone=res.holder_phone,
                        id_number=d.get("id_number", ""), created_by=request.user,
                    )
                    if d.get("create_portal_account") and res.holder_email:
                        if User.objects.filter(email__iexact=res.holder_email).exists():
                            raise ValidationError({"detail": "A user with the holder's email already exists. "
                                                             "Select the existing tenant instead."})
                tenancy = move_in(
                    tenant, res.unit_id, d["start_date"], user=request.user, reservation=res,
                    expected_end_date=d.get("expected_end_date"), monthly_rent=d.get("monthly_rent"),
                    deposit_amount=d.get("deposit_amount"), rent_due_day=d.get("rent_due_day"),
                    move_in_inspection_notes=d.get("move_in_inspection_notes", ""),
                )
                if d.get("create_portal_account") and not d.get("tenant") and tenant.email:
                    # Invitation linked to the new tenancy; the login is created on acceptance.
                    invitations.create_tenant_invitation(tenant, request.user)
        except invitations.InvitationError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        audit(request, "reservation.convert", tenancy, f"Converted reservation into tenancy for {tenant.full_name}")
        return Response({"tenancy_id": tenancy.pk, "tenant_id": tenant.pk}, status=201)
