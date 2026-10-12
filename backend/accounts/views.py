import hashlib
import hmac

from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.core.cache import cache
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.bot import check_human
from config.throttles import ScopeThrottle

from .audit import audit
from . import invitations
from .models import AuditLog, CompanySettings, Invitation, Role, STAFF_ROLES, User
from .permissions import (
    IsStaffMember, StaffCapability, accessible_property_ids, has_cap, tenant_has_portal_access,
)
from .serializers import (
    AcceptInvitationSerializer, AuditLogSerializer, CompanySettingsSerializer, InitialSetupSerializer,
    InvitationSerializer, LoginSerializer, MeSerializer, PasswordChangeSerializer, PasswordResetConfirmSerializer,
    PublicCompanySerializer, StaffInvitationCreateSerializer, StaffOptionSerializer, StaffSerializer,
)
from .services import send_password_link

def _lock_key(email):
    return "login-fail:" + hashlib.sha256(email.encode()).hexdigest()


STAFF_SESSION_SECONDS = 60 * 60 * 12        # 12 hours
TENANT_SESSION_SECONDS = 60 * 60 * 24 * 30  # 30 days – tenants stay signed in on their phone


@method_decorator(ensure_csrf_cookie, name="get")
class CsrfView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"detail": "ok"})


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopeThrottle]
    throttle_scope = "login"

    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        email = s.validated_data["email"].lower()
        # Per-account lock-out (applies equally to unknown emails – no enumeration)
        key = _lock_key(email)
        failures = cache.get(key, 0)
        if failures >= settings.LOGIN_MAX_FAILURES:
            return Response({"detail": f"Too many failed attempts. Try again in {settings.LOGIN_LOCKOUT_MINUTES} "
                                       "minutes or reset your password."}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        user = authenticate(request, email=email, password=s.validated_data["password"])
        generic = Response({"detail": "Invalid email or password."}, status=status.HTTP_400_BAD_REQUEST)
        if user is None or not user.is_active:
            cache.set(key, failures + 1, settings.LOGIN_LOCKOUT_MINUTES * 60)
            if failures + 1 >= settings.LOGIN_MAX_FAILURES:
                audit(request, "auth.lockout", None, f"Login locked after repeated failures for {email[:80]}")
            return generic
        cache.delete(key)
        portal = s.validated_data["portal"]
        if portal == "management" and not (user.is_staff_member or user.is_superuser):
            return Response({"detail": "This account does not have management access. Use the tenant portal."},
                            status=status.HTTP_400_BAD_REQUEST)
        if portal == "tenant" and not (user.is_tenant and hasattr(user, "tenant_profile")):
            return Response({"detail": "This is not a tenant account. Use the management login."},
                            status=status.HTTP_400_BAD_REQUEST)
        if portal == "tenant" and not tenant_has_portal_access(user):
            return Response({"detail": "Your tenant portal access has ended because you have no current tenancy. "
                                       "Please contact the management office."}, status=status.HTTP_403_FORBIDDEN)
        login(request, user)
        if s.validated_data["remember"]:
            request.session.set_expiry(TENANT_SESSION_SECONDS if portal == "tenant" else STAFF_SESSION_SECONDS)
        else:
            request.session.set_expiry(0)
        audit(request, "auth.login", user, f"{user.email} signed in to {portal} portal", actor=user)
        return Response(MeSerializer(user).data)


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request):
        return Response(MeSerializer(request.user).data)


class PasswordChangeView(APIView):
    throttle_classes = [ScopeThrottle]
    throttle_scope = "login"

    def post(self, request):
        s = PasswordChangeSerializer(data=request.data, context={"request": request})
        s.is_valid(raise_exception=True)
        user = request.user
        user.set_password(s.validated_data["new_password"])
        user.must_change_password = False
        user.save()
        update_session_auth_hash(request, user)
        audit(request, "auth.password_change", user, f"{user.email} changed their password")
        return Response({"detail": "Password updated."})


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopeThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        check_human(request)
        email = str(request.data.get("email", "")).strip().lower()
        user = User.objects.filter(email__iexact=email, is_active=True).first() if email else None
        if user and user.is_tenant and not tenant_has_portal_access(user):
            user = None  # former tenants cannot re-open portal access through a password reset
        if user:
            send_password_link(user)
        # Same response whether or not the account exists (no user enumeration)
        return Response({"detail": "If the email is registered, a reset link has been sent."})


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopeThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        s = PasswordResetConfirmSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            uid = force_str(urlsafe_base64_decode(s.validated_data["uid"]))
            user = User.objects.get(pk=uid, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None
        if user is None or not default_token_generator.check_token(user, s.validated_data["token"]):
            return Response({"detail": "This link is invalid or has expired."}, status=400)
        try:
            validate_password(s.validated_data["new_password"], user)
        except DjangoValidationError as exc:
            return Response({"new_password": exc.messages}, status=400)
        user.set_password(s.validated_data["new_password"])
        user.must_change_password = False
        user.save()
        audit(request, "auth.password_reset", user, f"{user.email} reset their password", actor=user)
        return Response({"detail": "Password updated. You can now sign in.", "role": user.role})


class StaffViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                   viewsets.GenericViewSet):
    """Staff accounts – company administrators only. New staff join only by
    accepting an invitation (StaffInvitationViewSet); there is no endpoint
    that creates a staff account directly."""

    serializer_class = StaffSerializer
    permission_classes = [StaffCapability]
    read_cap = "manage_staff"
    write_cap = "manage_staff"
    search_fields = ["email", "first_name", "last_name", "phone"]
    filterset_fields = ["role", "is_active"]
    ordering_fields = ["first_name", "role", "last_login"]

    def get_queryset(self):
        return User.objects.filter(role__in=STAFF_ROLES).prefetch_related("assignments__property")

    def perform_update(self, serializer):
        user = serializer.save()
        if user.pk == self.request.user.pk and user.role != Role.ADMIN and not user.is_superuser:
            # Prevent administrators from accidentally demoting themselves
            user.role = Role.ADMIN
            user.save(update_fields=["role"])
        audit(self.request, "staff.update", user, f"Updated staff account {user.email}",
              changes={"role": user.role})

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        user = self.get_object()
        if user.pk == request.user.pk:
            return Response({"detail": "You cannot deactivate your own account."}, status=400)
        invitations.deactivate_account(user, by=request.user, reason="Staff account deactivated")
        audit(request, "staff.deactivate", user, f"Deactivated {user.email} and ended their sessions")
        return Response(self.get_serializer(user).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        user = self.get_object()
        user.is_active = True
        user.save(update_fields=["is_active"])
        audit(request, "staff.activate", user, f"Activated {user.email}")
        return Response(self.get_serializer(user).data)

    @action(detail=True, methods=["post"], url_path="send-reset")
    def send_reset(self, request, pk=None):
        user = self.get_object()
        if not user.is_active:
            return Response({"detail": "Activate the account before sending a password link."}, status=400)
        send_password_link(user)
        audit(request, "staff.password_link", user, f"Sent password link to {user.email}")
        return Response({"detail": "Password link sent (see the notification log if email is not configured)."})


class StaffOptionsView(APIView):
    """Light list of staff for assignment pickers, limited to colleagues who
    share at least one property with the requester."""

    permission_classes = [IsStaffMember]

    def get(self, request):
        qs = User.objects.filter(is_active=True, role__in=STAFF_ROLES)
        ids = accessible_property_ids(request.user)
        if ids is not None:
            qs = qs.filter(Q(assignments__property_id__in=ids) | Q(role__in=[Role.ADMIN, Role.LANDLORD])).distinct()
        prop = request.query_params.get("property")
        if prop and prop.isdigit():
            qs = qs.filter(Q(assignments__property_id=int(prop)) | Q(role__in=[Role.ADMIN, Role.LANDLORD])).distinct()
        return Response(StaffOptionSerializer(qs.order_by("first_name"), many=True).data)


class CompanySettingsView(APIView):
    permission_classes = [IsStaffMember]

    def get(self, request):
        return Response(CompanySettingsSerializer(CompanySettings.load()).data)

    def patch(self, request):
        if not has_cap(request.user, "manage_settings"):
            return Response({"detail": "Your role does not allow this action."}, status=403)
        obj = CompanySettings.load()
        s = CompanySettingsSerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        audit(request, "settings.update", obj, "Updated company settings", changes={"fields": list(request.data)})
        return Response(s.data)


class PublicCompanyView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response(PublicCompanySerializer(CompanySettings.load()).data)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [StaffCapability]
    read_cap = "view_audit"
    search_fields = ["summary", "action", "actor__email"]
    filterset_fields = ["action", "object_type", "property"]

    def get_queryset(self):
        return AuditLog.objects.select_related("actor", "property")


# ------------------------------------------------------------------ invitations
def invite_response(inv, raw, status_code=201):
    data = InvitationSerializer(inv).data
    link = invitations.dev_link(raw)
    if link:
        data["dev_invite_link"] = link
        data["dev_note"] = ("DEVELOPMENT ONLY (DEBUG=true): share this link manually while email is not "
                            "configured. It is never returned when DEBUG is off.")
    return Response(data, status=status_code)


class StaffInvitationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Invite staff by email. Administrators only (capability manage_staff)."""

    serializer_class = InvitationSerializer
    permission_classes = [StaffCapability]
    read_cap = "manage_staff"
    write_cap = "manage_staff"
    throttle_scope = "invitation"
    pagination_class = None

    def get_throttles(self):
        return [ScopeThrottle()] if self.request.method == "POST" else super().get_throttles()

    def get_queryset(self):
        qs = Invitation.objects.filter(kind=Invitation.Kind.STAFF).select_related("created_by")
        if self.request.query_params.get("open") == "true":
            qs = qs.filter(accepted_at__isnull=True, revoked_at__isnull=True)
        return qs

    def list(self, request, *args, **kwargs):
        return Response(InvitationSerializer(self.get_queryset()[:200], many=True).data)

    def create(self, request):
        s = StaffInvitationCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            inv, raw = invitations.create_staff_invitation(
                email=d["email"], role=d["role"], by=request.user, first_name=d.get("first_name", ""),
                last_name=d.get("last_name", ""), phone=d.get("phone", ""), job_title=d.get("job_title", ""),
                property_ids=[p.pk for p in d.get("property_ids", [])],
            )
        except invitations.InvitationError as exc:
            return Response({"detail": str(exc)}, status=400)
        audit(request, "invitation.create", inv, f"Invited {inv.email} as {inv.get_role_display()}")
        return invite_response(inv, raw)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        inv = self.get_object()
        try:
            invitations.revoke_invitation(inv, request.user)
        except invitations.InvitationError as exc:
            return Response({"detail": str(exc)}, status=400)
        audit(request, "invitation.revoke", inv, f"Revoked invitation for {inv.email}")
        return Response(InvitationSerializer(inv).data)

    @action(detail=True, methods=["post"])
    def resend(self, request, pk=None):
        try:
            inv, raw = invitations.resend_invitation(self.get_object(), request.user)
        except invitations.InvitationError as exc:
            return Response({"detail": str(exc)}, status=400)
        audit(request, "invitation.resend", inv, f"Re-sent invitation to {inv.email} (previous link disabled)")
        return invite_response(inv, raw, 200)


class InvitationCheckView(APIView):
    """Public: tells the accept page whether a token is usable. The token is
    sent in the body (not the URL) so it never appears in access logs."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopeThrottle]
    throttle_scope = "invitation"

    def post(self, request):
        inv = invitations.find_open_invitation(str(request.data.get("token", "")))
        if inv is None:
            return Response({"detail": "This invitation link is invalid, has expired or has already been used."},
                            status=400)
        return Response({"kind": inv.kind, "email": inv.email, "first_name": inv.first_name,
                         "role": inv.role, "role_label": inv.get_role_display(), "expires_at": inv.expires_at,
                         "company": CompanySettings.load().name})


class InvitationAcceptView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopeThrottle]
    throttle_scope = "invitation"

    def post(self, request):
        s = AcceptInvitationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            user, inv = invitations.accept_invitation(s.validated_data["token"], s.validated_data["password"])
        except invitations.InvitationError as exc:
            return Response({"detail": str(exc)}, status=400)
        except DjangoValidationError as exc:
            return Response({"password": exc.messages}, status=400)
        audit(request, "invitation.accept", user,
              f"{user.email} accepted a {inv.get_kind_display().lower()} invitation", actor=user)
        return Response({"detail": "Your account is ready. You can now sign in.", "role": user.role,
                         "portal": "tenant" if user.is_tenant else "management"}, status=201)


class InitialSetupView(APIView):
    """Create the first company administrator. Works only while no active
    administrator exists and, with DEBUG off, only with SETUP_TOKEN."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "setup"

    def get_throttles(self):
        return [ScopeThrottle()] if self.request.method == "POST" else super().get_throttles()

    @staticmethod
    def _enabled():
        return settings.DEBUG or bool(settings.SETUP_TOKEN)

    def get(self, request):
        required = not invitations.admin_exists()
        return Response({"setup_required": required, "available": required and self._enabled(),
                         "token_required": bool(settings.SETUP_TOKEN)})

    def post(self, request):
        if not self._enabled():
            return Response({"detail": "Website setup is disabled. Create the first administrator on the server "
                                       "with 'manage.py createsuperuser'."}, status=403)
        s = InitialSetupSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        if settings.SETUP_TOKEN and not hmac.compare_digest(d.get("setup_token", "").encode(),
                                                            settings.SETUP_TOKEN.encode()):
            return Response({"detail": "The setup token is not correct."}, status=403)
        with transaction.atomic():
            CompanySettings.load()
            CompanySettings.objects.select_for_update().get(pk=1)  # serialise concurrent attempts
            if invitations.admin_exists():
                return Response({"detail": "Setup has already been completed. Sign in instead."}, status=403)
            if User.objects.filter(email__iexact=d["email"]).exists():
                return Response({"email": ["A user with this email already exists."]}, status=400)
            probe = User(email=d["email"], first_name=d["first_name"], last_name=d.get("last_name", ""))
            try:
                validate_password(d["password"], probe)
            except DjangoValidationError as exc:
                return Response({"password": exc.messages}, status=400)
            user = User.objects.create_superuser(email=d["email"], password=d["password"],
                                                 first_name=d["first_name"], last_name=d.get("last_name", ""))
        audit(request, "auth.initial_setup", user, f"Initial administrator {user.email} created", actor=user)
        return Response({"detail": "Administrator account created. Sign in to continue."}, status=201)
