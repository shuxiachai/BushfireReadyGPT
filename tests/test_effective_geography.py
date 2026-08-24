from types import SimpleNamespace

import pytest

from src.agents import pipeline as pipeline_module
from src.agents.australian_data_agent import AustralianDataAgent
from src.agents.official_knowledge_agent import OfficialKnowledgeAgent
from src.agents.profile_agent import ProfileAgent
from src.agents.report_agent import ReportAgent
from src.agents.risk_context_agent import RiskContextAgent
from src.data_artifacts import DataArtifactError
from src.data_paths import get_data_paths

AREA_SELECTION = {
    "state": "Queensland",
    "level": "SA4",
    "area_name": "Cairns",
}


def _allow_verified_area_selection(monkeypatch):
    monkeypatch.setattr(
        pipeline_module,
        "build_data_provenance",
        lambda *_args, **_kwargs: {"snapshot": "stable"},
    )
    monkeypatch.setattr(
        pipeline_module,
        "get_data_artifact_status",
        lambda _paths: {
            "core_ready": True,
            "optional_map_state": "bundle_verified",
            "integrity_error_code": "",
            "integrity_error": "",
        },
    )


def test_pipeline_passes_one_effective_profile_to_every_downstream_agent(monkeypatch):
    _allow_verified_area_selection(monkeypatch)
    observed_profiles = {}

    class DataAgent:
        def __init__(self, **_kwargs):
            pass

        def run(self, profile):
            observed_profiles["data"] = profile
            return {"sources": [], "data_limitations": []}

    class CommunityAgent:
        def __init__(self, **_kwargs):
            pass

        def run(self, profile, *, area_selection):
            observed_profiles["community"] = profile
            assert area_selection == AREA_SELECTION
            return {}

    class KnowledgeAgent:
        def __init__(self, **_kwargs):
            pass

        def run(self, profile, _scenario, _concerns, _timeframe):
            observed_profiles["knowledge"] = profile
            return {"status": "no_match", "retrieved_chunks": []}

    class RiskAgent:
        def __init__(self, **_kwargs):
            pass

        def run(self, profile):
            observed_profiles["risk"] = profile
            return {"matched_rule_ids": [], "risk_points": [], "assumptions": []}

    class PlanningAgent:
        def run(self, profile, _risk_context):
            observed_profiles["planning"] = profile
            return {"planning_priorities": []}

    class ReportAgent:
        def run(self, profile, *_args, **_kwargs):
            observed_profiles["report"] = profile
            return "effective prompt context"

    monkeypatch.setattr(pipeline_module, "AustralianDataAgent", DataAgent)
    monkeypatch.setattr(pipeline_module, "CommunityVulnerabilityAgent", CommunityAgent)
    monkeypatch.setattr(pipeline_module, "OfficialKnowledgeAgent", KnowledgeAgent)
    monkeypatch.setattr(pipeline_module, "RiskContextAgent", RiskAgent)
    monkeypatch.setattr(pipeline_module, "PlannerAgent", PlanningAgent)
    monkeypatch.setattr(pipeline_module, "ReportAgent", ReportAgent)
    monkeypatch.setattr(pipeline_module, "build_evidence_confidence_rows", lambda _analysis: [])

    analysis = pipeline_module.run_analysis_pipeline(
        location="My Community",
        audience="Community residents",
        scenario="Community preparedness",
        concerns=["Evacuation"],
        timeframe="7-day action plan",
        extra_context="",
        area_selection=AREA_SELECTION,
        data_paths=get_data_paths(),
    )

    effective_profile = analysis["profile"]
    assert effective_profile["location"] == "My Community"
    assert effective_profile["state"] == "Queensland"
    assert effective_profile["locality"] == "Cairns"
    assert observed_profiles
    assert all(profile is effective_profile for profile in observed_profiles.values())


def test_effective_profile_drives_sources_risk_rules_and_rag_query():
    form_profile = ProfileAgent().run(
        "My Community",
        "Community residents",
        "Community preparedness",
        ["Evacuation"],
        "7-day action plan",
        "",
    )
    effective_profile = pipeline_module._resolve_effective_profile(form_profile, AREA_SELECTION)
    source_names = [source["name"] for source in AustralianDataAgent().run(effective_profile)["sources"]]
    risk_rules = RiskContextAgent().run(effective_profile)["matched_rule_ids"]
    report_context = ReportAgent().run(
        effective_profile,
        {"sources": [], "data_limitations": []},
        {"risk_points": [], "assumptions": []},
        {"planning_priorities": []},
        area_selection=AREA_SELECTION,
    )
    retrieval = {}

    def retrieve(query, **kwargs):
        retrieval["query"] = query
        retrieval.update(kwargs)
        return {
            "status": "no_match",
            "status_label": "No matching passage",
            "retrieved_chunks": [],
        }

    OfficialKnowledgeAgent(service=SimpleNamespace(retrieve=retrieve)).run(
        effective_profile,
        "Community preparedness",
        ["Evacuation"],
        "7-day action plan",
    )

    assert form_profile["location"] == "My Community"
    assert form_profile["state"] == "Australia"
    assert form_profile["locality"] == "My Community"
    assert any("Cairns Regional Council" in name for name in source_names)
    assert {"queensland_general", "cairns_local"}.issubset(risk_rules)
    assert '"area_name": "Cairns"' in report_context
    assert "My Community" not in report_context
    non_cairns_profile = {**effective_profile, "locality": "Queensland - Outback"}
    assert "cairns_local" not in RiskContextAgent().run(non_cairns_profile)["matched_rule_ids"]
    assert retrieval["jurisdiction"] == "Queensland"
    assert "Queensland Cairns" in retrieval["query"]


def test_pipeline_rejects_cross_state_area_selection(monkeypatch):
    _allow_verified_area_selection(monkeypatch)

    with pytest.raises(DataArtifactError) as caught:
        pipeline_module.run_analysis_pipeline(
            location="Hobart, Tasmania",
            audience="Community residents",
            scenario="Community preparedness",
            concerns=["Evacuation"],
            timeframe="7-day action plan",
            extra_context="",
            area_selection=AREA_SELECTION,
            data_paths=get_data_paths(),
        )

    assert caught.value.code == "geography_mismatch"
    assert "Tasmania" in str(caught.value)
    assert "Queensland" in str(caught.value)
