from datetime import date
from decimal import Decimal

from django.core.files.base import ContentFile

from communications.models import Announcement, AnnouncementRecipient
from communications.services import publish_announcement
from documents.models import Document, DocumentAssignment, DocumentVersion
from maintenance.models import MaintenanceRequest, MaintenanceUpdate
from tenancies.services import complete_move_out

from .base import BaseTestCase

PDF = b"%PDF-1.4\n%demo\n"


class AnnouncementTargetingTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ta, _ = self.make_tenant("Aa", self.u1)      # P1, Block A
        self.tb, _ = self.make_tenant("Bb", self.u2)      # P1, Block B
        self.tc, _ = self.make_tenant("Cc", self.u4)      # P2
        self.former, ft = self.make_tenant("Ff", self.u3)  # P1, will move out
        complete_move_out(ft, actual_move_out=date.today(), notify=False)

    def recipients(self, ann):
        publish_announcement(ann)
        return set(AnnouncementRecipient.objects.filter(announcement=ann).values_list("tenant__first_name", flat=True))

    def test_property_targeting_excludes_other_properties_and_former_tenants(self):
        a = Announcement.objects.create(title="P1", body="b", audience="properties")
        a.properties.set([self.p1])
        self.assertEqual(self.recipients(a), {"Aa", "Bb"})

    def test_multiple_properties(self):
        a = Announcement.objects.create(title="P1+P2", body="b", audience="properties")
        a.properties.set([self.p1, self.p2])
        self.assertEqual(self.recipients(a), {"Aa", "Bb", "Cc"})

    def test_building_targeting(self):
        a = Announcement.objects.create(title="Block B", body="b", audience="buildings")
        a.buildings.set([self.b2])
        self.assertEqual(self.recipients(a), {"Bb"})

    def test_specific_tenants(self):
        a = Announcement.objects.create(title="One", body="b", audience="tenants")
        a.tenants.set([self.tc])
        self.assertEqual(self.recipients(a), {"Cc"})

    def test_all_tenants(self):
        a = Announcement.objects.create(title="All", body="b", audience="all_tenants")
        self.assertEqual(self.recipients(a), {"Aa", "Bb", "Cc"})

    def test_publish_is_idempotent(self):
        a = Announcement.objects.create(title="Once", body="b", audience="all_tenants")
        publish_announcement(a)
        publish_announcement(a)
        self.assertEqual(a.recipients.count(), 3)

    def test_manager_cannot_target_whole_portfolio_or_other_property(self):
        self.login(self.manager)
        r = self.client.post("/api/announcements/", {"title": "x", "body": "y", "audience": "all_tenants"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/announcements/", {"title": "x", "body": "y", "audience": "properties",
                                                     "property_ids": [self.p2.pk]}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/announcements/", {"title": "x", "body": "y", "audience": "properties",
                                                     "property_ids": [self.p1.pk], "requires_acknowledgement": True},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        r = self.client.post(f"/api/announcements/{r.data['id']}/publish/")
        self.assertEqual(r.data["stats"]["recipients"], 2)

    def test_tenant_reads_and_acknowledges_only_own_notices(self):
        a = Announcement.objects.create(title="P2 only", body="b", audience="properties", requires_acknowledgement=True)
        a.properties.set([self.p2])
        publish_announcement(a)
        self.login(self.ta.user)
        self.assertEqual(self.client.get("/api/portal/announcements/").data["count"], 0)
        rec = AnnouncementRecipient.objects.get(tenant=self.tc)
        self.assertEqual(self.client.get(f"/api/portal/announcements/{rec.pk}/").status_code, 404)
        self.login(self.tc.user)
        r = self.client.get(f"/api/portal/announcements/{rec.pk}/")
        self.assertIsNotNone(r.data["opened_at"])
        self.assertIsNone(r.data["acknowledged_at"])
        r = self.client.post(f"/api/portal/announcements/{rec.pk}/acknowledge/")
        self.assertIsNotNone(r.data["acknowledged_at"])


class DocumentAccessTests(BaseTestCase):
    def doc(self, title, **kw):
        d = Document.objects.create(title=title, status="approved", **kw)
        v = DocumentVersion.objects.create(document=d, version=1, file=ContentFile(PDF, name="f.pdf"),
                                           original_name="f.pdf")
        d.current_version = v
        d.save()
        return d

    def setUp(self):
        super().setUp()
        self.ta, _ = self.make_tenant("Aa", self.u1)
        self.tc, _ = self.make_tenant("Cc", self.u4)
        self.rules = self.doc("P1 rules", property=self.p1, workflow="acknowledge", is_library=True)
        DocumentAssignment.objects.create(document=self.rules, scope="property", property=self.p1)
        self.private = self.doc("Cc agreement", tenant=self.tc, workflow="info")
        DocumentAssignment.objects.create(document=self.private, scope="tenant", tenant=self.tc)
        self.draft = self.doc("Draft", property=self.p1)
        self.draft.status = "draft"
        self.draft.save()
        DocumentAssignment.objects.create(document=self.draft, scope="property", property=self.p1)

    def test_tenant_sees_only_assigned_approved_documents(self):
        self.login(self.ta.user)
        titles = {d["title"] for d in self.client.get("/api/portal/documents/").data}
        self.assertEqual(titles, {"P1 rules"})
        self.assertEqual(self.client.get(f"/api/portal/documents/{self.private.pk}/download/").status_code, 404)
        r = self.client.get(f"/api/portal/documents/{self.rules.pk}/download/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("private", r["Cache-Control"])

    def test_acknowledgement_recorded_per_version(self):
        self.login(self.ta.user)
        r = self.client.post(f"/api/portal/documents/{self.rules.pk}/acknowledge/")
        self.assertIsNotNone(r.data["acknowledged_at"])
        self.login(self.admin)
        rows = self.client.get(f"/api/documents/{self.rules.pk}/acknowledgements/").data["rows"]
        self.assertEqual([(x["tenant"], bool(x["acknowledged_at"])) for x in rows], [("Aa Test", True)])

    def test_signature_upload_workflow(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from documents.models import SignatureRequest

        doc = self.doc("Agreement", tenant=self.ta, workflow="signature")
        sr = SignatureRequest.objects.create(document=doc, version=doc.current_version, tenant=self.ta)
        self.login(self.tc.user)
        f = SimpleUploadedFile("signed.pdf", PDF, content_type="application/pdf")
        self.assertEqual(self.client.post(f"/api/portal/signature-requests/{sr.pk}/upload/", {"file": f}).status_code, 404)
        self.login(self.ta.user)
        bad = SimpleUploadedFile("signed.pdf", b"MZ-not-a-pdf", content_type="application/pdf")
        self.assertEqual(self.client.post(f"/api/portal/signature-requests/{sr.pk}/upload/", {"file": bad}).status_code, 400)
        f = SimpleUploadedFile("signed.pdf", PDF, content_type="application/pdf")
        r = self.client.post(f"/api/portal/signature-requests/{sr.pk}/upload/", {"file": f})
        self.assertEqual(r.data["status"], "submitted")
        self.login(self.manager)
        r = self.client.post(f"/api/signature-requests/{sr.pk}/verify/")
        self.assertEqual(r.data["status"], "verified")

    def test_former_tenant_loses_portal_documents_but_history_is_kept(self):
        _, t = self.make_tenant("Gone", self.u3)
        own = self.doc("Gone agreement", tenant=t.tenant)
        self.login(t.tenant.user)
        self.assertEqual(self.client.get(f"/api/portal/documents/{own.pk}/download/").status_code, 200)
        complete_move_out(t, actual_move_out=date.today(), notify=False)
        # Session ended and account deactivated: no portal or private-file access
        self.assertIn(self.client.get("/api/portal/documents/").status_code, (401, 403))
        self.assertIn(self.client.get(f"/api/portal/documents/{own.pk}/download/").status_code, (401, 403))
        # Staff still see the document and the tenancy history
        self.login(self.manager)
        self.assertEqual(self.client.get(f"/api/documents/{own.pk}/download/").status_code, 200)
        self.assertEqual(self.client.get(f"/api/tenancies/{t.pk}/").data["status"], "ended")

    def test_manager_cannot_open_other_property_documents(self):
        other = self.doc("P2 rules", property=self.p2)
        self.login(self.manager)
        self.assertEqual(self.client.get(f"/api/documents/{other.pk}/download/").status_code, 404)


class TenantIsolationTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ta, self.tna = self.make_tenant("Aa", self.u1, charge_deposit=False)
        self.tb, self.tnb = self.make_tenant("Bb", self.u2, charge_deposit=False)
        self.pay_b = self.pay(self.tnb, "1000")
        self.mr_b = MaintenanceRequest.objects.create(property=self.p1, unit=self.u2, tenant=self.tb,
                                                      tenancy=self.tnb, title="B's leak", description="x")

    def test_tenant_a_cannot_reach_tenant_b_records(self):
        self.login(self.ta.user)
        self.assertEqual(self.client.get(f"/api/portal/payments/{self.pay_b.pk}/receipt/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/portal/tenancies/{self.tnb.pk}/statement/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/portal/maintenance/{self.mr_b.pk}/").status_code, 404)
        r = self.client.get("/api/portal/account/", {"tenancy": self.tnb.pk})
        self.assertEqual(r.data["tenancy"]["id"], self.tna.pk)  # ignores foreign tenancy id
        self.assertEqual(self.client.get(f"/api/tenants/{self.tb.pk}/").status_code, 403)
        self.assertEqual(self.client.get(f"/api/tenancies/{self.tnb.pk}/ledger/").status_code, 403)
        body = str(self.client.get("/api/portal/dashboard/").data)
        self.assertNotIn("Bb", body)

    def test_tenant_can_get_own_receipt_and_statement(self):
        p = self.pay(self.tna, "500")
        self.login(self.ta.user)
        self.assertEqual(self.client.get(f"/api/portal/payments/{p.pk}/receipt/").status_code, 200)
        self.assertEqual(self.client.get(f"/api/portal/tenancies/{self.tna.pk}/statement/").status_code, 200)

    def test_stk_for_foreign_tenancy_falls_back_to_own(self):
        self.login(self.ta.user)
        r = self.client.post("/api/portal/payments/mpesa/", {"phone": "0712345678", "amount": "100",
                                                             "tenancy": self.tnb.pk}, format="json")
        self.assertEqual(r.status_code, 400)  # no current tenancy matches – never charges B's account


class MaintenanceTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ta, self.tna = self.make_tenant("Aa", self.u1)

    def test_tenant_request_auto_assigned_and_internal_notes_hidden(self):
        self.login(self.ta.user)
        r = self.client.post("/api/portal/maintenance/", {"title": "Tap", "description": "Leaks",
                                                          "category": "plumbing", "urgency": "normal",
                                                          "property": self.p2.pk}, format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        req = MaintenanceRequest.objects.get()
        self.assertEqual((req.property_id, req.unit_id), (self.p1.pk, self.u1.pk))  # ignores injected property
        self.login(self.caretaker)
        self.client.post(f"/api/maintenance/{req.pk}/note/", {"message": "secret cost note", "is_internal": True},
                         format="json")
        r = self.client.post(f"/api/maintenance/{req.pk}/status/", {"status": "in_progress",
                                                                    "message": "Plumber coming"}, format="json")
        self.assertEqual(r.data["status"], "in_progress")
        self.login(self.ta.user)
        body = str(self.client.get(f"/api/portal/maintenance/{req.pk}/").data)
        self.assertIn("Plumber coming", body)
        self.assertNotIn("secret cost note", body)

    def test_caretaker_cannot_manage_other_property_requests(self):
        _, t4 = self.make_tenant("Dd", self.u4)
        req = MaintenanceRequest.objects.create(property=self.p2, unit=self.u4, tenant=t4.tenant, title="x",
                                                description="y")
        self.login(self.caretaker)
        self.assertEqual(self.client.get(f"/api/maintenance/{req.pk}/").status_code, 404)
        r = self.client.post(f"/api/maintenance/{req.pk}/status/", {"status": "closed"}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_assignment_must_cover_property(self):
        req = MaintenanceRequest.objects.create(property=self.p1, unit=self.u1, title="x", description="y")
        r = self.login(self.manager).patch(f"/api/maintenance/{req.pk}/", {"assigned_to": self.manager2.pk},
                                           format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.patch(f"/api/maintenance/{req.pk}/", {"assigned_to": self.caretaker.pk}, format="json")
        self.assertEqual(r.data["status"], "assigned")


class ReportTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        _, self.t1 = self.make_tenant("Aa", self.u1, charge_deposit=False)
        _, self.t4 = self.make_tenant("Dd", self.u4, charge_deposit=False)
        self.pay(self.t1, "15000")
        self.pay(self.t4, "20000")
        self.pay(self.t4, "999", status="pending")

    def test_collections_and_arrears_reflect_data(self):
        self.login(self.admin)
        r = self.client.get("/api/reports/collections-by-property/")
        totals = {row["property"]: row["collected"] for row in r.data["rows"]}
        self.assertEqual(totals, {"Alpha Court": "15000.00", "Beta Place": "20000.00"})
        r = self.client.get("/api/reports/arrears/")
        self.assertEqual([(x["tenant"], x["balance"]) for x in r.data["rows"]], [("Aa Test", "5000.00")])
        r = self.client.get("/api/reports/occupancy/")
        self.assertEqual(r.data["totals"]["occupied"], 2)

    def test_manager_reports_are_scoped(self):
        self.login(self.manager)
        r = self.client.get("/api/reports/collections-by-property/")
        self.assertEqual([x["property"] for x in r.data["rows"]], ["Alpha Court"])
        self.assertEqual(self.client.get("/api/reports/occupancy/", {"property": self.p2.pk}).status_code, 403)
        csv = self.client.get("/api/reports/payment-history/", {"export": "csv"}).content.decode("utf-8-sig")
        self.assertIn("Aa Test", csv)
        self.assertNotIn("Dd Test", csv)

    def test_dashboard_figures(self):
        r = self.login(self.admin).get("/api/dashboard/")
        self.assertEqual(r.data["units"]["total"], 4)
        self.assertEqual(r.data["units"]["occupied"], 2)
        self.assertEqual(r.data["units"]["occupancy_rate"], 50.0)
        self.assertEqual(r.data["financials"]["collected"], "35000.00")
        self.assertEqual(r.data["financials"]["outstanding"], "5000.00")
        self.assertEqual(r.data["actions"]["payments_to_verify"], 1)
