from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, log, log1p
from typing import Any, Sequence

DAYS_PER_YEAR = 365
DEFAULT_REQUIRED_ANNUAL_RETURN_PERCENT = 7.0
MINIMUM_HOLDING_DAYS = 365
CATCH_UP_HORIZON_YEARS = (1, 3, 5)

STATUS_MEETS = "meets"
STATUS_BELOW = "below"
STATUS_UNAVAILABLE = "unavailable"

BASIS_TOTAL = "total"
BASIS_PRICE_ONLY = "price_only"

SCENARIO_NOTE = (
    "Catch-up and time-to-hurdle figures are arithmetic scenarios from the inputs "
    "shown, not forecasts or guarantees."
)


@dataclass(frozen=True)
class HoldingLot:
    cost_basis: Any
    days_held: int | None


@dataclass(frozen=True)
class CatchUpRequirement:
    years: int
    required_annual_return_percent: float | None


@dataclass(frozen=True)
class HurdleAnalysis:
    """Return since entry compared with a required annual return (the hurdle).

    The hurdle path is what each lot's cost would be worth today if it had earned
    the required annual return since its own entry date (365-day year, compounded).
    ``shortfall_amount`` is that path value minus the current value, so it is
    negative when the holding is ahead of the path.
    """

    symbol: str
    required_annual_return_percent: float
    status: str
    outlook_status: str
    lot_count: int
    days_held: int | None
    return_basis: str | None
    return_percent: float | None
    hurdle_return_percent: float | None
    excess_return_percentage_points: float | None
    annualized_return_percent: float | None
    shortfall_amount: float | None
    required_return_by_horizon: tuple[CatchUpRequirement, ...]
    forward_return_percent: float | None
    holding_assumed_return_percent: float | None
    years_to_catch_up: float | None
    replacement_assumed_return_percent: float | None
    replacement_months_to_hurdle_gain: float | None
    reasons: tuple[str, ...]
    note: str = SCENARIO_NOTE


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _finite(value: float | None) -> float | None:
    return value if value is not None and isfinite(value) else None


def _whole_days(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _grow(rate_percent: float, years: float) -> float | None:
    try:
        factor = (1 + rate_percent / 100) ** years
    except (OverflowError, ValueError, ZeroDivisionError):
        return None
    return factor if isfinite(factor) else None


def _hurdle_path_value(lots: Sequence[tuple[float, int]], hurdle: float) -> float | None:
    total = 0.0
    for cost, days in lots:
        factor = _grow(hurdle, days / DAYS_PER_YEAR)
        if factor is None:
            return None
        total += cost * factor
    return total if isfinite(total) else None


def _equivalent_annual_return_percent(
    lots: Sequence[tuple[float, int]],
    current_value: float,
) -> float | None:
    """Annual rate that grows every lot's cost from its entry date to the current value."""
    if current_value <= 0:
        return -100.0
    if len(lots) == 1:
        cost, days = lots[0]
        if days <= 0:
            return None
        try:
            return _finite(((current_value / cost) ** (DAYS_PER_YEAR / days) - 1) * 100)
        except (OverflowError, ValueError, ZeroDivisionError):
            return None

    years = [(cost, days / DAYS_PER_YEAR) for cost, days in lots]
    if not any(held > 0 for _, held in years):
        return None

    def value_at(rate: float) -> float:
        total = 0.0
        for cost, held in years:
            try:
                total += cost * (1 + rate) ** held
            except OverflowError:
                return float("inf")
        return total

    if value_at(-1.0) >= current_value:
        return -100.0
    low, high = -1.0, 1.0
    while value_at(high) < current_value:
        low, high = high, high * 2
        if high > 1e6:
            return None
    for _ in range(100):
        middle = (low + high) / 2
        if value_at(middle) < current_value:
            low = middle
        else:
            high = middle
    return _finite((low + high) / 2 * 100)


class HurdleAnalyzer:
    """Measure whether a holding has earned a required annual return.

    Everything here is arithmetic on supplied values. Nothing is forecast:
    outlook comes only from a supplied analyst target upside, and the
    time-to-hurdle figures exist only for an explicitly supplied assumed return.
    A verdict of "below" needs a full year of holding and dividends received, so
    missing inputs leave the status unavailable instead of guessing.
    """

    def __init__(self, minimum_holding_days: int = MINIMUM_HOLDING_DAYS):
        self.minimum_holding_days = minimum_holding_days

    def analyze(
        self,
        symbol: str,
        *,
        cost_basis: Any = None,
        market_value: Any = None,
        dividends: Any = None,
        days_held: int | None = None,
        lots: Sequence[HoldingLot] | None = None,
        required_annual_return_percent: float = DEFAULT_REQUIRED_ANNUAL_RETURN_PERCENT,
        forward_return_percent: Any = None,
        holding_assumed_return_percent: Any = None,
        replacement_assumed_return_percent: Any = None,
    ) -> HurdleAnalysis:
        hurdle = _number(required_annual_return_percent)
        if hurdle is None or hurdle < 0:
            raise ValueError("Required annual return must be a non-negative number.")

        reasons: list[str] = []
        value = _number(market_value)
        received = _number(dividends)
        forward = _number(forward_return_percent)
        assumed_holding = _number(holding_assumed_return_percent)
        replacement = _number(replacement_assumed_return_percent)
        holding_lots = list(lots) if lots is not None else [HoldingLot(cost_basis, days_held)]
        multiple = len(holding_lots) > 1

        costs = [_number(lot.cost_basis) for lot in holding_lots]
        lot_days = [_whole_days(lot.days_held) for lot in holding_lots]
        if not holding_lots:
            reasons.append("No holding lots were provided.")
        if any(days is None for days in lot_days):
            reasons.append(
                "Entry date is unavailable for at least one lot, so holding time cannot be measured."
                if multiple
                else "Entry date is unavailable, so holding time cannot be measured."
            )
        if any(cost is None or cost <= 0 for cost in costs):
            reasons.append(
                "A positive cost basis is required for every lot."
                if multiple
                else "A positive cost basis is required."
            )
        if value is None or value < 0:
            reasons.append("A non-negative market value is required.")

        usable: list[tuple[float, int]] = []
        for lot_cost, days in zip(costs, lot_days):
            if lot_cost is None or lot_cost <= 0 or days is None:
                usable = []
                break
            usable.append((lot_cost, days))

        status = STATUS_UNAVAILABLE
        basis: str | None = None
        reported_days = lot_days[0] if len(lot_days) == 1 else None
        return_percent = hurdle_return = excess = annualized = shortfall = None
        years_to_catch_up = None
        requirements = [CatchUpRequirement(years, None) for years in CATCH_UP_HORIZON_YEARS]

        if usable and value is not None and value >= 0:
            total_cost = sum(cost for cost, _ in usable)
            days = round(sum(cost * held for cost, held in usable) / total_cost)
            reported_days = days
            hurdle_value = _hurdle_path_value(usable, hurdle)
            if hurdle_value is None:
                reasons.append("The holding period is too long to compute a hurdle path.")
            else:
                received_amount = received if received is not None and received >= 0 else None
                basis = BASIS_TOTAL if received_amount is not None else BASIS_PRICE_ONLY
                if received_amount is None:
                    reasons.append(
                        "Dividends received are unavailable or invalid, so the return excludes "
                        "dividends and may understate total return."
                    )
                current_value = value + (received_amount or 0.0)
                return_percent = _finite((current_value / total_cost - 1) * 100)
                hurdle_return = _finite((hurdle_value / total_cost - 1) * 100)
                if return_percent is not None and hurdle_return is not None:
                    excess = return_percent - hurdle_return
                shortfall = _finite(hurdle_value - current_value)
                if days >= DAYS_PER_YEAR:
                    annualized = _equivalent_annual_return_percent(usable, current_value)
                else:
                    reasons.append("Held under one year, so the return is not annualized.")

                if current_value >= hurdle_value:
                    status = STATUS_MEETS
                elif days < self.minimum_holding_days:
                    reasons.append(
                        f"Held {days} days{' (cost-weighted)' if multiple else ''}; at least "
                        f"{self.minimum_holding_days} are required before a holding can be "
                        "judged below the hurdle."
                    )
                elif received_amount is None:
                    reasons.append(
                        "Price return is below the hurdle path; enter dividends received "
                        "(0 if none) to judge total return."
                    )
                else:
                    status = STATUS_BELOW

                requirements = []
                for years in CATCH_UP_HORIZON_YEARS:
                    required = None
                    growth = _grow(hurdle, years)
                    if current_value > 0 and growth is not None:
                        try:
                            required = _finite(
                                ((hurdle_value * growth / current_value) ** (1 / years) - 1) * 100
                            )
                        except (OverflowError, ValueError, ZeroDivisionError):
                            required = None
                    requirements.append(CatchUpRequirement(years, required))

                if assumed_holding is not None and assumed_holding > -100:
                    if current_value >= hurdle_value:
                        years_to_catch_up = 0.0
                    elif current_value > 0 and assumed_holding > hurdle:
                        try:
                            years_to_catch_up = _finite(
                                log(hurdle_value / current_value)
                                / (log1p(assumed_holding / 100) - log1p(hurdle / 100))
                            )
                        except (OverflowError, ValueError, ZeroDivisionError):
                            years_to_catch_up = None
                    else:
                        reasons.append(
                            f"At an assumed {assumed_holding:g}% per year the holding would not "
                            f"catch up with the {hurdle:g}% per year path."
                        )

        if forward is None:
            outlook_status = STATUS_UNAVAILABLE
            reasons.append("Analyst target upside is unavailable, so the forward outlook is unknown.")
        else:
            outlook_status = STATUS_BELOW if forward < hurdle else STATUS_MEETS

        replacement_months = None
        if replacement is not None and replacement > -100:
            if hurdle == 0:
                replacement_months = 0.0
            elif replacement > 0:
                try:
                    replacement_months = _finite(12 * log1p(hurdle / 100) / log1p(replacement / 100))
                except (OverflowError, ValueError, ZeroDivisionError):
                    replacement_months = None
            else:
                reasons.append(
                    "A replacement with an assumed non-positive annual return never reaches the hurdle gain."
                )

        return HurdleAnalysis(
            symbol=symbol,
            required_annual_return_percent=hurdle,
            status=status,
            outlook_status=outlook_status,
            lot_count=len(holding_lots),
            days_held=reported_days,
            return_basis=basis,
            return_percent=return_percent,
            hurdle_return_percent=hurdle_return,
            excess_return_percentage_points=_finite(excess),
            annualized_return_percent=annualized,
            shortfall_amount=shortfall,
            required_return_by_horizon=tuple(requirements),
            forward_return_percent=forward,
            holding_assumed_return_percent=assumed_holding,
            years_to_catch_up=years_to_catch_up,
            replacement_assumed_return_percent=replacement,
            replacement_months_to_hurdle_gain=replacement_months,
            reasons=tuple(dict.fromkeys(reasons)),
        )
