import pytest

from src.agents.australian_data_agent import AustralianDataAgent
from src.agents.profile_agent import ProfileAgent
from src.agents.risk_context_agent import RiskContextAgent
from src.data_artifacts import DataArtifactError, load_yaml_mapping


def _assert_schema_error(caught, path, field_path):
    assert caught.value.code == "artifact_schema_invalid"
    assert caught.value.relative_path == str(path)
    assert field_path in str(caught.value)


def test_profile_agent_converts_scalar_region_record_to_domain_error(tmp_path):
    region_path = tmp_path / "region_mappings.yml"
    region_path.write_text("regions:\n  - malformed\n", encoding="utf-8")

    with pytest.raises(DataArtifactError) as caught:
        ProfileAgent(region_mappings_path=region_path)

    _assert_schema_error(caught, region_path, "regions[0]")


def test_australian_data_agent_converts_mapping_source_collection_to_domain_error(tmp_path):
    source_path = tmp_path / "official_sources.yml"
    source_path.write_text("sources:\n  name: malformed\n", encoding="utf-8")
    agent = AustralianDataAgent(source_path=source_path)

    with pytest.raises(DataArtifactError) as caught:
        agent.run({"state": "Queensland", "locality": "Cairns"})

    _assert_schema_error(caught, source_path, "sources")


def test_risk_context_agent_converts_list_match_to_domain_error(tmp_path):
    rules_path = tmp_path / "risk_context_rules.yml"
    rules_path.write_text(
        "rules:\n  - id: malformed\n    match: []\n",
        encoding="utf-8",
    )
    agent = RiskContextAgent(rules_path=rules_path)

    with pytest.raises(DataArtifactError) as caught:
        agent.run({"location": "Cairns", "state": "Queensland", "scenario": "campus"})

    _assert_schema_error(caught, rules_path, "rules[0].match")


def test_risk_context_agent_converts_scalar_string_list_to_domain_error(tmp_path):
    rules_path = tmp_path / "risk_context_rules.yml"
    rules_path.write_text(
        "rules:\n  - id: malformed\n    match:\n      states: Queensland\n",
        encoding="utf-8",
    )
    agent = RiskContextAgent(rules_path=rules_path)

    with pytest.raises(DataArtifactError) as caught:
        agent.run({"location": "Cairns", "state": "Queensland", "scenario": "campus"})

    _assert_schema_error(caught, rules_path, "rules[0].match.states")


@pytest.mark.parametrize("document", ["[]\n", "false\n", "0\n"])
def test_falsy_non_mapping_yaml_remains_invalid(document, tmp_path):
    artifact_path = tmp_path / "artifact.yml"
    artifact_path.write_text(document, encoding="utf-8")

    with pytest.raises(DataArtifactError) as caught:
        load_yaml_mapping(artifact_path)

    assert caught.value.code == "artifact_invalid"
    assert caught.value.relative_path == str(artifact_path)


def test_empty_yaml_keeps_existing_empty_mapping_semantics(tmp_path):
    artifact_path = tmp_path / "artifact.yml"
    artifact_path.write_text("", encoding="utf-8")

    assert load_yaml_mapping(artifact_path) == {}


@pytest.mark.parametrize(
    ("label", "document", "field_path"),
    [
        (
            "official-source register",
            "sources:\n  - id: duplicate\n    name: First\n    purpose: Test\n    url: https://example.gov.au/1\n"
            "  - id: duplicate\n    name: Second\n    purpose: Test\n    url: https://example.gov.au/2\n",
            "sources[1].id",
        ),
        (
            "risk-context rules",
            "rules:\n  - id: duplicate\n  - id: duplicate\n",
            "rules[1].id",
        ),
    ],
)
def test_yaml_record_identifiers_must_be_unique(tmp_path, label, document, field_path):
    artifact_path = tmp_path / "artifact.yml"
    artifact_path.write_text(document, encoding="utf-8")

    with pytest.raises(DataArtifactError) as caught:
        load_yaml_mapping(artifact_path, label=label)

    _assert_schema_error(caught, artifact_path, field_path)


def test_required_yaml_strings_must_not_be_blank(tmp_path):
    artifact_path = tmp_path / "official_sources.yml"
    artifact_path.write_text(
        "sources:\n  - name: '  '\n    purpose: Test\n    url: https://example.gov.au\n",
        encoding="utf-8",
    )

    with pytest.raises(DataArtifactError) as caught:
        load_yaml_mapping(artifact_path, label="official-source register")

    _assert_schema_error(caught, artifact_path, "sources[0].name")
