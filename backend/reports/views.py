"""Dashboard metrics and reports. Every figure is computed from stored records
and restricted to the requesting user's accessible properties."""
import csv
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsStaffMember, StaffCapability, accessible_property_ids, has_cap
from billing.models import FollowUpTask, Payment
from billing.services import bulk_summaries
from communications.models import Announcement, AnnouncementRecipient
from documents.models import SignatureRequest
from leasing.models import RentalApplication, Reservation, ViewingRequest
from maintenance.models import MaintenanceRequest
from properties.models import Property, Unit
from tenancies.models import Tenancy

ZERO = Decimal("0")


def _parse_date(value, default):
    if not value:
        return default
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError({"detail": f"Invalid date: {value}"}) from exc


def _scope(request):
    """Return (property_ids or None, start, end) honouring the user's scope and
    an optional ?property= filter."""
    ids = accessible_property_ids(request.user)
    prop = request.query_params.get("property")
    if prop:
        if not prop.isdigit():
            raise ValidationError({"property": "Invalid property."})
        pid = int(prop)
        if ids is not None and pid not in ids:
            raise PermissionDenied("You are not assigned to this property.")
        ids = {pid}
    today = timezone.localdate()
    start = _parse_date(request.query_params.get("start"), today.replace(day=1))
    end = _parse_date(request.query_params.get("end"), today)
    if end < start:
        raise ValidationError({"detail": "End date must be after start date."})
    return ids, start, end


def _f(qs, ids, field="property_id"):
    return qs if ids is None else qs.filter(**{f"{field}__in": ids})


def money(v):
    return str((v or ZERO).quantize(Decimal("0.01")))


class DashboardView(APIView):
    permission_classes = [IsStaffMember]

    def get(self, request):
        ids, start, end = _scope(request)
        user = request.user
        today = timezone.localdate()
        props = _f(Property.objects.filter(status="active"), ids, "id")
        units = _f(Unit.objects.filter(is_archived=False, property__status="active"), ids)
        counts = {s: 0 for s, _ in Unit.Status.choices}
        for row in units.values("status").annotate(n=Count("id")):
            counts[row["status"]] = row["n"]
        total_units = sum(counts.values())
        data = {
            "period": {"start": start, "end": end},
            "properties": props.count(),
            "units": {"total": total_units, **counts,
                      "occupancy_rate": round(100 * counts["occupied"] / total_units, 1) if total_units else 0},
            "maintenance": {
                "open": _f(MaintenanceRequest.objects.filter(status__in=MaintenanceRequest.OPEN_STATUSES), ids).count(),
                "emergency": _f(MaintenanceRequest.objects.filter(status__in=MaintenanceRequest.OPEN_STATUSES,
                                                                  urgency__in=["high", "emergency"]), ids).count(),
                "recent": list(_f(MaintenanceRequest.objects.filter(status__in=MaintenanceRequest.OPEN_STATUSES), ids)
                               .order_by("-created_at")[:6]
                               .values("id", "reference", "title", "urgency", "status", "property__name",
                                       "unit__unit_number", "created_at")),
            },
            "announcements": list(
                _f(Announcement.objects.filter(status="published"), ids, "properties").distinct()
                .order_by("-published_at")[:5].values("id", "title", "priority", "published_at")
            ) if ids is not None else list(Announcement.objects.filter(status="published")
                                           .order_by("-published_at")[:5]
                                           .values("id", "title", "priority", "published_at")),
            "financials": None,
            "actions": {},
        }
        if has_cap(user, "manage_applications"):
            data["actions"].update({
                "pending_applications": _f(RentalApplication.objects.filter(status__in=["pending", "under_review"]),
                                           ids).count(),
                "new_viewing_requests": _f(ViewingRequest.objects.filter(status="new"), ids).count(),
                "reservations_expiring": _f(Reservation.objects.filter(
                    status="active", expires_at__lte=timezone.now() + timedelta(days=2)), ids).count(),
            })
        if has_cap(user, "view_payments"):
            verified = _f(Payment.objects.filter(status=Payment.Status.VERIFIED), ids)
            collected = verified.filter(paid_on__gte=start, paid_on__lte=end).aggregate(s=Sum("amount"))["s"] or ZERO
            tenancies = list(_f(Tenancy.objects.filter(status__in=Tenancy.CURRENT_STATUSES), ids)
                             .select_related("tenant", "unit", "unit__building", "property"))
            summaries = bulk_summaries(tenancies, today)
            outstanding = sum((s.balance for s in summaries.values() if s.balance > 0), ZERO)
            overdue_rows, upcoming_rows = [], []
            for t in tenancies:
                s = summaries[t.pk]
                row = {"tenancy_id": t.pk, "tenant_id": t.tenant_id, "tenant": t.tenant.full_name,
                       "unit": t.unit.label, "property": t.property.name, "balance": money(s.balance)}
                if s.overdue_amount > 0:
                    overdue_rows.append({**row, "overdue_amount": money(s.overdue_amount),
                                         "days_overdue": s.days_overdue})
                elif s.next_due_date and s.next_due_date <= today + timedelta(days=7) and (s.next_due_amount > 0):
                    upcoming_rows.append({**row, "due_date": s.next_due_date, "amount": money(s.next_due_amount)})
            overdue_rows.sort(key=lambda r: -r["days_overdue"])
            upcoming_rows.sort(key=lambda r: r["due_date"])
            data["financials"] = {
                "collected": money(collected),
                "outstanding": money(outstanding),
                "overdue_total": money(sum((s.overdue_amount for s in summaries.values()), ZERO)),
                "overdue_count": len(overdue_rows),
                "expected_monthly": money(sum((t.monthly_rent + t.service_charge for t in tenancies), ZERO)),
                "overdue": overdue_rows[:10],
                "upcoming": upcoming_rows[:10],
                "recent_payments": [
                    {"id": p.pk, "tenant": p.tenancy.tenant.full_name, "unit": p.tenancy.unit.label,
                     "amount": money(p.amount), "paid_on": p.paid_on, "method": p.get_method_display(),
                     "is_simulated": p.is_simulated}
                    for p in verified.select_related("tenancy__tenant", "tenancy__unit").order_by("-paid_on", "-id")[:8]
                ],
                "monthly": [
                    {"month": r["m"].strftime("%Y-%m"), "amount": money(r["s"])}
                    for r in verified.filter(paid_on__gte=(today.replace(day=1) - timedelta(days=150)).replace(day=1))
                    .annotate(m=TruncMonth("paid_on")).values("m").annotate(s=Sum("amount")).order_by("m")
                ],
            }
            data["actions"].update({
                "payments_to_verify": _f(Payment.objects.filter(status="pending"), ids).count(),
                "open_follow_ups": _f(FollowUpTask.objects.filter(status="open"), ids).count(),
            })
        if has_cap(user, "manage_documents"):
            sig = SignatureRequest.objects.filter(status="submitted")
            if ids is not None:
                sig = sig.filter(tenant__tenancies__property_id__in=ids).distinct()
            data["actions"]["signatures_to_review"] = sig.count()
        return Response(data)


# ------------------------------------------------------------------------ reports
def report_rent_collected(ids, start, end):
    qs = _f(Payment.objects.filter(status="verified", paid_on__gte=start, paid_on__lte=end), ids)
    rows = [{"month": r["m"].strftime("%Y-%m"), "payments": r["n"], "amount": money(r["s"]),
             "simulated_amount": money(r["sim"])}
            for r in qs.annotate(m=TruncMonth("paid_on")).values("m").annotate(
                n=Count("id"), s=Sum("amount"), sim=Sum("amount", filter=Q(is_simulated=True))).order_by("m")]
    total = qs.aggregate(s=Sum("amount"))["s"]
    return ["month", "payments", "amount", "simulated_amount"], rows, {"amount": money(total)}


def report_collections_by_property(ids, start, end):
    props = _f(Property.objects.all(), ids, "id")
    rows = []
    for p in props.annotate(
        collected=Sum("payments__amount", filter=Q(payments__status="verified", payments__paid_on__gte=start,
                                                    payments__paid_on__lte=end)),
        n=Count("payments", filter=Q(payments__status="verified", payments__paid_on__gte=start,
                                     payments__paid_on__lte=end)),
    ).order_by("name"):
        rows.append({"property": p.name, "town": p.town, "payments": p.n, "collected": money(p.collected)})
    return ["property", "town", "payments", "collected"], rows, {
        "collected": money(sum((Decimal(r["collected"]) for r in rows), ZERO))}


def report_arrears(ids, start, end):
    tenancies = list(_f(Tenancy.objects.filter(status__in=Tenancy.CURRENT_STATUSES), ids)
                     .select_related("tenant", "unit", "unit__building", "property"))
    summaries = bulk_summaries(tenancies, end)
    rows = []
    for t in tenancies:
        s = summaries[t.pk]
        if s.balance > 0:
            rows.append({"tenant": t.tenant.full_name, "phone": t.tenant.phone, "property": t.property.name,
                         "unit": t.unit.label, "balance": money(s.balance), "overdue": money(s.overdue_amount),
                         "days_overdue": s.days_overdue, "status": s.status})
    rows.sort(key=lambda r: -Decimal(r["balance"]))
    return ["tenant", "phone", "property", "unit", "balance", "overdue", "days_overdue", "status"], rows, {
        "balance": money(sum((Decimal(r["balance"]) for r in rows), ZERO)),
        "overdue": money(sum((Decimal(r["overdue"]) for r in rows), ZERO))}


def report_payment_history(ids, start, end, tenant=None):
    qs = _f(Payment.objects.filter(paid_on__gte=start, paid_on__lte=end), ids).select_related(
        "tenancy__tenant", "tenancy__unit", "property", "recorded_by").order_by("paid_on", "id")
    if tenant:
        qs = qs.filter(tenancy__tenant_id=tenant)
    rows = [{"date": p.paid_on, "receipt": p.receipt_number or "", "tenant": p.tenancy.tenant.full_name,
             "property": p.property.name, "unit": p.tenancy.unit.unit_number, "method": p.get_method_display(),
             "reference": p.reference, "amount": money(p.amount), "status": p.status,
             "simulated": "yes" if p.is_simulated else "no",
             "recorded_by": p.recorded_by.get_full_name() if p.recorded_by else ""} for p in qs]
    return ["date", "receipt", "tenant", "property", "unit", "method", "reference", "amount", "status", "simulated",
            "recorded_by"], rows, {"amount": money(sum((p.amount for p in qs if p.status == "verified"), ZERO))}


def report_occupancy(ids, start, end):
    rows = []
    for p in _f(Property.objects.filter(status="active"), ids, "id").order_by("name"):
        units = p.units.filter(is_archived=False)
        c = {s: 0 for s, _ in Unit.Status.choices}
        for s in units.values_list("status", flat=True):
            c[s] += 1
        total = sum(c.values())
        rows.append({"property": p.name, "total_units": total, **c,
                     "occupancy_rate": f"{(100 * c['occupied'] / total):.1f}" if total else "0.0",
                     "vacancy_rate": f"{(100 * c['available'] / total):.1f}" if total else "0.0"})
    cols = ["property", "total_units", "occupied", "available", "reserved", "maintenance", "unavailable",
            "occupancy_rate", "vacancy_rate"]
    tot = sum(r["total_units"] for r in rows)
    occ = sum(r["occupied"] for r in rows)
    return cols, rows, {"total_units": tot, "occupied": occ,
                        "occupancy_rate": f"{(100 * occ / tot):.1f}" if tot else "0.0"}


def report_moves(ids, start, end):
    rows = []
    for t in _f(Tenancy.objects.filter(start_date__gte=start, start_date__lte=end), ids).select_related(
            "tenant", "unit", "property"):
        rows.append({"date": t.start_date, "type": "move-in", "tenant": t.tenant.full_name, "property": t.property.name,
                     "unit": t.unit.unit_number, "deposit_refund": ""})
    for t in _f(Tenancy.objects.filter(actual_move_out__gte=start, actual_move_out__lte=end), ids).select_related(
            "tenant", "unit", "property"):
        rows.append({"date": t.actual_move_out, "type": "move-out", "tenant": t.tenant.full_name,
                     "property": t.property.name, "unit": t.unit.unit_number,
                     "deposit_refund": money(t.deposit_refund_amount) if t.deposit_refund_amount is not None else ""})
    rows.sort(key=lambda r: r["date"])
    return ["date", "type", "tenant", "property", "unit", "deposit_refund"], rows, {
        "move_ins": sum(1 for r in rows if r["type"] == "move-in"),
        "move_outs": sum(1 for r in rows if r["type"] == "move-out")}


def report_maintenance(ids, start, end):
    qs = _f(MaintenanceRequest.objects.filter(created_at__date__gte=start, created_at__date__lte=end), ids)
    rows = []
    for r in qs.select_related("property", "unit", "assigned_to").order_by("created_at"):
        days = (r.completed_at - r.created_at).days if r.completed_at else ""
        rows.append({"reference": r.reference, "created": r.created_at.date(), "property": r.property.name,
                     "unit": r.unit.unit_number if r.unit else "", "category": r.get_category_display(),
                     "urgency": r.urgency, "status": r.status,
                     "assigned_to": r.assigned_to.get_full_name() if r.assigned_to else "", "days_to_complete": days})
    done = [r for r in rows if r["days_to_complete"] != ""]
    return ["reference", "created", "property", "unit", "category", "urgency", "status", "assigned_to",
            "days_to_complete"], rows, {
        "total": len(rows), "completed": len(done),
        "avg_days_to_complete": f"{sum(r['days_to_complete'] for r in done) / len(done):.1f}" if done else ""}


def report_acknowledgements(ids, start, end):
    qs = Announcement.objects.filter(status__in=["published", "archived"], published_at__date__gte=start,
                                     published_at__date__lte=end)
    rows = []
    for a in qs.order_by("published_at"):
        recs = a.recipients.filter(tenant__isnull=False)
        if ids is not None:
            recs = recs.filter(property_id__in=ids)
            if not recs.exists():
                continue
        n = recs.count()
        rows.append({"announcement": a.title, "published": a.published_at.date(), "recipients": n,
                     "opened_in_portal": recs.filter(opened_at__isnull=False).count(),
                     "acknowledged": recs.filter(acknowledged_at__isnull=False).count(),
                     "requires_acknowledgement": "yes" if a.requires_acknowledgement else "no"})
    return ["announcement", "published", "recipients", "opened_in_portal", "acknowledged",
            "requires_acknowledgement"], rows, {}


def report_applications(ids, start, end):
    apps = _f(RentalApplication.objects.filter(created_at__date__gte=start, created_at__date__lte=end), ids)
    res = _f(Reservation.objects.filter(created_at__date__gte=start, created_at__date__lte=end), ids)
    views = _f(ViewingRequest.objects.filter(created_at__date__gte=start, created_at__date__lte=end), ids)
    rows = []
    for p in _f(Property.objects.all(), ids, "id").order_by("name"):
        a = apps.filter(property=p)
        r = res.filter(property=p)
        row = {"property": p.name, "viewing_requests": views.filter(property=p).count(), "applications": a.count(),
               "approved": a.filter(status="approved").count(), "rejected": a.filter(status="rejected").count(),
               "reservations": r.count(), "converted": r.filter(status="converted").count(),
               "expired": r.filter(status="expired").count()}
        if any(v for k, v in row.items() if k != "property"):
            rows.append(row)
    cols = ["property", "viewing_requests", "applications", "approved", "rejected", "reservations", "converted",
            "expired"]
    return cols, rows, {c: sum(r[c] for r in rows) for c in cols[1:]}


REPORTS = {
    "rent-collected": ("Rent collected by month", report_rent_collected, "view_payments"),
    "collections-by-property": ("Collections by property", report_collections_by_property, "view_payments"),
    "arrears": ("Outstanding rent and arrears", report_arrears, "view_payments"),
    "payment-history": ("Payment history", report_payment_history, "view_payments"),
    "occupancy": ("Occupancy and vacancy", report_occupancy, "view_reports"),
    "moves": ("Move-ins and move-outs", report_moves, "view_reports"),
    "maintenance": ("Maintenance requests", report_maintenance, "view_reports"),
    "acknowledgements": ("Announcement acknowledgement", report_acknowledgements, "view_reports"),
    "applications": ("Applications and reservations", report_applications, "view_reports"),
}


class ReportListView(APIView):
    permission_classes = [StaffCapability]
    read_cap = "view_reports"

    def get(self, request):
        return Response([{"key": k, "title": v[0]} for k, v in REPORTS.items() if has_cap(request.user, v[2])])


class ReportView(APIView):
    permission_classes = [StaffCapability]
    read_cap = "view_reports"

    def get(self, request, name):
        if name not in REPORTS:
            return Response({"detail": "Unknown report."}, status=404)
        title, fn, cap = REPORTS[name]
        if not has_cap(request.user, cap):
            raise PermissionDenied("Your role cannot view this report.")
        ids, start, end = _scope(request)
        kwargs = {}
        if name == "payment-history" and request.query_params.get("tenant", "").isdigit():
            kwargs["tenant"] = int(request.query_params["tenant"])
        columns, rows, totals = fn(ids, start, end, **kwargs)
        if request.query_params.get("export") == "csv":
            resp = HttpResponse(content_type="text/csv; charset=utf-8")
            resp["Content-Disposition"] = f'attachment; filename="{name}-{start}-{end}.csv"'
            resp.write("﻿")  # Excel-friendly UTF-8 BOM
            w = csv.writer(resp)
            w.writerow(columns)
            for r in rows:
                w.writerow([_csv_safe(r.get(c, "")) for c in columns])
            return resp
        return Response({"title": title, "columns": columns, "rows": rows, "totals": totals,
                         "start": start, "end": end})


def _csv_safe(value):
    """Prevent CSV formula injection when opened in spreadsheet software."""
    s = str(value)
    if s and s[0] in ("=", "+", "-", "@") and not _is_number(s):
        return "'" + s
    return s


def _is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False
