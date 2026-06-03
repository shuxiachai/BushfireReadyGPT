class ReportAgent:
    """Formats deterministic multi-agent findings for the LLM report prompt."""

    def run(self, profile, data_result, risk_context, plan_result, community_result=None):
        community_result = community_result or {}
        community_lines = self._format_community_result(community_result)
        lines = [
            "Local multi-agent analysis summary:",
            "",
            "Profile Agent:",
            f"- Location: {profile['location']}",
            f"- State / territory inference: {profile['state']}",
            f"- Scenario type: {profile['setting_type']}",
            f"- Audience: {profile['audience']}",
            f"- Timeframe: {profile['timeframe']}",
            "",
            "Risk Context Agent:",
            *[f"- {item}" for item in risk_context.get("risk_points", [])],
            "",
            "Community Vulnerability Agent:",
            *community_lines,
            "",
            "Australian Data Agent:",
            *[
                f"- {source['name']}: {source['purpose']} ({source['url']})"
                for source in data_result.get("sources", [])
            ],
            "",
            "Planner Agent:",
            *[f"- {item}" for item in plan_result.get("planning_priorities", [])],
            "",
            "Data limitations:",
            *[f"- {item}" for item in data_result.get("data_limitations", [])],
        ]
        if community_result.get("data_source_note"):
            lines.append(f"- {community_result['data_source_note']}")
        geography_reference_lines = self._format_geography_reference(community_result.get("geography_reference", {}))
        if geography_reference_lines:
            lines.extend(["", "ABS ASGS Geography Reference:", *geography_reference_lines])
        lines.extend(f"- {item}" for item in risk_context.get("assumptions", []))
        return "\n".join(lines)

    def _format_community_result(self, community_result):
        lines = []
        matched_location = community_result.get("matched_location")
        if matched_location:
            lines.append(f"- Matched community profile: {matched_location}")
        else:
            lines.append("- No matching community profile row found.")

        indicators = community_result.get("indicators", {})
        if indicators:
            lines.extend(
                [
                    f"- Population: {indicators.get('population')}",
                    f"- Older people percentage: {indicators.get('older_people_pct')}%",
                    f"- No-car households percentage: {indicators.get('no_car_households_pct')}%",
                    f"- Language support need: {indicators.get('language_support_needed')}",
                ]
            )
            if indicators.get("language_other_than_english_pct"):
                lines.append(
                    f"- Language other than English at home: {indicators.get('language_other_than_english_pct')}%"
                )
            if indicators.get("geography_type"):
                lines.append(f"- Geography mapping: {indicators.get('geography_type')}")
            if indicators.get("matched_sa2_count"):
                lines.append(f"- Matched SA2 count: {indicators.get('matched_sa2_count')}")

        lines.extend(f"- {note}" for note in community_result.get("vulnerability_notes", []))
        return lines

    def _format_geography_reference(self, geography_reference):
        if not geography_reference:
            return []

        lines = []
        selected = geography_reference.get("selected_asgs_area")
        if selected:
            lines.extend(
                [
                    f"- Selected ASGS area: {selected.get('selected_level')} {selected.get('selected_area')} ({selected.get('state_name')})",
                    f"- ASGS SA2 rows in selected area: {selected.get('sa2_count')}",
                    f"- SA3 reference: {selected.get('sa3_names')}",
                    f"- SA4 reference: {selected.get('sa4_names')}",
                    f"- GCCSA reference: {selected.get('gccsa_names')}",
                    f"- ASGS area reference: {selected.get('area_albers_sqkm')} sq km Albers area",
                    f"- ASGS hierarchy source file: {selected.get('source_file')}",
                ]
            )

        lga_candidates = geography_reference.get("lga_candidates", [])
        if lga_candidates:
            lines.append("- LGA 2025 candidate reference areas:")
            for item in lga_candidates:
                lines.append(
                    "  - "
                    f"{item.get('lga_name_2025')} ({item.get('state_name_2021')}), "
                    f"LGA code {item.get('lga_code_2025')}, "
                    f"area {item.get('area_albers_sqkm')} sq km"
                )

        if geography_reference.get("source_note"):
            lines.append(f"- {geography_reference.get('source_note')}")
        lines.extend(f"- {item}" for item in geography_reference.get("limitations", []))
        return lines
