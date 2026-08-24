import inspect
from pathlib import Path

import pytest

from src import export_content, markdown_tables
from src.docx_export import create_report_docx
from src.pdf_export import create_report_pdf
from src.ui.artifact_cache import _renderer_identity, get_report_artifact


def test_report_artifact_is_reused_for_identical_text_and_type():
    cache = {}
    calls = []

    def build(text):
        calls.append(text)
        return text.encode("utf-8")

    first = get_report_artifact("private report", "pdf", build, cache=cache)
    second = get_report_artifact("private report", "pdf", build, cache=cache)

    assert first == second == b"private report"
    assert calls == ["private report"]


def test_report_or_artifact_type_change_invalidates_only_the_relevant_entry():
    cache = {}
    calls = []

    def build(text):
        calls.append(text)
        return text.encode("utf-8")

    get_report_artifact("v1", "pdf", build, cache=cache)
    get_report_artifact("v1", "docx", build, cache=cache)
    get_report_artifact("v2", "pdf", build, cache=cache)

    assert calls == ["v1", "v1", "v2"]
    assert set(cache) == {"pdf", "docx"}

    def updated_build(text):
        calls.append(f"updated:{text}")
        return f"updated:{text}".encode()

    assert get_report_artifact("v2", "pdf", updated_build, cache=cache) == b"updated:v2"
    assert calls[-1] == "updated:v2"


def test_explicit_renderer_version_invalidates_cached_content():
    cache = {}
    calls = []

    def build(text):
        calls.append(text)
        return text.encode()

    build.__artifact_cache_version__ = "renderer-v1"
    get_report_artifact("report", "pdf", build, cache=cache)
    build.__artifact_cache_version__ = "renderer-v2"
    get_report_artifact("report", "pdf", build, cache=cache)

    assert calls == ["report", "report"]


@pytest.mark.parametrize(
    ("builder", "dependency"),
    [
        (create_report_pdf, export_content.extract_report_metadata),
        (create_report_pdf, markdown_tables.parse_markdown_table_row),
        (create_report_docx, export_content.extract_report_metadata),
        (create_report_docx, markdown_tables.parse_markdown_table_row),
    ],
)
def test_renderer_identity_tracks_transitive_source_dependencies(monkeypatch, builder, dependency):
    dependency_path = Path(inspect.getsourcefile(dependency)).resolve()
    original_read_bytes = Path.read_bytes
    original_identity = _renderer_identity(builder)

    def read_bytes_with_dependency_revision(path):
        content = original_read_bytes(path)
        if path.resolve() == dependency_path:
            return content + b"\n# simulated dependency revision"
        return content

    monkeypatch.setattr(Path, "read_bytes", read_bytes_with_dependency_revision)

    assert _renderer_identity(builder) != original_identity


@pytest.mark.parametrize(
    ("report", "kind", "builder", "error"),
    [
        ("", "pdf", lambda _text: b"pdf", ValueError),
        ("report", "", lambda _text: b"pdf", ValueError),
        ("report", "pdf", None, TypeError),
        ("report", "pdf", lambda _text: "not-bytes", TypeError),
    ],
)
def test_report_artifact_cache_rejects_invalid_inputs(report, kind, builder, error):
    with pytest.raises(error):
        get_report_artifact(report, kind, builder, cache={})
