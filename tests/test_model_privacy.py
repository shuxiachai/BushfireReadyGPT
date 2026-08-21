from types import SimpleNamespace

from src import audit, report_workflow
from src.config import (
    is_loopback_model_endpoint,
    safe_model_endpoint_display,
    validate_model_endpoint,
)
from src.export_register import build_export_register_snapshot
from src.report_template import append_human_signoff


class SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def __setattr__(self, name, value):
        self[name] = value


class CapturingAssistant:
    def __init__(self):
        self.prompts = []

    def get_assistant_response(self, prompt):
        self.prompts.append(prompt)
        return "# Model draft"


class GovernedOnlyAssistant:
    def __init__(self):
        self.prompts = []

    def get_assistant_response(self, _prompt):
        raise AssertionError("Governed workflows must not use the stateful legacy route.")

    def get_governed_response(self, prompt):
        self.prompts.append(prompt)
        return "# Isolated model draft"


def test_remote_ollama_endpoint_is_not_local_loopback():
    assert is_loopback_model_endpoint("http://localhost:11434/v1") is True
    assert is_loopback_model_endpoint("http://127.42.0.9:11434/v1") is True
    assert is_loopback_model_endpoint("http://[::1]:11434/v1") is True
    assert is_loopback_model_endpoint("http://ollama.internal:11434/v1") is False
    assert is_loopback_model_endpoint("https://127.0.0.1.example.com/v1") is False
    assert is_loopback_model_endpoint("https://localhost.example.com/v1") is False


def test_model_endpoint_display_removes_credentials_query_and_fragment():
    display = safe_model_endpoint_display(
        "https://private-user:private-password@example.test:8443/v1?api_key=secret#token"
    )

    assert display == "https://example.test:8443/v1"
    assert "private" not in display
    assert "secret" not in display
    assert "token" not in display


def test_external_model_endpoint_requires_https_and_clean_authority():
    assert validate_model_endpoint("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1"
    assert validate_model_endpoint("https://models.example.test/v1") == "https://models.example.test/v1"

    for endpoint in (
        "http://models.example.test/v1",
        "models.example.test/v1",
        "https://user:secret@models.example.test/v1",
        "https://models.example.test/v1?token=secret",
    ):
        try:
            validate_model_endpoint(endpoint)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"Unsafe endpoint was accepted: {endpoint}")


def test_governed_workflow_prefers_the_isolated_tool_free_route(monkeypatch):
    assistant = GovernedOnlyAssistant()
    state = SessionState({"assistant": assistant})
    monkeypatch.setattr(report_workflow, "st", SimpleNamespace(session_state=state))

    assert report_workflow._call_governed_model("private current report prompt") == ("# Isolated model draft")
    assert assistant.prompts == ["private current report prompt"]


def test_generation_prompt_excludes_organisation_and_reviewer_identity(monkeypatch):
    assistant = CapturingAssistant()
    state = SessionState(
        {
            "assistant": assistant,
            "pilot_mode": "Council Community Preparedness",
            "organisation_name": "SECRET ORGANISATION IDENTITY",
            "reviewer_name": "SECRET REVIEWER IDENTITY",
            "reviewer_role": "SECRET REVIEWER ROLE",
            "form_location": "Cairns, Queensland",
            "form_audience": "Community residents",
            "form_scenario": "Community preparedness",
            "form_concerns": ["Evacuation"],
            "form_timeframe": "7-day action plan",
            "form_extra_context": "General preparedness context only.",
            "selected_map_area": None,
        }
    )
    analysis = {"prompt_context": "Deterministic evidence context", "evidence_confidence": []}
    monkeypatch.setattr(report_workflow, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(report_workflow, "MODEL_ENDPOINT_IS_LOCAL", True)
    monkeypatch.setattr(report_workflow, "run_analysis_pipeline", lambda *args, **kwargs: analysis)
    monkeypatch.setattr(
        report_workflow,
        "_finalize_report_version",
        lambda raw_response, *args, **kwargs: (raw_response, None),
    )

    response, error = report_workflow.generate_current_report(lambda: None)

    assert error is None
    assert response == "# Model draft"
    assert len(assistant.prompts) == 2
    assert all("SECRET ORGANISATION IDENTITY" not in prompt for prompt in assistant.prompts)
    assert all("SECRET REVIEWER IDENTITY" not in prompt for prompt in assistant.prompts)
    assert all("SECRET REVIEWER ROLE" not in prompt for prompt in assistant.prompts)


def test_revision_prompt_excludes_human_review_signoff(monkeypatch, tmp_path):
    assistant = CapturingAssistant()
    draft_status = "Draft - human review required"
    review_record = {
        "approval_status": draft_status,
        "reviewer_name": "SECRET REVIEWER IDENTITY",
        "organisation_name": "SECRET ORGANISATION IDENTITY",
    }
    current_report = append_human_signoff(
        """# Governed report

## Executive Summary
Preparedness content.
""",
        review_record,
    )
    register_snapshot = build_export_register_snapshot()
    report_record = {
        "id": "privacy-revision-report",
        "version": 1,
        "text": current_report,
        "inputs": {"report_status": draft_status},
        "area_selection": None,
        "analysis": {},
        "model_context": {},
        "review_record": review_record,
        "export_register_snapshot": register_snapshot,
    }
    package_context = report_workflow._package_context_for_record(report_record)
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    report_record["audit_path"] = audit.save_report_audit(
        {
            "report_id": report_record["id"],
            "report_version": report_record["version"],
            "report_text": current_report,
            "inputs": report_record["inputs"],
            "area_selection": None,
            "analysis": {},
            "human_review": report_record["review_record"],
            "report_status": draft_status,
            "package_context": package_context,
            "export_register_snapshot": register_snapshot,
        }
    )
    state = SessionState({"assistant": assistant, "latest_report": report_record})
    monkeypatch.setattr(report_workflow, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(report_workflow, "MODEL_ENDPOINT_IS_LOCAL", True)
    monkeypatch.setattr(
        report_workflow,
        "_finalize_report_version",
        lambda raw_response, *args, **kwargs: (raw_response, None),
    )

    response, error = report_workflow.revise_current_report("Clarify the action plan.", lambda: None)

    assert error is None
    assert response == "# Model draft"
    assert "## Human Review Sign-off" not in assistant.prompts[0]
    assert "SECRET REVIEWER IDENTITY" not in assistant.prompts[0]
    assert "SECRET ORGANISATION IDENTITY" not in assistant.prompts[0]
    assert "## Executive Summary" in assistant.prompts[0]


def test_external_model_requests_require_operator_permission_and_session_acknowledgement(monkeypatch):
    assistant = CapturingAssistant()
    state = SessionState(
        {
            "assistant": assistant,
            "latest_report": {"text": "# Existing report"},
            "latest_analysis": {},
            "external_model_acknowledged": True,
        }
    )
    monkeypatch.setattr(report_workflow, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(report_workflow, "MODEL_ENDPOINT_IS_LOCAL", False)
    monkeypatch.setattr(report_workflow, "EXTERNAL_MODEL_ALLOWED", False)
    monkeypatch.setattr(report_workflow, "validate_current_report_form", lambda: None)
    monkeypatch.setattr(
        report_workflow,
        "run_analysis_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("analysis must not run")),
    )

    response, error = report_workflow.generate_current_report(lambda: None)

    assert response is None
    assert "BUSHFIRE_ALLOW_EXTERNAL_MODEL=true" in error
    assert assistant.prompts == []

    response, error = report_workflow.revise_current_report("Clarify wording.", lambda: None)

    assert response is None
    assert "BUSHFIRE_ALLOW_EXTERNAL_MODEL=true" in error
    assert assistant.prompts == []

    monkeypatch.setattr(report_workflow, "EXTERNAL_MODEL_ALLOWED", True)
    state["external_model_acknowledged"] = False

    response, error = report_workflow.revise_current_report("Clarify wording.", lambda: None)

    assert response is None
    assert "browser session" in error
    assert assistant.prompts == []
