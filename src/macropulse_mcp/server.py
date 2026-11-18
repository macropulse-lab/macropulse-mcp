"""MacroPulse MCP server (stdio).

Exposes the MacroPulse daily macro regime as read-only MCP tools. Public tools
work without credentials; the rest read MACROPULSE_API_KEY from the environment.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import logging
import os
import sys
from collections.abc import Awaitable
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from macropulse_mcp import __version__
from macropulse_mcp.client import Auth, MacroPulseClient, MacroPulseError
from macropulse_mcp.config import (
    BASE_ENV,
    DEFAULT_API_BASE,
    KEY_ENV,
    SIGNUP_URL,
    ConfigError,
    load_settings,
)
from macropulse_mcp.regimes import EXPLANATION

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
MacroPulse classifies each US trading day into one of four macro regimes
(expansion, recovery, tightening, risk_off) with a frozen v4 model (PCA plus a
Statistical Jump Model) that runs once a day at 21:00 UTC. Start with
get_current_regime; call explain_regimes to describe what the regimes mean.
The data is informational, not investment advice: report it as MacroPulse's
classification, not as a forecast of returns. Tools marked as needing a key
read MACROPULSE_API_KEY; if a call fails, relay the error text to the user,
since it says how to get or upgrade a key."""

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)
OFFLINE = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)

HistoryLimit = Annotated[
    int, Field(ge=1, le=1000, description="Rows to return, newest first (Free plan: max 30).")
]
Horizon = Annotated[int, Field(ge=1, le=10, description="Business days ahead (1-10).")]
LiquidityLimit = Annotated[int, Field(ge=1, le=500, description="Rows to return (1-500).")]
OptionalDate = Annotated[dt.date | None, Field(description="YYYY-MM-DD, inclusive.")]


async def _fetch(call: Awaitable[Any]) -> Any:
    try:
        return await call
    except MacroPulseError as exc:
        raise ToolError(str(exc)) from None


def _expect_dict(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ToolError("MacroPulse returned an unexpected response shape. Try again later.")
    return body


def create_server(client: MacroPulseClient) -> MCPServer:
    server = MCPServer(
        name="macropulse",
        title="MacroPulse",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://macropulse.live",
    )

    @server.tool(annotations=READ_ONLY)
    async def get_current_regime() -> dict[str, Any]:
        """Today's macro regime: label, risk score, target equity exposure for that
        regime and a one-line plain-English interpretation. Updated once a day after
        21:00 UTC. No API key needed."""
        return _expect_dict(await _fetch(client.get("/v1/public/regime", auth=Auth.PUBLIC)))

    @server.tool(annotations=READ_ONLY)
    async def get_signed_regime() -> dict[str, Any]:
        """The current regime as MacroPulse's signed payload: timestamp, regime,
        regime_id (0 expansion, 1 recovery, 2 tightening, 3 risk_off), risk score,
        the four regime probabilities, model version and `signature`. The signature
        is Ed25519 (base64) over the canonical JSON (sorted keys, no whitespace) of
        the payload without the `signature` field. Returned exactly as served; this
        tool does not verify the signature. No API key needed."""
        return _expect_dict(await _fetch(client.get("/v1/regime/current", auth=Auth.PUBLIC)))

    @server.tool(annotations=READ_ONLY)
    async def get_market_snapshot() -> dict[str, Any]:
        """Latest snapshot: most likely regime with confidence, days in the regime
        (persistence) and risk score, the net Fed liquidity z-score and trend, and the
        regime's target equity exposure as a fraction. No API key needed."""
        return _expect_dict(await _fetch(client.get("/v1/public/latest", auth=Auth.PUBLIC)))

    @server.tool(annotations=OFFLINE)
    def explain_regimes() -> dict[str, Any]:
        """What the four MacroPulse regimes mean, their regime_id and target equity
        exposure (100% / 75% / 25% / 0%), and how and when the model runs. Static
        reference text; makes no network call."""
        return copy.deepcopy(EXPLANATION)

    @server.tool(annotations=READ_ONLY)
    async def get_regime_history(
        limit: HistoryLimit = 30,
        start: OptionalDate = None,
        end: OptionalDate = None,
    ) -> dict[str, Any]:
        """Daily regime history, newest first: regime, risk score and the four regime
        probabilities per day. Needs MACROPULSE_API_KEY; the free plan works and
        returns at most 30 rows."""
        if start and end and start > end:
            raise ToolError("start must be on or before end.")
        params: dict[str, str | int] = {"limit": limit}
        if start:
            params["start"] = start.isoformat()
        if end:
            params["end"] = end.isoformat()
        body = await _fetch(client.get("/v1/regime/history", auth=Auth.KEY, params=params))
        if not isinstance(body, list):
            raise ToolError("MacroPulse returned an unexpected response shape. Try again later.")
        return {"count": len(body), "rows": body}

    @server.tool(annotations=READ_ONLY)
    async def get_forecast(horizon: Horizon = 5) -> dict[str, Any]:
        """Statistical (ARIMA) projection of the four regime probabilities and the risk
        score for the next 1-10 business days. A model extrapolation, not a prediction
        of prices. Needs MACROPULSE_API_KEY on the Starter or Pro plan."""
        call = client.get("/v1/forecast", auth=Auth.PAID, params={"horizon": horizon})
        return _expect_dict(await _fetch(call))

    @server.tool(annotations=READ_ONLY)
    async def get_scorecard() -> dict[str, Any]:
        """Macro scorecard: five normalized macro signals on a -1 to 1 scale. Needs
        MACROPULSE_API_KEY on the Starter or Pro plan."""
        return _expect_dict(await _fetch(client.get("/v1/scorecard", auth=Auth.PAID)))

    @server.tool(annotations=READ_ONLY)
    async def get_liquidity(limit: LiquidityLimit = 30) -> dict[str, Any]:
        """Net Fed liquidity time series (Fed balance sheet minus Treasury General
        Account minus reverse repo). Needs MACROPULSE_API_KEY on the Starter or Pro
        plan."""
        call = client.get("/v1/liquidity", auth=Auth.PAID, params={"limit": limit})
        return _expect_dict(await _fetch(call))

    return server


# Exit status for "can't start: configuration", distinct from a crash (1).
EXIT_CONFIG = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="macropulse-mcp",
        description="MCP server (stdio) for the MacroPulse daily macro regime.",
        epilog=(
            f"Public tools work without a key. For history, forecast, scorecard and "
            f"liquidity set {KEY_ENV} (free key at {SIGNUP_URL}). {BASE_ENV} overrides "
            f"the API URL (default {DEFAULT_API_BASE})."
        ),
    )
    parser.add_argument("--version", action="version", version=f"macropulse-mcp {__version__}")
    return parser


def main(argv: list[str] | None = None) -> None:
    """Console entry point. stdout carries the MCP protocol: messages go to stderr."""
    _parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(message)s")
    try:
        settings = load_settings(os.environ)
    except ConfigError as exc:
        print(f"macropulse-mcp: invalid configuration: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    if settings.api_key_problem:
        print(f"macropulse-mcp: {settings.api_key_problem}", file=sys.stderr)
    client = MacroPulseClient(settings)
    key_state = "set" if client.has_key else f"not set (public tools only; {SIGNUP_URL})"
    print(f"macropulse-mcp {__version__}: API key: {key_state}", file=sys.stderr)
    try:
        create_server(client).run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
