"""Settings from the environment. The API key is validated but never echoed."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_API_BASE = "https://api.macropulse.live"
SIGNUP_URL = "https://macropulse.live"
PRICING_URL = "https://macropulse.live/#pricing"

KEY_ENV = "MACROPULSE_API_KEY"
BASE_ENV = "MACROPULSE_API_BASE"

_MAX_KEY_LENGTH = 256
# Issued keys are mp_ + token_urlsafe(32) (46 chars); owner/legacy keys have no fixed
# format, so only a floor is enforced, not the prefix.
_MIN_KEY_LENGTH = 16
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class ConfigError(ValueError):
    """The environment cannot be used as given. Messages never contain secrets."""


@dataclass(frozen=True)
class Settings:
    api_base: str
    api_key: str | None
    # Set when MACROPULSE_API_KEY is present but unusable; shown instead of "missing key".
    api_key_problem: str | None


def load_settings(env: Mapping[str, str]) -> Settings:
    api_key, problem = _parse_key(env.get(KEY_ENV, ""))
    return Settings(
        api_base=_parse_base(env.get(BASE_ENV, "") or DEFAULT_API_BASE),
        api_key=api_key,
        api_key_problem=problem,
    )


def _parse_key(raw: str) -> tuple[str | None, str | None]:
    stripped = raw.strip()
    key = _unquote(stripped)
    # Never include the value in a message; its length is safe to report.
    fix = f"Copy the key again from {SIGNUP_URL}."
    if not key:
        if stripped:
            return None, f"{KEY_ENV} is set to empty quotes. {fix}"
        return None, None
    if len(key) < _MIN_KEY_LENGTH:
        return None, (
            f"{KEY_ENV} is too short to be a MacroPulse key ({len(key)} characters; keys "
            f"have at least {_MIN_KEY_LENGTH}). {fix}"
        )
    if len(key) > _MAX_KEY_LENGTH:
        return None, (
            f"{KEY_ENV} is too long to be a MacroPulse key ({len(key)} characters; the "
            f"limit is {_MAX_KEY_LENGTH}). {fix}"
        )
    # Printable ASCII without spaces: anything else cannot be a MacroPulse key and,
    # in a header, could smuggle extra lines.
    if not all("!" <= ch <= "~" for ch in key):
        return None, (
            f"{KEY_ENV} contains spaces, line breaks or non-ASCII characters, which a "
            f"MacroPulse key never has. {fix}"
        )
    return key, None


def _unquote(value: str) -> str:
    """Drop one pair of matching surrounding quotes.

    Windows `set KEY="..."` and hand-written .env or JSON configs keep the quotes;
    a key never starts or ends with one, so stripping a symmetric pair is safe.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1].strip()
    return value


def _parse_base(raw: str) -> str:
    base = raw.strip().rstrip("/")
    parts = urlsplit(base)
    host = parts.hostname or ""
    secure = parts.scheme == "https" or (parts.scheme == "http" and host in _LOCAL_HOSTS)
    if not host or not secure or parts.username or parts.password or parts.query or parts.fragment:
        raise ConfigError(
            f"{BASE_ENV} must be an https:// URL without credentials or query string "
            "(plain http:// is only allowed for localhost). Unset it to use "
            f"{DEFAULT_API_BASE}."
        )
    return base
