# macropulse-mcp

MCP (Model Context Protocol) server for [MacroPulse](https://macropulse.live) — daily macro regime classification as native tools for Claude, ChatGPT, and any MCP-compatible agent framework.

Ask your AI assistant *"what macro regime are we in?"* and it answers from the live feed.

## Install

```bash
pip install macropulse-mcp
```

## Configure

### Claude Code

```bash
claude mcp add macropulse -- macropulse-mcp
```

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "macropulse": {
      "command": "macropulse-mcp",
      "env": { "MACROPULSE_API_KEY": "mp_..." }
    }
  }
}
```

The API key is optional — public tools work without it. Get a free key at [macropulse.live](https://macropulse.live) for history, forecasts, and liquidity decomposition.

## Tools

| Tool | Auth | Description |
|------|------|-------------|
| `get_current_regime` | none | Today's regime, risk score, suggested equity exposure |
| `get_market_snapshot` | none | Regime + confidence, net-liquidity z-score and trend |
| `get_performance_series` | none | ~2y daily series: regime, S&P 500, gold, overlay strategy |
| `get_regime_history` | key | Per-day regime probabilities and risk scores |
| `get_forecast` | key (Starter+) | 5-day regime forecast with transition probabilities |
| `get_scorecard` | key (Starter+) | Signal hit rates and quality metrics |
| `get_liquidity` | key (Starter+) | Fed liquidity decomposition (Fed assets, TGA, RRP) |

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `MACROPULSE_API_KEY` | — | API key for authenticated tools |
| `MACROPULSE_API_BASE` | `https://api.macropulse.live` | Override for testing |

## The four regimes

| Regime | Meaning |
|--------|---------|
| `expansion` | Liquidity expanding, risk-on |
| `recovery` | Improving from stress, early risk-on |
| `tightening` | Fed draining liquidity, defensive |
| `risk_off` | Stress event, maximum defense |

## Links

- [MacroPulse](https://macropulse.live) · [API docs](https://macropulse.live/api-docs) · [Track record](https://macropulse.live/track-record)
- [IRL Engine](https://macropulse.live/irl) — pre-execution compliance for autonomous trading agents

## License

MIT
