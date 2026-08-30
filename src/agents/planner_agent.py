import re


class PlannerAgent:
    """Turns profile and risk context into planning priorities."""

    _FOCUS_RULES = {
        "evacuation": {
            "aliases": {"evacuation", "assisted evacuation"},
            "label": "evacuation planning",
            "match_terms": ["evacuation", "assisted movement"],
            "priority": "Document evacuation decision triggers, assisted movement, accountability and update processes.",
        },
        "candidate_assembly_points": {
            "aliases": {"candidate assembly points", "assembly point criteria"},
            "label": "candidate assembly point criteria",
            "match_terms": ["candidate assembly point", "assembly point criteria"],
            "priority": "Document candidate assembly point criteria, accessibility and verification requirements without declaring a venue safe.",
        },
        "first_aid": {
            "aliases": {"first aid training"},
            "label": "first aid and training",
            "match_terms": ["first aid", "training exercise"],
            "priority": "Cover first aid readiness, smoke and heat exposure, training and exercise records.",
        },
        "roles": {
            "aliases": {"roles and responsibilities"},
            "label": "roles and responsibilities",
            "match_terms": ["roles and responsibilities", "responsible role"],
            "priority": "Assign preparedness, communication, accountability, first aid and review responsibilities.",
        },
        "communications": {
            "aliases": {"communication channels", "communications", "warning channels"},
            "label": "communications and warning channels",
            "match_terms": ["communication", "warning channel", "notification"],
            "priority": "Cover official warning monitoring plus primary, accessible and backup communication channels.",
        },
        "smoke_health": {
            "aliases": {"smoke and health risk"},
            "label": "smoke and health risk",
            "match_terms": ["smoke exposure", "health support"],
            "priority": "Cover smoke and heat exposure controls and support for people with health vulnerabilities.",
        },
        "road_access": {
            "aliases": {"road disruption", "access roads", "water and access roads"},
            "label": "road and access disruption",
            "match_terms": ["road disruption", "access road", "road access", "route disruption"],
            "priority": "Plan for road and access disruption using candidate routes whose current status must be checked through official sources.",
        },
        "power_continuity": {
            "aliases": {"power communications outage", "communications outage", "backup power"},
            "label": "power and communications continuity",
            "match_terms": ["backup power", "power outage", "communications outage"],
            "priority": "Plan for power or communications outages with offline contacts and tested backup arrangements.",
        },
        "official_sources": {
            "aliases": {"official information sources", "official sources"},
            "label": "official information sources",
            "match_terms": ["official source", "official emergency"],
            "priority": "Identify official verification sources and state when a responsible person must check them.",
        },
        "human_review": {
            "aliases": {"human review and approval", "human review"},
            "label": "human review and approval",
            "match_terms": ["human review", "organisational approval"],
            "priority": "Keep the report in draft status until responsible human review and organisational approval are recorded.",
        },
        "vulnerable_people": {
            "aliases": {"vulnerable residents"},
            "label": "support for vulnerable residents",
            "match_terms": ["vulnerable resident", "support needs", "mobility assistance"],
            "priority": "Address mobility, transport, language, health and welfare-check support for vulnerable residents.",
        },
        "property_preparation": {
            "aliases": {"property preparation"},
            "label": "property preparation",
            "match_terms": ["property preparation", "prepare the home", "home maintenance"],
            "priority": "Cover property preparation and home maintenance actions that reduce risk before the bushfire season.",
        },
        "emergency_kits": {
            "aliases": {"emergency kit", "emergency kits"},
            "label": "emergency kits",
            "match_terms": ["emergency kit", "emergency supplies", "go bag"],
            "priority": "Cover emergency kits, accessible storage, medicines, documents and household-specific supplies.",
        },
        "pets": {
            "aliases": {"pet", "pets"},
            "label": "pet preparedness",
            "match_terms": ["pet", "animal plan"],
            "priority": "Include pet identification, transport, supplies and contingency arrangements.",
        },
        "medication_continuity": {
            "aliases": {"medication continuity"},
            "label": "medication continuity",
            "match_terms": ["medication continuity", "medication supply", "clinical continuity"],
            "priority": "Address medication continuity, clinical records, refrigeration and responsible clinical review.",
        },
        "livestock": {
            "aliases": {"livestock"},
            "label": "livestock preparedness",
            "match_terms": ["livestock", "animal movement"],
            "priority": "Plan livestock identification, early movement, water, feed and fallback arrangements.",
        },
        "vegetation": {
            "aliases": {"vegetation management"},
            "label": "vegetation management",
            "match_terms": ["vegetation management", "fuel management"],
            "priority": "Cover lawful vegetation and fuel management subject to property-specific and official guidance.",
        },
        "machinery": {
            "aliases": {"machinery"},
            "label": "machinery preparedness",
            "match_terms": ["machinery", "farm equipment", "agricultural equipment"],
            "priority": "Cover machinery maintenance, safe storage, shutdown responsibilities and equipment access.",
        },
        "water": {
            "aliases": {"water"},
            "label": "water continuity",
            "match_terms": ["water continuity", "backup water supply", "water supply limitation"],
            "priority": "Record water supply limitations, backup arrangements and responsible verification.",
        },
        "live_information_boundary": {
            "aliases": {
                "is an evacuation order active",
                "is the road currently safe",
                "where should people evacuate now",
                "which live evacuation route should people use now",
            },
            "label": "live emergency information boundary",
            "match_terms": ["official emergency", "triple zero", "000"],
            "priority": "Refuse live incident or route decisions; direct users to current official emergency services and call 000 for life-threatening emergencies.",
        },
    }
    _COMPOSITE_FOCUS_ALIASES = {
        "power communications outage": ("power_continuity", "communications"),
        "water and access roads": ("water", "road_access"),
    }

    @classmethod
    def _normalise_focus(cls, value):
        return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split())

    @classmethod
    def _resolve_focus_areas(cls, concerns):
        alias_map = {
            alias: (concept_id, rule) for concept_id, rule in cls._FOCUS_RULES.items() for alias in rule["aliases"]
        }
        resolved = []
        ignored = 0
        seen = set()
        for concern in concerns or []:
            normalised = cls._normalise_focus(concern)
            concept_ids = cls._COMPOSITE_FOCUS_ALIASES.get(normalised)
            if concept_ids is None:
                match = alias_map.get(normalised)
                if match is None:
                    ignored += 1
                    continue
                concept_ids = (match[0],)
            for concept_id in concept_ids:
                if concept_id in seen:
                    continue
                seen.add(concept_id)
                resolved.append(cls.canonical_focus_concept(concept_id))
        return resolved, ignored

    @classmethod
    def canonical_focus_concept(cls, concept_id):
        """Return a trusted focus concept by deterministic application ID."""

        rule = cls._FOCUS_RULES.get(str(concept_id or ""))
        if rule is None:
            return None
        return {
            "id": str(concept_id),
            "label": rule["label"],
            "match_terms": list(rule["match_terms"]),
            "priority": rule["priority"],
        }

    def run(self, profile, risk_context):
        priorities = [
            "Confirm official information sources and assign one responsible person to monitor them.",
            "Define evacuation triggers, communication channels, and roll-call responsibilities.",
            "Identify candidate assembly point types and require local approval before treating them as safe.",
            "Prepare first aid, smoke/heat health support, and backup communication arrangements.",
        ]

        focus_areas, ignored_focus_area_count = self._resolve_focus_areas(profile.get("concerns", []))
        priorities.extend(item["priority"] for item in focus_areas)

        if profile.get("setting_type") == "campus":
            priorities.append(
                "Keep student supervision, class lists, visitors, and parent/guardian communication explicit."
            )
        elif profile.get("setting_type") == "community":
            priorities.append(
                "Include vulnerable residents, transport access, multilingual communication, and neighbour check-ins."
            )
        elif profile.get("setting_type") == "aged_care":
            priorities.append(
                "Include resident mobility, medications, clinical governance, and transport provider coordination."
            )
        elif profile.get("setting_type") == "household":
            priorities.append(
                "Keep household decision-making, home preparation, emergency kits, pets and neighbour communication explicit."
            )
        elif profile.get("setting_type") == "farm":
            priorities.append(
                "Keep livestock, machinery, vegetation, water supply, access and neighbouring-property coordination explicit."
            )

        return {
            "planning_priorities": self._dedupe(priorities),
            "focus_area_concepts": focus_areas,
            "ignored_focus_area_count": ignored_focus_area_count,
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
