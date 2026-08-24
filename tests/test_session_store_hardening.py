import json
from types import SimpleNamespace

import pytest

from src import session_store


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": [], "messages": []},
        {"messages": [{}]},
        {"messages": "not-a-list"},
        {"messages": [], "latest_analysis": "not-an-object"},
        {"messages": [], "latest_report": []},
        {"messages": [], "latest_audit_path": {}},
        {"messages": [], "latest_analysis": {"community": {"indicators": []}}},
        {
            "messages": [],
            "latest_analysis": {"community": {"geography_reference": {"selected_asgs_area": []}}},
        },
        {
            "messages": [],
            "latest_analysis": {"community": {"geography_reference": {"lga_candidates": {}}}},
        },
        {
            "messages": [],
            "latest_report": {"analysis": {"community": {"geography_reference": {"limitations": ["valid", {}]}}}},
        },
        {
            "messages": [],
            "latest_analysis": {"community": {"data_quality": {"warnings": "not-a-list"}}},
        },
        {
            "messages": [],
            "latest_analysis": {"knowledge": {"retrieved_chunks": [{"rerank_reasons": ["valid", {}]}]}},
        },
        {"messages": [], "latest_quality": {"summary": []}},
        {"messages": [], "latest_report": {"text": "report", "analysis": []}},
        {"messages": [], "latest_report": {"text": "report", "review_record": {"review_checklist": {}}}},
    ],
)
def test_malformed_nested_session_state_is_rejected(tmp_path, monkeypatch, payload):
    target = tmp_path / "session.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(session_store, "SESSION_STATE_PATH", str(target))

    if payload.get("schema_version") == []:
        for invalid_version in ([], {}, True, 1.0, 999):
            target.write_text(
                json.dumps({"schema_version": invalid_version, "messages": []}),
                encoding="utf-8",
            )
            assert session_store._load_persisted_state() is None
    else:
        assert session_store._load_persisted_state() is None


def test_valid_nested_geography_reference_session_state_is_accepted():
    payload = {
        "messages": [],
        "latest_analysis": {
            "community": {
                "geography_reference": {
                    "selected_asgs_area": {"selected_level": "SA2", "selected_area": "Cairns City"},
                    "lga_candidates": [{"lga_name_2025": "Cairns"}],
                    "limitations": ["Requires human GIS review."],
                }
            }
        },
    }

    assert session_store._is_valid_persisted_state(payload) is True

    payload["latest_analysis"]["community"]["geography_reference"]["selected_asgs_area"] = None
    assert session_store._is_valid_persisted_state(payload) is True


def test_oversized_session_state_is_rejected_before_json_loading(tmp_path, monkeypatch):
    target = tmp_path / "session.json"
    target.write_text('{"messages": []}', encoding="utf-8")
    monkeypatch.setattr(session_store, "SESSION_STATE_PATH", str(target))
    monkeypatch.setattr(session_store, "MAX_PERSISTED_STATE_BYTES", 5)

    assert session_store._load_persisted_state() is None
    original_bytes = target.read_bytes()
    state = {key: None for key in session_store.PERSISTED_STATE_KEYS}
    state["messages"] = [{"role": "user", "content": "too large"}]
    monkeypatch.setattr(session_store, "st", SimpleNamespace(session_state=state))

    assert session_store.persist_session_state() is False
    assert target.read_bytes() == original_bytes
    assert "size limit" in state["persistence_warning"]


def test_excessive_session_nesting_and_serialization_recursion_fail_closed(tmp_path, monkeypatch):
    target = tmp_path / "session.json"
    depth = session_store.MAX_PERSISTED_STATE_NESTING + 1
    target.write_text(
        json.dumps({"messages": [{"role": "user", "content": "[" * depth}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(session_store, "SESSION_STATE_PATH", str(target))

    assert session_store._load_persisted_state()["messages"][0]["content"] == "[" * depth

    target.write_text(
        '{"messages":[],"unknown":' + "[" * depth + "0" + "]" * depth + "}",
        encoding="utf-8",
    )

    assert session_store._load_persisted_state() is None

    state = {key: None for key in session_store.PERSISTED_STATE_KEYS}
    state["messages"] = []
    monkeypatch.setattr(session_store, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(
        session_store.json,
        "dumps",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RecursionError("too deep")),
    )

    assert session_store.persist_session_state() is False
    assert "persistence failed" in state["persistence_warning"]


def test_clear_failure_does_not_reload_stale_session_in_running_app(tmp_path, monkeypatch):
    target = tmp_path / "session.json"
    target.write_text('{"messages": [{"role": "user", "content": "stale"}]}', encoding="utf-8")
    state = {"messages": [{"role": "user", "content": "current"}], "latest_report": {"text": "private"}}
    reruns = []
    monkeypatch.setattr(session_store, "SESSION_STATE_PATH", str(target))
    monkeypatch.setattr(session_store, "INTERACTION_LOG_PATH", None)
    monkeypatch.setattr(session_store.os, "remove", lambda _path: (_ for _ in ()).throw(PermissionError("locked")))
    monkeypatch.setattr(
        session_store,
        "st",
        SimpleNamespace(session_state=state, rerun=lambda: reruns.append(True)),
    )

    session_store.clear_conversation()

    assert "messages" not in state
    assert state["_skip_persisted_restore_once"] is True
    assert "could not be deleted" in state["persistence_warning"]
    assert session_store._load_persisted_state() is None
    assert reruns == [True]
