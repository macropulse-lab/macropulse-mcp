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
    [
        "mp_abc def",
        "mp_abc\r\nX-Injected: 1",
        "mp_\x00abc",
        "mp_ñandú",
        "mp_" + "a" * 300,
        "mp_tooshort",  # under 16 characters
        "x" * 15,  # one under the floor
        '"mp_abc def ghi jkl"',  # quotes removed, inner spaces still rejected
    ],
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


def test_accepts_keys_in_the_issued_format() -> None:
    # macropulse api/auth.py: f"mp_{secrets.token_urlsafe(32)}" -> 46 characters.
    import secrets

    issued = f"mp_{secrets.token_urlsafe(32)}"

    assert load_settings({"MACROPULSE_API_KEY": issued}).api_key == issued


def test_accepts_a_16_character_key_without_the_mp_prefix() -> None:
    # Owner and legacy env keys have no fixed format; only the length floor applies.
    key = "x" * 16

    assert load_settings({"MACROPULSE_API_KEY": key}).api_key == key


@pytest.mark.parametrize("quote", ['"', "'"])
def test_a_quoted_key_is_unquoted(quote: str) -> None:
    key = "mp_" + "a" * 43

    settings = load_settings({"MACROPULSE_API_KEY": f"  {quote}{key}{quote} "})

    assert settings.api_key == key
    assert settings.api_key_problem is None


@pytest.mark.parametrize("raw", ['"mp_' + "a" * 43 + "'", '"mp_' + "a" * 43])
def test_unbalanced_quotes_are_not_stripped(raw: str) -> None:
    settings = load_settings({"MACROPULSE_API_KEY": raw})

    assert settings.api_key == raw


def test_a_key_padded_with_spaces_is_trimmed() -> None:
    key = "x" * 16

    assert load_settings({"MACROPULSE_API_KEY": f" {key} "}).api_key == key


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("x" * 15, "too short"),
        ("x" * 257, "too long"),
        ("mp_" + "a" * 20 + " b", "spaces"),
    ],
)
def test_the_problem_names_its_cause_and_length_but_not_the_key(raw: str, reason: str) -> None:
    problem = load_settings({"MACROPULSE_API_KEY": raw}).api_key_problem

    assert problem is not None
    assert reason in problem
    assert raw not in problem
    if reason != "spaces":
        assert f"{len(raw)} characters" in problem
