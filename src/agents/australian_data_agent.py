from pathlib import Path

from src.agents.profile_agent import STATE_SHORT
from src.data_artifacts import load_yaml_mapping
from src.data_paths import get_data_paths


class AustralianDataAgent:
    """Selects relevant Australian official sources from local metadata."""

    def __init__(self, source_path=None, data_paths=None):
        self.data_paths = data_paths or get_data_paths()
        self.source_path = Path(source_path) if source_path else self.data_paths.official_sources

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
        data = load_yaml_mapping(self.source_path, label="official-source register")
        return data.get("sources", [])

    def _profile_tags(self, profile):
        tags = {"australia"}

        # Use resolved state from ProfileAgent output when available
        state = profile.get("state", "")
        if state and state != "Australia":
            tags.add(state.lower().replace(" ", "_"))
            short = STATE_SHORT.get(state.lower())
            if short:
                tags.add(short)

        # Locality-level tag (e.g. "cairns")
        locality = profile.get("locality", "").lower()
        if locality:
            tags.add(locality)

        return tags
