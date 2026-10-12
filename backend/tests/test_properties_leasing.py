from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from leasing.models import RentalApplication, Reservation
from leasing.services import expire_reservations, reserve_unit
from properties.models import Property, Unit
from tenancies.models import Tenancy

from .base import BaseTestCase


class PropertyTests(BaseTestCase):
    def test_admin_creates_edits_and_archives_property(self):
        self.login(self.admin)
        r = self.client.post("/api/properties/", {"name": "Gamma Flats", "address": "3 Rd", "county": "Kiambu",
                                                  "town": "Thika"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        pid = r.data["id"]
        self.assertTrue(r.data["slug"].startswith("gamma-flats"))
        r = self.client.patch(f"/api/properties/{pid}/", {"description": "Updated"}, format="json")
        self.assertEqual(r.data["description"], "Updated")
        self.client.post(f"/api/properties/{pid}/publish/")
        r = self.client.post(f"/api/properties/{pid}/archive/")
        self.assertEqual(r.data["status"], "archived")
        self.assertFalse(r.data["is_published"])

    def test_property_with_units_cannot_be_deleted(self):
        r = self.login(self.admin).delete(f"/api/properties/{self.p1.pk}/")
        self.assertEqual(r.status_code, 409)
        self.assertTrue(Property.objects.filter(pk=self.p1.pk).exists())

    def test_cannot_archive_property_with_current_tenants(self):
        self.make_tenant("Ann", self.u1)
        r = self.login(self.admin).post(f"/api/properties/{self.p1.pk}/archive/")
        self.assertEqual(r.status_code, 409)

    def test_unit_number_unique_per_property(self):
        r = self.login(self.manager).post("/api/units/", {"property": self.p1.pk, "unit_type": self.one_bed.pk,
                                                         "unit_number": "a1", "rent_amount": "5000"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_unit_status_cannot_be_forced_to_occupied(self):
        r = self.login(self.manager).patch(f"/api/units/{self.u1.pk}/", {"status": "occupied"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_public_listing_shows_only_published_listed_available_units(self):
        self.make_tenant("Occ", self.u1)  # u1 occupied
        self.u2.is_listed = False
        self.u2.save()
        hidden = Property.objects.create(name="Hidden", address="x", county="Nairobi", town="Nairobi",
                                         is_published=False)
        self.make_unit(hidden, "H1")
        r = APIClient().get("/api/public/properties/")
        names = {p["name"] for p in r.data}
        self.assertNotIn("Hidden", names)
        detail = APIClient().get(f"/api/public/properties/{self.p1.slug}/").data
        self.assertEqual([u["unit_number"] for u in detail["units"]], ["A2"])
        body = str(detail)
        self.assertNotIn("Occ", body)  # never exposes tenant identities
        self.assertEqual(APIClient().get(f"/api/public/properties/{hidden.slug}/").status_code, 404)

    def test_public_search_filters(self):
        self.make_unit(self.p2, "102", rent=50000)
        r = APIClient().get("/api/public/properties/", {"min_rent": 30000})
        self.assertEqual([p["name"] for p in r.data], ["Beta Place"])
        r = APIClient().get("/api/public/properties/", {"town": "Nairobi"})
        self.assertEqual([p["name"] for p in r.data], ["Alpha Court"])


class LeasingTests(BaseTestCase):
    def apply(self, unit, email="app@x.test"):
        return APIClient().post("/api/public/applications/", {
            "unit": unit.pk, "full_name": "App Licant", "email": email, "phone": "0711111111",
            "consent_given": True}, format="json")

    def test_application_requires_consent_and_does_not_create_tenancy(self):
        r = APIClient().post("/api/public/applications/", {"unit": self.u3.pk, "full_name": "X", "email": "x@x.test",
                                                           "phone": "0711"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.apply(self.u3)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Tenancy.objects.count(), 0)
        self.u3.refresh_from_db()
        self.assertEqual(self.u3.status, "available")

    def test_applicant_status_lookup_needs_reference_and_email(self):
        ref = self.apply(self.u3).data["reference"]
        r = APIClient().post("/api/public/applications/status/", {"reference": ref, "email": "wrong@x.test"},
                             format="json")
        self.assertEqual(r.status_code, 404)
        r = APIClient().post("/api/public/applications/status/", {"reference": ref, "email": "app@x.test"},
                             format="json")
        self.assertEqual(r.data["status"], "pending")

    def test_full_lifecycle_approve_reserve_convert(self):
        ref = self.apply(self.u3).data["reference"]
        app = RentalApplication.objects.get(reference=ref)
        self.login(self.manager)
        r = self.client.post(f"/api/applications/{app.pk}/reserve/", {}, format="json")
        self.assertEqual(r.status_code, 400)  # must be approved first
        self.client.post(f"/api/applications/{app.pk}/set-status/", {"status": "approved"}, format="json")
        r = self.client.post(f"/api/applications/{app.pk}/reserve/", {}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.u3.refresh_from_db()
        self.assertEqual(self.u3.status, "reserved")
        r = self.client.post(f"/api/reservations/{r.data['id']}/convert/",
                             {"start_date": str(date.today()), "create_portal_account": True}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.u3.refresh_from_db()
        self.assertEqual(self.u3.status, "occupied")
        self.assertEqual(Reservation.objects.get().status, "converted")
        self.assertEqual(Tenancy.objects.get().tenant.email, "app@x.test")

    def test_double_reservation_is_prevented(self):
        reserve_unit(self.u3.pk, holder_name="First", holder_phone="1")
        with self.assertRaises(ValidationError):
            reserve_unit(self.u3.pk, holder_name="Second", holder_phone="2")
        self.assertEqual(Reservation.objects.filter(unit=self.u3, status="active").count(), 1)

    def test_db_constraint_blocks_second_active_reservation(self):
        from django.db import IntegrityError, transaction

        Reservation.objects.create(unit=self.u3, property=self.p1, holder_name="A", holder_phone="1",
                                   expires_at=timezone.now() + timedelta(days=1))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reservation.objects.create(unit=self.u3, property=self.p1, holder_name="B", holder_phone="2",
                                       expires_at=timezone.now() + timedelta(days=1))

    def test_reserved_unit_cannot_be_let_to_someone_else(self):
        reserve_unit(self.u3.pk, holder_name="First", holder_phone="1")
        from tenancies.models import Tenant
        from tenancies.services import move_in

        other = Tenant.objects.create(first_name="Other", last_name="P", phone="1")
        with self.assertRaises(ValidationError):
            move_in(other, self.u3.pk, date.today(), notify=False)

    def test_expired_reservation_releases_unit(self):
        res = reserve_unit(self.u3.pk, holder_name="First", holder_phone="1",
                           expires_at=timezone.now() + timedelta(hours=1))
        self.assertEqual(expire_reservations(timezone.now() + timedelta(hours=2)), 1)
        res.refresh_from_db()
        self.u3.refresh_from_db()
        self.assertEqual(res.status, "expired")
        self.assertEqual(self.u3.status, Unit.Status.AVAILABLE)

    def test_rejecting_application_cancels_reservation(self):
        ref = self.apply(self.u3).data["reference"]
        app = RentalApplication.objects.get(reference=ref)
        self.login(self.manager)
        self.client.post(f"/api/applications/{app.pk}/set-status/", {"status": "approved"}, format="json")
        self.client.post(f"/api/applications/{app.pk}/reserve/", {}, format="json")
        self.client.post(f"/api/applications/{app.pk}/set-status/", {"status": "rejected"}, format="json")
        self.u3.refresh_from_db()
        self.assertEqual(self.u3.status, "available")

    def test_manager_cannot_see_other_property_applications(self):
        self.apply(self.u4)
        r = self.login(self.manager).get("/api/applications/")
        self.assertEqual(r.data["count"], 0)
