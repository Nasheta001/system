"""Replace the drawn placeholder photos of the DEMO properties with the sample photos in demo_photos/.

    python manage.py use_demo_photos

Only touches the five demo properties (matched by name); other properties are never changed.
seed_demo calls this automatically, so a reset keeps the photos.
"""
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

PHOTO_DIR = Path(__file__).resolve().parent / "demo_photos"

# property name -> photos (first one is the cover). Photos are reused where needed so none is left empty.
DEMO_PHOTOS = {
    "Bamburi Heights": [("sea-view-balcony", "Balcony with sea view"), ("bedroom-balcony", "Bedroom opening onto a balcony"),
                        ("living-balcony", "Living room")],
    "Nyali Breeze Apartments": [("estate-driveway", "Estate driveway"), ("kitchen-partition", "Kitchen"),
                                ("sea-view-balcony", "Balcony")],
    "Kisauni Gardens": [("single-rooms-corridor", "Corridor to the units"), ("studio-kitchen", "Studio with kitchenette"),
                        ("kitchen-open", "Kitchen")],
    "Milimani Court": [("townhouse-gates", "Private gated entrances"), ("living-balcony", "Living room"),
                       ("kitchen-open", "Kitchen")],
    "Mwembeni Residences": [("studio-kitchen", "Open-plan unit"), ("bedroom-balcony", "Bedroom"),
                            ("kitchen-partition", "Kitchen")],
}


def apply_demo_photos(stdout=None):
    from properties.models import Property, PropertyPhoto

    updated = 0
    for name, photos in DEMO_PHOTOS.items():
        prop = Property.objects.filter(name=name).first()
        if prop is None:
            continue
        for old in prop.photos.all():
            old.image.delete(save=False)
            old.delete()
        for i, (stem, caption) in enumerate(photos):
            data = (PHOTO_DIR / f"{stem}.jpg").read_bytes()
            PropertyPhoto.objects.create(property=prop, image=ContentFile(data, name=f"{stem}.jpg"), caption=caption,
                                         is_cover=(i == 0), sort_order=i)
        updated += 1
        if stdout:
            stdout.write(f"  {name}: {len(photos)} photos")
    return updated


class Command(BaseCommand):
    help = "Use the sample photos for the demo properties"

    def handle(self, *args, **options):
        n = apply_demo_photos(self.stdout)
        self.stdout.write(self.style.SUCCESS(f"Updated photos for {n} demo properties."))
