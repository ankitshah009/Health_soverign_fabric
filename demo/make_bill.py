#!/usr/bin/env python3
"""Generate a realistic itemized ER bill PNG for the Sovereign demo.

Renders a hospital "Itemized Statement" for an emergency-room visit
(sprained ankle) for patient "Demo Patient", total ~$4,200, with a
DUPLICATE CPT 99285 line so the vision + fraud pipeline can flag it.

Writes to two locations:
  - demo/sample_er_bill.png
  - frontend/public/sample-bill.png
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parents[1]
DEMO_OUT = REPO / "demo" / "sample_er_bill.png"
FRONTEND_OUT = REPO / "frontend" / "public" / "sample-bill.png"

# ── Canvas ────────────────────────────────────────────────────────────────────
W, H = 1275, 1650          # US-Letter-ish at ~150 DPI
MARGIN = 70
WHITE = (255, 255, 255)
INK = (24, 28, 34)
MUTED = (96, 104, 116)
LINE = (208, 214, 222)
ACCENT = (16, 78, 140)     # hospital navy
ACCENT_BG = (234, 241, 249)
ZEBRA = (247, 249, 252)
RED = (176, 36, 36)


def _font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    """Load the first available TrueType font, else Pillow's default."""
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


SANS = "/System/Library/Fonts/Supplemental/Arial.ttf"
SANS_B = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
MONO = "/System/Library/Fonts/Menlo.ttc"

f_title = _font([SANS_B, SANS], 40)
f_sub = _font([SANS, SANS_B], 21)
f_h = _font([SANS_B, SANS], 23)
f_label = _font([SANS_B, SANS], 16)
f_body = _font([SANS, SANS_B], 19)
f_small = _font([SANS, SANS_B], 16)
f_mono = _font([MONO, SANS], 18)
f_mono_b = _font([MONO, SANS], 19)
f_total = _font([SANS_B, SANS], 26)


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text, font=font))


def _right(draw, x_right: int, y: int, text: str, font, fill=INK) -> None:
    draw.text((x_right - _text_w(draw, text, font), y), text, font=font, fill=fill)


def build() -> Image.Image:
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    # ── Header band ──────────────────────────────────────────────────────────
    d.rectangle([0, 0, W, 150], fill=ACCENT)
    # logo glyph (cross in a rounded square)
    d.rounded_rectangle([MARGIN, 38, MARGIN + 74, 112], radius=14, fill=WHITE)
    d.rectangle([MARGIN + 31, 52, MARGIN + 43, 98], fill=ACCENT)
    d.rectangle([MARGIN + 14, 69, MARGIN + 60, 81], fill=ACCENT)

    d.text((MARGIN + 96, 44), "ST. MERIDIAN REGIONAL MEDICAL CENTER",
           font=f_title, fill=WHITE)
    d.text((MARGIN + 98, 92),
           "1450 Caldwell Avenue  •  Riverton, CA 90217  •  (310) 555-0182  •  Tax ID 95-1842736",
           font=f_small, fill=(214, 226, 240))

    y = 182
    d.text((MARGIN, y), "ITEMIZED STATEMENT OF CHARGES", font=f_h, fill=ACCENT)
    d.text((W - MARGIN - _text_w(d, "PAGE 1 OF 1", f_small), y + 6),
           "PAGE 1 OF 1", font=f_small, fill=MUTED)
    y += 40
    d.line([MARGIN, y, W - MARGIN, y], fill=LINE, width=2)

    # ── Patient / account meta (two columns) ─────────────────────────────────
    y += 24
    col2_x = W // 2 + 24

    def kv(x: int, yy: int, key: str, val: str, val_fill=INK) -> None:
        d.text((x, yy), key, font=f_label, fill=MUTED)
        d.text((x, yy + 21), val, font=f_body, fill=val_fill)

    kv(MARGIN, y, "PATIENT NAME", "Demo Patient")
    kv(col2_x, y, "ACCOUNT NUMBER", "ER-2026-0048817")
    y2 = y + 58
    kv(MARGIN, y2, "MEDICAL RECORD NO.", "MRN 7741-3329")
    kv(col2_x, y2, "STATEMENT DATE", "06/13/2026")
    y3 = y2 + 58
    kv(MARGIN, y3, "DATE OF SERVICE", "06/02/2026")
    kv(col2_x, y3, "ADMIT / DISCHARGE", "06/02/2026  18:42 / 21:15")
    y4 = y3 + 58
    kv(MARGIN, y4, "ATTENDING PROVIDER", "A. Reyes, MD  (Emergency Medicine)")
    kv(col2_x, y4, "PAYER", "Self-Pay / Insurance Denied")

    y = y4 + 70

    # ── Visit reason callout ─────────────────────────────────────────────────
    d.rounded_rectangle([MARGIN, y, W - MARGIN, y + 46], radius=8, fill=ACCENT_BG)
    d.text((MARGIN + 16, y + 13),
           "VISIT REASON:  Emergency Department evaluation — right ankle injury (sprain).  "
           "Dx: S93.401A  Sprain of unspecified ligament of right ankle.",
           font=f_small, fill=ACCENT)
    y += 70

    # ── Line item table ──────────────────────────────────────────────────────
    # Column layout
    x_code = MARGIN + 4
    x_desc = MARGIN + 150
    x_date = W - MARGIN - 330
    x_qty = W - MARGIN - 196
    x_charge_r = W - MARGIN - 8     # right edge for charges

    header_y = y
    d.rectangle([MARGIN, header_y, W - MARGIN, header_y + 36], fill=INK)
    d.text((x_code, header_y + 9), "CODE", font=f_label, fill=WHITE)
    d.text((x_desc, header_y + 9), "DESCRIPTION", font=f_label, fill=WHITE)
    d.text((x_date, header_y + 9), "DATE", font=f_label, fill=WHITE)
    d.text((x_qty, header_y + 9), "QTY", font=f_label, fill=WHITE)
    _right(d, x_charge_r, header_y + 9, "CHARGES", f_label, fill=WHITE)
    y = header_y + 36

    # (code, description, date, qty, charge)
    # NOTE: CPT 99285 appears TWICE — same code, same date — a duplicate charge.
    # That duplicate is the headline overcharge the fraud pipeline must flag.
    rows = [
        ("99285", "ER VISIT LEVEL 5 — HIGH COMPLEXITY", "06/02/2026", "1", 1800.00),
        ("99285", "ER VISIT LEVEL 5 — HIGH COMPLEXITY", "06/02/2026", "1", 1800.00),
        ("J7030", "IV INFUSION, NORMAL SALINE 1000 ML", "06/02/2026", "1", 450.00),
        ("73610", "X-RAY EXAM OF ANKLE, 3 VIEWS", "06/02/2026", "1", 95.00),
        ("A4565", "SUPPLIES — IMMOBILIZER / ANKLE SPLINT", "06/02/2026", "1", 55.00),
    ]

    row_h = 44
    for i, (code, desc, date, qty, charge) in enumerate(rows):
        ry = y + i * row_h
        if i % 2 == 1:
            d.rectangle([MARGIN, ry, W - MARGIN, ry + row_h], fill=ZEBRA)
        ty = ry + 12
        d.text((x_code, ty), code, font=f_mono_b, fill=INK)
        d.text((x_desc, ty), desc, font=f_body, fill=INK)
        d.text((x_date, ty), date, font=f_mono, fill=MUTED)
        d.text((x_qty + 6, ty), qty, font=f_mono, fill=MUTED)
        _right(d, x_charge_r, ty, f"${charge:,.2f}", f_mono_b, fill=INK)
        d.line([MARGIN, ry + row_h, W - MARGIN, ry + row_h], fill=LINE, width=1)

    y = y + len(rows) * row_h
    d.rectangle([MARGIN, header_y, MARGIN, y], fill=LINE)  # left rule anchor
    d.line([MARGIN, header_y, MARGIN, y], fill=LINE, width=1)
    d.line([W - MARGIN, header_y, W - MARGIN, y], fill=LINE, width=1)

    # ── Totals block ─────────────────────────────────────────────────────────
    subtotal = sum(r[4] for r in rows)
    y += 22
    tot_x_label = W - MARGIN - 430
    tot_x_val_r = x_charge_r

    def trow(yy: int, label: str, val: str, bold=False, fill=INK) -> None:
        lf = f_h if bold else f_body
        d.text((tot_x_label, yy), label, font=lf, fill=fill)
        _right(d, tot_x_val_r, yy, val, lf, fill=fill)

    trow(y, "Subtotal — Total Charges", f"${subtotal:,.2f}")
    y += 34
    trow(y, "Insurance Payments / Adjustments", "$0.00", fill=MUTED)
    y += 34
    trow(y, "Patient Payments", "$0.00", fill=MUTED)
    y += 14
    d.line([tot_x_label, y, tot_x_val_r, y], fill=INK, width=2)
    y += 14

    # Highlighted TOTAL DUE
    d.rounded_rectangle([tot_x_label - 18, y - 6, tot_x_val_r + 14, y + 44],
                        radius=8, fill=ACCENT)
    d.text((tot_x_label, y + 6), "TOTAL DUE", font=f_total, fill=WHITE)
    _right(d, tot_x_val_r, y + 6, f"${subtotal:,.2f}", f_total, fill=WHITE)
    y += 70

    # ── Notes / footer ───────────────────────────────────────────────────────
    d.line([MARGIN, y, W - MARGIN, y], fill=LINE, width=1)
    y += 16
    d.text((MARGIN, y), "REMITTANCE NOTES", font=f_label, fill=MUTED)
    y += 26
    notes = [
        "This is an itemized statement of charges for the above date of service. Charges reflect",
        "billed amounts prior to any insurance adjustment. Claim 2026-0048817 was returned by the",
        "payer marked DENIED — “service not covered as billed.”  Balance is now patient responsibility.",
        "Questions about specific line items or codes? Call Patient Financial Services at (310) 555-0199.",
    ]
    for line in notes:
        d.text((MARGIN, y), line, font=f_small, fill=MUTED)
        y += 24

    y += 10
    d.text((MARGIN, y),
           "Please remit payment within 30 days.  Statement ID 0048817-A  •  Generated 06/13/2026",
           font=f_small, fill=MUTED)

    # Bottom accent bar
    d.rectangle([0, H - 14, W, H], fill=ACCENT)
    return img


def main() -> None:
    DEMO_OUT.parent.mkdir(parents=True, exist_ok=True)
    FRONTEND_OUT.parent.mkdir(parents=True, exist_ok=True)

    img = build()
    img.save(DEMO_OUT, "PNG", optimize=True)
    shutil.copyfile(DEMO_OUT, FRONTEND_OUT)

    subtotal = 1800 + 1800 + 450 + 95 + 55
    print(f"OK  wrote {DEMO_OUT}  ({DEMO_OUT.stat().st_size:,} bytes, {img.width}x{img.height})")
    print(f"OK  wrote {FRONTEND_OUT}  ({FRONTEND_OUT.stat().st_size:,} bytes)")
    print(f"OK  total on bill = ${subtotal:,.2f}  (CPT 99285 billed twice = duplicate)")


if __name__ == "__main__":
    main()
