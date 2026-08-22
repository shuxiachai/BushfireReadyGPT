import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import app_state, session_store
from src import config as app_config
from src.app_state import WELCOME_MESSAGE


class SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def __setattr__(self, name, value):
        self[name] = value


def test_message_normalisation_filters_invalid_rows_and_refreshes_welcome_text():
    original = {"role": "user", "content": "Keep this message"}

    result = app_state.normalise_loaded_messages(
        [
            None,
            {
                "role": "assistant",
                "content": "Complete the form above to generate a formal Australian bushfire preparedness report",
            },
            original,
        ]
    )

    assert result == [{"role": "assistant", "content": WELCOME_MESSAGE}, original]


def test_active_location_and_map_labels_follow_current_state(monkeypatch):
    state = SessionState(
        {
            "form_location": "Current form location",
            "latest_analysis": {"profile": {"location": "Prior analysis location"}},
            "selected_map_area": {"state": "Queensland", "level": "SA4", "area_name": "Cairns"},
        }
    )
    monkeypatch.setattr(app_state, "st", SimpleNamespace(session_state=state))

    assert app_state.get_active_analysis_location() == "Current form location"
    assert app_state.get_active_map_selection_label() == "Queensland / SA4 / Cairns"

    state["form_location"] = ""
    assert app_state.get_active_analysis_location() == "Prior analysis location"
    state["latest_analysis"] = None
    state["selected_map_area"] = None
    assert app_state.get_active_analysis_location() == ""
    assert app_state.get_active_map_selection_label() is None


def test_latest_report_text_prefers_governed_record_then_report_messages(monkeypatch):
    state = SessionState({"latest_report": {"text": "# Governed"}, "messages": []})
    monkeypatch.setattr(app_state, "st", SimpleNamespace(session_state=state))
    assert app_state.get_latest_assistant_text() == "# Governed"

    state["latest_report"] = None
    state["messages"] = [
        {"role": "assistant", "kind": "report", "content": ["# Earlier report"]},
        {"role": "assistant", "kind": "report", "content": WELCOME_MESSAGE},
    ]
    assert app_state.get_latest_assistant_text() == "# Earlier report"
    state["messages"] = [{"role": "user", "content": "No report"}]
    assert app_state.get_latest_assistant_text() == ""


def test_save_latest_report_handles_empty_and_writes_private_markdown(tmp_path, monkeypatch):
    state = SessionState({"latest_report": None, "messages": []})
    monkeypatch.setattr(app_state, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(app_state, "PROJECT_ROOT", tmp_path)
    assert app_state.save_latest_report() is None

    state["latest_report"] = {"text": "# Saved report"}
    saved = Path(app_state.save_latest_report())
    assert saved.read_text(encoding="utf-8") == "# Saved report"
    assert saved.parent == tmp_path / "chat_history"


def test_initialize_state_builds_stateless_runtime_and_defaults(monkeypatch):
    state = SessionState()
    reruns = []
    monkeypatch.setattr(session_store, "SESSION_STATE_PATH", None)
    monkeypatch.setattr(
        session_store,
        "st",
        SimpleNamespace(session_state=state, rerun=lambda: reruns.append(True)),
    )

    session_store.initialize_state()

    assert state["messages"] == [{"role": "assistant", "content": WELCOME_MESSAGE}]
    assert state["model_client"].__class__.__name__ == "GovernedModelClient"
    assert state["latest_report"] is None
    assert state["session_id"]
    assert reruns == [True]


def test_session_persistence_round_trip_and_failure_warning(tmp_path, monkeypatch):
    target = tmp_path / "session.json"
    state = SessionState({key: None for key in session_store.PERSISTED_STATE_KEYS})
    state["messages"] = [{"role": "user", "content": "private"}]
    monkeypatch.setattr(session_store, "SESSION_STATE_PATH", str(target))
    monkeypatch.setattr(session_store, "st", SimpleNamespace(session_state=state))

    assert session_store.persist_session_state() is True
    assert json.loads(target.read_text(encoding="utf-8"))["messages"] == state["messages"]
    assert session_store._load_persisted_state()["messages"] == state["messages"]

    monkeypatch.setattr(
        session_store,
        "atomic_write_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    assert session_store.persist_session_state() is False
    assert "persistence failed" in state["persistence_warning"]


def test_session_loader_and_review_date_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(session_store, "SESSION_STATE_PATH", None)
    assert session_store._load_persisted_state() is None
    assert session_store.persist_session_state() is True
    assert session_store._parse_review_date("2026-08-22T10:00:00Z") == date(2026, 8, 22)
    assert session_store._parse_review_date("invalid") == date.today()

    invalid = tmp_path / "invalid.json"
    invalid.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(session_store, "SESSION_STATE_PATH", str(invalid))
    assert session_store._load_persisted_state() is None

    non_object = tmp_path / "list.json"
    non_object.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(session_store, "SESSION_STATE_PATH", str(non_object))
    assert session_store._load_persisted_state() is None


def test_restored_review_widgets_are_hydrated_only_from_verified_report(monkeypatch):
    from src import report_workflow

    state = SessionState()
    monkeypatch.setattr(session_store, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(report_workflow, "verify_report_record_snapshot", lambda _record: True)
    report = {
        "text": "# Verified report",
        "review_record": {
            "approval_status": "Reviewed draft",
            "reviewer_name": "Verified Reviewer",
            "reviewer_role": "Preparedness lead",
            "organisation_name": "Verified Organisation",
            "review_notes": "Checked against local records.",
            "review_date": "2026-08-20",
            "review_checklist": [{"id": "official_sources", "checked": True}],
        },
    }

    session_store._hydrate_restored_review_widgets(report)

    assert state["approval_status"] == "Reviewed draft"
    assert state["approval_reviewer_name"] == "Verified Reviewer"
    assert state["approval_review_date"] == date(2026, 8, 20)
    assert state["review_check_official_sources"] is True
    assert state["latest_review_record"] == report["review_record"]
    assert state["restored_governance_warning"] is None

    monkeypatch.setattr(report_workflow, "verify_report_record_snapshot", lambda _record: False)
    session_store._hydrate_restored_review_widgets({"text": "# Legacy report"})
    assert state["latest_review_record"] is None
    assert "read-only" in state["restored_governance_warning"]


def test_numeric_environment_settings_are_validated(monkeypatch):
    monkeypatch.delenv("TEST_POSITIVE_NUMBER", raising=False)
    assert app_config._positive_number("TEST_POSITIVE_NUMBER", 7) == 7

    monkeypatch.setenv("TEST_POSITIVE_NUMBER", "2.5")
    assert app_config._positive_number("TEST_POSITIVE_NUMBER", 7) == 2.5
    monkeypatch.setenv("TEST_POSITIVE_NUMBER", "0")
    assert app_config._positive_number("TEST_POSITIVE_NUMBER", 7, integer=True, allow_zero=True) == 0

    monkeypatch.setenv("TEST_POSITIVE_NUMBER", "not-a-number")
    with pytest.raises(RuntimeError, match="valid number"):
        app_config._positive_number("TEST_POSITIVE_NUMBER", 7)
    monkeypatch.setenv("TEST_POSITIVE_NUMBER", "-1")
    with pytest.raises(RuntimeError, match="greater than zero"):
        app_config._positive_number("TEST_POSITIVE_NUMBER", 7)


def test_endpoint_display_and_loopback_helpers_fail_closed():
    assert app_config.is_loopback_model_endpoint("") is False
    assert app_config.is_loopback_model_endpoint("[invalid-ipv6") is False
    assert app_config.is_loopback_model_endpoint("http:///missing-host") is False
    assert app_config.safe_model_endpoint_display("") == "<not configured>"
    assert app_config.safe_model_endpoint_display("http://example.test:invalid") == "<configured endpoint>"
    assert app_config.safe_model_endpoint_display("http:///missing-host") == "<configured endpoint>"
    with pytest.raises(RuntimeError, match="not a valid URL"):
        app_config.validate_model_endpoint("http://[invalid-ipv6")
