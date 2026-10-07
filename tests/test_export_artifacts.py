"""Offline exporter regressions use synthetic text and in-memory documents only."""

import copy
import hashlib
import json
import time
from datetime import datetime, timezone
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from pypdf import PdfReader

from src import audit, docx_export, export_artifacts, export_package, pdf_export
from src.export_register import REGISTER_SNAPSHOT_FILES
from src.governance import DRAFT_STATUS, build_review_checklist_snapshot
from src.report_generation_quality import evaluate_governed_report
from src.report_template import append_evidence_tables, append_human_signoff, apply_governance_notice
from tests.test_report_content_contract import _valid_report

SOURCE_TIME = "2026-10-07T04:46:06+00:00"
REPORT = "# Synthetic export identity\n\nLocation: Test district\n\nPreparedness review marker."


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _record_hash(record):
    return _digest(json.dumps({k: v for k, v in record.items() if k != "record_hash"}, sort_keys=True))


def _captured_chain(text=REPORT, *, source_time=SOURCE_TIME, report_id="synthetic-1", version=1, review=None):
    # This fixture represents only the binding fields returned by the separately
    # tested authoritative audit capture. It does not pretend to be a full audit.
    root = {
        "event_type": "report.created",
        "audit_id": f"root-{report_id}",
        "report_id": report_id,
        "report_version": version,
        "recorded_at": source_time,
        "report_content": {"sha256": _digest(text)},
    }
    root["record_hash"] = _record_hash(root)
    chain = [{"record": root}]
    if review is not None:
        latest = {
            **root,
            "event_type": "review.recorded",
            "audit_id": f"review-{report_id}",
            "recorded_at": "2026-10-08T09:30:00+00:00",
            "report_content": {"sha256": _digest(review)},
        }
        latest["record_hash"] = _record_hash(latest)
        chain.append({"record": latest})
    return chain


def _builders():
    calls = []

    def pdf(text, *, generated_at):
        calls.append(("pdf", text, generated_at))
        return f"pdf:{generated_at}:{text}".encode()

    def docx(text, *, generated_at):
        calls.append(("docx", text, generated_at))
        return f"docx:{generated_at}:{text}".encode()

    return pdf, docx, calls


def test_bound_renderers_freeze_visible_dates_pdf_metadata_and_docx_members(monkeypatch):
    monkeypatch.setattr(pdf_export, "_register_pdf_font", lambda: "Helvetica")
    clock = [datetime(2026, 10, 7, 4, 46, 59, tzinfo=timezone.utc).timestamp()]
    monkeypatch.setattr(time, "time", lambda: clock[0])

    class ChangingClock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime.fromtimestamp(clock[0], timezone.utc)
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

    monkeypatch.setattr(pdf_export, "datetime", ChangingClock)
    monkeypatch.setattr(docx_export, "datetime", ChangingClock)
    first_pdf = pdf_export.create_report_pdf(REPORT, generated_at=SOURCE_TIME)
    first_docx = docx_export.create_report_docx(REPORT, generated_at=SOURCE_TIME)
    clock[0] += 25 * 60 * 60
    assert pdf_export.create_report_pdf(REPORT, generated_at=SOURCE_TIME) == first_pdf
    assert docx_export.create_report_docx(REPORT, generated_at=SOURCE_TIME) == first_docx

    pdf = PdfReader(BytesIO(first_pdf))
    assert pdf.metadata.creation_date == datetime.fromisoformat(SOURCE_TIME)
    assert pdf.metadata.modification_date == datetime.fromisoformat(SOURCE_TIME)
    assert "2026-10-07 04:46 UTC" in pdf.pages[0].extract_text()
    assert "2026-10-07 04:46 UTC" in "\n".join(p.text for p in Document(BytesIO(first_docx)).paragraphs)
    with ZipFile(BytesIO(first_docx)) as archive:
        assert {entry.date_time for entry in archive.infolist()} == {(2026, 10, 7, 4, 46, 6)}
        core = archive.read("docProps/core.xml")
    assert core.count(b"2026-10-07T04:46:06Z") == 2


@pytest.mark.parametrize("first_consumer", ["standalone", "package"])
def test_standalone_and_package_resolvers_share_exact_bound_bytes(monkeypatch, first_consumer):
    chain = _captured_chain()
    cache = {}
    pdf, docx, calls = _builders()
    monkeypatch.setattr(audit, "capture_current_audit_chain", lambda _path: copy.deepcopy(chain))
    monkeypatch.setattr(pdf_export, "create_report_pdf", pdf)
    monkeypatch.setattr(docx_export, "create_report_docx", docx)

    def standalone():
        return export_artifacts.get_report_artifacts(REPORT, audit_path="verified-fixture", cache=cache)

    def package():
        return export_artifacts._artifacts_for_captured_chain(REPORT, chain, cache=cache)

    consumers = [standalone, package] if first_consumer == "standalone" else [package, standalone]
    first, second = [consumer() for consumer in consumers]
    assert first == second
    assert len(calls) == 2
    assert {call[2] for call in calls} == {SOURCE_TIME}


def test_restored_report_rebuilds_identical_artifacts_from_audit_not_session_clock(monkeypatch):
    monkeypatch.setattr(pdf_export, "_register_pdf_font", lambda: "Helvetica")
    chain = _captured_chain()
    monkeypatch.setattr(audit, "capture_current_audit_chain", lambda _path: copy.deepcopy(chain))
    initial = export_artifacts.get_report_artifacts(REPORT, audit_path="verified-fixture", cache={})
    restored = export_artifacts.get_report_artifacts(REPORT, audit_path="verified-fixture", cache={})
    assert initial == restored


def test_review_and_new_report_invalidate_cache_while_review_retains_root_clock():
    pdf, docx, calls = _builders()
    cache = {}

    def build(text, chain):
        return export_artifacts._artifacts_for_captured_chain(
            text, chain, cache=cache, pdf_builder=pdf, docx_builder=docx
        )

    original = build(REPORT, _captured_chain())
    reviewed_text = REPORT + "\n\nReviewer: Synthetic reviewer"
    reviewed = build(reviewed_text, _captured_chain(review=reviewed_text))
    assert original != reviewed
    assert {call[2] for call in calls} == {SOURCE_TIME}
    new_time = "2026-10-09T01:02:03+00:00"
    next_version = build(REPORT, _captured_chain(source_time=new_time, report_id="synthetic-2", version=2))
    assert next_version != original
    assert calls[-1][2] == new_time


def test_cache_does_not_supply_authority_for_a_changed_audit_head(monkeypatch):
    chain = _captured_chain()
    pdf, docx, calls = _builders()
    monkeypatch.setattr(pdf_export, "create_report_pdf", pdf)
    monkeypatch.setattr(docx_export, "create_report_docx", docx)
    captures = []

    def capture(path):
        captures.append(path)
        return copy.deepcopy(chain)

    monkeypatch.setattr(audit, "capture_current_audit_chain", capture)
    cache = {}
    export_artifacts.get_report_artifacts(REPORT, audit_path="current-head", cache=cache)
    chain = _captured_chain(REPORT + " changed")
    with pytest.raises(audit.AuditIntegrityError):
        export_artifacts.get_report_artifacts(REPORT, audit_path="current-head", cache=cache)
    assert len(captures) == 2
    assert len(calls) == 2


@pytest.mark.parametrize("tamper", ["payload", "untrusted_mapping"])
def test_tampered_or_external_cache_entries_are_rebuilt(tamper):
    pdf, docx, calls = _builders()
    cache = {}
    chain = _captured_chain()

    def build():
        return export_artifacts._artifacts_for_captured_chain(
            REPORT, chain, cache=cache, pdf_builder=pdf, docx_builder=docx
        )

    first = build()
    key, entry = next(iter(cache.items()))
    if tamper == "payload":
        object.__setattr__(entry, "pdf", b"tampered payload")
    else:
        cache[key] = {
            "binding": entry.binding,
            "pdf": b"external replacement",
            "docx": entry.docx,
            "pdf_sha256": hashlib.sha256(b"external replacement").hexdigest(),
            "docx_sha256": entry.docx_sha256,
        }
    assert build() == first
    assert len(calls) == 4


@pytest.mark.parametrize("change", ["renderer", "policy"])
def test_renderer_or_export_policy_change_rebuilds_cached_bundle(monkeypatch, change):
    pdf, docx, calls = _builders()
    cache = {}
    chain = _captured_chain()

    def build():
        return export_artifacts._artifacts_for_captured_chain(
            REPORT, chain, cache=cache, pdf_builder=pdf, docx_builder=docx
        )

    build()
    if change == "renderer":
        pdf.__artifact_cache_version__ = "changed-renderer"
    else:
        monkeypatch.setattr(export_artifacts, "EXPORT_ARTIFACT_POLICY", "changed-policy")
    build()
    assert len(calls) == 4


@pytest.mark.parametrize("value", [None, "", "not-a-date", "2026-10-07T04:46:06"])
def test_governed_clock_rejects_missing_or_naive_source_timestamp(value):
    chain = _captured_chain(source_time=value)
    pdf, docx, calls = _builders()
    with pytest.raises(audit.AuditIntegrityError):
        export_artifacts._artifacts_for_captured_chain(REPORT, chain, cache={}, pdf_builder=pdf, docx_builder=docx)
    assert calls == []


def test_bound_pdf_is_independent_of_source_date_epoch_and_has_context_specific_id(monkeypatch):
    monkeypatch.setattr(pdf_export, "_register_pdf_font", lambda: "Helvetica")
    rendered = []
    for epoch in (None, "946684800", "1791349200"):
        if epoch is None:
            monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
        else:
            monkeypatch.setenv("SOURCE_DATE_EPOCH", epoch)
        rendered.append(pdf_export.create_report_pdf(REPORT, generated_at=SOURCE_TIME))
    assert rendered[0] == rendered[1] == rendered[2]
    original_id = PdfReader(BytesIO(rendered[0])).trailer["/ID"]
    for text, clock in ((REPORT + " changed", SOURCE_TIME), (REPORT, "2026-10-08T04:46:06Z")):
        changed = pdf_export.create_report_pdf(text, generated_at=clock)
        assert PdfReader(BytesIO(changed)).trailer["/ID"] != original_id


def test_missing_reportlab_identifier_hook_fails_explicitly():
    class UnsupportedCanvas:
        _doc = object()

    with pytest.raises(RuntimeError, match="identifier hook"):
        pdf_export._bind_audited_pdf_metadata(UnsupportedCanvas(), REPORT, datetime.fromisoformat(SOURCE_TIME))


def test_review_audit_change_with_unchanged_text_still_invalidates_cache():
    pdf, docx, calls = _builders()
    cache = {}
    for chain in (_captured_chain(), _captured_chain(review=REPORT)):
        export_artifacts._artifacts_for_captured_chain(REPORT, chain, cache=cache, pdf_builder=pdf, docx_builder=docx)
    assert len(calls) == 4


@pytest.fixture
def governed_case(tmp_path, monkeypatch):
    """Real append-only audit and current quality gate; no model or policy mocks."""
    monkeypatch.setenv("BUSHFIRE_AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.setattr(audit, "_utc_now", lambda: SOURCE_TIME)
    narrative, analysis = _valid_report()
    review = audit.canonical_review_record(
        {
            "approval_status": DRAFT_STATUS,
            "review_checklist": build_review_checklist_snapshot(),
        }
    )
    text = append_human_signoff(append_evidence_tables(apply_governance_notice(narrative), analysis), review)
    assert evaluate_governed_report(text, analysis)["approval_gate"]["passed"] is True
    context = {"report_id": "synthetic-export-integration", "report_version": 1, "report_status": DRAFT_STATUS}
    registers = {path: "Synthetic frozen register\n" for path in REGISTER_SNAPSHOT_FILES}
    payload = {
        "report_id": context["report_id"],
        "report_version": 1,
        "report_text": text,
        "analysis": analysis,
        "human_review": review,
        "report_status": DRAFT_STATUS,
        "package_context": context,
        "export_register_snapshot": registers,
    }
    path = audit.save_report_audit(payload)
    return {
        "report_text": text,
        "audit_path": path,
        "review_record": review,
        "package_context": context,
        "register_snapshot": registers,
        "analysis": analysis,
    }


def _package_documents(case, cache):
    package = export_package.create_pilot_export_package(**case, artifact_cache=cache)
    with ZipFile(BytesIO(package["content"])) as archive:
        documents = {
            suffix: archive.read(next(name for name in archive.namelist() if name.endswith("." + suffix)))
            for suffix in ("md", "pdf", "docx")
        }
    assert package["manifest"]["governed_quality"]["approval_gate_passed"] is True
    return documents


@pytest.mark.parametrize("first_consumer", ["standalone", "package"])
def test_real_audit_package_and_standalone_remain_identical_across_minutes_and_restore(
    governed_case, monkeypatch, first_consumer
):
    monkeypatch.setattr(pdf_export, "_register_pdf_font", lambda: "Helvetica")
    clock = [datetime(2026, 10, 7, 4, 46, 59)]

    class ChangingClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0] if tz is None else clock[0].replace(tzinfo=timezone.utc).astimezone(tz)

    for module in (pdf_export, docx_export, export_package):
        monkeypatch.setattr(module, "datetime", ChangingClock)
    cache = {}

    def standalone(cache):
        return {
            "md": governed_case["report_text"].encode(),
            **export_artifacts.get_report_artifacts(
                governed_case["report_text"], audit_path=governed_case["audit_path"], cache=cache
            ),
        }

    consumers = [standalone, lambda cache: _package_documents(governed_case, cache)]
    if first_consumer == "package":
        consumers.reverse()
    first = consumers[0](cache)
    clock[0] = datetime(2026, 10, 8, 9, 17, 31)
    assert consumers[1](cache) == first
    assert standalone({}) == first
    assert _package_documents(governed_case, {}) == first


def test_real_review_invalidates_bound_bytes_preserves_source_clock_and_rejects_stale_head(governed_case, monkeypatch):
    monkeypatch.setattr(pdf_export, "_register_pdf_font", lambda: "Helvetica")
    cache = {}
    original = _package_documents(governed_case, cache)
    original_path = governed_case["audit_path"]
    review = {**governed_case["review_record"], "reviewer_name": "Synthetic reviewer"}
    text = append_human_signoff(governed_case["report_text"], review)
    monkeypatch.setattr(audit, "_utc_now", lambda: "2026-10-08T09:30:00+00:00")
    reviewed_path = audit.append_audit_event(
        original_path,
        "review.recorded",
        {
            "report_text": text,
            "human_review": review,
            "report_status": DRAFT_STATUS,
            "package_context": governed_case["package_context"],
            "analysis": governed_case["analysis"],
        },
    )
    reviewed_case = {**governed_case, "report_text": text, "review_record": review, "audit_path": reviewed_path}
    reviewed = _package_documents(reviewed_case, cache)
    assert all(reviewed[k] != original[k] for k in ("md", "pdf", "docx"))
    standalone = export_artifacts.get_report_artifacts(text, audit_path=reviewed_path, cache=cache)
    assert {k: reviewed[k] for k in ("pdf", "docx")} == standalone
    assert PdfReader(BytesIO(reviewed["pdf"])).metadata.creation_date == datetime.fromisoformat(SOURCE_TIME)
    for stale in (
        lambda: export_artifacts.get_report_artifacts(
            governed_case["report_text"], audit_path=original_path, cache=cache
        ),
        lambda: _package_documents(governed_case, cache),
    ):
        with pytest.raises(audit.AuditIntegrityError):
            stale()


def test_real_package_validates_context_even_after_artifact_cache_hit(governed_case, monkeypatch):
    monkeypatch.setattr(pdf_export, "_register_pdf_font", lambda: "Helvetica")
    cache = {}
    _package_documents(governed_case, cache)
    changed = {**governed_case, "package_context": {**governed_case["package_context"], "location": "Different"}}
    with pytest.raises(audit.AuditIntegrityError, match="context"):
        _package_documents(changed, cache)
