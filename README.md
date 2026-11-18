<div align="center">
<img src="https://raw.githubusercontent.com/macropulse-lab/macropulse-mcp/master/.github/brand/logo.svg" alt="MacroPulse" width="64" height="64">
</div>

# macropulse-mcp

<!-- mcp-name: io.github.macropulse-lab/macropulse-mcp -->

An [MCP](https://modelcontextprotocol.io) server for [MacroPulse](https://macropulse.live): the daily US macro regime as tools your AI agent can call in Claude Code, Claude Desktop, Cursor or any MCP client that runs local (stdio) servers. No code to write.

Ask *"what macro regime are we in, and what does it mean?"* and the agent answers from the live MacroPulse feed.

MacroPulse classifies each US trading day into one of four regimes (expansion, recovery, tightening, risk-off) with a frozen, versioned model: PCA over 13 daily macro and market features, followed by a Statistical Jump Model (v4). The pipeline runs once a day at 21:00 UTC, after the US close.

## Requirements

[uv](https://docs.astral.sh/uv/getting-started/installation/), which provides `uvx` and fetches a suitable Python for you. Alternatively `pipx install macropulse-mcp` or `pip install macropulse-mcp` on Python 3.12 or newer, then use `macropulse-mcp` as the command instead of `uvx macropulse-mcp`.

## Configure

The API key is optional: the public tools work without one. A free key (no credit card) unlocks regime history; forecast, scorecard and liquidity need the Starter or Pro plan. Get a key at [macropulse.live](https://macropulse.live).

### Claude Code

```bash
claude mcp add macropulse -- uvx macropulse-mcp
# with a key:
claude mcp add macropulse -e MACROPULSE_API_KEY=mp_your_key -- uvx macropulse-mcp
```

### Claude Desktop

Edit `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "macropulse": {
      "command": "uvx",
      "args": ["macropulse-mcp"],
      "env": { "MACROPULSE_API_KEY": "mp_your_key" }
    }
  }
}
```

Leave out `env` to use only the public tools. Claude Desktop on macOS does not inherit your shell's `PATH`; if it reports `spawn uvx ENOENT`, replace `"uvx"` with the output of `which uvx` (macOS/Linux) or `where uvx` (Windows).

### Cursor

Add the same block to `~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` (one project):

```json
{
  "mcpServers": {
    "macropulse": {
      "command": "uvx",
      "args": ["macropulse-mcp"],
      "env": { "MACROPULSE_API_KEY": "mp_your_key" }
    }
  }
}
```

## Tools

All tools are read-only.

| Tool | Needs | Returns |
| --- | --- | --- |
| `get_current_regime` | nothing | Today's regime, risk score, the regime's target equity exposure and a one-line interpretation |
| `get_signed_regime` | nothing | The current regime as MacroPulse's Ed25519-signed payload, returned exactly as served (the tool does not verify the signature) |
| `get_market_snapshot` | nothing | Regime with confidence and persistence, net Fed liquidity z-score and trend |
| `explain_regimes` | nothing (offline) | What the four regimes mean, their ids and target exposures, how and when the model runs |
| `get_regime_history` | key (Free: up to 30 rows) | Daily regime, risk score and regime probabilities, newest first; optional `limit`, `start`, `end` |
| `get_forecast` | key, Starter or Pro | ARIMA projection of the regime probabilities for 1-10 business days (`horizon`) |
| `get_scorecard` | key, Starter or Pro | Five normalized macro signals on a -1 to 1 scale |
| `get_liquidity` | key, Starter or Pro | Net Fed liquidity time series (`limit`, 1-500) |

When a call fails, the tool returns one line that says what to do: get a key, upgrade the plan, check the key, or try again later. The key is sent only in the `X-MacroPulse-Key` header and is never logged or echoed.

## The four regimes

| Regime | id | Target equity exposure |
| --- | --- | --- |
| Expansion | 0 | 100% |
| Recovery | 1 | 75% |
| Tightening | 2 | 25% |
| Risk-Off | 3 | 0% |

The exposure is a rule of thumb attached to each label, not a recommendation for any portfolio. Regimes for dates before 2026-07-03, when v4 went live, are a backfill computed with hindsight.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `MACROPULSE_API_KEY` | unset | API key for the keyed tools |
| `MACROPULSE_API_BASE` | `https://api.macropulse.live` | API URL override for testing (https only; plain http only for localhost) |

## Development

```bash
pip install -e ".[dev]"
pytest                                  # offline: the API is mocked
MACROPULSE_LIVE_SMOKE=1 pytest -m live  # optional: read-only, public endpoints, no key
```

## Disclaimer

MacroPulse data is informational only and is not investment advice.

## Links

[macropulse.live](https://macropulse.live) · [API docs](https://macropulse.live/api-docs) · [IRL](https://macropulse.live/irl), pre-execution compliance for trading agents, which uses the signed MacroPulse regime

## License

MIT
