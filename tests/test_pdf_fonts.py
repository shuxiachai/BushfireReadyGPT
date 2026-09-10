from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from src import pdf_export


def _record_registration(monkeypatch, available, rejected=()):
    attempts = []
    families = []
    monkeypatch.setattr(pdf_export.os.path, "isfile", lambda path: path in available)

    def load_font(name, path):
        attempts.append(path)
        if path in rejected:
            raise ValueError("font uses unsupported outlines")
        return (name, path)

    monkeypatch.setattr(pdf_export, "TTFont", load_font)
    monkeypatch.setattr(pdf_export.pdfmetrics, "registerFont", lambda _font: None)
    monkeypatch.setattr(pdf_export.pdfmetrics, "registerFontFamily", lambda *args, **kwargs: families.append(kwargs))
    return attempts, families


def test_configured_font_takes_precedence_and_registers_bold_family(monkeypatch):
    selected = "/app/fonts/custom.ttf"
    monkeypatch.setenv("BUSHFIRE_PDF_FONT_PATH", selected)
    attempts, families = _record_registration(monkeypatch, {selected, "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"})

    assert pdf_export._register_pdf_font() == pdf_export.FONT_NAME
    assert attempts == [selected]
    assert families[0]["bold"] == pdf_export.FONT_NAME


def test_linux_cjk_font_is_found_without_windows_fonts(monkeypatch):
    monkeypatch.delenv("BUSHFIRE_PDF_FONT_PATH", raising=False)
    selected = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
    attempts, _families = _record_registration(monkeypatch, {selected})

    assert pdf_export._register_pdf_font() == pdf_export.FONT_NAME
    assert attempts == [selected]


def test_unsupported_configured_font_falls_back_to_usable_system_font(monkeypatch):
    unsupported = "/app/fonts/unsupported.otf"
    selected = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
    monkeypatch.setenv("BUSHFIRE_PDF_FONT_PATH", unsupported)
    attempts, _families = _record_registration(monkeypatch, {unsupported, selected}, {unsupported})

    assert pdf_export._register_pdf_font() == pdf_export.FONT_NAME
    assert attempts == [unsupported, selected]


def test_missing_fonts_preserve_english_pdf_fallback(monkeypatch):
    monkeypatch.delenv("BUSHFIRE_PDF_FONT_PATH", raising=False)
    attempts, families = _record_registration(monkeypatch, set())

    assert pdf_export._register_pdf_font() == "Helvetica"
    assert not attempts
    assert not families


def test_installed_cjk_font_preserves_chinese_reviewer_in_pdf(monkeypatch):
    candidates = (
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
    )
    selected = next((path for path in candidates if path.is_file()), None)
    if selected is None:
        pytest.skip("requires an installed CJK TrueType font")
    monkeypatch.setenv("BUSHFIRE_PDF_FONT_PATH", str(selected))

    pdf = pdf_export.create_report_pdf("# Preparedness review\n\n**Reviewer: 柴靖博**\n\n学校防火准备。")
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)

    assert "柴靖博" in text
    assert "学校防火准备" in text
    face = pdf_export.pdfmetrics.getFont(pdf_export.FONT_NAME).face
    assert all(face.charToGlyph.get(ord(character), 0) != 0 for character in "柴靖博学校防火准备")
