"""HTTP access to the MacroPulse API.

Every failure becomes a `MacroPulseError` with a single, user-facing line that says
what to do next. The API key travels only in the `X-MacroPulse-Key` header, is never
logged, and is scrubbed from everything that comes back from the server, successful
bodies included.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import re
from typing import Any

import httpx

from macropulse_mcp import __version__
from macropulse_mcp.config import BASE_ENV, KEY_ENV, PRICING_URL, SIGNUP_URL, Settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
# Hard cap on one call, whatever the per-phase timeouts allow (slow-drip bodies).
DEFAULT_DEADLINE_SECONDS = 15.0
_DETAIL_MAX = 160
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_REDACTED = "[redacted]"


class Auth(enum.Enum):
    """What an endpoint needs, as documented in the MacroPulse API README."""

    PUBLIC = "public"
    KEY = "key"  # any key, the free plan included
    PAID = "paid"  # Starter or Pro


class MacroPulseError(Exception):
    """A failure the agent (and its user) can act on. The message is one line."""


_NO_KEY = {
    Auth.KEY: (
        "This tool needs a MacroPulse API key (the free plan works). Get one free at "
        f"{SIGNUP_URL} and set {KEY_ENV} in this MCP server's environment."
    ),
    Auth.PAID: (
        "This tool needs a MacroPulse API key on the Starter or Pro plan. Get a free key at "
        f"{SIGNUP_URL}, upgrade at {PRICING_URL}, and set {KEY_ENV} in this MCP server's "
        "environment."
    ),
}

IP_LOCKED_MESSAGE = (
    "Your key is bound to another IP address; wait 15 minutes of inactivity or use a "
    f"paid plan ({PRICING_URL})."
)


class MacroPulseClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self.timeout = timeout
        self.deadline_seconds = deadline_seconds

    @property
    def has_key(self) -> bool:
        return self._settings.api_key is not None

    async def get(
        self,
        path: str,
        *,
        auth: Auth,
        params: dict[str, str | int] | None = None,
    ) -> Any:
        """GET `path` and return the parsed JSON body, or raise `MacroPulseError`."""
        headers = {"User-Agent": f"macropulse-mcp/{__version__}", "Accept": "application/json"}
        if auth is not Auth.PUBLIC:
            headers["X-MacroPulse-Key"] = self._require_key(auth)

        try:
            async with asyncio.timeout(self.deadline_seconds):
                response = await self._send(path, headers, params)
        except (httpx.TimeoutException, TimeoutError) as exc:
            logger.warning("GET %s timed out (%s)", path, type(exc).__name__)
            raise MacroPulseError(
                f"The MacroPulse API did not respond in time ({self.deadline_seconds:g}-second "
                "limit). Try again later."
            ) from None
        except httpx.HTTPError as exc:
            logger.warning("GET %s failed (%s)", path, type(exc).__name__)
            raise MacroPulseError(
                f"Could not reach the MacroPulse API at {self._settings.api_base}. "
                "Check the network connection and try again."
            ) from None

        logger.debug("GET %s -> HTTP %d", path, response.status_code)
        if not response.is_success:
            raise MacroPulseError(self._scrub(_explain(response, self._settings.api_key)))
        try:
            body = response.json()
        except ValueError:
            logger.warning("GET %s returned a non-JSON body", path)
            raise MacroPulseError(
                "MacroPulse returned an unexpected response (not JSON). Try again later."
            ) from None
        return _scrub_json(body, self._settings.api_key)

    def _require_key(self, auth: Auth) -> str:
        if self._settings.api_key is None:
            raise MacroPulseError(self._settings.api_key_problem or _NO_KEY[auth])
        return self._settings.api_key

    async def _send(
        self, path: str, headers: dict[str, str], params: dict[str, str | int] | None
    ) -> httpx.Response:
        # Never follow redirects: the key header must not be replayed to another URL.
        async with httpx.AsyncClient(
            base_url=self._settings.api_base,
            timeout=self.timeout,
            transport=self._transport,
            follow_redirects=False,
        ) as http:
            return await http.get(path, headers=headers, params=params)

    def _scrub(self, text: str) -> str:
        return _scrub_text(text, self._settings.api_key)


def _scrub_text(text: str, key: str | None) -> str:
    return text.replace(key, _REDACTED) if key else text


def _scrub_json(value: Any, key: str | None) -> Any:
    """A copy of a parsed JSON value with the key removed from every string in it."""
    if not key:
        return value
    if isinstance(value, str):
        return _scrub_text(value, key)
    if isinstance(value, list):
        return [_scrub_json(item, key) for item in value]
    if isinstance(value, dict):
        return {_scrub_text(str(k), key): _scrub_json(v, key) for k, v in value.items()}
    return value


def _explain(response: httpx.Response, key: str | None) -> str:
    """Translate a non-2xx response into one actionable line."""
    status = response.status_code
    error, detail = _error_fields(response, key)
    lowered = detail.lower()

    if 300 <= status < 400:
        return (
            f"MacroPulse answered with a redirect (HTTP {status}), which this server does not "
            f"follow. Check {BASE_ENV}."
        )
    if status == 401:
        return (
            f"MacroPulse did not receive a usable API key. Check {KEY_ENV} "
            f"(free key at {SIGNUP_URL})."
        )
    if status == 402:
        return (
            "MacroPulse suspended this API key after a failed payment. Update the payment "
            "method at https://macropulse.live/dashboard."
        )
    if status == 403 and error == "ip_locked":
        return IP_LOCKED_MESSAGE
    if status == 403 and "requires" in lowered and "plan" in lowered:
        plan = "Pro plan" if "requires a pro plan" in lowered else "Starter or Pro plan"
        return (
            f"Your MacroPulse plan does not include this data: it needs the {plan}. "
            f"Upgrade at {PRICING_URL}."
        )
    if status == 403:
        return (
            f"MacroPulse rejected the API key as invalid or revoked. Check {KEY_ENV}, or "
            f"recover the key at {SIGNUP_URL}."
        )
    if status == 429:
        return (
            "MacroPulse rate limit reached for this key or address (daily limits reset at "
            f"midnight UTC). Plans with higher limits: {PRICING_URL}."
        )
    if status in (404, 503):
        return (
            f"MacroPulse has no data to serve right now (HTTP {status}). Try again later; "
            "the model publishes once a day after 21:00 UTC."
        )
    if status >= 500:
        return f"The MacroPulse API failed (HTTP {status}). Try again later."
    suffix = f": {detail}" if detail else ""
    return f"MacroPulse rejected the request (HTTP {status}){suffix}"


def _error_fields(response: httpx.Response, key: str | None) -> tuple[str, str]:
    """(`error`, `detail`) from a FastAPI-style error body, sanitized to one short line."""
    try:
        body = response.json()
    except ValueError:
        return "", ""
    if not isinstance(body, dict):
        return "", ""
    error = body.get("error")
    detail = body.get("detail")
    if isinstance(detail, list):  # FastAPI 422: [{"loc": [...], "msg": "..."}]
        detail = "; ".join(str(item.get("msg", "")) for item in detail if isinstance(item, dict))
    return _one_line(error, key), _one_line(detail, key)


def _one_line(value: object, key: str | None) -> str:
    if not isinstance(value, str):
        return ""
    # Scrub before truncating, so a key cut in half by the limit cannot survive.
    text = " ".join(_scrub_text(_CONTROL.sub(" ", value), key).split())
    return text if len(text) <= _DETAIL_MAX else text[: _DETAIL_MAX - 1] + "…"
