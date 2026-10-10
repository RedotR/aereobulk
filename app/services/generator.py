"""Copyright (c) 2026 Rajesh - Aereo project.

PDF generation with ReportLab, using one hard-coded landscape A4 template."""
import os
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# Standard PDF fonts only cover Latin-1. If one of these Unicode fonts exists
# on the machine we use it; otherwise we fall back to Helvetica.
UNICODE_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",  # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Debian/Ubuntu
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",  # Fedora/Alpine
    "C:/Windows/Fonts/arial.ttf",  # Windows
]


def _pick_font() -> str:
    for path in UNICODE_FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("CertFont", path))
                return "CertFont"
            except Exception:
                continue  # unreadable font file, try the next one
    return "Helvetica"


FONT = _pick_font()


def _draw_fitted(c, text, x, y, font_size, max_width, min_size=8):
    """Draw centered text, shrinking the font until it fits max_width."""
    while font_size > min_size and pdfmetrics.stringWidth(text, FONT, font_size) > max_width:
        font_size -= 1
    # If it still doesn't fit at min_size, cut it off rather than overflow the border.
    while len(text) > 1 and pdfmetrics.stringWidth(text, FONT, font_size) > max_width:
        text = text[:-2] + "…"
    c.setFont(FONT, font_size)
    c.drawCentredString(x, y, text)


def generate_certificate_pdf(
    output_path: str,
    recipient_name: str,
    event_name: str,
    issue_date: date,
    issuer_name: str | None = None,
) -> None:
    """Write one certificate PDF to output_path."""
    width, height = landscape(A4)
    mid = width / 2
    text_width = width - 160  # keep text well inside the border

    c = canvas.Canvas(output_path, pagesize=(width, height))

    # Double border
    c.setStrokeColor(colors.HexColor("#1f3a5f"))
    c.setLineWidth(4)
    c.rect(30, 30, width - 60, height - 60)
    c.setLineWidth(1)
    c.rect(40, 40, width - 80, height - 80)

    c.setFillColor(colors.HexColor("#1f3a5f"))
    _draw_fitted(c, "Certificate of Completion", mid, height - 140, 40, text_width)

    c.setFillColor(colors.HexColor("#555555"))
    _draw_fitted(c, "This certificate is proudly presented to", mid, height - 200, 16, text_width)

    c.setFillColor(colors.black)
    _draw_fitted(c, recipient_name, mid, height - 260, 36, text_width)
    c.setStrokeColor(colors.HexColor("#999999"))
    c.line(mid - 200, height - 272, mid + 200, height - 272)

    c.setFillColor(colors.HexColor("#555555"))
    _draw_fitted(c, "for successfully completing", mid, height - 312, 16, text_width)

    c.setFillColor(colors.HexColor("#1f3a5f"))
    _draw_fitted(c, event_name, mid, height - 355, 26, text_width)

    c.setFillColor(colors.HexColor("#555555"))
    _draw_fitted(c, f"Issued on {issue_date.strftime('%B %d, %Y')}", mid, 120, 14, text_width / 2)

    if issuer_name:
        c.setStrokeColor(colors.black)
        c.line(width - 280, 110, width - 90, 110)  # signature line
        c.setFillColor(colors.black)
        _draw_fitted(c, issuer_name, width - 185, 92, 14, 190)

    # Small copyright line at the bottom of the page
    c.setFillColor(colors.HexColor("#999999"))
    c.setFont(FONT, 8)
    c.drawCentredString(mid, 52, "\u00a9 2026 Rajesh \u2022 Aereo")

    c.save()
