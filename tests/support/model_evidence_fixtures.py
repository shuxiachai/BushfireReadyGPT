"""Pure analysis fixtures shared by evidence-focused tests."""


def _analysis(*chunks):
    return {
        "profile": {
            "state": "Queensland",
            "scenario_concept": {"id": "community_workshop"},
            "timeframe_concept": {"id": "seven_day"},
        },
        "knowledge": {"status": "ready", "retrieved_chunks": list(chunks)},
        "data": {"sources": [{"id": "one", "name": "Official One"}, {"id": "two", "name": "Official Two"}]},
    }
