"""Keep the suite hermetic: never pick up the developer's real routing files."""

import pytest


@pytest.fixture(autouse=True)
def _no_routing_files(monkeypatch):
    monkeypatch.setenv("LOCAL_CODER_ROUTING", "none")
