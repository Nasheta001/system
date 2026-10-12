from django.db.models import Count, Max, Min, Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.audit import audit
from accounts.permissions import IsStaffMember, StaffCapability, has_cap, require_property_access
from config.mixins import PropertyScopedMixin
from tenancies.models import Tenancy

from .models import Amenity, Building, Property, PropertyOwnership, PropertyPhoto, Unit, UnitType
from .serializers import (
    AmenitySerializer, BuildingSerializer, OwnershipSerializer, PhotoSerializer, PropertyDetailSerializer,
    PropertyListSerializer, PublicPropertyDetailSerializer, PublicPropertyListSerializer, UnitSerializer,
    UnitTypeSerializer,
)

ACTIVE_UNITS = Q(units__is_archived=False)


def annotate_counts(qs):
    return qs.annotate(
        total_units=Count("units", filter=ACTIVE_UNITS, distinct=True),
        occupied_units=Count("units", filter=ACTIVE_UNITS & Q(units__status="occupied"), distinct=True),
        available_units=Count("units", filter=ACTIVE_UNITS & Q(units__status="available"), distinct=True),
        reserved_units=Count("units", filter=ACTIVE_UNITS & Q(units__status="reserved"), distinct=True),
    )


class PropertyViewSet(PropertyScopedMixin, viewsets.ModelViewSet):
    property_field = "id"
    read_cap = "view_properties"
    write_cap = "manage_properties"
    action_caps = {"create": "create_properties", "destroy": "create_properties"}
    search_fields = ["name", "town", "county", "address", "neighbourhood"]
    filterset_fields = ["status", "is_published", "county", "town", "property_type"]
    ordering_fields = ["name", "town", "updated_at"]
    audit_name = "property"

    def get_queryset(self):
        qs = self.scope(Property.objects.all()).prefetch_related("photos")
        if self.action == "list":
            if self.request.query_params.get("include_archived") != "true" and "status" not in self.request.query_params:
                qs = qs.filter(status=Property.Status.ACTIVE)
            return annotate_counts(qs).order_by("name")
        return qs.prefetch_related("amenities", "buildings", "ownership_records")

    def get_serializer_class(self):
        return PropertyListSerializer if self.action == "list" else PropertyDetailSerializer

    def check_target(self, serializer, instance=None):
        if instance is not None:
            require_property_access(self.request.user, instance.pk)

    def destroy(self, request, *args, **kwargs):
        prop = self.get_object()
        if prop.units.exists() or prop.tenancies.exists() or prop.payments.exists():
            return Response(
                {"detail": "This property has units or financial/tenancy history. Archive it instead of deleting."},
                status=status.HTTP_409_CONFLICT,
            )
        audit(request, "property.delete", prop, f"Deleted empty property {prop.name}")
        prop.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _toggle(self, request, field_updates, action_name, msg):
        prop = self.get_object()
        for k, v in field_updates.items():
            setattr(prop, k, v)
        prop.save()
        audit(request, f"property.{action_name}", prop, f"{msg} {prop.name}")
        return Response(PropertyDetailSerializer(prop, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        prop = self.get_object()
        if prop.status != Property.Status.ACTIVE:
            return Response({"detail": "Restore the property before publishing it."}, status=400)
        return self._toggle(request, {"is_published": True}, "publish", "Published")

    @action(detail=True, methods=["post"])
    def unpublish(self, request, pk=None):
        return self._toggle(request, {"is_published": False}, "unpublish", "Unpublished")

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        prop = self.get_object()
        if prop.tenancies.filter(status__in=Tenancy.CURRENT_STATUSES).exists():
            return Response({"detail": "Move out all current tenants before archiving this property."}, status=409)
        prop.archive()
        prop.units.update(is_listed=False)
        audit(request, "property.archive", prop, f"Archived {prop.name}")
        return Response(PropertyDetailSerializer(prop, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        return self._toggle(request, {"status": Property.Status.ACTIVE, "archived_at": None}, "restore", "Restored")


class BuildingViewSet(PropertyScopedMixin, viewsets.ModelViewSet):
    serializer_class = BuildingSerializer
    read_cap = "view_properties"
    write_cap = "manage_properties"
    filterset_fields = ["property", "is_archived"]
    audit_name = "building"

    def get_queryset(self):
        return self.scope(Building.objects.annotate(
            unit_count=Count("units", filter=Q(units__is_archived=False))
        ).select_related("property"))

    def destroy(self, request, *args, **kwargs):
        b = self.get_object()
        if b.units.exists():
            return Response({"detail": "This building has units. Archive it instead."}, status=409)
        audit(request, "building.delete", b, f"Deleted building {b}")
        b.delete()
        return Response(status=204)


class UnitViewSet(PropertyScopedMixin, viewsets.ModelViewSet):
    serializer_class = UnitSerializer
    read_cap = "view_properties"
    write_cap = "manage_properties"
    filterset_fields = ["property", "building", "status", "unit_type", "is_listed", "is_archived"]
    search_fields = ["unit_number", "property__name", "building__name"]
    ordering_fields = ["unit_number", "rent_amount", "status"]
    audit_name = "unit"

    def get_queryset(self):
        qs = Unit.objects.select_related("property", "building", "unit_type").prefetch_related(
            Prefetch("tenancies", queryset=Tenancy.objects.filter(status__in=Tenancy.CURRENT_STATUSES)
                     .select_related("tenant"), to_attr="current_tenancies")
        )
        if self.action == "list" and self.request.query_params.get("is_archived") is None:
            qs = qs.filter(is_archived=False)
        return self.scope(qs)

    def destroy(self, request, *args, **kwargs):
        unit = self.get_object()
        if unit.tenancies.exists() or unit.applications.exists() or unit.reservations.exists():
            return Response({"detail": "This unit has tenancy or application history. Archive it instead."},
                            status=409)
        audit(request, "unit.delete", unit, f"Deleted unit {unit}")
        unit.delete()
        return Response(status=204)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        unit = self.get_object()
        if unit.status in (Unit.Status.OCCUPIED, Unit.Status.RESERVED):
            return Response({"detail": "Occupied or reserved units cannot be archived."}, status=409)
        unit.is_archived = True
        unit.is_listed = False
        unit.status = Unit.Status.UNAVAILABLE
        unit.save()
        audit(request, "unit.archive", unit, f"Archived unit {unit}")
        return Response(self.get_serializer(unit).data)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        unit = self.get_object()
        unit.is_archived = False
        unit.save(update_fields=["is_archived", "updated_at"])
        audit(request, "unit.restore", unit, f"Restored unit {unit}")
        return Response(self.get_serializer(unit).data)


class UnitTypeViewSet(viewsets.ModelViewSet):
    queryset = UnitType.objects.all()
    serializer_class = UnitTypeSerializer
    permission_classes = [StaffCapability]
    read_cap = "view_properties"
    write_cap = "create_properties"
    pagination_class = None

    def destroy(self, request, *args, **kwargs):
        if self.get_object().units.exists():
            return Response({"detail": "This unit type is in use."}, status=409)
        return super().destroy(request, *args, **kwargs)


class AmenityViewSet(viewsets.ModelViewSet):
    queryset = Amenity.objects.all()
    serializer_class = AmenitySerializer
    permission_classes = [StaffCapability]
    read_cap = "view_properties"
    write_cap = "manage_properties"
    pagination_class = None


class PhotoViewSet(PropertyScopedMixin, viewsets.ModelViewSet):
    serializer_class = PhotoSerializer
    read_cap = "view_properties"
    write_cap = "manage_properties"
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filterset_fields = ["property", "unit"]
    pagination_class = None

    def get_queryset(self):
        return self.scope(PropertyPhoto.objects.all())

    def perform_create(self, serializer):
        self.check_target(serializer)
        photo = serializer.save()
        if photo.is_cover:
            PropertyPhoto.objects.filter(property=photo.property).exclude(pk=photo.pk).update(is_cover=False)

    def perform_update(self, serializer):
        photo = super().perform_update(serializer)
        if photo.is_cover:
            PropertyPhoto.objects.filter(property=photo.property).exclude(pk=photo.pk).update(is_cover=False)

    def perform_destroy(self, instance):
        instance.image.delete(save=False)
        instance.delete()


class OwnershipViewSet(PropertyScopedMixin, viewsets.ModelViewSet):
    serializer_class = OwnershipSerializer
    read_cap = "view_reports"
    write_cap = "create_properties"
    filterset_fields = ["property"]
    audit_name = "ownership"

    def get_queryset(self):
        return self.scope(PropertyOwnership.objects.all())


# ------------------------------------------------------------------------ public
def public_listed_units():
    return Unit.objects.filter(
        is_listed=True, is_archived=False, status=Unit.Status.AVAILABLE, property__status=Property.Status.ACTIVE,
        property__is_published=True,
    ).select_related("unit_type", "building")


class PublicPropertyListView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        p = request.query_params
        units = public_listed_units()
        try:
            if p.get("min_rent"):
                units = units.filter(rent_amount__gte=p["min_rent"])
            if p.get("max_rent"):
                units = units.filter(rent_amount__lte=p["max_rent"])
            if p.get("bedrooms") not in (None, ""):
                b = int(p["bedrooms"])
                units = units.filter(bedrooms__gte=b) if b >= 3 else units.filter(bedrooms=b)
        except (ValueError, TypeError):
            return Response({"detail": "Invalid filter value."}, status=400)
        if p.get("unit_type"):
            units = units.filter(unit_type_id=p["unit_type"]) if p["unit_type"].isdigit() else units.none()
        props = Property.objects.filter(status=Property.Status.ACTIVE, is_published=True)
        for field in ("town", "county"):
            if p.get(field):
                props = props.filter(**{f"{field}__iexact": p[field]})
        if p.get("property_type"):
            props = props.filter(property_type=p["property_type"])
        if p.get("q"):
            q = p["q"][:100]
            props = props.filter(Q(name__icontains=q) | Q(town__icontains=q) | Q(neighbourhood__icontains=q)
                                 | Q(county__icontains=q))
        has_unit_filter = any(p.get(k) for k in ("min_rent", "max_rent", "bedrooms", "unit_type"))
        props = props.filter(units__in=units) if has_unit_filter else props
        props = props.annotate(
            min_rent=Min("units__rent_amount", filter=Q(units__in=public_listed_units())),
            max_rent=Max("units__rent_amount", filter=Q(units__in=public_listed_units())),
            available_count=Count("units", filter=Q(units__in=units), distinct=True),
        ).prefetch_related(
            "photos", Prefetch("units", queryset=units, to_attr="listed_units")
        ).distinct().order_by("-is_featured", "name")
        if p.get("available_only") == "true":
            props = props.filter(available_count__gt=0)
        data = PublicPropertyListSerializer(props, many=True, context={"request": request}).data
        return Response(data)


class PublicPropertyDetailView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, slug):
        qs = Property.objects.filter(status=Property.Status.ACTIVE, is_published=True).prefetch_related(
            "amenities", "photos", Prefetch("units", queryset=public_listed_units(), to_attr="listed_units")
        )
        prop = get_object_or_404(qs, slug=slug)
        return Response(PublicPropertyDetailSerializer(prop, context={"request": request}).data)


class PublicFiltersView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        published = Property.objects.filter(status=Property.Status.ACTIVE, is_published=True)
        return Response({
            "towns": sorted(set(published.values_list("town", flat=True))),
            "counties": sorted(set(published.values_list("county", flat=True))),
            "unit_types": UnitTypeSerializer(UnitType.objects.all(), many=True).data,
            "property_types": [{"value": v, "label": l} for v, l in Property.PropertyType.choices],
        })
