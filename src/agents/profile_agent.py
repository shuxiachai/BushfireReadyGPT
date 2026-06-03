class ProfileAgent:
    """Normalizes user form inputs into a compact analysis profile."""

    def run(self, location, audience, scenario, concerns, timeframe, extra_context):
        location_text = location.strip()
        scenario_text = scenario.strip()
        lower_location = location_text.lower()
        lower_scenario = scenario_text.lower()

        state = "Queensland" if "queensland" in lower_location or "cairns" in lower_location else "Australia"
        locality = "Cairns" if "cairns" in lower_location else location_text

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
