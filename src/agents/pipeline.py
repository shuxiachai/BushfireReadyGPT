from src.agents.australian_data_agent import AustralianDataAgent
from src.agents.community_vulnerability_agent import CommunityVulnerabilityAgent
from src.agents.planner_agent import PlannerAgent
from src.agents.profile_agent import ProfileAgent
from src.agents.report_agent import ReportAgent
from src.agents.risk_context_agent import RiskContextAgent


def run_analysis_pipeline(location, audience, scenario, concerns, timeframe, extra_context, area_selection=None):
    """Run the deterministic Australia-focused multi-agent analysis pipeline."""

    profile = ProfileAgent().run(location, audience, scenario, concerns, timeframe, extra_context)
    data_result = AustralianDataAgent().run(profile)
    community_result = CommunityVulnerabilityAgent().run(profile, area_selection=area_selection)
    risk_context = RiskContextAgent().run(profile)
    plan_result = PlannerAgent().run(profile, risk_context)
    prompt_context = ReportAgent().run(profile, data_result, risk_context, plan_result, community_result)

    return {
        "profile": profile,
        "data": data_result,
        "community": community_result,
        "risk_context": risk_context,
        "plan": plan_result,
        "area_selection": area_selection,
        "prompt_context": prompt_context,
    }
