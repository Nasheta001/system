import shutil
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.management.commands.setup_defaults import ensure_defaults
from accounts.models import PropertyAssignment, Role, User
from billing.models import Payment
from billing.services import assign_receipt_number
from properties.models import Building, Property, Unit, UnitType
from tenancies.models import Tenant
from tenancies.services import move_in

PASSWORD = "Str0ng-Test-Pass!"


class BaseTestCase(TestCase):
    """Two properties (P1, P2), staff with different roles and tenants."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        for d in (settings.MEDIA_ROOT, settings.PRIVATE_MEDIA_ROOT):
            shutil.rmtree(d, ignore_errors=True)

    def setUp(self):
        ensure_defaults()
        self.one_bed = UnitType.objects.get(name="One bedroom")
        self.admin = self.make_user("admin@x.test", Role.ADMIN)
        self.landlord = self.make_user("landlord@x.test", Role.LANDLORD)
        self.manager = self.make_user("manager@x.test", Role.MANAGER)
        self.manager2 = self.make_user("manager2@x.test", Role.MANAGER)
        self.caretaker = self.make_user("caretaker@x.test", Role.CARETAKER)
        self.p1 = Property.objects.create(name="Alpha Court", address="1 Test Rd", county="Nairobi", town="Nairobi",
                                          is_published=True)
        self.p2 = Property.objects.create(name="Beta Place", address="2 Test Rd", county="Mombasa", town="Mombasa",
                                          is_published=True)
        self.b1 = Building.objects.create(property=self.p1, name="Block A")
        self.b2 = Building.objects.create(property=self.p1, name="Block B")
        self.u1 = self.make_unit(self.p1, "A1", building=self.b1)
        self.u2 = self.make_unit(self.p1, "B1", building=self.b2)
        self.u3 = self.make_unit(self.p1, "A2", building=self.b1)
        self.u4 = self.make_unit(self.p2, "101")
        PropertyAssignment.objects.create(user=self.manager, property=self.p1)
        PropertyAssignment.objects.create(user=self.manager2, property=self.p2)
        PropertyAssignment.objects.create(user=self.caretaker, property=self.p1)
        self.client = APIClient()

    # -------------------------------------------------------------- helpers
    def make_user(self, email, role, password=PASSWORD, **kw):
        return User.objects.create_user(email=email, password=password, role=role, first_name=email.split("@")[0],
                                        **kw)

    def make_unit(self, prop, number, rent=Decimal("20000"), building=None, **kw):
        return Unit.objects.create(property=prop, building=building, unit_type=self.one_bed, unit_number=number,
                                   rent_amount=rent, deposit_amount=rent, rent_due_day=5, is_listed=True, **kw)

    def make_tenant(self, first, unit=None, start=None, portal=True, **tenancy_kw):
        user = self.make_user(f"{first.lower()}@tenant.test", Role.TENANT) if portal else None
        t = Tenant.objects.create(user=user, first_name=first, last_name="Test", email=f"{first.lower()}@tenant.test",
                                  phone="0712345678")
        tenancy = None
        if unit is not None:
            tenancy = move_in(t, unit.pk, start or date.today().replace(day=1), notify=False, **tenancy_kw)
        return t, tenancy

    def pay(self, tenancy, amount, paid_on=None, status="verified"):
        p = Payment.objects.create(tenancy=tenancy, property_id=tenancy.property_id, amount=Decimal(amount),
                                   method="cash", paid_on=paid_on or date.today(), status=status)
        if status == "verified":
            assign_receipt_number(p)
            p.save()
        return p

    def login(self, user):
        self.client.force_authenticate(user=None)
        self.client.logout()
        self.client.force_login(user)
        return self.client
