"""The console entry point: no tracebacks for the user, ever."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from mcp.server.mcpserver import MCPServer

from macropulse_mcp import __version__, server

from .conftest import FAKE_KEY


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    inherited = {k: v for k, v in os.environ.items() if not k.startswith("MACROPULSE_")}
    full_env = {**inherited, **(env or {})}
    return subprocess.run(
        [sys.executable, "-m", "macropulse_mcp", *args],
        capture_output=True,
        text=True,
        env=full_env,
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )


def test_version_flag() -> None:
    proc = _run("--version")

    assert proc.returncode == 0
    assert proc.stdout.strip() == f"macropulse-mcp {__version__}"


def test_help_mentions_the_key_and_where_to_get_it() -> None:
    proc = _run("--help")

    assert proc.returncode == 0
    assert "MACROPULSE_API_KEY" in proc.stdout
    assert "https://macropulse.live" in proc.stdout


def test_bad_base_url_exits_2_with_one_line_on_stderr() -> None:
    proc = _run(env={"MACROPULSE_API_BASE": "http://api.macropulse.live"})

    assert proc.returncode == 2
    assert proc.stdout == ""  # stdout belongs to the MCP protocol
    assert "Traceback" not in proc.stderr
    assert "MACROPULSE_API_BASE" in proc.stderr


def test_startup_banner_never_prints_the_key() -> None:
    # stdin is closed, so the stdio server starts and exits at EOF.
    proc = _run(env={"MACROPULSE_API_KEY": FAKE_KEY})

    assert "Traceback" not in proc.stderr
    assert FAKE_KEY not in proc.stderr
    assert FAKE_KEY not in proc.stdout
    assert "API key: set" in proc.stderr


# In-process twins of the subprocess tests above (these count towards coverage).


def test_main_rejects_bad_base_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MACROPULSE_API_BASE", "http://api.macropulse.live")

    with pytest.raises(SystemExit) as excinfo:
        server.main([])

    assert excinfo.value.code == server.EXIT_CONFIG
    out, err = capsys.readouterr()
    assert out == ""
    assert "MACROPULSE_API_BASE" in err


@pytest.mark.parametrize(
    ("key", "expected"),
    [(None, "API key: not set"), (FAKE_KEY, "API key: set"), ("mp_" + "a" * 20 + " key", "spaces")],
)
def test_main_banner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    key: str | None,
    expected: str,
) -> None:
    monkeypatch.delenv("MACROPULSE_API_BASE", raising=False)
    if key is None:
        monkeypatch.delenv("MACROPULSE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("MACROPULSE_API_KEY", key)
    runs: list[str] = []
    monkeypatch.setattr(MCPServer, "run", lambda self, *a, **k: runs.append("ran"))

    server.main([])

    out, err = capsys.readouterr()
    assert runs == ["ran"]
    assert out == ""
    assert expected in err
    assert FAKE_KEY not in err


def test_main_exits_quietly_on_ctrl_c(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupted(self: MCPServer, *args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.delenv("MACROPULSE_API_BASE", raising=False)
    monkeypatch.setattr(MCPServer, "run", interrupted)

    server.main([])

    assert "Traceback" not in capsys.readouterr().err


async def test_real_stdio_session_lists_tools_and_answers_offline() -> None:
    from mcp import Client, StdioServerParameters

    inherited = {k: v for k, v in os.environ.items() if not k.startswith("MACROPULSE_")}
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "macropulse_mcp"], env=inherited
    )

    async with Client(params) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        result = await client.call_tool("explain_regimes", {})

    assert "get_signed_regime" in names
    assert not result.is_error
    assert result.structured_content is not None
    assert len(result.structured_content["regimes"]) == 4
