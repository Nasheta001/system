"""Load FICTIONAL demonstration data.

    python manage.py seed_demo            # load into an empty database
    python manage.py seed_demo --reset    # wipe business data and reload (asks for confirmation)

All people, phone numbers and emails are invented. Demo emails use the
reserved `.test` domain so no real person can receive them.
"""
import random
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import AuditLog, CompanySettings, PropertyAssignment, Role, StaffProfile, User
from billing.models import Charge, FollowUpTask, MpesaTransaction, Payment, ReminderLog
from billing.services import account_summary, add_months, generate_charges_for_tenancy, month_start, verify_payment
from communications.models import Announcement, Notification
from communications.services import publish_announcement
from documents.models import Document, DocumentAssignment, DocumentVersion, SignatureRequest
from leasing.models import RentalApplication, Reservation, ViewingRequest
from leasing.services import reserve_unit, set_application_status
from maintenance.models import MaintenanceRequest, MaintenanceUpdate
from properties.models import Amenity, Building, Property, PropertyOwnership, PropertyPhoto, Unit, UnitType
from tenancies.models import Tenancy, Tenant
from tenancies.services import complete_move_out, move_in

from .setup_defaults import ensure_defaults

DEMO_PASSWORD = "Demo@2026!"
DOMAIN = "demo.propman.test"

FIRST = ["Amina", "Brian", "Cynthia", "David", "Esther", "Felix", "Grace", "Hassan", "Irene", "James", "Kevin",
         "Lydia", "Moses", "Naomi", "Otieno", "Purity", "Quincy", "Rose", "Samuel", "Tabitha", "Victor", "Wanjiku",
         "Yusuf", "Zawadi", "Allan", "Beatrice", "Collins", "Dorcas"]
LAST = ["Achieng", "Barasa", "Chebet", "Duba", "Ekiru", "Gitau", "Hamisi", "Imbuga", "Jeptoo", "Kamau", "Lagat",
        "Muthoni", "Njoroge", "Odhiambo", "Wekesa", "Rotich", "Simiyu", "Tanui", "Waweru", "Yego", "Kiprono"]

PROPERTIES = [
    {
        "name": "Bamburi Heights", "property_type": "apartments", "county": "Mombasa", "town": "Mombasa",
        "neighbourhood": "Bamburi", "address": "Fictional Rd 12, off Mombasa–Malindi Road, Bamburi",
        "description": "Modern apartments a short walk from Bamburi Beach, with secure parking, borehole water "
                       "and a rooftop terrace with an ocean breeze.",
        "amenities": ["Borehole water", "Backup generator", "CCTV", "24/7 security", "Parking", "Lift",
                      "Rooftop terrace"],
        "buildings": {"Block A": [("A1", "One bedroom", 45000), ("A2", "One bedroom", 45000), ("A3", "Two bedroom", 65000),
                                  ("A4", "Two bedroom", 65000), ("A5", "One bedroom", 46000), ("A6", "Two bedroom", 66000)],
                      "Block B": [("B1", "One bedroom", 44000), ("B2", "Two bedroom", 64000), ("B3", "Two bedroom", 64000),
                                  ("B4", "Three bedroom", 85000), ("B5", "One bedroom", 44000)]},
        "colour": (36, 92, 77), "published": True, "featured": True, "service_charge": 3000,
    },
    {
        "name": "Kisauni Gardens", "property_type": "bedsitters", "county": "Mombasa", "town": "Mombasa",
        "neighbourhood": "Kisauni", "address": "Example Lane 4, near Kisauni Road",
        "description": "Affordable bedsitters and studios with reliable water, prepaid electricity and quick "
                       "access to the New Nyali Bridge.",
        "amenities": ["Borehole water", "Prepaid electricity", "CCTV", "Garbage collection"],
        "buildings": {None: [("G1", "Bedsitter", 12000), ("G2", "Bedsitter", 12000), ("G3", "Studio", 16000),
                             ("F1", "Bedsitter", 12500), ("F2", "Studio", 16500), ("F3", "Studio", 17000),
                             ("F4", "Bedsitter", 12500), ("S1", "One bedroom", 22000)]},
        "colour": (120, 86, 52), "published": True, "featured": False, "service_charge": 0,
    },
    {
        "name": "Nyali Breeze Apartments", "property_type": "apartments", "county": "Mombasa", "town": "Mombasa",
        "neighbourhood": "Nyali", "address": "Sample Close 7, Links Road, Nyali",
        "description": "Spacious coastal apartments with sea breeze balconies, a swimming pool and children's "
                       "play area, minutes from Nyali Beach.",
        "amenities": ["Swimming pool", "Children's play area", "Backup generator", "24/7 security", "Parking",
                      "Balcony"],
        "buildings": {"Tower 1": [("101", "Two bedroom", 55000), ("102", "Two bedroom", 55000),
                                  ("201", "Three bedroom", 90000), ("202", "Three bedroom", 90000),
                                  ("301", "Two bedroom", 57000)]},
        "colour": (32, 96, 138), "published": True, "featured": True, "service_charge": 5000,
    },
    {
        "name": "Milimani Court", "property_type": "apartments", "county": "Nakuru", "town": "Nakuru",
        "neighbourhood": "Milimani", "address": "Placeholder Avenue 3, Milimani",
        "description": "Quiet, family-friendly one and two bedroom units near Nakuru town centre.",
        "amenities": ["Parking", "Borehole water", "Garbage collection"],
        "buildings": {None: [("1", "One bedroom", 22000), ("2", "One bedroom", 22000), ("3", "Two bedroom", 30000),
                             ("4", "Two bedroom", 30000)]},
        "colour": (98, 70, 120), "published": True, "featured": False, "service_charge": 0,
    },
    {
        "name": "Mwembeni Residences", "property_type": "apartments", "county": "Mombasa", "town": "Mombasa",
        "neighbourhood": "Mwembeni", "address": "Demo Street 9, Mwembeni, Mombasa",
        "description": "New development – finishing works in progress. Not yet published.",
        "amenities": ["Parking", "Lift"],
        "buildings": {None: [("L1", "Two bedroom", 35000), ("L2", "Two bedroom", 35000)]},
        "colour": (60, 60, 60), "published": False, "featured": False, "service_charge": 0,
    },
]


def placeholder_image(colour, label, seed):
    """Draw a simple illustrated building facade (clearly a placeholder)."""
    from PIL import Image, ImageDraw

    rnd = random.Random(seed)
    w, h = 1200, 800
    img = Image.new("RGB", (w, h), (226, 232, 236))
    d = ImageDraw.Draw(img)
    for y in range(h // 2):  # sky gradient
        t = y / (h / 2)
        d.line([(0, y), (w, y)], fill=(int(180 + 50 * t), int(205 + 30 * t), int(228 + 20 * t)))
    d.rectangle([0, int(h * 0.82), w, h], fill=(96, 122, 88))
    x = 80
    while x < w - 120:
        bw = rnd.randint(220, 340)
        bh = rnd.randint(380, 600)
        top = int(h * 0.82) - bh
        shade = tuple(max(0, min(255, c + rnd.randint(-18, 18))) for c in colour)
        d.rectangle([x, top, x + bw, int(h * 0.82)], fill=shade)
        for wy in range(top + 30, int(h * 0.82) - 50, 58):
            for wx in range(x + 22, x + bw - 40, 52):
                lit = rnd.random() > 0.35
                d.rectangle([wx, wy, wx + 30, wy + 34], fill=(250, 236, 180) if lit else (210, 222, 230))
        x += bw + rnd.randint(30, 60)
    buf = BytesIO()
    img.save(buf, "JPEG", quality=82)
    return ContentFile(buf.getvalue(), name=f"{label.lower().replace(' ', '-')}-{seed}.jpg")


def simple_pdf(title, paragraphs):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buf = BytesIO()
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Spacer(1, 12),
             Paragraph("<i>Fictional demonstration document.</i>", styles["Normal"]), Spacer(1, 12)]
    for p in paragraphs:
        story += [Paragraph(p, styles["BodyText"]), Spacer(1, 8)]
    SimpleDocTemplate(buf, pagesize=A4, title=title).build(story)
    return ContentFile(buf.getvalue(), name=f"{title.lower().replace(' ', '-')[:40]}.pdf")


class Command(BaseCommand):
    help = "Load fictional demonstration data (properties, staff, tenants, payments, notices, maintenance)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete ALL business data first")
        parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation")

    def handle(self, *args, **opts):
        if opts["reset"]:
            if not settings.DEBUG and not opts["yes"]:
                raise CommandError("Refusing to reset with DEBUG off. Pass --yes if you are sure.")
            if not opts["yes"]:
                answer = input("This deletes ALL properties, tenants, payments and non-superuser users. Type 'reset': ")
                if answer.strip() != "reset":
                    raise CommandError("Cancelled.")
            self.reset()
        elif Property.objects.exists():
            raise CommandError("Database already has properties. Use --reset to replace them with demo data.")
        with transaction.atomic():
            self.seed()
        from .use_demo_photos import apply_demo_photos

        apply_demo_photos()  # sample photos instead of the drawn placeholders
        self.stdout.write(self.style.SUCCESS(
            f"Demo data loaded. Sign in with any demo account using password {DEMO_PASSWORD}"))

    def reset(self):
        from communications.models import AnnouncementAttachment
        from maintenance.models import MaintenanceAttachment

        # Remove stored files belonging to the records about to be deleted
        for qs, field in [(PropertyPhoto.objects.all(), "image"), (DocumentVersion.objects.all(), "file"),
                          (SignatureRequest.objects.exclude(signed_file=""), "signed_file"),
                          (AnnouncementAttachment.objects.all(), "file"), (MaintenanceAttachment.objects.all(), "file")]:
            for obj in qs:
                getattr(obj, field).delete(save=False)
        with transaction.atomic():
            for model in [Notification, AuditLog, ReminderLog, FollowUpTask, MpesaTransaction, SignatureRequest,
                          DocumentAssignment]:
                model.objects.all().delete()
            Document.objects.update(current_version=None)
            for model in [DocumentVersion, Document, MaintenanceUpdate, MaintenanceRequest, Announcement, Payment,
                          Charge]:
                model.objects.all().delete()
            Tenancy.objects.update(reservation=None, transferred_from=None)
            for model in [Tenancy, Reservation, RentalApplication, ViewingRequest, Tenant, PropertyPhoto,
                          PropertyOwnership, PropertyAssignment, Unit, Building, Property]:
                model.objects.all().delete()
            User.objects.filter(is_superuser=False).delete()
        self.stdout.write("Existing business data removed.")

    # ------------------------------------------------------------------ seed
    def seed(self):
        rnd = random.Random(2026)
        ensure_defaults()
        today = timezone.localdate()
        company = CompanySettings.load()
        company.name = "Mwangaza Homes (Demo)"
        company.tagline = "Well-managed homes across Kenya"
        company.about = ("Mwangaza Homes is a fictional property management company used to demonstrate this "
                         "platform. We manage apartments and bedsitters in Mombasa (Bamburi, Kisauni, Nyali and Mwembeni) "
                         "and Nakuru with responsive maintenance and transparent rent accounts.")
        company.phone = "0700 000 100"
        company.whatsapp = "254700000100"
        company.email = f"hello@{DOMAIN}"
        company.address = "Demo Plaza, 2nd Floor, Nyali, Mombasa"
        company.privacy_notice = (
            "We collect the contact and tenancy information you provide to process enquiries, applications and "
            "tenancies, in line with the Kenya Data Protection Act, 2019. Information is used only for managing "
            "your tenancy or application, is accessible only to authorised staff, and is retained for as long as "
            "required for legal and accounting purposes. You may request access to or correction of your data by "
            "contacting our office.")
        company.faq = [
            {"question": "How much deposit do I pay?",
             "answer": "Most units require one month's rent as a refundable deposit. The exact amount is shown on each listing."},
            {"question": "How do I pay rent?",
             "answer": "Tenants pay through the tenant portal using M-Pesa, or at our office by bank transfer. "
                       "Every verified payment gets a receipt."},
            {"question": "How do I report a repair?",
             "answer": "Sign in to the tenant portal and open a maintenance request. You can follow its progress there."},
            {"question": "Can I view a unit before applying?",
             "answer": "Yes. Use 'Request a viewing' on any listing and our team will call you to arrange a time."},
        ]
        company.save()

        def staff(email, first, last, role, title, phone):
            u = User.objects.create_user(email=f"{email}@{DOMAIN}", password=DEMO_PASSWORD, first_name=first,
                                         last_name=last, role=role, phone=phone)
            StaffProfile.objects.create(user=u, job_title=title)
            return u

        admin = staff("admin", "Faith", "Mumbi", Role.ADMIN, "Operations Director", "0700000101")
        landlord = staff("landlord", "Peter", "Kariuki", Role.LANDLORD, "Portfolio Owner", "0700000102")
        mgr_nbi = staff("manager", "Grace", "Wanjiru", Role.MANAGER, "Property Manager – Bamburi & Kisauni", "0700000103")
        mgr_coast = staff("manager.coast", "Hassan", "Omar", Role.MANAGER, "Property Manager – Nyali, Mwembeni & Nakuru", "0700000104")
        caretaker = staff("caretaker", "Joseph", "Mutua", Role.CARETAKER, "Caretaker – Bamburi Heights", "0700000105")

        unit_types = {u.name: u for u in UnitType.objects.all()}
        props = {}
        for i, spec in enumerate(PROPERTIES):
            p = Property.objects.create(
                name=spec["name"], property_type=spec["property_type"], county=spec["county"], town=spec["town"],
                neighbourhood=spec["neighbourhood"], address=spec["address"], description=spec["description"],
                contact_phone="0700 000 100", contact_email=f"lettings@{DOMAIN}", whatsapp="254700000100",
                map_url=f"https://www.google.com/maps/search/?api=1&query={spec['neighbourhood']}+{spec['town']}",
                rent_terms="One month's rent as deposit. Rent is due on the 5th of each month. "
                           "Water billed separately where metered.",
                is_published=spec["published"], is_featured=spec["featured"],
            )
            p.amenities.set(Amenity.objects.filter(name__in=spec["amenities"]))
            for n in range(3):
                PropertyPhoto.objects.create(property=p, image=placeholder_image(spec["colour"], spec["name"], i * 10 + n),
                                             caption=["Exterior (illustration)", "Street view (illustration)", "Compound (illustration)"][n], is_cover=(n == 0),
                                             sort_order=n)
            PropertyOwnership.objects.create(
                property=p, owner_name="Mwangaza Homes (Demo)" if i % 2 == 0 else "Fictional Investments Ltd",
                arrangement="owned" if i % 2 == 0 else "managed", start_date=date(2022, 1, 1),
                management_fee_percent=None if i % 2 == 0 else Decimal("8.00"))
            for bname, units in spec["buildings"].items():
                building = Building.objects.create(property=p, name=bname, floors=4) if bname else None
                for num, tname, rent in units:
                    ut = unit_types[tname]
                    Unit.objects.create(
                        property=p, building=building, unit_type=ut, unit_number=num, bedrooms=ut.bedrooms,
                        bathrooms=2 if ut.bedrooms >= 2 else 1, floor=rnd.randint(0, 4), rent_amount=rent,
                        deposit_amount=rent, service_charge=spec["service_charge"], rent_due_day=5,
                        is_listed=spec["published"],
                        listing_description=f"{tname} unit with good natural light and ample storage.",
                        size_sqm=Decimal(28 + 22 * ut.bedrooms + rnd.randint(0, 8)),
                    )
            props[spec["name"]] = p

        for name in ["Bamburi Heights", "Kisauni Gardens"]:
            PropertyAssignment.objects.create(user=mgr_nbi, property=props[name], is_primary_contact=True,
                                              assigned_by=admin)
        for name in ["Nyali Breeze Apartments", "Milimani Court", "Mwembeni Residences"]:
            PropertyAssignment.objects.create(user=mgr_coast, property=props[name], is_primary_contact=True,
                                              assigned_by=admin)
        PropertyAssignment.objects.create(user=caretaker, property=props["Bamburi Heights"], assigned_by=admin)
        Unit.objects.filter(property=props["Mwembeni Residences"]).update(status="unavailable", is_listed=False)

        # ---------------------------------------------------------- tenants & tenancies
        names = iter([(f, l) for f, l in zip(FIRST, LAST * 2)])
        tenants = []

        def new_tenant(first, last, portal=False, email=None):
            idx = len(tenants) + 1
            email = email or f"{first.lower()}.{last.lower()}@{DOMAIN}"
            user = None
            if portal:
                user = User.objects.create_user(email=email, password=DEMO_PASSWORD, first_name=first,
                                                last_name=last, role=Role.TENANT, phone=f"07000002{idx:02d}")
            t = Tenant.objects.create(
                user=user, first_name=first, last_name=last, email=email, phone=f"07000002{idx:02d}",
                id_number=f"DEMO{100000 + idx}", occupation=rnd.choice(["Teacher", "Nurse", "Engineer", "Trader",
                                                                         "Accountant", "Designer", "Driver"]),
                emergency_contact_name=f"{rnd.choice(FIRST)} {rnd.choice(LAST)}",
                emergency_contact_phone=f"07000003{idx:02d}", emergency_contact_relationship="Sibling",
                created_by=admin, data_consent_at=timezone.now(),
            )
            tenants.append(t)
            return t

        occupied_plan = {
            "Bamburi Heights": ["A1", "A2", "A3", "A4", "B1", "B2", "B3", "B4"],
            "Kisauni Gardens": ["G1", "G2", "G3", "F1", "F2", "S1"],
            "Nyali Breeze Apartments": ["101", "102", "201"],
            "Milimani Court": ["1", "3"],
        }
        demo_tenant = None
        tenancies = []
        for pname, nums in occupied_plan.items():
            p = props[pname]
            for num in nums:
                unit = Unit.objects.get(property=p, unit_number=num)
                if pname == "Bamburi Heights" and num == "A3":
                    t = new_tenant("Amina", "Otieno", portal=True, email=f"tenant@{DOMAIN}")
                    demo_tenant = t
                    months_back = 7
                else:
                    first, last = next(names)
                    t = new_tenant(first, last, portal=rnd.random() < 0.6)
                    months_back = rnd.randint(2, 14)
                start = add_months(month_start(today), -months_back).replace(day=1)
                tenancy = move_in(t, unit.pk, start, user=mgr_nbi, notify=False,
                                  expected_end_date=add_months(start, 12) - timedelta(days=1))
                tenancies.append(tenancy)

        # Payments: most tenants pay on time; some partial; a few overdue.
        method_cycle = ["mpesa_manual", "bank", "cash", "mpesa_manual"]
        for k, tenancy in enumerate(tenancies):
            profile = "good" if k % 5 not in (3, 4) else ("partial" if k % 5 == 3 else "late")
            if tenancy.tenant == demo_tenant:
                profile = "demo"
            charges = list(tenancy.charges.order_by("due_date"))
            for c in charges:
                if c.kind == "deposit":
                    self._pay(tenancy, c.amount, c.due_date, "bank", admin, rnd)
                    continue
                if c.kind != "rent" and c.kind != "service":
                    continue
                is_current_month = c.period == month_start(today)
                amount = c.amount
                if profile == "late" and c.due_date >= add_months(month_start(today), -1):
                    continue  # last two months unpaid
                if profile == "partial" and is_current_month:
                    amount = (c.amount / 2).quantize(Decimal("1"))
                if profile in ("demo",) and is_current_month and c.kind == "rent":
                    continue  # demo tenant still owes this month's rent
                if is_current_month and c.due_date > today and profile == "good" and rnd.random() < 0.5:
                    continue
                paid_on = min(today, c.due_date - timedelta(days=rnd.randint(0, 4)))
                self._pay(tenancy, amount, paid_on, method_cycle[k % 4], admin, rnd)
        # A pending (unverified) payment recorded by a manager
        t0 = tenancies[1]
        Payment.objects.create(tenancy=t0, property_id=t0.property_id, amount=Decimal("5000"), method="bank",
                               reference="DEMO-BANK-7781", paid_on=today, recorded_by=mgr_nbi,
                               notes="Bank slip received at office – awaiting verification")

        # A former tenant (moved out) to show history
        unit = Unit.objects.get(property=props["Milimani Court"], unit_number="2")
        former = new_tenant("Collins", "Kiprono", portal=False)
        start = add_months(month_start(today), -10)
        ft = move_in(former, unit.pk, start, user=mgr_coast, notify=False)
        for c in ft.charges.all():
            self._pay(ft, c.amount, c.due_date, "bank", admin, rnd)
        complete_move_out(ft, actual_move_out=add_months(month_start(today), -2) - timedelta(days=1), user=mgr_coast,
                          inspection_date=add_months(month_start(today), -2), inspection_notes="Minor wall scuffs.",
                          deposit_deductions=Decimal("2000"), deduction_notes="Repainting living room",
                          unit_status_after="available", notify=False)

        # ---------------------------------------------------------- leasing
        avail = list(Unit.objects.filter(status="available", is_listed=True))
        applicants = [("Lilian", "Akinyi"), ("Mark", "Ndegwa"), ("Sharon", "Wairimu"), ("Tom", "Ouma")]
        for i, (f, l) in enumerate(applicants):
            unit = avail[i % len(avail)]
            app = RentalApplication.objects.create(
                unit=unit, property=unit.property, full_name=f"{f} {l}", email=f"{f.lower()}.{l.lower()}@{DOMAIN}",
                phone=f"07000004{i:02d}", occupation="Analyst", household_size=rnd.randint(1, 4),
                desired_move_in=today + timedelta(days=14 + i), message="I would like to move in next month.",
                consent_given=True)
            if i == 0:
                set_application_status(app, "under_review", user=mgr_nbi)
            if i == 1:
                app = set_application_status(app, "approved", user=mgr_nbi,
                                             applicant_message="Approved – please visit the office to sign.")
                reserve_unit(unit.pk, holder_name=app.full_name, holder_phone=app.phone, holder_email=app.email,
                             application=app, user=mgr_nbi)
        for i, (f, l) in enumerate([("Ann", "Moraa"), ("Ken", "Mutiso"), ("Joy", "Nyambura")]):
            unit = avail[(i + 4) % len(avail)]
            ViewingRequest.objects.create(property=unit.property, unit=unit, full_name=f"{f} {l}",
                                          phone=f"07000005{i:02d}", email=f"{f.lower()}@{DOMAIN}",
                                          preferred_date=today + timedelta(days=i + 2), consent_given=True,
                                          message="Is parking available?")

        # ---------------------------------------------------------- documents library
        def library_doc(title, category, prop, workflow, paragraphs, scope="property"):
            d = Document.objects.create(title=title, category=category, workflow=workflow, is_library=True,
                                        property=prop, created_by=admin, status="approved", approved_by=admin,
                                        approved_at=timezone.now())
            v = DocumentVersion.objects.create(document=d, version=1, file=simple_pdf(title, paragraphs),
                                               original_name=f"{title}.pdf", size=1, uploaded_by=admin)
            d.current_version = v
            d.save(update_fields=["current_version"])
            if scope == "all":
                DocumentAssignment.objects.create(document=d, scope="all_tenants", assigned_by=admin)
            else:
                DocumentAssignment.objects.create(document=d, scope="property", property=prop, assigned_by=admin)
            return d

        library_doc("Emergency contacts", "emergency", None, "info", [
            "Management office: 0700 000 100 (fictional).", "Security desk: 0700 000 199 (fictional).",
            "Police / ambulance / fire: 999 or 112."], scope="all")
        for p in [props["Bamburi Heights"], props["Kisauni Gardens"], props["Nyali Breeze Apartments"],
                  props["Milimani Court"]]:
            library_doc(f"House rules – {p.name}", "rules", p, "acknowledge", [
                "Quiet hours are 10pm – 6am.", "Visitors must be signed in at the gate.",
                "Common areas must be kept clear at all times.", "Pets require written approval from management."])
            library_doc(f"Waste disposal schedule – {p.name}", "waste", p, "info", [
                "Garbage is collected on Tuesdays and Fridays before 9am.",
                "Separate recyclables (plastic, paper, glass) into the marked bins."])
        library_doc("Water rationing arrangements – Kisauni", "water", props["Kisauni Gardens"], "info", [
            "Borehole water is supplied 5am–10am and 5pm–9pm daily.",
            "Report leaks immediately through a maintenance request."])
        # Tenancy agreement requiring signature for the demo tenant
        dt = demo_tenant.current_tenancy()
        agreement = Document.objects.create(
            title="Tenancy agreement – Bamburi Heights A3", category="tenancy_agreement", workflow="signature",
            property=dt.property, tenant=demo_tenant, tenancy=dt, created_by=admin, status="approved",
            approved_by=admin, approved_at=timezone.now())
        v = DocumentVersion.objects.create(document=agreement, version=1, file=simple_pdf(
            "Tenancy agreement (demo)", ["This fictional agreement is for demonstration only.",
                                         "Sign by hand, scan or photograph, and upload the signed copy in the portal."]),
            original_name="Tenancy agreement.pdf", size=1, uploaded_by=admin)
        agreement.current_version = v
        agreement.save(update_fields=["current_version"])
        DocumentAssignment.objects.create(document=agreement, scope="tenant", tenant=demo_tenant, assigned_by=admin)
        SignatureRequest.objects.create(document=agreement, version=v, tenant=demo_tenant, created_by=admin,
                                        due_date=today + timedelta(days=7))

        # ---------------------------------------------------------- announcements
        a1 = Announcement.objects.create(
            title="Office closed on public holiday", body="Our offices will be closed on the next public holiday. "
            "For emergencies, call the security desk.", audience="all_tenants", priority="normal", author=admin,
            send_email=True)
        publish_announcement(a1)
        a2 = Announcement.objects.create(
            title="Scheduled water interruption – Bamburi Heights",
            body="Water supply will be interrupted on Saturday from 9am to 1pm for tank cleaning. "
                 "Please store enough water in advance.",
            audience="properties", priority="high", author=mgr_nbi, requires_acknowledgement=True, send_sms=True)
        a2.properties.set([props["Bamburi Heights"]])
        publish_announcement(a2)
        a3 = Announcement.objects.create(
            title="Fire drill – Block B", body="A fire drill will take place in Block B next Wednesday at 10am.",
            audience="buildings", priority="normal", author=mgr_nbi)
        a3.buildings.set(Building.objects.filter(property=props["Bamburi Heights"], name="Block B"))
        publish_announcement(a3)
        a4 = Announcement.objects.create(
            title="Pest control visit", body="Pest control will treat all units next month. Details to follow.",
            audience="properties", priority="normal", author=mgr_coast, status="scheduled",
            publish_at=timezone.now() + timedelta(days=3))
        a4.properties.set([props["Nyali Breeze Apartments"], props["Milimani Court"]])
        tpl = Announcement.objects.create(
            title="Template: Garbage collection change", body="Garbage collection days are changing to [DAYS] "
            "from [DATE]. Please put bags out before 8am.", audience="properties", author=admin, is_template=True)
        tpl.properties.set([props["Kisauni Gardens"]])

        # ---------------------------------------------------------- maintenance
        issues = [
            ("Leaking kitchen tap", "plumbing", "normal", "in_progress"),
            ("Bedroom socket not working", "electrical", "high", "assigned"),
            ("Broken window latch", "security", "normal", "submitted"),
            ("No water since morning", "water", "emergency", "completed"),
            ("Cockroaches in kitchen", "pest", "low", "closed"),
            ("Door lock jammed", "security", "high", "awaiting_parts"),
        ]
        for i, (title, cat, urg, st) in enumerate(issues):
            ten = tenancies[i] if i else demo_tenant.current_tenancy()
            req = MaintenanceRequest.objects.create(
                property=ten.property, unit=ten.unit, tenant=ten.tenant, tenancy=ten,
                reported_by=ten.tenant.user, title=title, description=f"{title}. Please assist.", category=cat,
                urgency=urg, status=st, assigned_to=caretaker if st not in ("submitted",) else None,
                completed_at=timezone.now() if st in ("completed", "closed") else None,
                resolution_notes="Fixed and tested." if st in ("completed", "closed") else "")
            if st != "submitted":
                MaintenanceUpdate.objects.create(request=req, author=mgr_nbi, status_from="submitted",
                                                 status_to=st, message="We are working on this.")
                MaintenanceUpdate.objects.create(request=req, author=caretaker, is_internal=True,
                                                 message="Internal: check if the landlord covers part costs.")

        # A follow-up task for an overdue tenant
        for t in tenancies:
            s = account_summary(t)
            if s.overdue_amount > 0:
                FollowUpTask.objects.create(property=t.property, tenancy=t,
                                            title=f"Overdue rent: {t.tenant.full_name} ({t.unit.label})",
                                            details=f"KES {s.overdue_amount:,.2f} overdue {s.days_overdue} days.")
                break

        # Demo seeding should not leave a queue of fake outbound messages pretending to be delivered
        Notification.objects.exclude(channel="in_app").filter(status="queued").update(status="skipped",
                                                                                        last_error="Demo seed")

    def _pay(self, tenancy, amount, paid_on, method, user, rnd):
        p = Payment.objects.create(
            tenancy=tenancy, property_id=tenancy.property_id, amount=amount, method=method,
            reference="" if method == "cash" else f"DEMO{rnd.randint(100000, 999999)}", paid_on=paid_on,
            recorded_by=user)
        p.status = "verified"
        p.verified_by = user
        p.verified_at = timezone.now()
        from billing.services import assign_receipt_number

        assign_receipt_number(p)
        p.save()
        return p
