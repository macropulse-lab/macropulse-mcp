"""Environment parsing: base URL safety and API key hygiene."""

from __future__ import annotations

import pytest

from macropulse_mcp.config import DEFAULT_API_BASE, ConfigError, load_settings

from .conftest import FAKE_KEY


def test_defaults_to_production_without_key() -> None:
    settings = load_settings({})

    assert settings.api_base == DEFAULT_API_BASE == "https://api.macropulse.live"
    assert settings.api_key is None
    assert settings.api_key_problem is None


def test_reads_and_trims_the_key() -> None:
    settings = load_settings({"MACROPULSE_API_KEY": f"  {FAKE_KEY}\n"})

    assert settings.api_key == FAKE_KEY


def test_blank_key_counts_as_no_key() -> None:
    assert load_settings({"MACROPULSE_API_KEY": "   "}).api_key is None


@pytest.mark.parametrize(
    "bad_key",
    ["mp_abc def", "mp_abc\r\nX-Injected: 1", "mp_\x00abc", "mp_ñandú", "mp_" + "a" * 300],
)
def test_malformed_key_is_dropped_and_explained_without_echoing_it(bad_key: str) -> None:
    settings = load_settings({"MACROPULSE_API_KEY": bad_key})

    assert settings.api_key is None
    assert settings.api_key_problem is not None
    assert "MACROPULSE_API_KEY" in settings.api_key_problem
    assert bad_key.strip() not in settings.api_key_problem


@pytest.mark.parametrize(
    "base",
    [
        "https://api.macropulse.live/",
        "http://localhost:8000",
        "http://127.0.0.1:8000/",
    ],
)
def test_accepts_https_or_local_http(base: str) -> None:
    assert load_settings({"MACROPULSE_API_BASE": base}).api_base == base.rstrip("/")


@pytest.mark.parametrize(
    "base",
    [
        "http://api.macropulse.live",  # the key would travel in clear text
        "ftp://api.macropulse.live",
        "https://user:pass@api.macropulse.live",
        "https://api.macropulse.live/?x=1",
        "api.macropulse.live",
        "https://",
    ],
)
def test_rejects_unsafe_base_urls(base: str) -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_settings({"MACROPULSE_API_BASE": base})

    assert "MACROPULSE_API_BASE" in str(excinfo.value)
    assert "pass" not in str(excinfo.value)
