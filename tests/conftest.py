"""Unit/regression tests never depend on live external services."""
import pytest

@pytest.fixture(autouse=True)
def block_external_requests(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Live network is forbidden in pytest; use mocked fixtures or a separate live probe')
    monkeypatch.setattr('requests.sessions.Session.request',blocked)
