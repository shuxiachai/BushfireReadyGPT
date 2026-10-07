"""Pure analysis fixtures shared by evidence-focused tests."""


def _analysis(*chunks):
    return {
        "profile": {"state": "Queensland"},
        "knowledge": {"status": "ready", "retrieved_chunks": list(chunks)},
        "data": {"sources": [{"id": "one", "name": "Official One"}, {"id": "two", "name": "Official Two"}]},
    }
