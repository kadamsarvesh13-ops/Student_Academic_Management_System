"""PDF generation with ReportLab."""

from __future__ import annotations

import io
from datetime import datetime
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BLUE = colors.HexColor("#1F4E9E")
LIGHT = colors.HexColor("#EAF1FB")


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return str(v)


def _table(data: list[list[str]], col_widths=None) -> Table:
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B8C4D6")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _doc(buf, landscape_mode=False) -> SimpleDocTemplate:
    size = landscape(A4) if landscape_mode else A4
    return SimpleDocTemplate(buf, pagesize=size, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                             topMargin=1.5 * cm, bottomMargin=1.5 * cm)


def _styles():
    ss = getSampleStyleSheet()
    return (ParagraphStyle("T", parent=ss["Title"], textColor=BLUE, fontSize=18),
            ParagraphStyle("S", parent=ss["Normal"], textColor=colors.HexColor("#57606A"), fontSize=9),
            ss["Heading3"], ss["Normal"])


def table_pdf(title: str, df: pd.DataFrame, subtitle: str = "") -> bytes:
    """Generic report: title + table of any DataFrame."""
    buf = io.BytesIO()
    title_s, sub_s, _, _ = _styles()
    cells = [[str(c) for c in df.columns]]
    cells += [[_fmt(v) for v in row] for row in df.itertuples(index=False)]
    wide = len(df.columns) > 6
    doc = _doc(buf, landscape_mode=wide)
    story = [Paragraph(escape(title), title_s),
             Paragraph(escape(subtitle) + f" &nbsp; Generated {datetime.now():%d %b %Y %H:%M}", sub_s),
             Spacer(1, 0.4 * cm)]
    story.append(_table(cells) if len(df) else Paragraph("No records.", sub_s))
    doc.build(story)
    return buf.getvalue()


def result_sheet_pdf(result: dict, institution: str = "") -> bytes:
    """Semester result sheet from marks_management.semester_result()."""
    buf = io.BytesIO()
    title_s, sub_s, h3, normal = _styles()
    st, rows = result["student"], result["rows"]
    doc = _doc(buf, landscape_mode=True)
    story = [Paragraph(escape(institution or "Semester Result Sheet"), title_s),
             Paragraph(f"Semester {result['semester']} - generated {datetime.now():%d %b %Y}", sub_s),
             Spacer(1, 0.3 * cm),
             Paragraph(f"<b>Name:</b> {escape(st['name'])} &nbsp;&nbsp; <b>ID:</b> {st['student_id']} "
                       f"&nbsp;&nbsp; <b>Dept:</b> {escape(st['department'])} &nbsp;&nbsp; "
                       f"<b>Division:</b> {escape(st['division'])}", normal),
             Spacer(1, 0.4 * cm)]
    header = ["Code", "Subject", "Credits", "Internal", "Practical", "External", "Total", "Max", "%", "Grade"]
    data = [header] + [[r.course_code, r.course_name, r.credits, _fmt(r.internal), _fmt(r.practical),
                        _fmt(r.external), _fmt(r.total), r.max_total, _fmt(r.percentage), r.grade]
                       for r in rows.itertuples()]
    story.append(_table(data, [2 * cm, 7 * cm, 1.6 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm, 1.6 * cm,
                               1.4 * cm, 1.6 * cm, 1.6 * cm]))
    story += [Spacer(1, 0.5 * cm),
              Paragraph(f"<b>Result:</b> {result['status']} &nbsp;&nbsp; <b>SGPA:</b> {_fmt(result['sgpa'])} "
                        f"&nbsp;&nbsp; <b>Overall %:</b> {_fmt(result['percentage'])}", h3)]
    doc.build(story)
    return buf.getvalue()
