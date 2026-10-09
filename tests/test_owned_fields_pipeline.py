"""Exercise frozen field assembly against the bundled deterministic pipeline."""

import socket
from copy import deepcopy

import pytest

from src.agents import run_analysis_pipeline
from src.report_content_contract import evaluate_report_content_contract
from src.report_owned_fields import build_owned_field_spec, owned_fields_budget, render_owned_blocks


@pytest.mark.parametrize(
    "location",
    [
        "Cairns, Queensland",
        "Sydney, New South Wales",
        "Melbourne, Victoria",
        "Perth, Western Australia",
        "Adelaide, South Australia",
        "Hobart, Tasmania",
        "Darwin, Northern Territory",
        "Canberra, Australian Capital Territory",
        "Unrecognised locality",
    ],
)
def test_bundled_pipeline_fields_keep_provenance_unknowns_and_body_budget(monkeypatch, location):
    def forbid_network(*_args, **_kwargs):
        pytest.fail("The deterministic field check must not contact a model or network service.")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    monkeypatch.setattr(socket, "create_connection", forbid_network)
    analysis = run_analysis_pipeline(
        location,
        "Synthetic participants",
        "Community workshop material",
        ["Evacuation planning", "Communication and warnings"],
        "7-day action plan",
        "",
    )
    frozen = deepcopy(analysis)
    spec = build_owned_field_spec(analysis)
    blocks = render_owned_blocks(spec)
    provenance = next(
        check
        for check in evaluate_report_content_contract(blocks["p2"], analysis)
        if check["name"] == "Processed community provenance"
    )
    assert provenance["status"] == "pass"
    for measurement in spec.measurements:
        if measurement.value is not None:
            assert measurement.value in blocks["p2"]
    if any(measurement.value is None for measurement in spec.measurements):
        assert "unknown, not measured in the supplied snapshot [P2]" in blocks["p2"]
    budget = owned_fields_budget(analysis)
    assert budget["owned_word_count"] + budget["model_body_min_words"] >= 650
    assert budget["owned_word_count"] + budget["model_body_max_words"] == 800
    assert 300 <= budget["model_body_min_words"] <= budget["model_body_max_words"]
    assert analysis == frozen
