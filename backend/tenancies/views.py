from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Prefetch, Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import invitations
from accounts.audit import audit
from accounts.models import Role, User
from accounts.permissions import (
    IsTenantUser, StaffCapability, accessible_property_ids, has_cap, require_property_access,
    tenant_has_portal_access,
)
from accounts.services import send_password_link
from accounts.views import invite_response
from billing.services import account_summary, bulk_summaries

from . import services
from .models import Tenancy, Tenant
from .serializers import (
    CaretakerTenantSerializer, MoveInSerializer, MoveOutSerializer, NoticeSerializer, PortalProfileSerializer,
    TenancySerializer, TenantCreateSerializer, TenantListSerializer, TenantSerializer, TransferSerializer,
)


def _drf(exc):
    if hasattr(exc, "message_dict"):
        return ValidationError(exc.message_dict)
    return ValidationError({"detail": exc.messages})


def scoped_tenants(user):
    qs = Tenant.objects.all()
    ids = accessible_property_ids(user)
    if user.role == Role.CARETAKER:
        # Caretakers only see current tenants in their assigned buildings
        return qs.filter(tenancies__property_id__in=ids or [],
                         tenancies__status__in=Tenancy.CURRENT_STATUSES).distinct()
    if ids is None:
        return qs
    return qs.filter(
        Q(tenancies__property_id__in=ids) | Q(created_by=user, tenancies__isnull=True)
    ).distinct()


def scoped_tenancies(user):
    qs = Tenancy.objects.select_related("tenant", "unit", "unit__building", "property", "reminder_schedule")
    ids = accessible_property_ids(user)
    if user.role == Role.CARETAKER:
        qs = qs.filter(status__in=Tenancy.CURRENT_STATUSES)
    return qs if ids is None else qs.filter(property_id__in=ids)


class TenantViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                    mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [StaffCapability]
    read_cap = "view_tenants"
    write_cap = "manage_tenants"
    search_fields = ["first_name", "last_name", "email", "phone", "tenancies__unit__unit_number"]
    filterset_fields = ["status"]
    ordering_fields = ["first_name", "created_at"]

    def get_queryset(self):
        qs = scoped_tenants(self.request.user).prefetch_related(
            Prefetch("tenancies", queryset=Tenancy.objects.select_related("unit", "unit__building", "property")
                     .order_by("-start_date"))
        ).select_related("user")
        prop = self.request.query_params.get("property")
        if prop and prop.isdigit():
            qs = qs.filter(tenancies__property_id=int(prop), tenancies__status__in=Tenancy.CURRENT_STATUSES)
        if self.request.query_params.get("account_status") == "overdue":
            pass  # filtered after summaries in list()
        return qs.order_by("first_name", "last_name")

    def get_serializer_class(self):
        if getattr(self.request.user, "role", None) == Role.CARETAKER:
            return CaretakerTenantSerializer
        if self.action == "create":
            return TenantCreateSerializer
        if self.action == "list":
            return TenantListSerializer
        return TenantSerializer

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        want = request.query_params.get("account_status")
        page = self.paginate_queryset(qs) if not want else None
        rows = list(page if page is not None else qs)
        summaries = {}
        if has_cap(request.user, "view_payments"):
            current = {}
            for t in rows:
                for ten in t.tenancies.all():
                    if ten.status in Tenancy.CURRENT_STATUSES:
                        current[t.pk] = ten
                        break
            by_tenancy = bulk_summaries(current.values())
            summaries = {tid: by_tenancy[ten.pk] for tid, ten in current.items()}
            if want:
                rows = [t for t in rows if summaries.get(t.pk) and summaries[t.pk].status == want]
        ser = self.get_serializer(rows, many=True, context={**self.get_serializer_context(), "summaries": summaries})
        if page is not None:
            return self.get_paginated_response(ser.data)
        return Response({"count": len(rows), "next": None, "previous": None, "results": ser.data})

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        unit = data.pop("unit", None)
        move_in_fields = {k: data.pop(k) for k in
                          ["start_date", "monthly_rent", "deposit_amount", "rent_due_day", "expected_end_date"]
                          if k in data}
        portal = data.pop("create_portal_account", False)
        if unit is not None:
            require_property_access(self.request.user, unit.property_id)
        self._invite_raw = None
        try:
            with transaction.atomic():
                tenant = Tenant.objects.create(created_by=self.request.user, **data)
                if unit is not None:
                    services.move_in(tenant, unit.pk, user=self.request.user, **move_in_fields)
                if portal:
                    # Invitation only: the login is created when the tenant accepts it.
                    _, self._invite_raw = invitations.create_tenant_invitation(tenant, self.request.user)
        except invitations.InvitationError as exc:
            raise ValidationError({"create_portal_account": str(exc)}) from exc
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        serializer.instance = tenant
        audit(self.request, "tenant.create", tenant, f"Registered tenant {tenant.full_name}",
              property_id=unit.property_id if unit else None)

    def perform_update(self, serializer):
        tenant = serializer.save()
        if tenant.user_id and tenant.email and tenant.user.email != tenant.email:
            if User.objects.filter(email__iexact=tenant.email).exclude(pk=tenant.user_id).exists():
                raise ValidationError({"email": "Another account already uses this email."})
            tenant.user.email = tenant.email
            tenant.user.save(update_fields=["email"])
        audit(self.request, "tenant.update", tenant, f"Updated tenant {tenant.full_name}",
              changes={"fields": sorted(serializer.validated_data.keys())})

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        link = invitations.dev_link(self._invite_raw) if getattr(self, "_invite_raw", None) else None
        if link:
            response.data["dev_invite_link"] = link
        return response

    @action(detail=True, methods=["post"], url_path="portal-account")
    def portal_account(self, request, pk=None):
        """Invite the tenant to the portal (or re-issue the invitation), or send
        an existing, active account holder a password link."""
        tenant = self.get_object()
        if tenant.user_id:
            if not (tenant.user.is_active and tenant_has_portal_access(tenant.user)):
                return Response({"detail": "Portal access for this tenant is disabled."}, status=400)
            send_password_link(tenant.user)
            audit(request, "tenant.portal_account", tenant, f"Password link sent to {tenant.full_name}")
            return Response({"detail": "Password link sent."})
        try:
            inv, raw = invitations.create_tenant_invitation(tenant, request.user)
        except invitations.InvitationError as exc:
            return Response({"detail": str(exc)}, status=400)
        audit(request, "tenant.portal_invite", tenant, f"Portal invitation sent to {tenant.full_name} "
                                                       f"(expires {inv.expires_at:%d %b %Y %H:%M})")
        response = invite_response(inv, raw)
        response.data["detail"] = "Invitation sent."
        return response

    @action(detail=True, methods=["post"], url_path="portal-invite/revoke")
    def revoke_portal_invite(self, request, pk=None):
        tenant = self.get_object()
        count = invitations.revoke_open_invitations(tenant=tenant, by=request.user, reason="Revoked by staff")
        if not count:
            return Response({"detail": "There is no open invitation to revoke."}, status=400)
        audit(request, "tenant.portal_invite_revoke", tenant, f"Revoked portal invitation for {tenant.full_name}")
        return Response({"detail": "Invitation revoked. The link no longer works."})

    @action(detail=True, methods=["post"], url_path="portal-access")
    def portal_access(self, request, pk=None):
        tenant = self.get_object()
        if not tenant.user_id:
            return Response({"detail": "This tenant has no portal account."}, status=400)
        enable = bool(request.data.get("enabled"))
        if enable:
            if not tenant.current_tenancy():
                return Response({"detail": "Only tenants with a current tenancy can have portal access."},
                                status=400)
            tenant.user.is_active = True
            tenant.user.save(update_fields=["is_active", "updated_at"])
        else:
            invitations.deactivate_account(tenant.user, by=request.user, reason="Portal access disabled by staff")
        audit(request, "tenant.portal_access", tenant,
              f"{'Enabled' if enable else 'Disabled'} portal access for {tenant.full_name}")
        return Response({"detail": "Updated.", "portal_active": enable})


class TenancyViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                     viewsets.GenericViewSet):
    serializer_class = TenancySerializer
    permission_classes = [StaffCapability]
    read_cap = "view_tenants"
    write_cap = "manage_tenants"
    filterset_fields = ["status", "property", "tenant", "unit"]
    search_fields = ["tenant__first_name", "tenant__last_name", "unit__unit_number"]
    ordering_fields = ["start_date", "monthly_rent"]

    def get_queryset(self):
        return scoped_tenancies(self.request.user)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["with_account"] = has_cap(self.request.user, "view_payments") and self.action != "list"
        ctx["hide_financials"] = not has_cap(self.request.user, "view_payments")
        return ctx

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        rows = list(page if page is not None else qs)
        summaries = bulk_summaries(rows) if has_cap(request.user, "view_payments") else {}
        ser = self.get_serializer(rows, many=True, context={**self.get_serializer_context(), "summaries": summaries})
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    def perform_update(self, serializer):
        tenancy = serializer.save()
        audit(self.request, "tenancy.update", tenancy, f"Updated tenancy terms for {tenancy}",
              changes={k: str(v) for k, v in serializer.validated_data.items()})

    def _run(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DjangoValidationError as exc:
            raise _drf(exc) from exc

    @action(detail=False, methods=["post"], url_path="move-in")
    def move_in(self, request):
        s = MoveInSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        tenant, unit = d.pop("tenant"), d.pop("unit")
        require_property_access(request.user, unit.property_id)
        if not scoped_tenants(request.user).filter(pk=tenant.pk).exists():
            raise PermissionDenied("You cannot access this tenant.")
        tenancy = self._run(services.move_in, tenant, unit.pk, d.pop("start_date"), user=request.user, **d)
        audit(request, "tenancy.move_in", tenancy, f"Moved {tenant.full_name} into {unit}")
        return Response(TenancySerializer(tenancy, context={"with_account": True}).data, status=201)

    @action(detail=True, methods=["post"])
    def notice(self, request, pk=None):
        tenancy = self.get_object()
        s = NoticeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        tenancy = self._run(services.give_notice, tenancy, user=request.user, **s.validated_data)
        audit(request, "tenancy.notice", tenancy, f"Recorded notice for {tenancy}")
        return Response(TenancySerializer(tenancy, context={"with_account": True}).data)

    @action(detail=True, methods=["post"], url_path="move-out")
    def move_out(self, request, pk=None):
        tenancy = self.get_object()
        s = MoveOutSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        tenancy = self._run(services.complete_move_out, tenancy, user=request.user, **s.validated_data)
        audit(request, "tenancy.move_out", tenancy, f"Completed move-out for {tenancy}",
              changes={"deposit_refund": str(tenancy.deposit_refund_amount)})
        return Response(TenancySerializer(tenancy, context={"with_account": True}).data)

    @action(detail=True, methods=["post"])
    def transfer(self, request, pk=None):
        tenancy = self.get_object()
        s = TransferSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        unit = s.validated_data["unit"]
        require_property_access(request.user, unit.property_id)
        new = self._run(services.transfer, tenancy, unit.pk, s.validated_data["transfer_date"], user=request.user,
                        monthly_rent=s.validated_data.get("monthly_rent"))
        audit(request, "tenancy.transfer", new, f"Transferred {new.tenant.full_name} to {new.unit}")
        return Response(TenancySerializer(new, context={"with_account": True}).data, status=201)


# ------------------------------------------------------------------------ tenant portal
def portal_tenant(request):
    return request.user.tenant_profile


class PortalProfileView(APIView):
    permission_classes = [IsTenantUser]

    def get(self, request):
        return Response(PortalProfileSerializer(portal_tenant(request)).data)

    def patch(self, request):
        s = PortalProfileSerializer(portal_tenant(request), data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)


class PortalDashboardView(APIView):
    permission_classes = [IsTenantUser]

    def get(self, request):
        from billing.models import Payment
        from communications.models import AnnouncementRecipient
        from maintenance.models import MaintenanceRequest

        tenant = portal_tenant(request)
        tenancy = tenant.current_tenancy() or tenant.tenancies.order_by("-start_date").first()
        data = {"tenant": PortalProfileSerializer(tenant).data, "tenancy": None, "account": None,
                "recent_payments": [], "announcements": [], "maintenance": [], "manager": None}
        if tenancy:
            from accounts.models import PropertyAssignment

            data["tenancy"] = {
                "id": tenancy.pk, "status": tenancy.status, "property": tenancy.property.name,
                "unit": tenancy.unit.label, "unit_type": tenancy.unit.unit_type.name,
                "start_date": tenancy.start_date, "expected_end_date": tenancy.expected_end_date,
                "monthly_rent": tenancy.monthly_rent, "service_charge": tenancy.service_charge,
                "rent_due_day": tenancy.rent_due_day, "deposit_amount": tenancy.deposit_amount,
                "planned_move_out": tenancy.planned_move_out,
            }
            data["account"] = account_summary(tenancy).as_dict()
            data["recent_payments"] = list(
                Payment.objects.filter(tenancy__tenant=tenant, status=Payment.Status.VERIFIED)
                .order_by("-paid_on", "-id")[:5]
                .values("id", "amount", "paid_on", "method", "receipt_number", "is_simulated")
            )
            contact = (PropertyAssignment.objects.filter(property=tenancy.property, user__is_active=True,
                                                         user__role=Role.MANAGER)
                       .select_related("user").order_by("-is_primary_contact").first())
            prop = tenancy.property
            data["manager"] = {
                "name": contact.user.get_full_name() if contact else "Management office",
                "phone": (contact.user.phone if contact else "") or prop.contact_phone,
                "email": (contact.user.email if contact else "") or prop.contact_email,
                "whatsapp": prop.whatsapp,
            }
        data["announcements"] = [
            {"id": r.announcement_id, "title": r.announcement.title, "priority": r.announcement.priority,
             "published_at": r.announcement.published_at, "opened": bool(r.opened_at),
             "requires_acknowledgement": r.announcement.requires_acknowledgement,
             "acknowledged": bool(r.acknowledged_at)}
            for r in AnnouncementRecipient.objects.filter(tenant=tenant, announcement__status="published")
            .select_related("announcement").order_by("-announcement__published_at")[:5]
        ]
        data["maintenance"] = list(
            MaintenanceRequest.objects.filter(tenant=tenant).order_by("-created_at")[:5]
            .values("id", "reference", "title", "status", "created_at")
        )
        from documents.services import tenant_pending_document_actions

        data["pending_documents"] = tenant_pending_document_actions(tenant)
        return Response(data)
