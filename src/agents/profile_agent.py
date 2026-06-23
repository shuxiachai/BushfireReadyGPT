from pathlib import Path

import yaml

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

    _REGION_MAPPINGS_PATH = "data_australia/region_mappings.yml"

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
        "New South Wales": ["sydney", "newcastle", "wollongong", "central coast"],
        "Victoria": ["melbourne", "geelong", "ballarat", "bendigo"],
        "Queensland": ["brisbane", "gold coast", "sunshine coast"],
        "Western Australia": ["perth", "fremantle", "bunbury"],
        "South Australia": ["adelaide", "port augusta", "mount gambier"],
        "Tasmania": ["hobart", "launceston", "devonport"],
        "Northern Territory": ["darwin", "alice springs", "katherine"],
    }

    def __init__(self):
        self._region_map = self._load_region_map()

    def _load_region_map(self):
        path = Path(self._REGION_MAPPINGS_PATH)
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        result = {}
        for region in data.get("regions", []):
            locality = region.get("location", "")
            state = region.get("state", "Australia")
            result[locality.lower()] = {"locality": locality, "state": state}
        return result

    def _resolve_location(self, location_text):
        lower = location_text.lower()
        # Tier 1: configured locality from region_mappings.yml
        for key, info in self._region_map.items():
            if key in lower:
                return info["locality"], info["state"]
        # Tier 2: state name or postal code in the location string
        for state, keywords in self._STATE_KEYWORDS.items():
            if any(kw in lower for kw in keywords):
                return location_text, state
        # Tier 3: major city names
        for state, cities in self._CITY_KEYWORDS.items():
            if any(city in lower for city in cities):
                return location_text, state
        return location_text, "Australia"

    def run(self, location, audience, scenario, concerns, timeframe, extra_context):
        location_text = location.strip()
        scenario_text = scenario.strip()
        lower_scenario = scenario_text.lower()

        locality, state = self._resolve_location(location_text)

        if any(keyword in lower_scenario for keyword in ["campus", "school", "university"]):
            setting_type = "campus"
        elif any(keyword in lower_scenario for keyword in ["community", "resident"]):
            setting_type = "community"
        elif any(keyword in lower_scenario for keyword in ["aged care", "nursing"]):
            setting_type = "aged_care"
        else:
            setting_type = "general"

        return {
            "location": location_text,
            "locality": locality,
            "state": state,
            "audience": audience.strip(),
            "scenario": scenario_text,
            "setting_type": setting_type,
            "concerns": concerns,
            "timeframe": timeframe,
            "extra_context": extra_context.strip(),
        }
