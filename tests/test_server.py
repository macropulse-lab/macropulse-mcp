"""The MCP surface, exercised through a real in-process MCP client."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer

from macropulse_mcp import __version__
from macropulse_mcp.server import create_server

from .conftest import FAKE_KEY, FakeApi, make_client

SIGNED = {
    "timestamp": "2026-11-17T00:00:00Z",
    "macro_regime": "tightening",
    "risk_score": -13.8,
    "probabilities": {
        "expansion": 0.1288,
        "tightening": 0.6291,
        "risk_off": 0.0487,
        "recovery": 0.1933,
    },
    "volatility_state": "normal",
    "model_version": "v4",
    "regime_id": 2,
    "broadcast_time": 1794873600000,
    "signature": "c2lnbmF0dXJl",
}

EXPECTED_TOOLS = {
    "get_current_regime",
    "get_signed_regime",
    "get_market_snapshot",
    "explain_regimes",
    "get_regime_history",
    "get_forecast",
    "get_scorecard",
    "get_liquidity",
}


def server_for(api: FakeApi, api_key: str | None = FAKE_KEY) -> MCPServer:
    return create_server(make_client(api, api_key=api_key))


async def call(server: MCPServer, name: str, args: dict[str, Any] | None = None) -> Any:
    async with Client(server) as client:
        result = await client.call_tool(name, args or {})
    assert not result.is_error, result.content
    return result.structured_content


async def call_error(
    server: MCPServer, name: str, args: dict[str, Any] | None = None, *, one_line: bool = True
) -> str:
    async with Client(server) as client:
        result = await client.call_tool(name, args or {})
    assert result.is_error, result.structured_content
    text: str = result.content[0].text  # type: ignore[union-attr]
    assert "Traceback" not in text
    if one_line:  # our own messages; schema errors are formatted by the SDK
        assert "\n" not in text
    return text


async def test_tool_list_and_read_only_annotations(api: FakeApi) -> None:
    async with Client(server_for(api)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    assert set(tools) == EXPECTED_TOOLS
    for name, tool in tools.items():
        assert tool.annotations is not None, name
        assert tool.annotations.read_only_hint is True, name
        assert tool.description, name


async def test_server_reports_its_version(api: FakeApi) -> None:
    async with Client(server_for(api)) as client:
        info = client.server_info

    assert info is not None
    assert info.name == "macropulse"
    assert info.version == __version__


async def test_descriptions_make_no_performance_claims(api: FakeApi) -> None:
    async with Client(server_for(api)) as client:
        tools = (await client.list_tools()).tools
    text = " ".join((t.description or "") for t in tools).lower()

    for banned in ("alpha", "outperform", "beat the market", "sharpe", "% return", "chatgpt"):
        assert banned not in text, banned


async def test_input_schemas_carry_the_api_limits(api: FakeApi) -> None:
    async with Client(server_for(api)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    history = tools["get_regime_history"].input_schema["properties"]["limit"]
    assert (history["minimum"], history["maximum"], history["default"]) == (1, 1000, 30)
    horizon = tools["get_forecast"].input_schema["properties"]["horizon"]
    assert (horizon["minimum"], horizon["maximum"], horizon["default"]) == (1, 10, 5)
    liquidity = tools["get_liquidity"].input_schema["properties"]["limit"]
    assert (liquidity["minimum"], liquidity["maximum"], liquidity["default"]) == (1, 500, 30)


# --- public tools ------------------------------------------------------------


async def test_get_current_regime(api: FakeApi) -> None:
    api.json("/v1/public/regime", {"regime": "tightening", "equity_exposure": "25%"})

    out = await call(server_for(api, api_key=None), "get_current_regime")

    assert out == {"regime": "tightening", "equity_exposure": "25%"}
    assert api.last.url.path == "/v1/public/regime"


async def test_get_signed_regime_returns_the_payload_untouched_and_keyless(api: FakeApi) -> None:
    api.json("/v1/regime/current", SIGNED)

    out = await call(server_for(api), "get_signed_regime")

    assert out == SIGNED
    assert api.last.url.path == "/v1/regime/current"
    assert "x-macropulse-key" not in api.last.headers


async def test_get_signed_regime_does_not_claim_a_published_key(api: FakeApi) -> None:
    async with Client(server_for(api)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    description = (tools["get_signed_regime"].description or "").lower()

    assert "ed25519" in description
    assert "does not verify" in description
    assert "anyone can verify" not in description


async def test_get_market_snapshot(api: FakeApi) -> None:
    api.json("/v1/public/latest", {"date": "2026-11-17", "regime": {"most_likely": "tightening"}})

    out = await call(server_for(api, api_key=None), "get_market_snapshot")

    assert out["regime"]["most_likely"] == "tightening"
    assert api.last.url.path == "/v1/public/latest"
    assert "x-macropulse-key" not in api.last.headers


async def test_explain_regimes_is_static_and_offline(api: FakeApi) -> None:
    out = await call(server_for(api, api_key=None), "explain_regimes")

    assert api.requests == []
    exposures = {r["id"]: r["target_equity_exposure"] for r in out["regimes"]}
    assert exposures == {
        "expansion": "100%",
        "recovery": "75%",
        "tightening": "25%",
        "risk_off": "0%",
    }
    assert [r["regime_id"] for r in out["regimes"]] == [0, 1, 2, 3]
    assert "Statistical Jump Model" in out["model"]
    assert "21:00 UTC" in out["schedule"]
    assert "not investment advice" in out["disclaimer"].lower()


# --- keyed tools -------------------------------------------------------------


async def test_get_regime_history_uses_limit_not_days(api: FakeApi) -> None:
    api.json("/v1/regime/history", [{"macro_regime": "tightening"}] * 3)

    out = await call(server_for(api), "get_regime_history", {"limit": 3})

    assert out == {"count": 3, "rows": [{"macro_regime": "tightening"}] * 3}
    assert dict(api.last.url.params) == {"limit": "3"}
    assert api.last.headers["x-macropulse-key"] == FAKE_KEY


async def test_get_regime_history_date_range(api: FakeApi) -> None:
    api.json("/v1/regime/history", [])

    await call(
        server_for(api),
        "get_regime_history",
        {"limit": 10, "start": "2026-10-01", "end": "2026-10-31"},
    )

    assert dict(api.last.url.params) == {"limit": "10", "start": "2026-10-01", "end": "2026-10-31"}


async def test_get_regime_history_rejects_inverted_range(api: FakeApi) -> None:
    text = await call_error(
        server_for(api), "get_regime_history", {"start": "2026-10-31", "end": "2026-10-01"}
    )

    assert "start" in text and "end" in text
    assert api.requests == []


@pytest.mark.parametrize("limit", [0, 1001, "many"])
async def test_get_regime_history_validates_limit(api: FakeApi, limit: object) -> None:
    text = await call_error(server_for(api), "get_regime_history", {"limit": limit}, one_line=False)

    assert "limit" in text
    assert api.requests == []


async def test_get_forecast(api: FakeApi) -> None:
    api.json("/v1/forecast", {"horizon": 7, "forecast": []})

    out = await call(server_for(api), "get_forecast", {"horizon": 7})

    assert out["horizon"] == 7
    assert dict(api.last.url.params) == {"horizon": "7"}
    assert api.last.headers["x-macropulse-key"] == FAKE_KEY


async def test_get_forecast_validates_horizon(api: FakeApi) -> None:
    text = await call_error(server_for(api), "get_forecast", {"horizon": 11}, one_line=False)

    assert "horizon" in text
    assert api.requests == []


async def test_get_scorecard(api: FakeApi) -> None:
    api.json("/v1/scorecard", {"signals": {"liquidity": 0.2}})

    out = await call(server_for(api), "get_scorecard")

    assert out == {"signals": {"liquidity": 0.2}}
    assert api.last.url.path == "/v1/scorecard"


async def test_get_liquidity(api: FakeApi) -> None:
    api.json("/v1/liquidity", {"rows": []})

    await call(server_for(api), "get_liquidity", {"limit": 90})

    assert api.last.url.path == "/v1/liquidity"
    assert dict(api.last.url.params) == {"limit": "90"}


# --- the denied / blocked / failed paths -------------------------------------


@pytest.mark.parametrize(
    ("tool", "plan_hint"),
    [
        ("get_regime_history", "the free plan works"),
        ("get_forecast", "Starter or Pro"),
        ("get_scorecard", "Starter or Pro"),
        ("get_liquidity", "Starter or Pro"),
    ],
)
async def test_keyed_tools_without_key_explain_how_to_get_one(
    api: FakeApi, tool: str, plan_hint: str
) -> None:
    text = await call_error(server_for(api, api_key=None), tool)

    assert plan_hint in text
    assert "https://macropulse.live" in text
    assert "MACROPULSE_API_KEY" in text
    assert api.requests == []


async def test_free_key_on_paid_tool_is_told_to_upgrade(api: FakeApi) -> None:
    api.json(
        "/v1/forecast",
        {"detail": "This endpoint requires a Starter or Pro plan. Upgrade at https://x"},
        status=403,
    )

    text = await call_error(server_for(api), "get_forecast")

    assert "Starter or Pro" in text
    assert "https://macropulse.live/#pricing" in text


async def test_unexpected_payload_shape_is_a_clear_error(api: FakeApi) -> None:
    api.json("/v1/regime/history", {"not": "a list"})

    text = await call_error(server_for(api), "get_regime_history")

    assert "unexpected response" in text


async def test_server_down_is_a_clear_error(api: FakeApi) -> None:
    api.json("/v1/public/regime", {"detail": "Data temporarily unavailable"}, status=503)

    text = await call_error(server_for(api, api_key=None), "get_current_regime")

    assert "no data to serve right now" in text


async def test_key_never_appears_in_tool_output_or_logs(
    api: FakeApi, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    echo = {"detail": f"Invalid or revoked API key: {FAKE_KEY}"}
    for path in ("/v1/regime/history", "/v1/forecast", "/v1/scorecard", "/v1/liquidity"):
        api.json(path, echo, status=403)
    server = server_for(api)

    texts = [
        await call_error(server, tool)
        for tool in ("get_regime_history", "get_forecast", "get_scorecard", "get_liquidity")
    ]

    assert len(api.requests) == 4
    assert all(FAKE_KEY not in t for t in texts)
    assert FAKE_KEY not in caplog.text


async def test_public_tool_rejects_a_non_object_body(api: FakeApi) -> None:
    api.json("/v1/public/latest", ["not", "an", "object"])

    text = await call_error(server_for(api, api_key=None), "get_market_snapshot")

    assert "unexpected response" in text
