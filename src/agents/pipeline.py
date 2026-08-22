from src.agents.australian_data_agent import AustralianDataAgent
from src.agents.community_vulnerability_agent import CommunityVulnerabilityAgent
from src.agents.official_knowledge_agent import OfficialKnowledgeAgent
from src.agents.planner_agent import PlannerAgent
from src.agents.profile_agent import ProfileAgent
from src.agents.report_agent import ReportAgent
from src.agents.risk_context_agent import RiskContextAgent
from src.data_artifacts import (
    DataArtifactError,
    build_data_provenance,
    get_data_artifact_status,
)
from src.data_paths import get_data_paths, safe_data_path_label
from src.evidence_confidence import build_evidence_confidence_rows
from src.runtime_trace import trace_stage


def run_analysis_pipeline(
    location,
    audience,
    scenario,
    concerns,
    timeframe,
    extra_context,
    area_selection=None,
    data_paths=None,
):
    """Run the deterministic Australia-focused multi-agent analysis pipeline."""

    paths = data_paths or get_data_paths()
    with trace_stage("data_integrity", map_selection_present=bool(area_selection)) as span:
        pre_analysis_provenance = build_data_provenance(
            paths,
            include_all_sa2_profile=bool(area_selection),
        )
        artifact_status = get_data_artifact_status(paths)
        span.add_metrics(artifact_core_ready=artifact_status["core_ready"] is True)
        if area_selection and artifact_status["optional_map_state"] != "bundle_verified":
            raise DataArtifactError(
                "optional_map_unverified",
                "An explicit national-map selection requires a sidecar-verified profile and boundary bundle.",
            )
        default_data_dir = (paths.project_root / "data_australia").resolve()
        if paths.data_dir.resolve() == default_data_dir and not artifact_status["core_ready"]:
            raise DataArtifactError(
                artifact_status["integrity_error_code"] or "core_data_invalid",
                "Bundled core data failed integrity validation: "
                + (artifact_status["integrity_error"] or "unknown validation error"),
            )
    with trace_stage("profile_agent"):
        profile = ProfileAgent(data_paths=paths).run(
            location,
            audience,
            scenario,
            concerns,
            timeframe,
            extra_context,
        )
    with trace_stage("australian_data_agent"):
        data_result = AustralianDataAgent(data_paths=paths).run(profile)
    with trace_stage("community_vulnerability_agent"):
        community_result = CommunityVulnerabilityAgent(data_paths=paths).run(
            profile,
            area_selection=area_selection,
        )
    with trace_stage("official_knowledge_agent") as span:
        knowledge_result = OfficialKnowledgeAgent(data_paths=paths).run(
            profile,
            scenario,
            concerns,
            timeframe,
        )
        span.add_metrics(
            knowledge_status=str(knowledge_result.get("status") or "unknown"),
            retrieved_chunks=len(knowledge_result.get("retrieved_chunks") or []),
        )
    with trace_stage("risk_context_agent"):
        risk_context = RiskContextAgent(data_paths=paths).run(profile)
    with trace_stage("planner_agent"):
        plan_result = PlannerAgent().run(profile, risk_context)
    with trace_stage("report_agent"):
        prompt_context = ReportAgent().run(
            profile,
            data_result,
            risk_context,
            plan_result,
            community_result,
            knowledge_result,
        )
    with trace_stage("data_integrity"):
        post_analysis_provenance = build_data_provenance(
            paths,
            include_all_sa2_profile=bool(area_selection),
        )
        if post_analysis_provenance != pre_analysis_provenance:
            raise DataArtifactError(
                "data_changed_during_analysis",
                "A configured data artifact changed while analysis was running; retry with a stable data snapshot.",
            )

    analysis = {
        "profile": profile,
        "data": data_result,
        "community": community_result,
        "knowledge": knowledge_result,
        "risk_context": risk_context,
        "plan": plan_result,
        "area_selection": area_selection,
        "prompt_context": prompt_context,
        "resolved_data_paths": {name: safe_data_path_label(path, paths) for name, path in vars(paths).items()},
        "data_integrity": artifact_status,
        "data_provenance": post_analysis_provenance,
    }
    with trace_stage("evidence_confidence"):
        analysis["evidence_confidence"] = build_evidence_confidence_rows(analysis)
    return analysis
