import pytest

from src.agents.pipeline import _resolve_effective_profile
from src.agents.profile_agent import ProfileAgent
from src.data_artifacts import DataArtifactError


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("Victoria Park, WA", "Western Australia"),
        ("Victoria River, NT", "Northern Territory"),
        ("Queensland Road, Perth, WA", "Western Australia"),
        ("Victoria Road, Sydney, NSW 2000", "New South Wales"),
        ("Victoria Park WA 6100, Australia", "Western Australia"),
        ("Queensland Road, Perth, Western Australia", "Western Australia"),
        ("Albany, Queensland", "Queensland"),
        ("Albany, WA", "Western Australia"),
        ("Canberra", "Australian Capital Territory"),
        ("South Australia", "South Australia"),
        ("Victoria Park", "Australia"),
        ("Cairns Queensland", "Queensland"),
        ("Sydney New South Wales", "New South Wales"),
        ("Perth Western Australia 6000", "Western Australia"),
        ("Perth Western Australia", "Western Australia"),
        ("Hobart Tasmania", "Tasmania"),
        ("Darwin Northern Territory", "Northern Territory"),
        ("Canberra Australian Capital Territory 2600 Australia", "Australian Capital Territory"),
        ("Adelaide South Australia 5000 Australia", "South Australia"),
        ("Ballarat Victoria Australia", "Victoria"),
        ("Queensland Road", "Australia"),
        ("Victoria Road", "Australia"),
        ("Western Australia Road", "Australia"),
        ("Queensland Road Perth Western Australia 6000 Australia", "Western Australia"),
        ("Victoria Park Western Australia", "Western Australia"),
        ("Victoria River Northern Territory", "Northern Territory"),
    ],
)
def test_explicit_address_components_override_state_words_inside_place_names(location, expected):
    profile = ProfileAgent().run(location, "Community", "Community preparedness", [], "7-day action plan", "")
    assert profile["state"] == expected


@pytest.mark.parametrize(
    "location",
    ["Sydney, NSW, QLD", "Perth, Western Australia, Victoria", "NSW / QLD", "Cairns Queensland; Sydney NSW"],
)
def test_conflicting_explicit_states_require_disambiguation(location):
    with pytest.raises(DataArtifactError) as caught:
        ProfileAgent()._resolve_location(location)
    assert caught.value.code == "geography_ambiguous"


def test_corrected_place_state_is_consistent_with_an_explicit_map_selection():
    locality, state = ProfileAgent()._resolve_location("Victoria Park, WA")
    profile = {"locality": locality, "state": state}
    selected = {"state": "Western Australia", "area_name": "Victoria Park"}
    assert _resolve_effective_profile(profile, selected)["state"] == "Western Australia"
    with pytest.raises(DataArtifactError) as caught:
        _resolve_effective_profile(profile, {**selected, "state": "Victoria"})
    assert caught.value.code == "geography_mismatch"
