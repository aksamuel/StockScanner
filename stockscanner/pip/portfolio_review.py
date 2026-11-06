"""Read-only portfolio review: rank holdings by how far they trail the return hurdle."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Any, Iterable, Mapping

from .dead_money import DeadMoneyAssessment, DeadMoneyDetector
from .hurdle import (
    DEFAULT_REQUIRED_ANNUAL_RETURN_PERCENT,
    STATUS_UNAVAILABLE,
    HoldingLot,
    HurdleAnalysis,
    HurdleAnalyzer,
)
from .models import ReplacementCandidate
from .position_lifecycle import PositionLifecycleAnalyzer
from .replacement_engine import ReplacementCandidateEngine

DEFAULT_TOP_N = 5
DEFAULT_REPLACEMENT_LIMIT = 5
MAX_SKIPPED_SYMBOLS = 20

SKIP_MIXED_CURRENCY = "mixed_currency"
SKIP_SHORT_POSITION = "short_position"
SKIP_NO_COST_BASIS = "no_cost_basis"
SKIP_NO_ENTRY_DATE = "no_entry_date"
SKIP_NO_MARKET_VALUE = "no_market_value"
SKIP_NOT_COMPUTABLE = "not_computable"

SKIP_MESSAGES = {
    SKIP_MIXED_CURRENCY: (
        "Positions in more than one currency, or without a currency, are not compared "
        "because PIP does not convert currencies."
    ),
    SKIP_SHORT_POSITION: "Short positions are not compared; the return hurdle applies to long holdings only.",
    SKIP_NO_COST_BASIS: "A positive cost basis is required for every lot; zero-cost or missing-cost lots cannot be compared.",
    SKIP_NO_ENTRY_DATE: "Entry date is unavailable for at least one lot, so holding time cannot be measured.",
    SKIP_NO_MARKET_VALUE: "A non-negative market value is required.",
    SKIP_NOT_COMPUTABLE: "The hurdle path could not be computed for this holding.",
}

REVIEW_NOTES = (
    "Holdings are ranked by how many percentage points their return since purchase trails what "
    "the same cost would have earned at the required annual return. This is a comparison, not a forecast.",
    "Returns are price-only because dividends received are not part of imported positions, so "
    "dividend payers can look further behind than they are.",
    "Only holdings kept at least the minimum holding period are ranked. Dead-money verdicts need "
    "a saved CPS or an analyst outlook; replacements also need candidate scores you supply.",
    "This review only reads saved data. PIP never places or transmits orders.",
)
TRUNCATED_NOTE = (
    "The position list was longer than the review limit, so some holdings were not reviewed."
)
UNCONFIRMED_REASON = (
    "Dividends received are unknown, so this shortfall is price-only and a dead-money verdict is "
    "withheld. Analyze this holding and enter dividends received to confirm."
)


@dataclass(frozen=True)
class ReplacementAdvice:
    compared: bool
    reasons: tuple[str, ...]
    candidates: tuple[ReplacementCandidate, ...]


@dataclass(frozen=True)
class ReviewedHolding:
    rank: int
    symbol: str
    currency: str
    hurdle: HurdleAnalysis
    cps: float | None
    dead_money: DeadMoneyAssessment
    replacements: ReplacementAdvice


@dataclass(frozen=True)
class ReviewSkip:
    reason: str
    message: str
    count: int
    symbols: tuple[str, ...]


@dataclass(frozen=True)
class ReviewSummary:
    holdings: int
    not_analysable: int
    held_under_minimum: int
    meeting_hurdle: int
    behind_hurdle: int
    truncated: bool


@dataclass(frozen=True)
class PortfolioReview:
    required_annual_return_percent: float
    minimum_holding_days: int
    top_n: int
    summary: ReviewSummary
    top: tuple[ReviewedHolding, ...]
    skipped: tuple[ReviewSkip, ...]
    notes: tuple[str, ...]


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _score(value: Any) -> float | None:
    number = _to_float(value)
    return number if number is not None and 0 <= number <= 100 else None


def _symbol(row: Mapping[str, Any]) -> str:
    return str(row.get("symbol") or "").strip().upper()


def _currency(row: Mapping[str, Any]) -> str:
    return str(row.get("currency") or "").strip().upper()


def _group_open_positions(
    positions: Iterable[Mapping[str, Any]],
) -> dict[str, list[tuple[Mapping[str, Any], float]]]:
    grouped: dict[str, list[tuple[Mapping[str, Any], float]]] = {}
    for row in positions:
        symbol = _symbol(row)
        quantity = _to_float(row.get("quantity"))
        if symbol and quantity:
            grouped.setdefault(symbol, []).append((row, quantity))
    return grouped


def _latest_signals(rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    latest: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        symbol = _symbol(row)
        if not symbol:
            continue
        current = latest.get(symbol)
        if current is None or str(row.get("signal_date") or "") > str(current.get("signal_date") or ""):
            latest[symbol] = row
    return latest


def _forward_return_percent(signal: Mapping[str, Any] | None, price: float | None) -> float | None:
    if not signal:
        return None
    target = _to_float(signal.get("target_price"))
    if target is not None and target > 0 and price is not None and price > 0:
        return (target / price - 1) * 100
    return _to_float(signal.get("target_upside"))


class PortfolioReviewer:
    """Ranks open positions by distance behind the return hurdle without writing anything."""

    def __init__(
        self,
        *,
        lifecycle_analyzer: PositionLifecycleAnalyzer | None = None,
        hurdle_analyzer: HurdleAnalyzer | None = None,
        dead_money_detector: DeadMoneyDetector | None = None,
        replacement_engine: ReplacementCandidateEngine | None = None,
    ):
        self.lifecycle_analyzer = lifecycle_analyzer or PositionLifecycleAnalyzer()
        self.hurdle_analyzer = hurdle_analyzer or HurdleAnalyzer()
        self.dead_money_detector = dead_money_detector or DeadMoneyDetector()
        self.replacement_engine = replacement_engine or ReplacementCandidateEngine()

    def review(
        self,
        positions: Iterable[Mapping[str, Any]],
        *,
        scores: Iterable[Mapping[str, Any]] = (),
        signals: Iterable[Mapping[str, Any]] = (),
        required_annual_return_percent: float = DEFAULT_REQUIRED_ANNUAL_RETURN_PERCENT,
        top_n: int = DEFAULT_TOP_N,
        peer_scores: Iterable[tuple[str, float]] = (),
        replacement_limit: int = DEFAULT_REPLACEMENT_LIMIT,
        truncated: bool = False,
    ) -> PortfolioReview:
        required = _to_float(required_annual_return_percent)
        if required is None or required < 0:
            raise ValueError("Required annual return must be a non-negative number.")
        if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 1:
            raise ValueError("top_n must be a positive whole number.")
        if (
            isinstance(replacement_limit, bool)
            or not isinstance(replacement_limit, int)
            or replacement_limit < 1
        ):
            raise ValueError("replacement_limit must be a positive whole number.")

        holdings = _group_open_positions(positions)
        score_rows = {_symbol(row): row for row in scores if _symbol(row)}
        signal_rows = _latest_signals(signals)
        # A symbol supplied twice keeps its lowest score so a conflicting entry cannot inflate a candidate.
        candidate_scores: dict[str, float] = {}
        for candidate_symbol, candidate_score in peer_scores:
            name = str(candidate_symbol).strip().upper()
            number = _to_float(candidate_score)
            if name and number is not None:
                candidate_scores[name] = min(number, candidate_scores.get(name, number))
        peers = sorted(candidate_scores.items())
        held_symbols = tuple(holdings)

        skipped: dict[str, list[str]] = {}
        behind: list[tuple[str, str, HurdleAnalysis]] = []
        held_under_minimum = meeting_hurdle = 0
        for symbol in sorted(holdings):
            analysis, currency, skip_reason = self._analyse_holding(
                symbol, holdings[symbol], required, signal_rows.get(symbol)
            )
            if analysis is None:
                skipped.setdefault(skip_reason or SKIP_NOT_COMPUTABLE, []).append(symbol)
            elif analysis.days_held is None or analysis.days_held < self.hurdle_analyzer.minimum_holding_days:
                held_under_minimum += 1
            elif analysis.shortfall_amount is not None and analysis.shortfall_amount > 0:
                behind.append((symbol, currency, analysis))
            else:
                meeting_hurdle += 1

        behind.sort(key=lambda item: (item[2].excess_return_percentage_points, item[0]))
        top = []
        for rank, (symbol, currency, analysis) in enumerate(behind[:top_n], start=1):
            score_row = score_rows.get(symbol, {})
            cps = _score(score_row.get("cps"))
            dead_money = self.dead_money_detector.assess(
                symbol,
                cps=cps,
                total_return_percent=None,
                opportunity_cost_score=_score(score_row.get("opportunity_cost")),
                hurdle=analysis,
            )
            if dead_money.is_dead_money is False and analysis.status == STATUS_UNAVAILABLE:
                dead_money = replace(
                    dead_money,
                    is_dead_money=None,
                    reasons=dead_money.reasons + (UNCONFIRMED_REASON,),
                )
            top.append(
                ReviewedHolding(
                    rank=rank,
                    symbol=symbol,
                    currency=currency,
                    hurdle=analysis,
                    cps=cps,
                    dead_money=dead_money,
                    replacements=self._replacement_advice(
                        symbol, cps, peers, held_symbols, replacement_limit
                    ),
                )
            )

        skips = tuple(
            ReviewSkip(
                reason=reason,
                message=SKIP_MESSAGES[reason],
                count=len(symbols),
                symbols=tuple(symbols[:MAX_SKIPPED_SYMBOLS]),
            )
            for reason, symbols in sorted(skipped.items(), key=lambda item: (-len(item[1]), item[0]))
        )
        return PortfolioReview(
            required_annual_return_percent=required,
            minimum_holding_days=self.hurdle_analyzer.minimum_holding_days,
            top_n=top_n,
            summary=ReviewSummary(
                holdings=len(holdings),
                not_analysable=sum(skip.count for skip in skips),
                held_under_minimum=held_under_minimum,
                meeting_hurdle=meeting_hurdle,
                behind_hurdle=len(behind),
                truncated=truncated,
            ),
            top=tuple(top),
            skipped=skips,
            notes=REVIEW_NOTES + ((TRUNCATED_NOTE,) if truncated else ()),
        )

    def _analyse_holding(
        self,
        symbol: str,
        rows: list[tuple[Mapping[str, Any], float]],
        required: float,
        signal: Mapping[str, Any] | None,
    ) -> tuple[HurdleAnalysis | None, str, str | None]:
        currencies = {_currency(row) for row, _ in rows}
        if len(currencies) != 1 or "" in currencies:
            return None, "", SKIP_MIXED_CURRENCY
        currency = next(iter(currencies))
        if any(quantity < 0 for _, quantity in rows):
            return None, currency, SKIP_SHORT_POSITION

        costs: list[float | None] = []
        values: list[float | None] = []
        days: list[int | None] = []
        for row, quantity in rows:
            cost = _to_float(row.get("cost_basis"))
            if cost is None:
                average_cost = _to_float(row.get("average_cost"))
                cost = average_cost * quantity if average_cost is not None else None
            value = _to_float(row.get("market_value"))
            if value is None:
                price = _to_float(row.get("market_price"))
                value = price * quantity if price is not None else None
            costs.append(cost)
            values.append(value)
            days.append(self.lifecycle_analyzer.days_since(row.get("entry_date")))

        if any(cost is None or cost <= 0 for cost in costs):
            return None, currency, SKIP_NO_COST_BASIS
        if any(held is None for held in days):
            return None, currency, SKIP_NO_ENTRY_DATE
        total_value = None if any(value is None for value in values) else sum(values)
        if total_value is None or total_value < 0:
            return None, currency, SKIP_NO_MARKET_VALUE

        total_quantity = sum(quantity for _, quantity in rows)
        price = total_value / total_quantity if total_quantity > 0 else None
        analysis = self.hurdle_analyzer.analyze(
            symbol,
            lots=[HoldingLot(cost, held) for cost, held in zip(costs, days)],
            market_value=total_value,
            dividends=None,
            required_annual_return_percent=required,
            forward_return_percent=_forward_return_percent(signal, price),
        )
        if analysis.excess_return_percentage_points is None or analysis.shortfall_amount is None:
            return None, currency, SKIP_NOT_COMPUTABLE
        return analysis, currency, None

    def _replacement_advice(
        self,
        symbol: str,
        cps: float | None,
        peers: list[tuple[str, float]],
        held_symbols: tuple[str, ...],
        limit: int,
    ) -> ReplacementAdvice:
        reasons = []
        if not peers:
            reasons.append("No replacement candidate scores were supplied.")
        if cps is None:
            reasons.append(
                "This holding has no saved CPS, so candidates cannot be compared with it; "
                "analyze the holding to save one."
            )
        if reasons:
            return ReplacementAdvice(False, tuple(reasons), ())
        candidates = self.replacement_engine.generate_candidates(
            symbol=symbol,
            current_score=cps,
            peer_scores=peers,
            max_candidates=limit,
            held_symbols=held_symbols,
        )
        if not candidates:
            return ReplacementAdvice(
                True, ("No supplied candidate scores are above this holding's CPS.",), ()
            )
        return ReplacementAdvice(True, (), tuple(candidates))
