from io import BytesIO

from docx import Document
from pypdf import PdfReader

from src.docx_export import create_report_docx
from src.markdown_tables import (
    is_markdown_table_row,
    is_markdown_table_separator,
    parse_markdown_table_row,
)
from src.pdf_export import create_report_pdf


def test_parse_ordinary_table_row():
    assert parse_markdown_table_row("| Source | Status |") == ["Source", "Status"]
    assert is_markdown_table_row("  | Source | Status |  ")


def test_parse_escaped_pipe_as_cell_content():
    assert parse_markdown_table_row(r"| Fire district \| brigade | Ready |") == [
        "Fire district | brigade",
        "Ready",
    ]


def test_parse_preserves_empty_cells():
    assert parse_markdown_table_row("| Alpha || Charlie |") == ["Alpha", "", "Charlie"]
    assert parse_markdown_table_row("| | Bravo | |") == ["", "Bravo", ""]


def test_alignment_separator_rows_are_identified():
    assert is_markdown_table_separator("| :--- | ---: | :---: |")
    assert is_markdown_table_separator("| : - - - | - - - : |")
    assert not is_markdown_table_separator("| Header | Value |")
    assert not is_markdown_table_separator("| --- | |")


def test_non_table_text_is_rejected():
    assert parse_markdown_table_row("Alpha | Bravo") is None
    assert parse_markdown_table_row(r"| Alpha | Bravo \|") is None
    assert not is_markdown_table_row("| missing closing delimiter")


def test_pdf_and_docx_exports_share_escaped_pipe_and_empty_cell_semantics():
    report = r"""# Table parser regression

| Label | Empty | Status |
| :--- | ---: | :---: |
| Fire district \| brigade || Ready |
"""

    document = Document(BytesIO(create_report_docx(report)))
    document_rows = [[cell.text for cell in row.cells] for table in document.tables for row in table.rows]
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(create_report_pdf(report))).pages)

    assert ["Fire district | brigade", "", "Ready"] in document_rows
    assert "Fire district | brigade" in pdf_text
    assert "Ready" in pdf_text
