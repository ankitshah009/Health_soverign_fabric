"""Generate a realistic itemized ER medical bill as a PDF (with planted overcharges).

The bill contains the errors Sovereign is meant to catch:
  - CPT 99285 (highest-level ER visit) billed TWICE on the same date (duplicate)
  - Level-5 ER code for a minor sprained-ankle visit (upcoding)
  - IV saline (J7030) billed at $450 vs a ~$40-80 fair price (price-above-fair-market)
  - Whole claim DENIED as "not medically necessary" (appealable denial)
"""
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
)

OUT = "/Users/ankitparagshah/GitHub/Health_soverign_fabric/demo/sample_medical_bill.pdf"

NAVY = colors.HexColor("#0F2A4A")
TEAL = colors.HexColor("#0E7490")
RED = colors.HexColor("#B42318")
LIGHT = colors.HexColor("#EEF2F7")
GREYTX = colors.HexColor("#475467")

styles = getSampleStyleSheet()
H = ParagraphStyle("H", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=18, textColor=NAVY, leading=20)
SUB = ParagraphStyle("SUB", parent=styles["Normal"], fontName="Helvetica", fontSize=9, textColor=GREYTX, leading=12)
LBL = ParagraphStyle("LBL", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=7.5, textColor=GREYTX, leading=10)
VAL = ParagraphStyle("VAL", parent=styles["Normal"], fontName="Helvetica", fontSize=9.5, textColor=colors.HexColor("#101828"), leading=12)
SECTION = ParagraphStyle("SECTION", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=10, textColor=NAVY, leading=14)
SMALL = ParagraphStyle("SMALL", parent=styles["Normal"], fontName="Helvetica", fontSize=7.5, textColor=GREYTX, leading=10)


def field(label, value, vstyle=VAL):
    return [Paragraph(label, LBL), Paragraph(value, vstyle)]


def build():
    doc = SimpleDocTemplate(
        OUT, pagesize=letter,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.55 * inch, bottomMargin=0.55 * inch,
        title="Itemized Statement of Charges",
    )
    story = []

    # ── Header: hospital (left) + statement meta (right) ──
    left = [
        Paragraph("RIVERSIDE GENERAL HOSPITAL", H),
        Paragraph("Emergency Department &nbsp;•&nbsp; 1450 Medical Center Dr, San Francisco, CA 94110", SUB),
        Paragraph("Patient Billing: (415) 555-0142 &nbsp;•&nbsp; billing@riversidegeneral.org", SUB),
    ]
    right = Table(
        [field("STATEMENT DATE", "June 10, 2026"),
         field("ACCOUNT NUMBER", "RGH-2026-0048817"),
         field("STATEMENT TYPE", "Itemized Statement")],
        colWidths=[1.3 * inch, 1.45 * inch], hAlign="RIGHT",
    )
    right.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    head = Table([[left, right]], colWidths=[4.4 * inch, 2.8 * inch])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [head, Spacer(1, 8), HRFlowable(width="100%", thickness=2, color=NAVY), Spacer(1, 10)]

    # ── Patient + service block ──
    pat = Table([
        field("PATIENT NAME", "Ankit Shah") + field("DATE OF SERVICE", "June 2, 2026"),
        field("DATE OF BIRTH", "March 14, 1990") + field("GUARANTOR", "Ankit Shah"),
        field("MEDICAL RECORD #", "MRN-558217") + field("VISIT TYPE", "Emergency Department"),
    ], colWidths=[1.5 * inch, 1.85 * inch, 1.5 * inch, 1.85 * inch])
    pat.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [pat, Spacer(1, 6)]

    # ── Insurance / claim status (DENIED) ──
    ins = Table([[
        Paragraph("INSURANCE", LBL), Paragraph("Blue Cross Blue Shield PPO", VAL),
        Paragraph("MEMBER ID", LBL), Paragraph("BCBS-PPO-2026", VAL),
        Paragraph("CLAIM STATUS", LBL), Paragraph('<font color="#B42318"><b>DENIED</b></font>', VAL),
    ]], colWidths=[0.95 * inch, 1.75 * inch, 0.85 * inch, 1.25 * inch, 0.95 * inch, 0.95 * inch])
    ins.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0D5DD")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [ins]
    story += [Spacer(1, 2), Paragraph(
        "Denial reason (CARC CO-50): Services determined not medically necessary for the diagnosis submitted.", SMALL)]
    story += [Spacer(1, 12)]

    # ── Itemized charges ──
    story += [Paragraph("ITEMIZED CHARGES", SECTION), Spacer(1, 4)]
    header = ["CODE", "DESCRIPTION", "DATE", "QTY", "CHARGES"]
    rows = [
        ["99285", "Emergency dept visit — Level 5 (highest complexity)", "06/02/2026", "1", "$1,800.00"],
        ["99285", "Emergency dept visit — Level 5 (highest complexity)", "06/02/2026", "1", "$1,800.00"],
        ["J7030", "IV infusion, normal saline 1000 mL", "06/02/2026", "1", "$450.00"],
        ["73610", "X-ray, ankle; 2 views (radiology)", "06/02/2026", "1", "$95.00"],
        ["A4570", "Splint, ankle (durable medical equipment)", "06/02/2026", "1", "$55.00"],
    ]
    data = [header] + rows
    tbl = Table(data, colWidths=[0.75 * inch, 3.55 * inch, 0.95 * inch, 0.5 * inch, 1.0 * inch], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("ALIGN", (3, 0), (4, -1), "RIGHT"),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FC")]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#E4E7EC")),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [tbl, Spacer(1, 10)]

    # ── Totals (right aligned) ──
    totals = Table([
        ["Total Charges", "$4,200.00"],
        ["Insurance Allowed Amount", "$0.00"],
        ["Plan Paid", "$0.00"],
        ["Patient Responsibility", "$4,200.00"],
    ], colWidths=[2.0 * inch, 1.2 * inch], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("TEXTCOLOR", (0, 0), (-1, 2), GREYTX),
        ("LINEABOVE", (0, 3), (-1, 3), 0.6, colors.HexColor("#D0D5DD")),
        ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [totals, Spacer(1, 10)]

    due = Table([["AMOUNT DUE", "$4,200.00"]], colWidths=[4.55 * inch, 2.2 * inch])
    due.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY), ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 13),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"), ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    story += [due, Spacer(1, 12)]

    story += [HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#D0D5DD")), Spacer(1, 6)]
    story += [Paragraph(
        "Payment due upon receipt. You have the right to request a fully itemized bill and to dispute any charge. "
        "If you believe a charge is incorrect or your claim was wrongly denied, you may appeal. "
        "Remit to: Riverside General Hospital, P.O. Box 7781, San Francisco, CA 94120.", SMALL)]

    doc.build(story)
    print("WROTE:", OUT)


if __name__ == "__main__":
    build()
