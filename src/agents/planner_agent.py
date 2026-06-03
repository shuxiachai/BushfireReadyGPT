class PlannerAgent:
    """Turns profile and risk context into planning priorities."""

    def run(self, profile, risk_context):
        priorities = [
            "Confirm official information sources and assign one responsible person to monitor them.",
            "Define evacuation triggers, communication channels, and roll-call responsibilities.",
            "Identify candidate assembly point types and require local approval before treating them as safe.",
            "Prepare first aid, smoke/heat health support, and backup communication arrangements.",
        ]

        concern_map = {
            "Evacuation": "Include clear evacuation routes, decision triggers, and accounting procedures.",
            "Candidate assembly points": "Include candidate assembly point criteria, accessibility, smoke exposure, shade, water, and traffic separation.",
            "First aid training": "Include first aid, AED awareness, burn care, smoke exposure response, and drill records.",
            "Roles and responsibilities": "Use a role table with responsibilities for management, teachers/staff, students, wardens, first aiders, and communications.",
            "Communication channels": "Include primary and backup channels for staff, students, families, and official updates.",
            "Smoke and health risk": "Include smoke exposure controls and support for people with asthma or respiratory conditions.",
            "Road disruption": "Include alternative routes and transport coordination assumptions.",
            "Power / communications outage": "Include offline contact lists, backup power assumptions, and non-internet communication options.",
            "Official information sources": "List official sources and explain when each one should be checked.",
            "Human review and approval": "Include review responsibilities, draft status and approval requirements before operational use.",
        }

        for concern in profile.get("concerns", []):
            if concern in concern_map:
                priorities.append(concern_map[concern])

        if profile.get("setting_type") == "campus":
            priorities.append("Keep student supervision, class lists, visitors, and parent/guardian communication explicit.")
        elif profile.get("setting_type") == "community":
            priorities.append("Include vulnerable residents, transport access, multilingual communication, and neighbour check-ins.")
        elif profile.get("setting_type") == "aged_care":
            priorities.append("Include resident mobility, medications, clinical governance, and transport provider coordination.")

        return {
            "planning_priorities": self._dedupe(priorities),
            "one_week_focus": [
                "Day 1: confirm responsible roles and official information sources.",
                "Day 2: draft evacuation and communication procedures.",
                "Day 3: review candidate assembly point criteria.",
                "Day 4: check first aid supplies and training needs.",
                "Day 5: run a tabletop review or short drill.",
                "Day 6: update documentation based on feedback.",
                "Day 7: approve the draft plan and schedule the next review.",
            ],
            "risk_rule_count": len(risk_context.get("matched_rule_ids", [])),
        }

    def _dedupe(self, items):
        seen = set()
        result = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result
