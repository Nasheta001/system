"""Role capabilities and property-level scoping.

Every sensitive endpoint uses these helpers server-side. Hiding buttons in the
Angular UI is purely cosmetic; these checks are the actual security boundary.
"""
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import Role

ALL_CAPS = {
    "view_properties", "create_properties", "manage_properties",
    "view_tenants", "manage_tenants",
    "view_payments", "manage_payments", "verify_payments",
    "manage_applications",
    "view_announcements", "manage_announcements",
    "view_documents", "manage_documents",
    "view_maintenance", "manage_maintenance",
    "view_reports",
    "manage_staff", "manage_settings", "view_audit",
}

ROLE_CAPABILITIES = {
    Role.ADMIN: set(ALL_CAPS),
    Role.LANDLORD: ALL_CAPS - {"manage_staff"},
    Role.MANAGER: {
        "view_properties", "manage_properties",
        "view_tenants", "manage_tenants",
        "view_payments", "manage_payments",
        "manage_applications",
        "view_announcements", "manage_announcements",
        "view_documents", "manage_documents",
        "view_maintenance", "manage_maintenance",
        "view_reports",
    },
    Role.CARETAKER: {
        "view_properties", "view_tenants",
        "view_announcements", "view_documents",
        "view_maintenance", "manage_maintenance",
    },
    Role.TENANT: set(),
}


def capabilities(user):
    if not user or not user.is_authenticated or not user.is_active:
        return set()
    if user.is_superuser:
        return set(ALL_CAPS)
    return set(ROLE_CAPABILITIES.get(user.role, set()))


def has_cap(user, cap):
    return cap in capabilities(user)


def accessible_property_ids(user):
    """Return None when the user can access the whole portfolio, otherwise the
    set of property ids they are assigned to."""
    if user.has_portfolio_access:
        return None
    if user.role in (Role.MANAGER, Role.CARETAKER):
        return set(user.assignments.values_list("property_id", flat=True))
    return set()


def scope_to_properties(queryset, user, field="property"):
    ids = accessible_property_ids(user)
    if ids is None:
        return queryset
    return queryset.filter(**{f"{field}__in": ids})


def can_access_property(user, property_id):
    ids = accessible_property_ids(user)
    return ids is None or (property_id is not None and int(property_id) in ids)


def require_property_access(user, property_id):
    if not can_access_property(user, property_id):
        raise PermissionDenied("You are not assigned to this property.")


def require_cap(user, cap):
    if not has_cap(user, cap):
        raise PermissionDenied("Your role does not allow this action.")


class IsStaffMember(BasePermission):
    message = "Management access only."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_active and (u.is_staff_member or u.is_superuser))


def tenant_has_portal_access(user):
    """A tenant login only works while the linked tenant record has a current
    (active or notice) tenancy. Ending the last tenancy closes the portal even
    if a session is still open; history stays in the database for staff."""
    from tenancies.models import Tenancy

    tenant = getattr(user, "tenant_profile", None)
    return bool(tenant and tenant.tenancies.filter(status__in=Tenancy.CURRENT_STATUSES).exists())


class IsTenantUser(BasePermission):
    message = "Tenant portal access only."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_active and u.is_tenant and tenant_has_portal_access(u))


class StaffCapability(BasePermission):
    """Requires a staff member plus a capability.

    Views declare `read_cap` (for safe methods) and `write_cap` (for unsafe
    methods). Individual actions may override via `action_caps`.
    """

    message = "Your role does not allow this action."

    def has_permission(self, request, view):
        if not IsStaffMember().has_permission(request, view):
            return False
        action_caps = getattr(view, "action_caps", {}) or {}
        action = getattr(view, "action", None)
        if action in action_caps:
            cap = action_caps[action]
        elif request.method in SAFE_METHODS:
            cap = getattr(view, "read_cap", None)
        else:
            cap = getattr(view, "write_cap", None)
        return cap is None or has_cap(request.user, cap)
