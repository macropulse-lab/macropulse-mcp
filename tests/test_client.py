"""HTTP layer: auth header, error translation, timeouts, key hygiene."""

from __future__ import annotations

from collections.abc import AsyncIterator

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
        "Your key is bound to another IP address; wait 15 minutes of inactivity or use a paid plan",
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


async def test_relayed_server_text_is_labelled_as_the_apis(api: FakeApi) -> None:
    api.json("/v1/forecast", {"detail": "horizon looks odd"}, status=418)

    with pytest.raises(MacroPulseError) as excinfo:
        await make_client(api).get("/v1/forecast", auth=Auth.PAID)

    assert str(excinfo.value) == (
        "MacroPulse rejected the request (HTTP 418): MacroPulse API said: horizon looks odd"
    )


@pytest.mark.parametrize("status", [200, 500])
async def test_deeply_nested_json_is_rejected_cleanly(api: FakeApi, status: int) -> None:
    deep = "[" * 200_000 + "]" * 200_000
    api.raw(
        "/v1/scorecard",
        lambda _r: httpx.Response(
            status, content=deep.encode(), headers={"content-type": "application/json"}
        ),
    )

    with pytest.raises(MacroPulseError) as excinfo:
        await make_client(api).get("/v1/scorecard", auth=Auth.PAID)

    assert "\n" not in str(excinfo.value)


async def test_declared_oversized_body_is_refused_without_reading_it(api: FakeApi) -> None:
    from macropulse_mcp.client import MAX_BODY_BYTES

    api.raw(
        "/v1/public/regime",
        lambda _r: httpx.Response(
            200, headers={"content-length": str(MAX_BODY_BYTES + 1)}, content=b"{}"
        ),
    )

    with pytest.raises(MacroPulseError, match=r"larger than 2 MB"):
        await make_client(api).get("/v1/public/regime", auth=Auth.PUBLIC)


async def test_streamed_oversized_body_is_cut_off(api: FakeApi) -> None:
    from macropulse_mcp.client import MAX_BODY_BYTES

    def chunks() -> object:
        async def gen() -> AsyncIterator[bytes]:
            for _ in range(MAX_BODY_BYTES // 65536 + 2):
                yield b" " * 65536

        return gen()

    api.raw("/v1/public/regime", lambda _r: httpx.Response(200, content=chunks()))  # type: ignore[arg-type]

    with pytest.raises(MacroPulseError, match=r"larger than 2 MB; it was not read"):
        await make_client(api).get("/v1/public/regime", auth=Auth.PUBLIC)


@pytest.mark.parametrize("encoding", ["gzip", "gzip, gzip", "br", "deflate", " GZIP "])
async def test_compressed_bodies_are_refused_unread(api: FakeApi, encoding: str) -> None:
    import gzip

    # A double-gzipped bomb: a few KB on the wire, 200 MB once inflated.
    bomb = gzip.compress(gzip.compress(b"0" * (200 * 1024 * 1024)))
    read = False

    def body() -> object:
        async def gen() -> AsyncIterator[bytes]:
            nonlocal read
            read = True
            yield bomb

        return gen()

    api.raw(
        "/v1/public/regime",
        lambda _r: httpx.Response(
            200,
            content=body(),  # type: ignore[arg-type]
            headers={"content-encoding": encoding, "content-type": "application/json"},
        ),
    )

    with pytest.raises(MacroPulseError, match="compressed response") as excinfo:
        await make_client(api).get("/v1/public/regime", auth=Auth.PUBLIC)

    assert not read
    assert "\n" not in str(excinfo.value)


async def test_identity_encoded_bodies_are_read(api: FakeApi) -> None:
    api.raw(
        "/v1/public/regime",
        lambda _r: httpx.Response(
            200,
            content=b'{"regime": "tightening"}',
            headers={"content-encoding": "identity", "content-type": "application/json"},
        ),
    )

    body = await make_client(api).get("/v1/public/regime", auth=Auth.PUBLIC)

    assert body == {"regime": "tightening"}


async def test_requests_ask_for_an_uncompressed_body(api: FakeApi) -> None:
    api.json("/v1/scorecard", {})

    await make_client(api).get("/v1/scorecard", auth=Auth.PAID)

    assert api.last.headers["accept-encoding"] == "identity"


async def test_body_that_parses_but_is_too_deep_to_scrub_is_a_clean_error(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    from macropulse_mcp import client as client_module

    def overflow(_value: object, _key: str | None) -> object:
        raise RecursionError("maximum recursion depth exceeded")

    # Deterministic stand-in for a body nested deep enough to parse but not to scrub.
    monkeypatch.setattr(client_module, "_scrub_json", overflow)
    api.json("/v1/scorecard", {"ok": True})

    with pytest.raises(MacroPulseError, match="too deeply nested") as excinfo:
        await make_client(api, api_key=FAKE_KEY).get("/v1/scorecard", auth=Auth.PAID)

    assert "\n" not in str(excinfo.value)
