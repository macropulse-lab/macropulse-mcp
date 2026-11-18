"""Shared fakes: a scripted MacroPulse API behind httpx.MockTransport (no network)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from macropulse_mcp.client import MacroPulseClient
from macropulse_mcp.config import Settings

# Shaped like a real key (mp_ + token_urlsafe(32)) but obviously fake.
FAKE_KEY = "mp_TEST-not-a-real-key_0123456789abcdefghijklmnopqrstu"
API_BASE = "https://api.test.invalid"

Handler = Callable[[httpx.Request], httpx.Response]


@dataclass
class FakeApi:
    """Records every request and answers from a per-path script."""

    routes: dict[str, Handler] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)

    def json(self, path: str, body: Any, status: int = 200) -> None:
        self.routes[path] = lambda _req: httpx.Response(status, json=body)

    def raw(self, path: str, handler: Handler) -> None:
        self.routes[path] = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.routes.get(request.url.path)
        if handler is None:
            return httpx.Response(404, json={"detail": "Not Found"})
        return handler(request)

    @property
    def last(self) -> httpx.Request:
        assert self.requests, "no request was made"
        return self.requests[-1]


def make_client(api: FakeApi, api_key: str | None = FAKE_KEY, **kwargs: Any) -> MacroPulseClient:
    settings = Settings(api_base=API_BASE, api_key=api_key, api_key_problem=None)
    return MacroPulseClient(settings, transport=httpx.MockTransport(api), **kwargs)


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


def dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True)
