"""Optional read-only smoke test against the public production API, without a key.

Skipped unless MACROPULSE_LIVE_SMOKE=1. Never uses an API key.
"""

from __future__ import annotations

import os

import pytest

from macropulse_mcp.client import Auth, MacroPulseClient
from macropulse_mcp.config import DEFAULT_API_BASE, Settings

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("MACROPULSE_LIVE_SMOKE") != "1",
        reason="set MACROPULSE_LIVE_SMOKE=1 to hit the public production API",
    ),
]

REGIMES = {"expansion", "recovery", "tightening", "risk_off"}


def _keyless_client() -> MacroPulseClient:
    return MacroPulseClient(Settings(api_base=DEFAULT_API_BASE, api_key=None, api_key_problem=None))


async def test_public_regime() -> None:
    body = await _keyless_client().get("/v1/public/regime", auth=Auth.PUBLIC)

    assert body["regime"] in REGIMES
    assert body["equity_exposure"] in {"100%", "75%", "25%", "0%"}


async def test_signed_regime() -> None:
    body = await _keyless_client().get("/v1/regime/current", auth=Auth.PUBLIC)

    assert body["macro_regime"] in REGIMES
    assert body["regime_id"] in {0, 1, 2, 3}
    assert isinstance(body["signature"], str) and body["signature"]
