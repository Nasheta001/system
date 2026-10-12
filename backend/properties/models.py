import builtins
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from config.validators import validate_image_upload


class Amenity(models.Model):
    name = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "amenities"

    def __str__(self):
        return self.name


class Property(models.Model):
    class PropertyType(models.TextChoices):
        APARTMENTS = "apartments", "Apartment block"
        BEDSITTERS = "bedsitters", "Bedsitter / studio block"
        MIXED_USE = "mixed_use", "Mixed-use (residential & commercial)"
        MAISONETTES = "maisonettes", "Maisonettes / townhouses"
        COMMERCIAL = "commercial", "Commercial"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True)
    property_type = models.CharField(max_length=20, choices=PropertyType.choices, default=PropertyType.APARTMENTS)
    description = models.TextField(blank=True)
    address = models.CharField(max_length=255)
    county = models.CharField(max_length=60, db_index=True)
    town = models.CharField(max_length=80, db_index=True)
    neighbourhood = models.CharField(max_length=100, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    map_url = models.URLField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    contact_email = models.EmailField(blank=True)
    whatsapp = models.CharField(max_length=30, blank=True)
    rent_terms = models.TextField(blank=True, help_text="Public summary of deposit and payment terms")
    amenities = models.ManyToManyField(Amenity, blank=True, related_name="properties")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    is_published = models.BooleanField(default=False, help_text="Visible on the public website")
    is_featured = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "properties"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f"{self.name}-{self.town}")[:150] or "property"
            slug, n = base, 2
            while Property.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def archive(self):
        self.status = self.Status.ARCHIVED
        self.is_published = False
        self.archived_at = timezone.now()
        self.save(update_fields=["status", "is_published", "archived_at", "updated_at"])


def property_photo_path(instance, filename):
    import os
    import uuid

    ext = os.path.splitext(filename)[1].lower()
    return f"public/properties/{instance.property_id}/{uuid.uuid4().hex}{ext}"


class PropertyPhoto(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="photos")
    unit = models.ForeignKey("Unit", null=True, blank=True, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to=property_photo_path, validators=[validate_image_upload])
    caption = models.CharField(max_length=150, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_cover = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_cover", "sort_order", "id"]


class PropertyOwnership(models.Model):
    """Historical record of who owns or contracts the management of a property."""

    class Arrangement(models.TextChoices):
        OWNED = "owned", "Owned by company"
        MANAGED = "managed", "Managed on behalf of owner"
        LEASED = "leased", "Head-leased"

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="ownership_records")
    owner_name = models.CharField(max_length=150)
    owner_phone = models.CharField(max_length=30, blank=True)
    owner_email = models.EmailField(blank=True)
    arrangement = models.CharField(max_length=10, choices=Arrangement.choices, default=Arrangement.OWNED)
    management_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-start_date"]


class Building(models.Model):
    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name="buildings")
    name = models.CharField(max_length=80, help_text="e.g. Block A")
    floors = models.PositiveSmallIntegerField(default=1)
    description = models.TextField(blank=True)
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["property", "name"]
        constraints = [models.UniqueConstraint(fields=["property", "name"], name="uniq_building_name")]

    def __str__(self):
        return f"{self.property.name} – {self.name}"


class UnitType(models.Model):
    name = models.CharField(max_length=60, unique=True)
    bedrooms = models.PositiveSmallIntegerField(default=0)
    description = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Unit(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        RESERVED = "reserved", "Reserved"
        OCCUPIED = "occupied", "Occupied"
        MAINTENANCE = "maintenance", "Under maintenance"
        UNAVAILABLE = "unavailable", "Unavailable"

    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name="units")
    building = models.ForeignKey(Building, null=True, blank=True, on_delete=models.PROTECT, related_name="units")
    unit_type = models.ForeignKey(UnitType, on_delete=models.PROTECT, related_name="units")
    unit_number = models.CharField(max_length=20)
    floor = models.SmallIntegerField(default=0)
    bedrooms = models.PositiveSmallIntegerField(default=0)
    bathrooms = models.PositiveSmallIntegerField(default=1)
    size_sqm = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    rent_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    deposit_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0"), validators=[MinValueValidator(Decimal("0"))]
    )
    service_charge = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0"), validators=[MinValueValidator(Decimal("0"))]
    )
    rent_due_day = models.PositiveSmallIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(28)]
    )
    payment_terms = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.AVAILABLE, db_index=True)
    is_listed = models.BooleanField(default=False, help_text="Approved for the public website when available")
    listing_description = models.TextField(blank=True)
    available_from = models.DateField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property", "building__name", "unit_number"]
        constraints = [models.UniqueConstraint(fields=["property", "unit_number"], name="uniq_unit_number")]
        indexes = [models.Index(fields=["property", "status"])]

    def __str__(self):
        return f"{self.property.name} – {self.unit_number}"

    def clean(self):
        if self.building_id and self.building.property_id != self.property_id:
            raise ValidationError({"building": "The building must belong to the same property."})

    @builtins.property
    def label(self):
        if self.building_id:
            return f"{self.building.name} / {self.unit_number}"
        return self.unit_number
