"""PDF receipts and statements (generated on demand, never stored publicly)."""
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from accounts.models import CompanySettings

from .models import Charge, Payment
from .services import account_summary

INK = colors.HexColor("#1f2a37")
MUTED = colors.HexColor("#6b7280")
LINE = colors.HexColor("#d9dee5")
BRAND = colors.HexColor("#1d5c4d")


def money(v):
    return f"KES {v:,.2f}"


def _doc(buffer, title):
    return SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                             bottomMargin=16 * mm, title=title)


def _header(story, styles, title):
    company = CompanySettings.load()
    story.append(Paragraph(f"<font color='#1d5c4d' size=16><b>{escape(company.name)}</b></font>", styles["Normal"]))
    contact = " · ".join(x for x in [company.address, company.phone, company.email] if x)
    if contact:
        story.append(Paragraph(f"<font color='#6b7280' size=9>{escape(contact)}</font>", styles["Normal"]))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(f"<font size=14><b>{title}</b></font>", styles["Normal"]))
    story.append(Spacer(1, 4 * mm))


def _kv_table(rows):
    t = Table(rows, colWidths=[45 * mm, 120 * mm])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
    ]))
    return t


def receipt_pdf(payment: Payment):
    buf = BytesIO()
    styles = getSampleStyleSheet()
    story = []
    _header(story, styles, "Payment receipt")
    if payment.is_simulated:
        story.append(Paragraph(
            "<font color='#b42318'><b>SIMULATED DEMO PAYMENT – NOT A REAL M-PESA TRANSACTION. "
            "No money was transferred.</b></font>", styles["Normal"]))
        story.append(Spacer(1, 4 * mm))
    t = payment.tenancy
    story.append(_kv_table([
        ["Receipt number", payment.receipt_number or "—"],
        ["Date paid", payment.paid_on.strftime("%d %B %Y")],
        ["Received from", t.tenant.full_name],
        ["Property / unit", f"{t.property.name} – {t.unit.label}"],
        ["Amount", money(payment.amount)],
        ["Method", payment.get_method_display()],
        ["Reference", payment.reference or "—"],
        ["Status", payment.get_status_display()],
    ]))
    story.append(Spacer(1, 6 * mm))
    summary = account_summary(t)
    story.append(Paragraph(
        f"Account balance as at {timezone.localdate():%d %b %Y}: <b>{money(summary.balance)}</b>"
        + (" (credit)" if summary.balance < 0 else ""), styles["Normal"]))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph("<font color='#6b7280' size=8>This receipt was generated electronically.</font>",
                           styles["Normal"]))
    _doc(buf, f"Receipt {payment.receipt_number}").build(story)
    return buf.getvalue()


def ledger_rows(tenancy):
    """Chronological list of charges and verified payments with running balance."""
    rows = []
    for c in tenancy.charges.filter(voided=False):
        credit = c.kind == Charge.Kind.CREDIT
        rows.append({"date": c.due_date, "type": "credit" if credit else "charge", "description": c.description,
                     "debit": None if credit else c.amount, "credit": c.amount if credit else None, "id": c.pk,
                     "order": 0})
    for p in tenancy.payments.filter(status=Payment.Status.VERIFIED):
        label = f"Payment – {p.get_method_display()}" + (f" ({p.reference})" if p.reference else "")
        rows.append({"date": p.paid_on, "type": "payment", "description": label, "debit": None, "credit": p.amount,
                     "id": p.pk, "receipt_number": p.receipt_number, "is_simulated": p.is_simulated, "order": 1})
    rows.sort(key=lambda r: (r["date"], r["order"], r["id"]))
    bal = 0
    for r in rows:
        bal += (r["debit"] or 0) - (r["credit"] or 0)
        r["balance"] = bal
    return rows


def statement_pdf(tenancy):
    buf = BytesIO()
    styles = getSampleStyleSheet()
    story = []
    _header(story, styles, "Rent statement")
    story.append(_kv_table([
        ["Tenant", tenancy.tenant.full_name],
        ["Property / unit", f"{tenancy.property.name} – {tenancy.unit.label}"],
        ["Tenancy", f"{tenancy.start_date:%d %b %Y} – "
                    f"{tenancy.actual_move_out.strftime('%d %b %Y') if tenancy.actual_move_out else 'current'}"],
        ["Monthly rent", money(tenancy.monthly_rent)],
        ["Statement date", timezone.localdate().strftime("%d %B %Y")],
    ]))
    story.append(Spacer(1, 6 * mm))
    data = [["Date", "Description", "Charges", "Payments / credits", "Balance"]]
    for r in ledger_rows(tenancy):
        desc = escape(r["description"]) + (" [SIMULATED]" if r.get("is_simulated") else "")
        data.append([r["date"].strftime("%d %b %Y"), Paragraph(desc, styles["BodyText"]),
                     f"{r['debit']:,.2f}" if r["debit"] else "", f"{r['credit']:,.2f}" if r["credit"] else "",
                     f"{r['balance']:,.2f}"])
    t = Table(data, colWidths=[24 * mm, 70 * mm, 24 * mm, 28 * mm, 26 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, LINE),
    ]))
    story.append(t)
    story.append(Spacer(1, 6 * mm))
    s = account_summary(tenancy)
    story.append(Paragraph(f"<b>Closing balance: {money(s.balance)}</b>"
                           + (" (credit in your favour)" if s.balance < 0 else ""), styles["Normal"]))
    _doc(buf, "Rent statement").build(story)
    return buf.getvalue()
