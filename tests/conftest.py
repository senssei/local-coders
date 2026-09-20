"""Keep the suite hermetic: no real routing files, and no discovery cache hiding what a test just changed."""

import pytest


@pytest.fixture(autouse=True)
def _hermetic_environment(monkeypatch):
    monkeypatch.setenv("LOCAL_CODER_ROUTING", "none")
    monkeypatch.setenv("LOCAL_CODER_DISCOVERY_TTL", "0")
