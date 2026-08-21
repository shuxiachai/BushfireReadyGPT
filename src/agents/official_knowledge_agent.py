from src.rag.errors import RagError
from src.rag.service import RagService


class OfficialKnowledgeAgent:
    """Retrieve static official preparedness passages from the verified local RAG index."""

    def __init__(self, data_paths=None, service=None):
        self.data_paths = data_paths
        self.service = service

    def run(self, profile, scenario, concerns, timeframe):
        setting = profile.get("setting_type") or "community"
        state = profile.get("state") or "Australia"
        locality = profile.get("locality") or ""
        concern_text = ", ".join(concerns or []) or "general bushfire preparedness"
        query = (
            f"Official static bushfire preparedness guidance for {state} {locality}. "
            f"Scenario: {scenario}. Setting: {setting}. Focus: {concern_text}. "
            f"Planning timeframe: {timeframe}."
        )
        try:
            service = self.service or RagService(data_paths=self.data_paths)
            result = service.retrieve(
                query,
                jurisdiction=state,
                trusted_planning_scope=True,
            )
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
        result["query_components"] = {
            "state": state,
            "locality": locality,
            "setting_type": setting,
            "scenario": scenario,
            "concerns": list(concerns or []),
            "timeframe": timeframe,
        }
        return result
