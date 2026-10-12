from django.core.management.base import BaseCommand

from accounts.models import CompanySettings
from billing.reminders import ensure_default_schedule
from communications.services import ensure_templates
from properties.models import Amenity, UnitType

UNIT_TYPES = [("Studio", 0, 1), ("Bedsitter", 0, 2), ("One bedroom", 1, 3), ("Two bedroom", 2, 4),
              ("Three bedroom", 3, 5), ("Shop / commercial", 0, 9)]
AMENITIES = ["Borehole water", "Backup generator", "CCTV", "24/7 security", "Parking", "Lift", "Gym",
             "Swimming pool", "Children's play area", "High-speed internet ready", "Rooftop terrace",
             "Prepaid electricity", "Garbage collection", "Balcony", "Servant quarters"]


def ensure_defaults():
    CompanySettings.load()
    for name, beds, order in UNIT_TYPES:
        UnitType.objects.get_or_create(name=name, defaults={"bedrooms": beds, "sort_order": order})
    for a in AMENITIES:
        Amenity.objects.get_or_create(name=a)
    ensure_templates()
    ensure_default_schedule()


class Command(BaseCommand):
    help = "Create default unit types, amenities, message templates and the default reminder schedule."

    def handle(self, *args, **opts):
        ensure_defaults()
        self.stdout.write(self.style.SUCCESS("Defaults are in place."))
