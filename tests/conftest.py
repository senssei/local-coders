"""Keep the suite hermetic: no real routing files, and no discovery cache hiding what a test just changed."""

import pytest


@pytest.fixture(autouse=True)
def _hermetic_environment(monkeypatch):
    monkeypatch.setenv("LOCAL_CODER_ROUTING", "none")
    monkeypatch.setenv("LOCAL_CODER_DISCOVERY_TTL", "0")


@pytest.fixture(autouse=True)
def _no_perf_recording(monkeypatch, tmp_path):
    """Tests must not write the developer's real performance state."""
    monkeypatch.setenv("LOCAL_CODER_PERF", "0")
    monkeypatch.setenv("LOCAL_CODER_STATE_DIR", str(tmp_path / "state"))
