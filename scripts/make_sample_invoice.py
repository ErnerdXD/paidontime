#!/usr/bin/env python3
"""Create a text-based sample invoice for local AI extraction tests."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples" / "sample_invoice.docx"
OUT.parent.mkdir(parents=True, exist_ok=True)

doc = Document()
section = doc.sections[0]
section.top_margin = Inches(0.8)
section.bottom_margin = Inches(0.8)
section.left_margin = Inches(0.9)
section.right_margin = Inches(0.9)

style = doc.styles["Normal"]
style.font.name = "Calibri"
style.font.size = Pt(10.5)


def para(text: str = "", size: float = 10.5, bold: bool = False, color: RGBColor | None = None):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = color
    return p


para("STUDIO NORTH", 20, True, RGBColor(11, 93, 59))
para("Brand and product design", 9, False, RGBColor(100, 110, 100))
para("")
para("INVOICE", 26, True, RGBColor(20, 30, 25))
para("")
para("Bill to", 9, True, RGBColor(100, 110, 100))
para("Aina Studio", 12, True)
para("aina@example.com", 10)
para("")
para("Invoice no.  INV-2026-014", 10, True)
para("Issue date  08 November 2026", 10)
para("Due date    22 November 2026", 10)
para("Currency    MYR", 10)
para("")
para("Description", 9, True, RGBColor(100, 110, 100))
para("Brand identity sprint — discovery, direction, and final handoff.", 10)
para("")
para("Subtotal    MYR 1,250.00", 10)
para("Tax         MYR 0.00", 10)
p = para("Total due   MYR 1,250.00", 13, True, RGBColor(11, 93, 59))
p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
para("")
para("Payment by PayPal. Thank you.", 9, False, RGBColor(100, 110, 100))

doc.save(OUT)
print(OUT)
