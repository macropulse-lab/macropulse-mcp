"""HTTP layer: auth header, error translation, timeouts, key hygiene."""

from __future__ import annotations

import logging

import httpx
import pytest

from macropulse_mcp.client import Auth, MacroPulseError

from .conftest import API_BASE, FAKE_KEY, FakeApi, dumps, make_client


async def test_public_calls_never_send_the_key(api: FakeApi) -> None:
    api.json("/v1/public/regime", {"regime": "tightening"})

    body = await make_client(api).get("/v1/public/regime", auth=Auth.PUBLIC)

    assert body == {"regime": "tightening"}
    assert "x-macropulse-key" not in api.last.headers
    assert str(api.last.url) == f"{API_BASE}/v1/public/regime"


async def test_keyed_calls_send_the_header_not_a_query_param(api: FakeApi) -> None:
    api.json("/v1/scorecard", {"signals": []})

    await make_client(api).get("/v1/scorecard", auth=Auth.PAID, params={"a": 1})

    assert api.last.headers["x-macropulse-key"] == FAKE_KEY
    assert FAKE_KEY not in str(api.last.url)
    assert api.last.url.params["a"] == "1"


async def test_sends_a_versioned_user_agent(api: FakeApi) -> None:
    api.json("/v1/public/regime", {})

    await make_client(api).get("/v1/public/regime", auth=Auth.PUBLIC)

    assert api.last.headers["user-agent"].startswith("macropulse-mcp/")


@pytest.mark.parametrize(
    ("auth", "expected"),
    [
        (Auth.KEY, "the free plan works"),
        (Auth.PAID, "Starter or Pro"),
    ],
)
async def test_missing_key_fails_before_any_request(
    api: FakeApi, auth: Auth, expected: str
) -> None:
    with pytest.raises(MacroPulseError) as excinfo:
        await make_client(api, api_key=None).get("/v1/forecast", auth=auth)

    message = str(excinfo.value)
    assert expected in message
    assert "https://macropulse.live" in message
    assert "MACROPULSE_API_KEY" in message
    assert "\n" not in message
    assert api.requests == []


async def test_malformed_key_problem_is_reported_instead_of_missing_key(api: FakeApi) -> None:
    from macropulse_mcp.client import MacroPulseClient
    from macropulse_mcp.config import Settings

    settings = Settings(api_base=API_BASE, api_key=None, api_key_problem="key is malformed")
    client = MacroPulseClient(settings, transport=httpx.MockTransport(api))

    with pytest.raises(MacroPulseError, match="key is malformed"):
        await client.get("/v1/forecast", auth=Auth.PAID)
    assert api.requests == []


ERROR_CASES = [
    (401, {"detail": "Missing API key."}, "Check MACROPULSE_API_KEY"),
    (403, {"detail": "Invalid or revoked API key."}, "invalid or revoked"),
    (
        403,
        {"detail": "This endpoint requires a Starter or Pro plan. Upgrade at https://x"},
        "needs the Starter or Pro plan",
    ),
    (
        403,
        {
            "error": "ip_locked",
            # The real detail (api/middleware/rate_limit.py) is ~230 chars; truncation
            # would cut the actionable part, so the client uses its own fixed text.
            "detail": (
                "Your API key is temporarily bound to another IP address. Wait 15 minutes of "
                "inactivity for the lock to release, then retry from any location. Paid "
                "plans (Starter and Pro) can call from multiple locations."
            ),
        },
        "Your key is bound to another IP address; wait 15 minutes of inactivity or use a "
        "paid plan",
    ),
    (402, {"detail": "suspended due to a failed payment"}, "failed payment"),
    (429, {"error": "rate_limit_exceeded", "detail": "Daily limit"}, "rate limit"),
    (503, {"detail": "Data temporarily unavailable"}, "no data to serve right now"),
    (500, {"detail": "boom"}, "HTTP 500"),
    (422, {"detail": [{"loc": ["query", "limit"], "msg": "too big"}]}, "HTTP 422"),
]


@pytest.mark.parametrize(("status", "body", "expected"), ERROR_CASES)
async def test_http_errors_become_one_line_messages(
    api: FakeApi, status: int, body: object, expected: str
) -> None:
    api.json("/v1/forecast", body, status=status)

    with pytest.raises(MacroPulseError) as excinfo:
        await make_client(api).get("/v1/forecast", auth=Auth.PAID)

    message = str(excinfo.value)
    assert expected in message
    assert "\n" not in message
    assert len(message) < 400


async def test_error_text_from_the_server_is_sanitized(api: FakeApi) -> None:
    hostile = "x" * 1000 + "\n\x1b[31mline two"
    api.json("/v1/forecast", {"detail": hostile}, status=418)

    with pytest.raises(MacroPulseError) as excinfo:
        await make_client(api).get("/v1/forecast", auth=Auth.PAID)

    message = str(excinfo.value)
    assert "\n" not in message
    assert "\x1b" not in message
    assert len(message) < 400


async def test_a_server_echoing_the_key_never_leaks_it(api: FakeApi) -> None:
    api.json("/v1/forecast", {"detail": f"Invalid or revoked API key {FAKE_KEY}."}, status=403)

    with pytest.raises(MacroPulseError) as excinfo:
        await make_client(api).get("/v1/forecast", auth=Auth.PAID)

    assert FAKE_KEY not in str(excinfo.value)


async def test_timeout_is_translated(api: FakeApi) -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    api.raw("/v1/public/regime", slow)

    with pytest.raises(MacroPulseError, match="did not respond in time"):
        await make_client(api).get("/v1/public/regime", auth=Auth.PUBLIC)


async def test_network_failure_is_translated(api: FakeApi) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    api.raw("/v1/public/regime", down)

    with pytest.raises(MacroPulseError, match="Could not reach the MacroPulse API"):
        await make_client(api).get("/v1/public/regime", auth=Auth.PUBLIC)


async def test_non_json_body_is_rejected(api: FakeApi) -> None:
    api.raw("/v1/public/regime", lambda _r: httpx.Response(200, text="<html>oops</html>"))

    with pytest.raises(MacroPulseError, match="unexpected response"):
        await make_client(api).get("/v1/public/regime", auth=Auth.PUBLIC)


async def test_default_timeout_is_bounded(api: FakeApi) -> None:
    client = make_client(api)

    assert client.timeout.read is not None and client.timeout.read <= 10
    assert client.timeout.connect is not None and client.timeout.connect <= 5


async def test_logs_never_contain_the_key(api: FakeApi, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    api.json("/v1/scorecard", {"ok": True})
    api.json("/v1/forecast", {"detail": f"bad key {FAKE_KEY}"}, status=403)
    client = make_client(api)

    await client.get("/v1/scorecard", auth=Auth.PAID)
    with pytest.raises(MacroPulseError):
        await client.get("/v1/forecast", auth=Auth.PAID)

    assert caplog.records, "expected some debug logging to inspect"
    assert FAKE_KEY not in caplog.text


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(418, text="I'm a teapot"),
        httpx.Response(418, json=["not", "a", "dict"]),
        httpx.Response(418, json={"detail": 42}),
    ],
)
async def test_odd_error_bodies_still_give_a_message(
    api: FakeApi, response: httpx.Response
) -> None:
    api.raw("/v1/forecast", lambda _r: response)

    with pytest.raises(MacroPulseError, match=r"^MacroPulse rejected the request \(HTTP 418\)$"):
        await make_client(api).get("/v1/forecast", auth=Auth.PAID)


def test_has_key(api: FakeApi) -> None:
    assert make_client(api).has_key is True
    assert make_client(api, api_key=None).has_key is False


async def test_a_successful_body_echoing_the_key_is_scrubbed(api: FakeApi) -> None:
    api.json(
        "/v1/scorecard",
        {"echo": f"key={FAKE_KEY}", "nested": [{"k": FAKE_KEY}], FAKE_KEY: 1, "n": 0.5},
    )

    body = await make_client(api).get("/v1/scorecard", auth=Auth.PAID)

    assert FAKE_KEY not in dumps(body)
    assert body == {
        "echo": "key=[redacted]",
        "nested": [{"k": "[redacted]"}],
        "[redacted]": 1,
        "n": 0.5,
    }


async def test_key_straddling_the_detail_limit_is_scrubbed_before_truncation(
    api: FakeApi,
) -> None:
    # Place the key so that truncating first would leave a prefix of it behind.
    detail = "x" * 140 + FAKE_KEY + " tail"
    api.json("/v1/forecast", {"detail": detail}, status=418)

    with pytest.raises(MacroPulseError) as excinfo:
        await make_client(api).get("/v1/forecast", auth=Auth.PAID)

    message = str(excinfo.value)
    assert FAKE_KEY[:12] not in message
    assert "[redacted]" in message


async def test_redirects_are_never_followed(api: FakeApi) -> None:
    api.raw(
        "/v1/scorecard",
        lambda _r: httpx.Response(302, headers={"Location": "https://evil.invalid/steal"}),
    )
    api.json("/steal", {"stolen": True})

    with pytest.raises(MacroPulseError, match=r"redirect \(HTTP 302\)"):
        await make_client(api).get("/v1/scorecard", auth=Auth.PAID)

    assert len(api.requests) == 1
    assert api.last.url.path == "/v1/scorecard"


async def test_http_client_is_built_with_follow_redirects_false(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[object] = []
    real = httpx.AsyncClient

    def spy(*args: object, **kwargs: object) -> httpx.AsyncClient:
        seen.append(kwargs.get("follow_redirects"))
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", spy)
    api.json("/v1/public/regime", {})

    await make_client(api).get("/v1/public/regime", auth=Auth.PUBLIC)

    assert seen == [False]


async def test_total_deadline_caps_a_slow_response(api: FakeApi) -> None:
    import asyncio

    class Slow(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(5)
            return httpx.Response(200, json={})

    from macropulse_mcp.client import MacroPulseClient
    from macropulse_mcp.config import Settings

    client = MacroPulseClient(
        Settings(api_base=API_BASE, api_key=None, api_key_problem=None),
        transport=Slow(),
        deadline_seconds=0.05,
    )

    with pytest.raises(MacroPulseError, match="did not respond in time"):
        await client.get("/v1/public/regime", auth=Auth.PUBLIC)
