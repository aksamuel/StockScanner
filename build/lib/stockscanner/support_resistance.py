"""Explainable support and resistance zones derived from completed daily bars."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


MINIMUM_BARS = 20
SWING_WINDOW = 3
LOOKBACK_BARS = 180
BREAKOUT_LOOKBACK = 20
ATR_WINDOW = 14
ATR_TOLERANCE_MULTIPLIER = 0.5
FALLBACK_TOLERANCE_PERCENT = 0.01


@dataclass
class _Candidate:
    level: float
    kind: str
    source: str
    weight: float = 1.0
    volume_confirmed: bool = False


@dataclass
class _Zone:
    level: float
    lower: float
    upper: float
    role: str
    tests: int
    confidence: str
    sources: list[str] = field(default_factory=list)
    role_reversal: bool = False


def _empty_result(status: str = "Unavailable") -> dict:
    return {
        "Support Low": None,
        "Support High": None,
        "Support Distance %": None,
        "Support Tests": 0,
        "Support Confidence": "Unavailable",
        "Support Details": "",
        "Resistance Low": None,
        "Resistance High": None,
        "Resistance Distance %": None,
        "Resistance Tests": 0,
        "Resistance Confidence": "Unavailable",
        "Resistance Details": "",
        "Zone Status": status,
        "Zone Tolerance": None,
        "Zone Tolerance %": None,
    }


def _atr(dataframe: pd.DataFrame) -> float | None:
    if not {"High", "Low", "Close"}.issubset(dataframe.columns):
        return None
    high = pd.to_numeric(dataframe["High"], errors="coerce")
    low = pd.to_numeric(dataframe["Low"], errors="coerce")
    close = pd.to_numeric(dataframe["Close"], errors="coerce")
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    value = true_range.rolling(ATR_WINDOW, min_periods=ATR_WINDOW).mean().iloc[-1]
    return float(value) if pd.notna(value) and value > 0 else None


def _volume_weight(dataframe: pd.DataFrame, position: int) -> tuple[float, bool]:
    if "Volume" not in dataframe.columns:
        return 1.0, False
    volume = pd.to_numeric(dataframe["Volume"], errors="coerce")
    current = volume.iloc[position]
    average = volume.rolling(20, min_periods=5).mean().iloc[position]
    confirmed = pd.notna(current) and pd.notna(average) and average > 0 and current >= 1.5 * average
    return (1.5 if confirmed else 1.0), bool(confirmed)


def _candidate_levels(dataframe: pd.DataFrame) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    high = pd.to_numeric(dataframe["High"], errors="coerce")
    low = pd.to_numeric(dataframe["Low"], errors="coerce")
    close = pd.to_numeric(dataframe["Close"], errors="coerce")

    for position in range(SWING_WINDOW, len(dataframe) - SWING_WINDOW):
        high_window = high.iloc[position - SWING_WINDOW : position + SWING_WINDOW + 1]
        low_window = low.iloc[position - SWING_WINDOW : position + SWING_WINDOW + 1]
        weight, confirmed = _volume_weight(dataframe, position)
        if (
            pd.notna(high.iloc[position])
            and high.iloc[position] == high_window.max()
            and int((high_window == high.iloc[position]).sum()) == 1
        ):
            candidates.append(
                _Candidate(float(high.iloc[position]), "resistance", "swing high", weight, confirmed)
            )
        if (
            pd.notna(low.iloc[position])
            and low.iloc[position] == low_window.min()
            and int((low_window == low.iloc[position]).sum()) == 1
        ):
            candidates.append(
                _Candidate(float(low.iloc[position]), "support", "swing low", weight, confirmed)
            )

    latest_close = float(close.iloc[-1])
    for column, label in (("MA20", "MA20"), ("MA50", "MA50"), ("MA200", "MA200")):
        if column not in dataframe.columns:
            continue
        level = pd.to_numeric(dataframe[column], errors="coerce").iloc[-1]
        if pd.notna(level) and level > 0:
            kind = "support" if level <= latest_close else "resistance"
            candidates.append(_Candidate(float(level), kind, label, 0.75))

    prior_high = high.shift(1).rolling(BREAKOUT_LOOKBACK, min_periods=BREAKOUT_LOOKBACK).max()
    prior_low = low.shift(1).rolling(BREAKOUT_LOOKBACK, min_periods=BREAKOUT_LOOKBACK).min()
    for position in range(BREAKOUT_LOOKBACK, len(dataframe)):
        weight, confirmed = _volume_weight(dataframe, position)
        if (
            pd.notna(prior_high.iloc[position])
            and close.iloc[position] > prior_high.iloc[position]
            and close.iloc[position - 1] <= prior_high.iloc[position]
        ):
            candidates.append(
                _Candidate(
                    float(prior_high.iloc[position]),
                    "resistance",
                    "breakout level",
                    weight + (0.5 if confirmed else 0),
                    confirmed,
                )
            )
        if (
            pd.notna(prior_low.iloc[position])
            and close.iloc[position] < prior_low.iloc[position]
            and close.iloc[position - 1] >= prior_low.iloc[position]
        ):
            candidates.append(
                _Candidate(
                    float(prior_low.iloc[position]),
                    "support",
                    "breakdown level",
                    weight + (0.5 if confirmed else 0),
                    confirmed,
                )
            )
    return candidates


def _cluster_candidates(
    candidates: list[_Candidate], tolerance: float, completed_close: float
) -> list[_Zone]:
    clusters: list[list[_Candidate]] = []
    for candidate in sorted(candidates, key=lambda item: item.level):
        if not clusters:
            clusters.append([candidate])
            continue
        cluster = clusters[-1]
        center = np.average(
            [item.level for item in cluster], weights=[item.weight for item in cluster]
        )
        if abs(candidate.level - center) <= tolerance:
            cluster.append(candidate)
        else:
            clusters.append([candidate])

    zones: list[_Zone] = []
    for cluster in clusters:
        weights = [item.weight for item in cluster]
        center = float(np.average([item.level for item in cluster], weights=weights))
        support_weight = sum(item.weight for item in cluster if item.kind == "support")
        resistance_weight = sum(item.weight for item in cluster if item.kind == "resistance")
        role = "support" if support_weight >= resistance_weight else "resistance"
        lower = center - tolerance
        upper = center + tolerance
        reversed_role = False
        if role == "resistance" and completed_close > upper:
            role = "support"
            reversed_role = True
        elif role == "support" and completed_close < lower:
            role = "resistance"
            reversed_role = True
        tests = len(cluster)
        total_weight = sum(weights)
        confidence = "High" if tests >= 3 or total_weight >= 3.5 else "Medium" if tests >= 2 else "Low"
        sources = sorted({item.source for item in cluster})
        if any(item.volume_confirmed for item in cluster):
            sources.append("volume confirmed")
        zones.append(
            _Zone(
                center,
                lower,
                upper,
                role,
                tests,
                confidence,
                sources,
                reversed_role,
            )
        )
    return zones


def _zone_details(zone: _Zone) -> str:
    details = f"{zone.confidence}; {zone.tests} test{'s' if zone.tests != 1 else ''}; "
    details += ", ".join(zone.sources)
    if zone.role_reversal:
        details += "; role reversal"
    return details


def analyze_support_resistance(
    completed_data: pd.DataFrame, current_price: float | None = None
) -> dict:
    """Return nearest zones and status without modifying score or rank inputs.

    ``completed_data`` must contain only completed daily candles. ``current_price``
    may be a live price and is used solely for relative-position classification.
    """
    result = _empty_result()
    required = {"High", "Low", "Close"}
    if (
        completed_data is None
        or len(completed_data) < MINIMUM_BARS
        or not required.issubset(completed_data.columns)
    ):
        return result

    data = completed_data.tail(LOOKBACK_BARS).copy()
    for column in required:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=list(required))
    if len(data) < MINIMUM_BARS:
        return result

    completed_close = float(data["Close"].iloc[-1])
    try:
        price = float(current_price) if current_price is not None else completed_close
    except (TypeError, ValueError):
        return result
    if not np.isfinite(price) or price <= 0:
        return result

    atr = _atr(data)
    tolerance = (
        atr * ATR_TOLERANCE_MULTIPLIER
        if atr is not None
        else completed_close * FALLBACK_TOLERANCE_PERCENT
    )
    if not np.isfinite(tolerance) or tolerance <= 0:
        tolerance = completed_close * FALLBACK_TOLERANCE_PERCENT

    candidates = _candidate_levels(data)
    if not candidates:
        result["Zone Status"] = "Insufficient Levels"
        result["Zone Tolerance"] = round(tolerance, 2)
        result["Zone Tolerance %"] = round(tolerance / price * 100, 2)
        return result

    zones = _cluster_candidates(candidates, tolerance, completed_close)
    supports = [zone for zone in zones if zone.role == "support" and price >= zone.lower]
    resistances = [zone for zone in zones if zone.role == "resistance" and price <= zone.upper]
    support = min(supports, key=lambda zone: abs(price - zone.level)) if supports else None
    resistance = (
        min(resistances, key=lambda zone: abs(price - zone.level)) if resistances else None
    )

    crossed_resistance = [
        zone
        for zone in zones
        if zone.role == "resistance"
        and completed_close <= zone.upper
        and price > zone.upper
    ]
    crossed_support = [
        zone
        for zone in zones
        if zone.role == "support"
        and completed_close >= zone.lower
        and price < zone.lower
    ]

    if crossed_resistance:
        status = "Breakout Above Resistance"
    elif crossed_support:
        status = "Breakdown Below Support"
    elif support and support.lower <= price <= support.upper:
        status = "At Support"
    elif resistance and resistance.lower <= price <= resistance.upper:
        status = "At Resistance"
    else:
        status = "Between Zones"

    result.update(
        {
            "Zone Status": status,
            "Zone Tolerance": round(tolerance, 2),
            "Zone Tolerance %": round(tolerance / price * 100, 2),
        }
    )
    if support:
        result.update(
            {
                "Support Low": round(support.lower, 2),
                "Support High": round(support.upper, 2),
                "Support Distance %": round(abs(price - support.level) / price * 100, 2),
                "Support Tests": support.tests,
                "Support Confidence": support.confidence,
                "Support Details": _zone_details(support),
            }
        )
    if resistance:
        result.update(
            {
                "Resistance Low": round(resistance.lower, 2),
                "Resistance High": round(resistance.upper, 2),
                "Resistance Distance %": round(abs(resistance.level - price) / price * 100, 2),
                "Resistance Tests": resistance.tests,
                "Resistance Confidence": resistance.confidence,
                "Resistance Details": _zone_details(resistance),
            }
        )
    return result
