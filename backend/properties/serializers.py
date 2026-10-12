from rest_framework import serializers

from .models import Amenity, Building, Property, PropertyOwnership, PropertyPhoto, Unit, UnitType


def media_url(url):
    """Site-relative for local storage (/media/...), so the SPA's own domain serves it (directly or
    through its proxy); absolute URLs from object storage are returned unchanged."""
    return url


class AmenitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Amenity
        fields = ["id", "name"]


class UnitTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnitType
        fields = ["id", "name", "bedrooms", "description", "sort_order"]


class PhotoSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = PropertyPhoto
        fields = ["id", "property", "unit", "image", "url", "caption", "sort_order", "is_cover", "uploaded_at"]
        extra_kwargs = {"image": {"write_only": True}}

    def get_url(self, obj):
        url = obj.image.url
        return media_url(url)

    def validate_image(self, f):
        from config.validators import sanitize_image, validate_image_upload

        validate_image_upload(f)
        return sanitize_image(f)

    def validate(self, attrs):
        unit = attrs.get("unit")
        prop = attrs.get("property") or getattr(self.instance, "property", None)
        if unit and prop and unit.property_id != prop.pk:
            raise serializers.ValidationError({"unit": "Unit must belong to the property."})
        return attrs


class OwnershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyOwnership
        fields = "__all__"


class BuildingSerializer(serializers.ModelSerializer):
    unit_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Building
        fields = ["id", "property", "name", "floors", "description", "is_archived", "unit_count"]

    def validate(self, attrs):
        if self.instance and "property" in attrs and attrs["property"] != self.instance.property:
            raise serializers.ValidationError({"property": "A building cannot be moved to another property."})
        return attrs


class UnitSerializer(serializers.ModelSerializer):
    property_name = serializers.CharField(source="property.name", read_only=True)
    building_name = serializers.CharField(source="building.name", read_only=True, default=None)
    unit_type_name = serializers.CharField(source="unit_type.name", read_only=True)
    label = serializers.CharField(read_only=True)
    current_tenant = serializers.SerializerMethodField()

    class Meta:
        model = Unit
        fields = ["id", "property", "property_name", "building", "building_name", "unit_type", "unit_type_name",
                  "unit_number", "label", "floor", "bedrooms", "bathrooms", "size_sqm", "rent_amount",
                  "deposit_amount", "service_charge", "rent_due_day", "payment_terms", "status", "is_listed",
                  "listing_description", "available_from", "is_archived", "current_tenant", "created_at"]
        read_only_fields = ["is_archived"]

    def get_current_tenant(self, obj):
        # Populated via prefetch in the viewset; only staff endpoints use this serializer
        tenancy = getattr(obj, "current_tenancies", None)
        if tenancy:
            t = tenancy[0]
            return {"tenancy_id": t.pk, "tenant_id": t.tenant_id, "name": t.tenant.full_name}
        return None

    def validate(self, attrs):
        prop = attrs.get("property") or getattr(self.instance, "property", None)
        building = attrs.get("building", getattr(self.instance, "building", None))
        if self.instance and "property" in attrs and attrs["property"] != self.instance.property:
            raise serializers.ValidationError({"property": "A unit cannot be moved to another property."})
        if building and prop and building.property_id != prop.pk:
            raise serializers.ValidationError({"building": "The building must belong to the same property."})
        number = attrs.get("unit_number", getattr(self.instance, "unit_number", None))
        if prop and number:
            qs = Unit.objects.filter(property=prop, unit_number__iexact=number)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({"unit_number": "This unit number already exists in the property."})
        status = attrs.get("status")
        if status and self.instance and status != self.instance.status:
            if self.instance.status == Unit.Status.OCCUPIED or status in (Unit.Status.OCCUPIED, Unit.Status.RESERVED):
                raise serializers.ValidationError(
                    {"status": "Occupied/reserved status is managed by the tenancy and reservation workflows."}
                )
        elif status in (Unit.Status.OCCUPIED, Unit.Status.RESERVED) and not self.instance:
            raise serializers.ValidationError({"status": "New units start as available or unavailable."})
        return attrs


class PropertyListSerializer(serializers.ModelSerializer):
    total_units = serializers.IntegerField(read_only=True, default=0)
    occupied_units = serializers.IntegerField(read_only=True, default=0)
    available_units = serializers.IntegerField(read_only=True, default=0)
    reserved_units = serializers.IntegerField(read_only=True, default=0)
    occupancy_rate = serializers.SerializerMethodField()
    cover_photo = serializers.SerializerMethodField()

    class Meta:
        model = Property
        fields = ["id", "name", "slug", "property_type", "town", "county", "neighbourhood", "status",
                  "is_published", "is_featured", "total_units", "occupied_units", "available_units",
                  "reserved_units", "occupancy_rate", "cover_photo", "updated_at"]

    def get_occupancy_rate(self, obj):
        total = getattr(obj, "total_units", 0) or 0
        return round(100 * (getattr(obj, "occupied_units", 0) or 0) / total, 1) if total else 0

    def get_cover_photo(self, obj):
        photos = list(obj.photos.all())
        if not photos:
            return None
        url = photos[0].image.url
        return media_url(url)


class PropertyDetailSerializer(serializers.ModelSerializer):
    amenities = AmenitySerializer(many=True, read_only=True)
    amenity_ids = serializers.PrimaryKeyRelatedField(
        source="amenities", queryset=Amenity.objects.all(), many=True, write_only=True, required=False
    )
    photos = PhotoSerializer(many=True, read_only=True)
    buildings = serializers.SerializerMethodField()
    ownership_records = OwnershipSerializer(many=True, read_only=True)
    stats = serializers.SerializerMethodField()

    class Meta:
        model = Property
        fields = ["id", "name", "slug", "property_type", "description", "address", "county", "town",
                  "neighbourhood", "latitude", "longitude", "map_url", "contact_phone", "contact_email", "whatsapp",
                  "rent_terms", "amenities", "amenity_ids", "photos", "buildings", "ownership_records", "status",
                  "is_published", "is_featured", "archived_at", "created_at", "updated_at", "stats"]
        read_only_fields = ["slug", "status", "archived_at", "is_published"]

    def get_buildings(self, obj):
        return BuildingSerializer(obj.buildings.all(), many=True).data

    def get_stats(self, obj):
        units = obj.units.filter(is_archived=False)
        counts = {s: 0 for s, _ in Unit.Status.choices}
        for s in units.values_list("status", flat=True):
            counts[s] += 1
        total = sum(counts.values())
        return {"total_units": total, **counts,
                "occupancy_rate": round(100 * counts["occupied"] / total, 1) if total else 0}


# ---------------------------------------------------------------- public (no private data)
class PublicPhotoSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = PropertyPhoto
        fields = ["id", "url", "caption", "unit"]

    def get_url(self, obj):
        return media_url(obj.image.url)


class PublicUnitSerializer(serializers.ModelSerializer):
    unit_type = serializers.CharField(source="unit_type.name")
    building = serializers.CharField(source="building.name", default=None)

    class Meta:
        model = Unit
        fields = ["id", "unit_number", "building", "unit_type", "bedrooms", "bathrooms", "size_sqm", "floor",
                  "rent_amount", "deposit_amount", "service_charge", "payment_terms", "listing_description",
                  "available_from"]


class PublicPropertyListSerializer(serializers.ModelSerializer):
    cover_photo = serializers.SerializerMethodField()
    min_rent = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    max_rent = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    available_count = serializers.IntegerField(read_only=True)
    unit_types = serializers.SerializerMethodField()
    bedrooms = serializers.SerializerMethodField()

    class Meta:
        model = Property
        fields = ["id", "name", "slug", "property_type", "town", "county", "neighbourhood", "cover_photo",
                  "min_rent", "max_rent", "available_count", "unit_types", "bedrooms", "is_featured"]

    def _listed(self, obj):
        return getattr(obj, "listed_units", [])

    def get_unit_types(self, obj):
        return sorted({u.unit_type.name for u in self._listed(obj)})

    def get_bedrooms(self, obj):
        return sorted({u.bedrooms for u in self._listed(obj)})

    def get_cover_photo(self, obj):
        photos = [p for p in obj.photos.all() if p.unit_id is None] or list(obj.photos.all())
        if not photos:
            return None
        return media_url(photos[0].image.url)


class PublicPropertyDetailSerializer(serializers.ModelSerializer):
    amenities = serializers.SlugRelatedField(slug_field="name", many=True, read_only=True)
    photos = PublicPhotoSerializer(many=True, read_only=True)
    units = serializers.SerializerMethodField()

    class Meta:
        model = Property
        fields = ["id", "name", "slug", "property_type", "description", "address", "county", "town",
                  "neighbourhood", "latitude", "longitude", "map_url", "contact_phone", "contact_email", "whatsapp",
                  "rent_terms", "amenities", "photos", "units"]

    def get_units(self, obj):
        return PublicUnitSerializer(getattr(obj, "listed_units", []), many=True).data
