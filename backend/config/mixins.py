from rest_framework.exceptions import PermissionDenied

from accounts.audit import audit
from accounts.permissions import StaffCapability, can_access_property, scope_to_properties


class PropertyScopedMixin:
    """For staff viewsets whose objects belong to a property.

    * `property_field` – ORM path from the model to its Property FK.
    * Querysets are always restricted to the requester's accessible properties,
      so an object outside the user's scope returns 404 rather than leaking.
    * Writes are checked against the target property, including changes that
      would move an object into a property the user cannot access.
    """

    permission_classes = [StaffCapability]
    property_field = "property"
    audit_name = None

    def scope(self, qs):
        return scope_to_properties(qs, self.request.user, self.property_field)

    def get_queryset(self):
        return self.scope(super().get_queryset())

    def _property_id_from(self, data, instance=None):
        prop = data.get("property")
        if prop is None and "unit" in data and data["unit"] is not None:
            prop = data["unit"].property
        if prop is None and "building" in data and data["building"] is not None:
            prop = data["building"].property
        if prop is None and instance is not None:
            return getattr(instance, "property_id", None)
        return getattr(prop, "pk", prop)

    def check_target(self, serializer, instance=None):
        pid = self._property_id_from(serializer.validated_data, instance)
        if pid is not None and not can_access_property(self.request.user, pid):
            raise PermissionDenied("You are not assigned to this property.")

    def perform_create(self, serializer):
        self.check_target(serializer)
        obj = serializer.save()
        if self.audit_name:
            audit(self.request, f"{self.audit_name}.create", obj, f"Created {self.audit_name} {obj}")
        return obj

    def perform_update(self, serializer):
        self.check_target(serializer, serializer.instance)
        obj = serializer.save()
        if self.audit_name:
            audit(self.request, f"{self.audit_name}.update", obj, f"Updated {self.audit_name} {obj}",
                  changes={"fields": sorted(serializer.validated_data.keys())})
        return obj
