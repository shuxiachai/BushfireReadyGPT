import re
from pathlib import Path

from src.data_artifacts import load_yaml_mapping
from src.data_paths import get_data_paths


class RiskContextAgent:
    """Builds a local risk context from deterministic Australia-focused rules."""

    def __init__(self, rules_path=None, data_paths=None):
        self.data_paths = data_paths or get_data_paths()
        self.rules_path = Path(rules_path) if rules_path is not None else self.data_paths.risk_context_rules

    def run(self, profile):
        rules = self._load_rules()
        location = profile["location"].lower()
        scenario = profile["scenario"].lower()
        resolved_state = profile.get("state", "").lower()
        matched_rules = []

        for rule in rules:
            match = rule.get("match", {})
            states = [item.lower() for item in match.get("states", [])]
            location_keywords = [item.lower() for item in match.get("location_keywords", [])]
            scenario_keywords = [item.lower() for item in match.get("scenario_keywords", [])]
            state_match = bool(resolved_state and resolved_state in states)
            location_match = any(self._matches_keyword(location, keyword) for keyword in location_keywords)
            scenario_match = any(self._matches_keyword(scenario, keyword) for keyword in scenario_keywords)
            if states and resolved_state not in {"", "australia"}:
                location_scope_match = state_match
            else:
                location_scope_match = location_match

            if location_scope_match or scenario_match:
                matched_rules.append(rule)

        risk_points = []
        assumptions = []
        for rule in matched_rules:
            risk_points.extend(rule.get("risk_points", []))
            assumptions.extend(rule.get("assumptions", []))

        if not risk_points:
            risk_points.append(
                "Use Australian state or territory emergency services, local council information, and Bureau of Meteorology warnings to verify current risk."
            )
            assumptions.append("No local rule matched this location or scenario yet.")

        return {
            "matched_rule_ids": [rule.get("id") for rule in matched_rules],
            "risk_points": self._dedupe(risk_points),
            "assumptions": self._dedupe(assumptions),
        }

    def _load_rules(self):
        data = load_yaml_mapping(self.rules_path, label="risk-context rules")
        return data.get("rules", [])

    def _matches_keyword(self, text, keyword):
        return (
            re.search(
                rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])",
                text,
            )
            is not None
        )

    def _dedupe(self, items):
        seen = set()
        result = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result
