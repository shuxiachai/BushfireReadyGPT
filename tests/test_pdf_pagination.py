"""Pagination regressions use original synthetic text, not deployment reports."""

from io import BytesIO

import pytest
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer

from src import pdf_export

SIGNOFF = """## Human Review Sign-off

This records human review only and is not official emergency advice.

| Field | Value |
| --- | --- |
| Review status | Draft - human review required |
| Reviewer name | Reviewer marker |
| Identity verification | Not technically verified by this prototype |

- [ ] Geography review marker.
- [ ] Source review marker.
- [ ] Final approval marker.
"""


@pytest.fixture(autouse=True)
def portable_font(monkeypatch):
    monkeypatch.setattr(pdf_export, "_register_pdf_font", lambda: "Helvetica")


def _page_texts(payload):
    return [page.extract_text() for page in PdfReader(BytesIO(payload)).pages]


def _build_story(story):
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
    )
    document.build(story)
    return _page_texts(buffer.getvalue())


def test_short_source_tail_and_signoff_share_the_same_page():
    markdown = "# Synthetic review report\n\n## Evidence\n\n- Final source note marker.\n\n" + SIGNOFF
    pages = _page_texts(pdf_export.create_report_pdf(markdown))
    # The cover remains separate, but a two-line evidence tail must not force
    # the small sign-off onto a third, otherwise unnecessary page.
    assert len(pages) == 2
    assert "Final source note marker" in pages[1]
    assert "Human Review Sign-off" in pages[1]
    assert "Final approval marker" in pages[1]
    assert pdf_export.DRAFT_NOTICE in pages[0]
    assert "Call 000 in a life-threatening emergency." in " ".join(pages[0].split())
    assert all("Planning support only." in page for page in pages)


def test_signoff_keeps_table_and_checklist_together_when_space_is_insufficient():
    styles = pdf_export._build_styles("Helvetica")
    signoff = pdf_export._markdown_to_story(SIGNOFF, styles)[-1]
    assert isinstance(signoff, KeepTogether)
    pages = _build_story([Paragraph("Preceding evidence marker", styles["body"]), Spacer(1, 590), signoff])
    assert len(pages) == 2
    assert "Preceding evidence marker" in pages[0]
    assert "Human Review Sign-off" not in pages[0]
    assert "Human Review Sign-off" in pages[1]
    assert "Review status" in pages[1]
    assert "Reviewer marker" in pages[1]
    assert "Final approval marker" in pages[1]


def test_signoff_can_follow_an_orphan_source_note_without_forced_break():
    styles = pdf_export._build_styles("Helvetica")
    signoff = pdf_export._markdown_to_story(SIGNOFF, styles)[-1]
    pages = _build_story(
        [
            Paragraph("Previous evidence page", styles["body"]),
            PageBreak(),
            Paragraph("Last source note continued from the preceding evidence list.", styles["bullet"]),
            signoff,
        ]
    )
    assert len(pages) == 2
    assert "Last source note" in pages[1]
    assert "Human Review Sign-off" in pages[1]
    assert "Final approval marker" in pages[1]


def test_oversized_signoff_splits_without_shrinking_or_losing_content():
    items = [
        f"- Review item {number:03}: synthetic reviewer detail for pagination verification." for number in range(90)
    ]
    markdown = "# Oversized review fixture\n\n" + SIGNOFF + "\n" + "\n".join(items)
    pages = _page_texts(pdf_export.create_report_pdf(markdown))
    assert len(pages) >= 3
    extracted = "\n".join(pages)
    for number in range(90):
        assert extracted.count(f"Review item {number:03}:") == 1
    assert extracted.count("Human Review Sign-off") == 1
    assert "Not technically verified by this prototype" in extracted
    styles = pdf_export._build_styles("Helvetica")
    assert styles["body"].fontSize == 10
    assert styles["bullet"].fontSize == 9.5
    assert styles["h1"].fontSize == 15


def test_later_sections_are_not_accidentally_attached_to_signoff():
    styles = pdf_export._build_styles("Helvetica")
    story = pdf_export._markdown_to_story(SIGNOFF + "\n## Separate appendix\n\nAppendix marker.\n", styles)
    review_index = next(index for index, item in enumerate(story) if isinstance(item, KeepTogether))
    group = story[review_index]
    assert group._content[0].getPlainText() == "Human Review Sign-off"
    assert story[review_index + 1].getPlainText() == "Separate appendix"
    assert all(not isinstance(item, PageBreak) for item in group._content)
    # Only the intentional cover boundary remains a hard page break.
    assert sum(isinstance(item, PageBreak) for item in story) == 1


def test_long_evidence_table_repeats_headers_and_preserves_all_rows_before_signoff():
    rows = [f"| Row {number:03} | Synthetic value {number:03} | Evidence note marker |" for number in range(85)]
    markdown = (
        "# Long evidence fixture\n\n## Evidence register\n\n"
        "| Evidence field | Value | Source note |\n| --- | --- | --- |\n" + "\n".join(rows) + "\n\n" + SIGNOFF
    )
    pages = _page_texts(pdf_export.create_report_pdf(markdown))
    extracted = "\n".join(pages)
    table_pages = [page for page in pages if "Evidence note marker" in page]
    assert len(table_pages) >= 3
    assert all("Evidence field" in page and "Source note" in page for page in table_pages)
    for number in range(85):
        assert extracted.count(f"Row {number:03}") == 1
    assert "Final approval marker" in pages[-1]


def test_blank_markdown_spacing_cannot_leave_table_title_at_previous_page_bottom():
    styles = pdf_export._build_styles("Helvetica")
    story = [
        Paragraph("Previous body marker", styles["body"]),
        Spacer(1, 650),
        Paragraph("Evidence table heading marker", styles["h2"]),
        Spacer(1, 0.08 * cm),
    ]
    pdf_export._append_table(
        story,
        ["| Column marker | Value |", "| --- | --- |", "| Row marker | " + "long synthetic cell " * 15 + " |"],
        styles,
    )
    pages = _build_story(pdf_export._keep_heading_spacing(story))
    assert len(pages) == 2
    assert "Evidence table heading marker" not in pages[0]
    assert "Evidence table heading marker" in pages[1]
    assert "Column marker" in pages[1]
    assert "Row marker" in pages[1]
