from django.core.management.base import BaseCommand
from django.db import transaction

from config.fields import PREFIX, cipher
from tenancies.models import Tenant

ENCRYPTED = [(Tenant, "id_number")]


class Command(BaseCommand):
    help = ("Re-encrypt encrypted fields with the first key in FIELD_ENCRYPTION_KEYS. "
            "Rotation: put the NEW key first, keep the old key second, run this, then remove the old key.")

    def handle(self, *args, **opts):
        f = cipher()
        total = 0
        with transaction.atomic():
            for model, field in ENCRYPTED:
                for pk, raw in model.objects.values_list("pk", field).iterator():
                    # values_list goes through from_db_value, so raw is plaintext here
                    if not raw:
                        continue
                    token = PREFIX + f.encrypt(raw.encode()).decode()
                    model.objects.filter(pk=pk).update(**{field: token})
                    total += 1
        self.stdout.write(self.style.SUCCESS(f"Re-encrypted {total} value(s)."))
