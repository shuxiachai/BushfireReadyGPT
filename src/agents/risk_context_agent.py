from pathlib import Path

import yaml


class RiskContextAgent:
    """Builds a local risk context from deterministic Australia-focused rules."""

    def __init__(self, rules_path="data_australia/risk_context_rules.yml"):
        self.rules_path = Path(rules_path)

    def run(self, profile):
        rules = self._load_rules()
        location = profile["location"].lower()
        scenario = profile["scenario"].lower()
        matched_rules = []

        for rule in rules:
            match = rule.get("match", {})
            location_keywords = [item.lower() for item in match.get("location_keywords", [])]
            scenario_keywords = [item.lower() for item in match.get("scenario_keywords", [])]
            location_match = any(keyword in location for keyword in location_keywords)
            scenario_match = any(keyword in scenario for keyword in scenario_keywords)

            if location_match or scenario_match:
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
        with open(self.rules_path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        return data.get("rules", [])

    def _dedupe(self, items):
        seen = set()
        result = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result
