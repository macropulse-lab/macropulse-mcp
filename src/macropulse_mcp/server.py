"""
MacroPulse MCP server.

Exposes the MacroPulse macro regime API as MCP tools so LLMs and agent
frameworks can query the current regime, history, and forecasts natively.

Public tools work without credentials. Authenticated tools require the
MACROPULSE_API_KEY environment variable (free key: https://macropulse.live).
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API_BASE = os.environ.get("MACROPULSE_API_BASE", "https://api.macropulse.live")
API_KEY = os.environ.get("MACROPULSE_API_KEY", "")
TIMEOUT_SECONDS = 15.0

mcp = FastMCP(
    "macropulse",
    instructions=(
        "MacroPulse provides daily macro regime classification for US markets: "
        "four regimes (expansion, recovery, tightening, risk_off) derived from "
        "Fed liquidity, credit spreads, volatility, and yield curve data. "
        "Use get_current_regime for the latest signal. Authenticated tools "
        "require a MacroPulse API key (free at https://macropulse.live)."
    ),
)


def _get(path: str, *, authed: bool = False, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET a MacroPulse endpoint and return parsed JSON, raising on errors."""
    headers = {}
    if authed:
        if not API_KEY:
            raise RuntimeError(
                "This tool requires a MacroPulse API key. Set the MACROPULSE_API_KEY "
                "environment variable — get a free key at https://macropulse.live"
            )
        headers["X-MacroPulse-Key"] = API_KEY

    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        resp = client.get(f"{API_BASE}{path}", headers=headers, params=params)
        if resp.status_code == 401:
            raise RuntimeError("MacroPulse API key rejected. Check MACROPULSE_API_KEY.")
        if resp.status_code == 403:
            raise RuntimeError(
                "This endpoint requires a higher MacroPulse tier. "
                "See https://macropulse.live/pricing"
            )
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
def get_current_regime() -> dict[str, Any]:
    """Get today's macro regime classification: regime label, risk score
    (-100 to +100), suggested equity exposure, and a one-line interpretation.
    Public — no API key required."""
    return _get("/v1/public/regime")


@mcp.tool()
def get_market_snapshot() -> dict[str, Any]:
    """Get the latest public market snapshot: regime with confidence and
    persistence, net-liquidity z-score and trend, and suggested equity
    exposure. Public — no API key required."""
    return _get("/v1/public/latest")


@mcp.tool()
def get_performance_series() -> dict[str, Any]:
    """Get the public daily time series (trailing ~2 years): regime, risk
    score, S&P 500, gold, and the regime-overlay strategy — all indexed to
    100. Useful for charting or computing regime-conditioned statistics.
    Public — no API key required."""
    return _get("/v1/public/chart-data")


@mcp.tool()
def get_regime_history(days: int = 30) -> Any:
    """Get the authenticated regime history for the last N days, including
    per-day regime probabilities and risk scores. Free tier: 30-day window;
    Starter: 6 months; Pro: full history. Requires MACROPULSE_API_KEY."""
    return _get("/v1/regime/history", authed=True, params={"days": days})


@mcp.tool()
def get_forecast() -> dict[str, Any]:
    """Get the 5-day regime forecast with transition probabilities.
    Requires MACROPULSE_API_KEY (Starter tier or above)."""
    return _get("/v1/forecast", authed=True)


@mcp.tool()
def get_scorecard() -> dict[str, Any]:
    """Get the signal scorecard: hit rates, regime persistence, and signal
    quality metrics. Requires MACROPULSE_API_KEY (Starter tier or above)."""
    return _get("/v1/scorecard", authed=True)


@mcp.tool()
def get_liquidity() -> dict[str, Any]:
    """Get the Fed liquidity decomposition: net liquidity, Fed assets, TGA,
    and RRP balances with trends. Requires MACROPULSE_API_KEY (Starter tier
    or above)."""
    return _get("/v1/liquidity", authed=True)


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
