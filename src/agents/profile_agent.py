import re
from pathlib import Path

from src.data_artifacts import load_yaml_mapping
from src.data_paths import get_data_paths

# Canonical short-form aliases for all 8 states/territories.
# Centralised here and imported by other modules to avoid duplication.
STATE_SHORT = {
    "queensland": "qld",
    "new south wales": "nsw",
    "victoria": "vic",
    "western australia": "wa",
    "south australia": "sa",
    "tasmania": "tas",
    "northern territory": "nt",
    "australian capital territory": "act",
}


class ProfileAgent:
    """Normalizes user form inputs into a compact analysis profile."""

    _SCENARIO_CONCEPTS = {
        "school bushfire preparedness": {
            "id": "school_preparedness",
            "label": "School bushfire preparedness",
            "setting_type": "campus",
            "match_terms": [
                "school bushfire preparedness",
                "school preparedness plan",
                "campus bushfire preparedness",
            ],
        },
        "council community preparedness": {
            "id": "council_community_preparedness",
            "label": "Council community preparedness",
            "setting_type": "community",
            "match_terms": [
                "council community preparedness",
                "council-led community preparedness",
                "council preparedness program",
                "council preparedness plan",
            ],
        },
        "community workshop material": {
            "id": "community_workshop",
            "label": "Community workshop material",
            "setting_type": "community",
            "match_terms": ["community workshop", "community preparedness workshop"],
        },
        "household bushfire preparedness": {
            "id": "household_preparedness",
            "label": "Household bushfire preparedness",
            "setting_type": "household",
            "match_terms": [
                "household bushfire preparedness",
                "household preparedness plan",
                "home preparedness",
            ],
        },
        "aged care care facility preparedness": {
            "id": "aged_care_preparedness",
            "label": "Aged care / care facility preparedness",
            "setting_type": "aged_care",
            "match_terms": [
                "aged care preparedness",
                "care facility preparedness",
                "aged care bushfire plan",
            ],
        },
        "farm land management preparedness": {
            "id": "farm_land_management",
            "label": "Farm / land management preparedness",
            "setting_type": "farm",
            "match_terms": [
                "farm bushfire preparedness",
                "farm preparedness plan",
                "land management preparedness",
            ],
        },
        "current active bushfire route safety request": {
            "id": "live_route_request",
            "label": "Current active bushfire route safety request",
            "setting_type": "general",
            "match_terms": [
                "current route safety request",
                "live evacuation route request",
                "active bushfire route",
            ],
        },
    }
    _TIMEFRAME_CONCEPTS = {
        "7 day action plan": {"id": "seven_day", "label": "7-day action plan"},
        "this month preparedness plan": {"id": "this_month", "label": "This-month preparedness plan"},
        "before the next bushfire season": {
            "id": "before_next_season",
            "label": "Before the next bushfire season",
        },
        "long term community resilience planning": {
            "id": "long_term_resilience",
            "label": "Long-term community resilience planning",
        },
        "immediate live decision": {"id": "immediate_live_decision", "label": "Immediate live decision"},
    }

    # Tier 2: match state name or postal abbreviation in the location string
    _STATE_KEYWORDS = {
        "Queensland": ["queensland", "qld"],
        "New South Wales": ["new south wales", "nsw"],
        "Victoria": ["victoria", "vic"],
        "Western Australia": ["western australia", "wa"],
        "South Australia": ["south australia", "sa"],
        "Tasmania": ["tasmania", "tas"],
        "Northern Territory": ["northern territory", "nt"],
        "Australian Capital Territory": ["australian capital territory", "act", "canberra"],
    }

    # Tier 3: recognise major city names when no state keyword is present
    _CITY_KEYWORDS = {
        "New South Wales": ["sydney", "newcastle", "wollongong", "central coast", "wagga wagga"],
        "Victoria": ["melbourne", "geelong", "ballarat", "bendigo", "warrnambool"],
        "Queensland": ["brisbane", "gold coast", "sunshine coast"],
        "Western Australia": ["perth", "fremantle", "bunbury"],
        "South Australia": ["adelaide", "port augusta", "mount gambier"],
        "Tasmania": ["hobart", "launceston", "devonport"],
        "Northern Territory": ["darwin", "alice springs", "katherine"],
    }

    def __init__(self, region_mappings_path=None, data_paths=None):
        self.data_paths = data_paths or get_data_paths()
        self.region_mappings_path = (
            Path(region_mappings_path) if region_mappings_path is not None else self.data_paths.region_mappings
        )
        self._region_map = self._load_region_map()

    def _load_region_map(self):
        data = load_yaml_mapping(
            self.region_mappings_path,
            label="region mapping",
        )
        result = {}
        for region in data.get("regions", []):
            locality = region.get("location", "")
            state = region.get("state", "Australia")
            result[locality.lower()] = {"locality": locality, "state": state}
        return result

    def _resolve_location(self, location_text):
        lower = location_text.lower()
        explicit_state = self._resolve_explicit_state(lower)
        # Tier 1: configured locality from region_mappings.yml
        for key, info in self._region_map.items():
            mapped_state = info["state"]
            if explicit_state and mapped_state != explicit_state:
                continue
            if self._matches_locality_segment(lower, key):
                return info["locality"], explicit_state or mapped_state
        # Tier 2: state name or postal code in the location string
        if explicit_state:
            return location_text, explicit_state
        # Tier 3: major city names
        for state, cities in self._CITY_KEYWORDS.items():
            if any(self._matches_locality_segment(lower, city) for city in cities):
                return location_text, state
        return location_text, "Australia"

    def _resolve_explicit_state(self, lower_location):
        for state, keywords in self._STATE_KEYWORDS.items():
            if any(self._matches_location_keyword(lower_location, keyword) for keyword in keywords):
                return state
        return None

    def _matches_location_keyword(self, location, keyword):
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", location) is not None

    def _matches_locality_segment(self, location, locality):
        locality = self._normalise_place(locality)
        allowed_suffixes = {"", "area", "campus", "cbd", "city", "community", "region"}
        for raw_segment in str(location).split(","):
            segment = self._normalise_place(raw_segment)
            if segment == locality:
                return True
            if segment.startswith(f"{locality} ") and segment[len(locality) + 1 :] in allowed_suffixes:
                return True
            if segment == f"greater {locality}":
                return True
        return False

    def _normalise_place(self, value):
        return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())

    @classmethod
    def _normalise_concept_key(cls, value):
        return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split())

    @classmethod
    def _canonical_concept(cls, value, concepts):
        concept = concepts.get(cls._normalise_concept_key(value))
        return dict(concept) if concept is not None else None

    @classmethod
    def resolve_scenario_concept(cls, value):
        """Resolve only an exact application-recognised scenario label."""

        return cls._canonical_concept(value, cls._SCENARIO_CONCEPTS)

    def run(self, location, audience, scenario, concerns, timeframe, extra_context):
        location_text = location.strip()
        scenario_text = scenario.strip()
        lower_scenario = scenario_text.lower()
        scenario_concept = self.resolve_scenario_concept(scenario_text)
        timeframe_concept = self._canonical_concept(timeframe, self._TIMEFRAME_CONCEPTS)

        locality, state = self._resolve_location(location_text)

        if scenario_concept is not None:
            setting_type = scenario_concept["setting_type"]
        elif any(keyword in lower_scenario for keyword in ["campus", "school", "university"]):
            setting_type = "campus"
        elif any(keyword in lower_scenario for keyword in ["community", "resident"]):
            setting_type = "community"
        elif any(keyword in lower_scenario for keyword in ["aged care", "nursing"]):
            setting_type = "aged_care"
        elif any(keyword in lower_scenario for keyword in ["household", "home preparedness"]):
            setting_type = "household"
        elif any(keyword in lower_scenario for keyword in ["farm", "land management"]):
            setting_type = "farm"
        else:
            setting_type = "general"

        return {
            "location": location_text,
            "locality": locality,
            "state": state,
            "audience": audience.strip(),
            "scenario": scenario_text,
            "scenario_concept": scenario_concept,
            "setting_type": setting_type,
            "concerns": concerns,
            "timeframe": timeframe,
            "timeframe_concept": timeframe_concept,
            "extra_context": extra_context.strip(),
        }
