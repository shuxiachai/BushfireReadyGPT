import json
from types import SimpleNamespace

import pytest

from src import audit, report_workflow
from src.agents.official_knowledge_agent import OfficialKnowledgeAgent
from src.export_register import build_export_register_snapshot
from src.model_response import ModelResponseError
from src.rag.errors import RagError
from src.report_template import append_evidence_tables, append_human_signoff
from src.runtime_trace import load_trace_summary


class _SessionState(dict):
    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value


def _analysis(knowledge):
    return {
        "knowledge": knowledge,
        "prompt_context": "Verified planning context",
        "evidence_confidence": [],
        "data": {"sources": [{"id": "one", "name": "Official One"}, {"id": "two", "name": "Official Two"}]},
    }


@pytest.fixture
def workflow(monkeypatch):
    calls, finalizations = [], []

    def generate(prompt):
        calls.append(prompt)
        return "# Short unsafe draft\n\nThis plan guarantees safety."

    state = _SessionState(model_client=SimpleNamespace(generate=generate))
    monkeypatch.setattr(report_workflow, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(report_workflow, "is_cloud_deployment", lambda: True)
    monkeypatch.setattr(report_workflow, "is_access_authorized", lambda _: True)
    monkeypatch.setattr(report_workflow, "MODEL_ENDPOINT_IS_LOCAL", True)
    monkeypatch.setattr(report_workflow, "validate_current_report_form", lambda: None)
    monkeypatch.setattr(
        report_workflow, "collect_report_inputs", lambda: {"location": "Cairns", "audience": "Residents"}
    )
    monkeypatch.setattr(report_workflow, "build_report_prompt", lambda *args, **kwargs: "Generate a governed draft.")

    def finalize(text, analysis, *_args, **_kwargs):
        finalizations.append(report_workflow.evaluate_governed_report(text, analysis))
        return text, None

    monkeypatch.setattr(report_workflow, "_finalize_report_version", finalize)
    return SimpleNamespace(state=state, calls=calls, finalizations=finalizations)


@pytest.mark.parametrize(
    "status", ["disabled", "not_installed", "not_built", "invalid", "unavailable", "error", "unknown"]
)
def test_cloud_stops_infrastructure_failures_before_model_or_finalization(status, workflow, monkeypatch):
    knowledge = {
        "status": status,
        "retrieved_chunks": [],
        "error": "Private server path: /data/private-index/model-cache",
        "error_code": "rag_embedding_invalid",
    }
    monkeypatch.setattr(report_workflow, "run_analysis_pipeline", lambda *args, **kwargs: _analysis(knowledge))
    response, error = report_workflow.generate_current_report(lambda: None)
    assert response is None
    assert "knowledge service is unavailable" in error
    assert "No report-model request was sent" in error
    assert "/data" not in error
    assert workflow.calls == []
    assert workflow.finalizations == []


@pytest.mark.parametrize("knowledge", [None, {}, [], {"status": []}, {"status": None}])
def test_cloud_missing_or_malformed_retrieval_status_fails_closed(knowledge, workflow, monkeypatch):
    monkeypatch.setattr(report_workflow, "run_analysis_pipeline", lambda *args, **kwargs: _analysis(knowledge))
    response, error = report_workflow.generate_current_report(lambda: None)
    assert response is None and error
    assert workflow.calls == []


def test_runtime_embedding_error_translated_by_knowledge_agent_still_blocks_cloud(workflow, monkeypatch):
    def broken_retrieve(*_args, **_kwargs):
        raise RagError("rag_embedding_unavailable", "Private cache location /data/embeddings no longer exists")

    knowledge = OfficialKnowledgeAgent(service=SimpleNamespace(retrieve=broken_retrieve)).run(
        {"state": "Queensland"}, "Council community preparedness", ["Evacuation"], "7-day action plan"
    )
    assert knowledge["status"] == "unavailable"
    monkeypatch.setattr(report_workflow, "run_analysis_pipeline", lambda *args, **kwargs: _analysis(knowledge))
    response, error = report_workflow.generate_current_report(lambda: None)
    assert response is None and "knowledge service" in error
    assert "/data" not in error
    assert not workflow.calls


@pytest.mark.parametrize("status", ["no_match", "out_of_scope"])
def test_valid_cloud_abstentions_keep_existing_repairs_and_safety_gate(status, workflow, monkeypatch):
    analysis = _analysis({"status": status, "retrieved_chunks": []})
    monkeypatch.setattr(report_workflow, "run_analysis_pipeline", lambda *args, **kwargs: analysis)
    response, error = report_workflow.generate_current_report(lambda: None)
    assert response and error is None
    assert len(workflow.calls) == 3
    assert workflow.finalizations[0]["approval_gate"]["passed"] is False
    failures = workflow.finalizations[0]["approval_gate"]["blocking_failures"]
    assert any("absolute_safety_guarantee" in str(item) for item in failures)


@pytest.mark.parametrize("status", ["disabled", "not_built", "invalid", "unavailable"])
def test_local_application_keeps_documented_degraded_generation(status, workflow, monkeypatch):
    monkeypatch.setattr(report_workflow, "is_cloud_deployment", lambda: False)
    monkeypatch.setattr(
        report_workflow,
        "run_analysis_pipeline",
        lambda *args, **kwargs: _analysis({"status": status, "retrieved_chunks": []}),
    )
    response, error = report_workflow.generate_current_report(lambda: None)
    assert response and error is None
    assert len(workflow.calls) == 3


def _frozen_report(analysis, monkeypatch, tmp_path):
    snapshot = build_export_register_snapshot()
    record = {
        "id": "frozen-cloud-test",
        "version": 1,
        "text": "# Frozen report\n\nPreparedness planning content.",
        "inputs": {"report_status": "Draft - human review required"},
        "area_selection": None,
        "analysis": analysis,
        "model_context": {},
        "review_record": {"approval_status": "Draft - human review required"},
        "export_register_snapshot": snapshot,
    }
    record["text"] = append_human_signoff(append_evidence_tables(record["text"], analysis), record["review_record"])
    monkeypatch.setenv("BUSHFIRE_AUDIT_DIR", str(tmp_path))
    record["audit_path"] = audit.save_report_audit(
        {
            "report_id": record["id"],
            "report_version": record["version"],
            "report_text": record["text"],
            "inputs": record["inputs"],
            "area_selection": None,
            "analysis": analysis,
            "human_review": record["review_record"],
            "report_status": "Draft - human review required",
            "package_context": report_workflow._package_context_for_record(record),
            "export_register_snapshot": snapshot,
        }
    )
    audited = audit.load_and_verify_audit(record["audit_path"])
    record["quality"] = audited["quality"]
    record["generation_gate_blocked"] = audited["generation_gate_blocked"]
    assert report_workflow.verify_report_record_snapshot(record)
    return record


def test_cloud_rejects_revision_of_verified_but_degraded_frozen_evidence(workflow, monkeypatch, tmp_path):
    workflow.state.latest_report = _frozen_report(
        _analysis({"status": "unavailable", "retrieved_chunks": []}), monkeypatch, tmp_path
    )
    response, error = report_workflow.revise_current_report("Clarify the draft.", lambda: None)
    assert response is None
    assert "knowledge service" in error
    assert workflow.calls == []
    assert workflow.finalizations == []


@pytest.mark.parametrize("status", ["ready", "no_match", "out_of_scope"])
def test_valid_frozen_revision_does_not_depend_on_current_index(status, workflow, monkeypatch, tmp_path):
    workflow.state.latest_report = _frozen_report(
        _analysis({"status": status, "retrieved_chunks": []}), monkeypatch, tmp_path
    )

    def do_not_reretrieve(*_args, **_kwargs):
        raise AssertionError("A revision must preserve its authenticated frozen evidence instead of retrieving again.")

    monkeypatch.setattr(report_workflow, "run_analysis_pipeline", do_not_reretrieve)
    response, error = report_workflow.revise_current_report("Clarify the draft.", lambda: None)
    assert response and error is None
    assert len(workflow.calls) == 3
    assert workflow.finalizations[0]["approval_gate"]["passed"] is False


def test_expired_session_is_blocked_before_rag_analysis(workflow, monkeypatch):
    monkeypatch.setattr(report_workflow, "is_access_authorized", lambda _: False)

    def do_not_analyze(*_args, **_kwargs):
        raise AssertionError("Unauthenticated requests must not use embedding resources.")

    monkeypatch.setattr(report_workflow, "run_analysis_pipeline", do_not_analyze)
    response, error = report_workflow.generate_current_report(lambda: None)
    assert response is None and "Sign in again" in error
    assert workflow.calls == []


def test_revoked_external_acknowledgement_is_rechecked_before_a_repair(workflow, monkeypatch):
    monkeypatch.setattr(report_workflow, "MODEL_ENDPOINT_IS_LOCAL", False)
    monkeypatch.setattr(report_workflow, "EXTERNAL_MODEL_ALLOWED", True)
    workflow.state.external_model_acknowledged = True
    monkeypatch.setattr(
        report_workflow,
        "run_analysis_pipeline",
        lambda *args, **kwargs: _analysis({"status": "no_match", "retrieved_chunks": []}),
    )

    def revoke_after_first_response(prompt):
        workflow.calls.append(prompt)
        workflow.state.external_model_acknowledged = False
        return "# Incomplete draft requiring repair"

    workflow.state.model_client = SimpleNamespace(generate=revoke_after_first_response)
    response, error = report_workflow.generate_current_report(lambda: None)
    assert response is None and "browser session" in error
    assert len(workflow.calls) == 1
    assert not workflow.finalizations


@pytest.mark.parametrize("operation", ["generate", "revise"])
@pytest.mark.parametrize(
    ("failure_reason", "expected_attempts"),
    [("length", 3), ("incomplete_narrative", 3), ("content_filter", 1)],
)
def test_failed_model_attempts_remain_in_generation_and_revision_trace(
    workflow, monkeypatch, tmp_path, operation, failure_reason, expected_attempts
):
    trace_dir = tmp_path / "traces"
    monkeypatch.setenv("BUSHFIRE_TRACE_ENABLED", "true")
    monkeypatch.setenv("BUSHFIRE_TRACE_DIR", str(trace_dir))
    analysis = _analysis({"status": "ready", "retrieved_chunks": []})
    monkeypatch.setattr(report_workflow, "run_analysis_pipeline", lambda *args, **kwargs: analysis)

    def fail_generation(prompt):
        workflow.calls.append(prompt)
        raise ModelResponseError(failure_reason)

    workflow.state.model_client = SimpleNamespace(generate=fail_generation)
    if operation == "revise":
        previous = _frozen_report(analysis, monkeypatch, tmp_path / "audit")
        workflow.state.latest_report = previous
        response, error = report_workflow.revise_current_report("PRIVATE revision wording", lambda: None)
        assert workflow.state.latest_report is previous
    else:
        response, error = report_workflow.generate_current_report(lambda: None)

    assert response is None and error
    assert not workflow.finalizations
    assert len(workflow.calls) == expected_attempts
    trace_files = list(trace_dir.glob("trace_*.json"))
    assert len(trace_files) == 1
    rendered = trace_files[0].read_text(encoding="utf-8")
    trace = json.loads(rendered)
    assert trace["status"] == "failed"
    assert trace["operation"] == f"report.{operation}"
    assert trace["metrics"]["generation_attempts"] == expected_attempts
    assert trace["metrics"]["repair_required"] is (expected_attempts > 1)
    model_stages = [stage for stage in trace["stages"] if stage["name"] in {"model_generation", "model_repair"}]
    assert [stage["metrics"]["attempt"] for stage in model_stages] == list(range(1, expected_attempts + 1))
    assert all(stage["error_code"] == f"model_response_{failure_reason}" for stage in model_stages)
    assert "PRIVATE revision wording" not in rendered
    assert "Cairns" not in rendered
    assert "Verified planning context" not in rendered

    summary = load_trace_summary(trace_dir=trace_dir)
    assert summary["traces"] == 1
    assert summary["invalid_files"] == 0
    assert summary["success_rate"] == 0.0
    assert summary["repair_rate"] == (1.0 if expected_attempts > 1 else 0.0)
