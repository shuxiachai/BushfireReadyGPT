from pathlib import Path

import yaml


class AustralianDataAgent:
    """Selects relevant Australian official sources from local metadata."""

    def __init__(self, source_path="data_australia/official_sources.yml"):
        self.source_path = Path(source_path)

    def run(self, profile):
        sources = self._load_sources()
        tags = self._profile_tags(profile)
        selected = []

        for source in sources:
            source_tags = set(source.get("scope", []))
            if source_tags.intersection(tags) or "australia" in source_tags:
                selected.append(source)

        return {
            "sources": selected,
            "data_limitations": [
                "The current prototype uses local metadata for official sources and does not read live warning feeds.",
                "Official websites must be checked for current warnings, fire bans, evacuation instructions, and severe weather updates.",
            ],
        }

    def _load_sources(self):
        with open(self.source_path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        return data.get("sources", [])

    def _profile_tags(self, profile):
        tags = {"australia"}
        location = profile["location"].lower()
        scenario = profile["scenario"].lower()

        if "queensland" in location or "qld" in location or "cairns" in location:
            tags.add("queensland")
        if "cairns" in location:
            tags.add("cairns")
        if "campus" in scenario or "school" in scenario or "university" in scenario:
            tags.add("preparedness")
        if "community" in scenario:
            tags.add("local")
        tags.update({"warnings", "disaster", "weather", "fire"})
        return tags
