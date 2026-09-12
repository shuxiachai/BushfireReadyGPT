from src.agents.planner_agent import PlannerAgent
from src.rag.errors import RagError
from src.rag.service import RagService

OFFICIAL_QUERY_SCHEMA = "official-form-query-v1"
FOCUS_QUERY_SCHEMA = "official-focus-query-plan-v1"
MAX_FOCUS_QUERIES = 4


def build_focus_queries(concerns):
    """Bounded app-owned queries without U0 prose or locality/time dilution.

    Jurisdiction stays a retrieval filter. Selection is input ordered and
    independent of evaluation targets and corpus IDs.
    """
    concepts, _ = PlannerAgent._resolve_focus_areas(concerns)
    return [
        {
            "focus_id": concept["id"],
            "query": "Bushfire preparedness " + "; ".join(concept["match_terms"][:2]),
        }
        for concept in concepts
        if concept["id"] != "live_information_boundary"
    ][:MAX_FOCUS_QUERIES]


def build_official_query(profile, scenario, concerns, timeframe):
    """One query contract shared by the application and form-based diagnostics."""

    setting = profile.get("setting_type") or "community"
    state = profile.get("state") or "Australia"
    locality = profile.get("locality") or ""
    concern_text = ", ".join(concerns or []) or "general bushfire preparedness"
    query = (
        f"Official static bushfire preparedness guidance for {state} {locality}. "
        f"Scenario: {scenario}. Setting: {setting}. Focus: {concern_text}. "
        f"Planning timeframe: {timeframe}."
    )
    return query, {
        "state": state,
        "locality": locality,
        "setting_type": setting,
        "scenario": scenario,
        "concerns": list(concerns or []),
        "timeframe": timeframe,
    }


class OfficialKnowledgeAgent:
    """Retrieve static official preparedness passages from the verified local RAG index."""

    def __init__(self, data_paths=None, service=None):
        self.data_paths = data_paths
        self.service = service

    def run(self, profile, scenario, concerns, timeframe):
        query, components = build_official_query(profile, scenario, concerns, timeframe)
        state = components["state"]
        try:
            service = self.service or RagService(data_paths=self.data_paths)
            # Class capability avoids inventing methods on loose mocks and
            # preserves services implementing only the original API.
            if callable(getattr(type(service), "retrieve_planning", None)):
                result = service.retrieve_planning(
                    query, focus_queries=build_focus_queries(concerns), jurisdiction=state
                )
            else:
                result = service.retrieve(query, jurisdiction=state, trusted_planning_scope=True)
        except RagError as error:
            return {
                "status": "unavailable",
                "status_label": "RAG retrieval unavailable",
                "query_sha256": "",
                "jurisdiction_filter": state,
                "embedding_model": "",
                "index_manifest_sha256": "",
                "retrieved_chunks": [],
                "error_code": error.code,
                "limitations": [
                    "No RAG passage was supplied to the report model.",
                    "The deterministic source register and existing planning rules remain available.",
                ],
            }
        result["query_components"] = components
        return result
