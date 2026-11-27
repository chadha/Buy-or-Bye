"""Shared test setup.

Tests must never read or write the developer's real idealo usage counter
(~/.buyorbye/idealo_usage.json, the daily call budget): every test gets its own file.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_idealo_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("IDEALO_USAGE_FILE", str(tmp_path / "idealo_usage.json"))
    monkeypatch.delenv("IDEALO_DAILY_LIMIT", raising=False)
    monkeypatch.delenv("IDEALO_PRICE_CHECK_RESERVE", raising=False)
