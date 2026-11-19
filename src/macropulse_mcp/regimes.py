"""Static reference text for `explain_regimes`.

Wording follows the audited copy on macropulse.live (regime cards, FAQ). The
"textbook profile" lines describe how such regimes are commonly characterized,
not MacroPulse results. No performance figures belong here.
"""

from __future__ import annotations

from typing import Any

REGIMES: tuple[dict[str, Any], ...] = (
    {
        "id": "expansion",
        "regime_id": 0,
        "label": "Expansion",
        "summary": "Risk-on. Equities lead.",
        "target_equity_exposure": "100%",
        "textbook_profile": (
            "Growth accelerating, inflation contained. Equities and credit outperform; "
            "long-duration bonds lag. Cyclicals and high-beta shine."
        ),
    },
    {
        "id": "recovery",
        "regime_id": 1,
        "label": "Recovery",
        "summary": "Cyclicals re-rate.",
        "target_equity_exposure": "75%",
        "textbook_profile": (
            "Growth troughing, policy easing. Small caps, value and high-beta cyclicals "
            "outperform from oversold lows. Credit spreads compress."
        ),
    },
    {
        "id": "tightening",
        "regime_id": 2,
        "label": "Tightening",
        "summary": "Defensive bias.",
        "target_equity_exposure": "25%",
        "textbook_profile": (
            "Growth decelerating with sticky prices. Quality and dividend factors outperform. "
            "Cyclicals and high-duration assets lag as rates bite."
        ),
    },
    {
        "id": "risk_off",
        "regime_id": 3,
        "label": "Risk-Off",
        "summary": "Duration wins.",
        "target_equity_exposure": "0%",
        "textbook_profile": (
            "Recession dynamics dominant. Treasuries and gold rally; equity vol expands; "
            "credit spreads widen."
        ),
    },
)

EXPLANATION: dict[str, Any] = {
    "what_is_a_regime": (
        "A macro regime is a persistent state of the economy defined by the combination of "
        "liquidity conditions, credit spreads, growth momentum and volatility. MacroPulse "
        "assigns one of four states to every calendar day, weekends included."
    ),
    "regimes": list(REGIMES),
    "profiles_note": (
        "The summary and textbook_profile lines are illustrative: they describe how such "
        "regimes are commonly characterized, not MacroPulse results or forecasts."
    ),
    "target_equity_exposure_note": (
        "Each regime maps to a target equity exposure (100% / 75% / 25% / 0%). It is a "
        "rule of thumb attached to the label, not a recommendation for any portfolio."
    ),
    "model": (
        "Frozen, versioned v4 model: PCA over 13 daily macro and market features (FRED and "
        "Yahoo Finance) followed by a Statistical Jump Model."
    ),
    "schedule": (
        "The pipeline runs once a day at 21:00 UTC, after the US market close. Regimes for "
        "dates before 2026-07-03, when v4 went live, are a backfill computed with hindsight."
    ),
    "disclaimer": "Informational only. Not investment advice.",
}
