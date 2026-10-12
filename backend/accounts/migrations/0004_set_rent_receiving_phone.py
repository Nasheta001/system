"""Set the landlord's designated M-Pesa rent-receiving number.

Only fills the field when it is still empty, so a number changed later in
Settings → Company profile is never overwritten. This is the Send Money
(person-to-person) workflow: tenant reports are verified by staff; it is not
an STK Push/Daraja shortcode.
"""
from django.db import migrations

RENT_RECEIVING_PHONE = "+254112157383"


def forwards(apps, schema_editor):
    CompanySettings = apps.get_model("accounts", "CompanySettings")
    obj, _ = CompanySettings.objects.get_or_create(pk=1)
    if not obj.rent_receiving_phone:
        obj.rent_receiving_phone = RENT_RECEIVING_PHONE
        obj.rent_phone_payments_enabled = True
        obj.save(update_fields=["rent_receiving_phone", "rent_phone_payments_enabled"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_companysettings_rent_phone_payments_enabled_and_more")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
