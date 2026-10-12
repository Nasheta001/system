from django.db import migrations


def encrypt_existing(apps, schema_editor):
    """Encrypt ID numbers stored as plaintext before field encryption existed."""
    from config.fields import PREFIX, encrypt

    Tenant = apps.get_model("tenancies", "Tenant")
    for pk, value in Tenant.objects.exclude(id_number="").values_list("pk", "id_number"):
        if value and not value.startswith(PREFIX):
            Tenant.objects.filter(pk=pk).update(id_number=encrypt(value))


class Migration(migrations.Migration):
    dependencies = [("tenancies", "0002_alter_tenant_alternative_phone_and_more")]

    operations = [migrations.RunPython(encrypt_existing, migrations.RunPython.noop)]
