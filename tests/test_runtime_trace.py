import json

import pytest

from src.agents import run_analysis_pipeline
from src.runtime_trace import RuntimeTrace, TracePrivacyError, load_trace_summary


def test_runtime_trace_records_only_allowlisted_operational_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_TRACE_DIR", str(tmp_path))
    monkeypatch.setenv("BUSHFIRE_TRACE_ENABLED", "true")
    with RuntimeTrace("report.generate", report_source="generated", model_boundary="local_loopback") as trace:
        with trace.stage("model_generation", attempt=1, prompt_characters=120) as stage:
            stage.add_metrics(response_characters=250)
        trace.add_metrics(
            generation_attempts=1,
            repair_required=False,
            grounding_status="pass",
            support_rate=1.0,
        )
        trace.set_outcome("success")

    payload = json.loads(next(tmp_path.glob("trace_*.json")).read_text(encoding="utf-8"))

    assert payload["schema"] == "bushfire-runtime-trace-v1"
    assert payload["status"] == "success"
    assert payload["privacy"]["content_stored"] is False
    assert payload["stages"][0]["metrics"] == {
        "attempt": 1,
        "prompt_characters": 120,
        "response_characters": 250,
    }
    rendered = json.dumps(payload)
    assert "prompt text" not in rendered
    assert "report body" not in rendered


def test_runtime_trace_rejects_free_text_and_unknown_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_TRACE_DIR", str(tmp_path))
    monkeypatch.setenv("BUSHFIRE_TRACE_ENABLED", "true")

    with pytest.raises(TracePrivacyError):
        RuntimeTrace("report.generate", location="Cairns")

    with RuntimeTrace("report.generate") as trace:
        with pytest.raises(TracePrivacyError):
            trace.add_metrics(error_code="contains a user-facing error message")


def test_runtime_trace_captures_safe_error_code_and_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_TRACE_DIR", str(tmp_path))
    monkeypatch.setenv("BUSHFIRE_TRACE_ENABLED", "true")
    with pytest.raises(RuntimeError):
        with RuntimeTrace("report.generate") as trace:
            with trace.stage("analysis_pipeline" if False else "data_integrity"):
                raise RuntimeError("sensitive internal detail")

    summary = load_trace_summary(trace_dir=tmp_path)

    assert summary["traces"] == 1
    assert summary["success_rate"] == 0.0
    assert summary["failure_codes"] == {"runtime_error": 1}
    assert summary["stage_errors"] == {"data_integrity:runtime_error": 1}
    assert "sensitive internal detail" not in next(tmp_path.glob("trace_*.json")).read_text(encoding="utf-8")


def test_runtime_trace_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_TRACE_DIR", str(tmp_path))
    monkeypatch.setenv("BUSHFIRE_TRACE_ENABLED", "false")

    with RuntimeTrace("report.revise"):
        pass

    assert list(tmp_path.iterdir()) == []


def test_trace_summary_skips_malformed_files(tmp_path):
    (tmp_path / "trace_broken.json").write_text('{"schema": "wrong"}', encoding="utf-8")

    summary = load_trace_summary(trace_dir=tmp_path)

    assert summary["traces"] == 0
    assert summary["invalid_files"] == 1


def test_analysis_pipeline_emits_content_free_agent_stage_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_TRACE_DIR", str(tmp_path))
    monkeypatch.setenv("BUSHFIRE_TRACE_ENABLED", "true")

    with RuntimeTrace("report.generate"):
        run_analysis_pipeline(
            "Cairns, Queensland",
            "school staff and students",
            "School Preparedness",
            ["Evacuation"],
            "7-day action plan",
            "private scenario wording",
        )

    rendered = next(tmp_path.glob("trace_*.json")).read_text(encoding="utf-8")
    payload = json.loads(rendered)
    stages = {stage["name"] for stage in payload["stages"]}

    assert {
        "profile_agent",
        "australian_data_agent",
        "community_vulnerability_agent",
        "official_knowledge_agent",
        "risk_context_agent",
        "planner_agent",
        "report_agent",
        "evidence_confidence",
    }.issubset(stages)
    assert "Cairns" not in rendered
    assert "school staff" not in rendered
    assert "private scenario wording" not in rendered
