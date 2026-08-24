import logging
import os
import re
from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.export_content import extract_report_metadata, plain_markdown_text
from src.markdown_tables import (
    is_markdown_table_row,
    is_markdown_table_separator,
    parse_markdown_table_row,
)

FONT_NAME = "BushfireReadyPDF"
LOGGER = logging.getLogger(__name__)
DRAFT_NOTICE = "DRAFT - NOT EMERGENCY ADVICE - HUMAN REVIEW REQUIRED"
DRAFT_NOTICE_DETAIL = (
    "Preparedness planning support only. This document does not provide live fire conditions, "
    "fire bans, evacuation orders or life-safety directions. The responsible organisation must "
    "review and approve it before formal use. Call 000 in a life-threatening emergency."
)
COMPACT_TABLE_CELL_CHARACTER_LIMIT = 600


def _register_pdf_font():
    font_candidates = [
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
    ]
    for font_path in font_candidates:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont(FONT_NAME, font_path))
                return FONT_NAME
            except Exception as error:
                LOGGER.debug("Could not register PDF font %s: %s", font_path, error)
                continue
    return "Helvetica"


def _escape_text(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_inline_markdown(text):
    text = _escape_text(text.strip())
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`(.+?)`", r"<font face='Courier'>\1</font>", text)
    return text


def _build_styles(font_name):
    base_styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "BushfireTitle",
            parent=base_styles["Title"],
            fontName=font_name,
            fontSize=20,
            leading=26,
            textColor=colors.HexColor("#18212f"),
            spaceAfter=14,
            alignment=TA_LEFT,
        ),
        "cover_kicker": ParagraphStyle(
            "BushfireCoverKicker",
            parent=base_styles["BodyText"],
            fontName=font_name,
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#7f2a19"),
            alignment=TA_CENTER,
            spaceAfter=14,
        ),
        "cover_title": ParagraphStyle(
            "BushfireCoverTitle",
            parent=base_styles["Title"],
            fontName=font_name,
            fontSize=24,
            leading=31,
            textColor=colors.HexColor("#18212f"),
            alignment=TA_CENTER,
            spaceAfter=22,
        ),
        "cover_meta": ParagraphStyle(
            "BushfireCoverMeta",
            parent=base_styles["BodyText"],
            fontName=font_name,
            fontSize=11,
            leading=17,
            textColor=colors.HexColor("#344054"),
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "cover_note": ParagraphStyle(
            "BushfireCoverNote",
            parent=base_styles["BodyText"],
            fontName=font_name,
            fontSize=9,
            leading=14,
            textColor=colors.HexColor("#667085"),
            alignment=TA_CENTER,
            spaceBefore=20,
        ),
        "draft_banner": ParagraphStyle(
            "BushfireDraftBanner",
            parent=base_styles["BodyText"],
            fontName=font_name,
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#b42318"),
            alignment=TA_CENTER,
            spaceBefore=6,
            spaceAfter=12,
            borderWidth=1,
            borderColor=colors.HexColor("#fda29b"),
            borderPadding=8,
            backColor=colors.HexColor("#fff1f3"),
        ),
        "h1": ParagraphStyle(
            "BushfireHeading1",
            parent=base_styles["Heading1"],
            fontName=font_name,
            fontSize=15,
            leading=20,
            textColor=colors.HexColor("#7f2a19"),
            spaceBefore=12,
            spaceAfter=7,
        ),
        "h2": ParagraphStyle(
            "BushfireHeading2",
            parent=base_styles["Heading2"],
            fontName=font_name,
            fontSize=12.5,
            leading=17,
            textColor=colors.HexColor("#18212f"),
            spaceBefore=9,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "BushfireBody",
            parent=base_styles["BodyText"],
            fontName=font_name,
            fontSize=10,
            leading=15,
            textColor=colors.HexColor("#18212f"),
            spaceAfter=6,
        ),
        "meta": ParagraphStyle(
            "BushfireMeta",
            parent=base_styles["BodyText"],
            fontName=font_name,
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#667085"),
            spaceAfter=12,
        ),
        "bullet": ParagraphStyle(
            "BushfireBullet",
            parent=base_styles["BodyText"],
            fontName=font_name,
            fontSize=9.5,
            leading=14,
            leftIndent=14,
            firstLineIndent=-8,
            textColor=colors.HexColor("#18212f"),
        ),
        "record_heading": ParagraphStyle(
            "BushfireRecordHeading",
            parent=base_styles["Heading3"],
            fontName=font_name,
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#7f2a19"),
            spaceBefore=6,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "record_label": ParagraphStyle(
            "BushfireRecordLabel",
            parent=base_styles["BodyText"],
            fontName=font_name,
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#344054"),
        ),
        "record_value": ParagraphStyle(
            "BushfireRecordValue",
            parent=base_styles["BodyText"],
            fontName=font_name,
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#18212f"),
        ),
    }


def _plain_markdown_text(text):
    return plain_markdown_text(text)


def _extract_meta_from_report(markdown_text):
    meta = extract_report_metadata(markdown_text)
    meta["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return meta


def _build_cover_story(meta, styles):
    return [
        Spacer(1, 2.2 * cm),
        Paragraph("BushfireReadyGPT", styles["cover_kicker"]),
        Paragraph(_format_inline_markdown(meta["title"]), styles["cover_title"]),
        Paragraph(DRAFT_NOTICE, styles["draft_banner"]),
        Paragraph(f"Location: {_escape_text(meta['location'])}", styles["cover_meta"]),
        Paragraph(f"Audience: {_escape_text(meta['audience'])}", styles["cover_meta"]),
        Paragraph(f"Generated: {meta['generated_at']}", styles["cover_meta"]),
        Spacer(1, 1.2 * cm),
        Paragraph("Australian Bushfire Preparedness Report", styles["cover_kicker"]),
        Paragraph(
            DRAFT_NOTICE_DETAIL,
            styles["cover_note"],
        ),
        PageBreak(),
    ]


def _flush_bullets(story, bullet_items, styles):
    if not bullet_items:
        return
    for item in bullet_items:
        story.append(Paragraph(f"- {_format_inline_markdown(item)}", styles["bullet"]))
    story.append(Spacer(1, 0.08 * cm))
    bullet_items.clear()


def _append_table(story, table_lines, styles):
    raw_data = []
    for line in table_lines:
        if is_markdown_table_separator(line):
            continue
        cells = parse_markdown_table_row(line)
        if cells is not None:
            raw_data.append(cells)
    if not raw_data:
        return
    column_count = max(len(row) for row in raw_data)
    has_oversized_cell = any(len(cell) > COMPACT_TABLE_CELL_CHARACTER_LIMIT for row in raw_data[1:] for cell in row)
    if column_count > 4 or has_oversized_cell:
        _append_record_tables(story, raw_data, styles)
        return

    data = [[Paragraph(_format_inline_markdown(cell), styles["body"]) for cell in row] for row in raw_data]
    column_widths = {
        1: [16.9 * cm],
        2: [5.0 * cm, 11.9 * cm],
        3: [5.0 * cm, 5.2 * cm, 6.7 * cm],
        4: [3.2 * cm, 4.5 * cm, 4.7 * cm, 4.5 * cm],
    }
    table = Table(
        data,
        colWidths=column_widths[column_count],
        repeatRows=1,
        hAlign="LEFT",
        splitByRow=1,
        splitInRow=0,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f6f8fb")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#18212f")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d0d5dd")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.16 * cm))


def _append_record_tables(story, data, styles):
    headers = data[0]
    for record_index, row in enumerate(data[1:], start=1):
        record_data = []
        for column_index, header in enumerate(headers):
            value = row[column_index] if column_index < len(row) else ""
            record_data.append(
                [
                    Paragraph(f"<b>{_format_inline_markdown(header)}</b>", styles["record_label"]),
                    Paragraph(_format_inline_markdown(value), styles["record_value"]),
                ]
            )
        table = Table(
            record_data,
            colWidths=[4.1 * cm, 12.8 * cm],
            hAlign="LEFT",
            splitByRow=1,
            splitInRow=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f6f8fb")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d0d5dd")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(Paragraph(f"Record {record_index}", styles["record_heading"]))
        story.append(table)
        story.append(Spacer(1, 0.1 * cm))


def _markdown_to_story(markdown_text, styles):
    meta = _extract_meta_from_report(markdown_text)
    story = _build_cover_story(meta, styles)
    bullet_items = []

    story.append(Paragraph(_format_inline_markdown(meta["title"]), styles["title"]))
    story.append(
        Paragraph(
            f"Generated by BushfireReadyGPT | {meta['generated_at']}",
            styles["meta"],
        )
    )

    lines = markdown_text.splitlines()
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        line = raw_line.strip()
        if not line:
            _flush_bullets(story, bullet_items, styles)
            story.append(Spacer(1, 0.08 * cm))
            index += 1
            continue

        if is_markdown_table_row(line):
            _flush_bullets(story, bullet_items, styles)
            table_lines = []
            while index < len(lines) and is_markdown_table_row(lines[index].strip()):
                table_lines.append(lines[index].strip())
                index += 1
            _append_table(story, table_lines, styles)
            continue
        elif line.startswith("### "):
            _flush_bullets(story, bullet_items, styles)
            story.append(Paragraph(_format_inline_markdown(line[4:]), styles["h2"]))
        elif line.startswith("## "):
            _flush_bullets(story, bullet_items, styles)
            heading = line[3:]
            if heading == "Human Review Sign-off":
                story.append(PageBreak())
            story.append(Paragraph(_format_inline_markdown(heading), styles["h1"]))
        elif line.startswith("# "):
            _flush_bullets(story, bullet_items, styles)
            story.append(Paragraph(_format_inline_markdown(line[2:]), styles["title"]))
        elif line.startswith(("- ", "* ")):
            bullet_items.append(line[2:])
        elif re.match(r"^\d+\.\s+", line):
            _flush_bullets(story, bullet_items, styles)
            story.append(Paragraph(_format_inline_markdown(line), styles["body"]))
        else:
            _flush_bullets(story, bullet_items, styles)
            story.append(Paragraph(_format_inline_markdown(line), styles["body"]))
        index += 1

    _flush_bullets(story, bullet_items, styles)
    return story


def _draw_header_footer(canvas, document):
    canvas.saveState()
    width, height = A4

    canvas.setStrokeColor(colors.HexColor("#ead8cf"))
    canvas.setLineWidth(0.4)
    canvas.line(document.leftMargin, height - 1.15 * cm, width - document.rightMargin, height - 1.15 * cm)
    canvas.line(document.leftMargin, 1.05 * cm, width - document.rightMargin, 1.05 * cm)

    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawString(document.leftMargin, height - 0.85 * cm, "BushfireReadyGPT")
    canvas.drawRightString(width - document.rightMargin, 0.65 * cm, f"Page {document.page}")
    canvas.drawString(
        document.leftMargin, 0.65 * cm, "Planning support only. Verify official emergency sources before acting."
    )
    canvas.restoreState()


def create_report_pdf(markdown_text):
    font_name = _register_pdf_font()
    styles = _build_styles(font_name)
    buffer = BytesIO()
    left_margin = 1.6 * cm
    right_margin = 1.6 * cm
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=right_margin,
        leftMargin=left_margin,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
        title="BushfireReadyGPT Report",
        author="BushfireReadyGPT",
    )
    document.build(
        _markdown_to_story(markdown_text, styles),
        onFirstPage=_draw_header_footer,
        onLaterPages=_draw_header_footer,
    )
    buffer.seek(0)
    return buffer.getvalue()
