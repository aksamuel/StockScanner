"""Read-only per-symbol overview of a portfolio's saved positions.

Everything here is pure: it reads rows the caller already loaded, never converts
currencies, and never fills in a value the import did not provide.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import isfinite
from typing import Any, Iterable, Mapping

FLAG_MIXED_CURRENCY = "mixed_currency"
FLAG_SHORT_POSITION = "short_position"
FLAG_MISSING_COST_BASIS = "missing_cost_basis"
FLAG_MISSING_ENTRY_DATE = "missing_entry_date"
FLAG_MISSING_MARKET_VALUE = "missing_market_value"

FLAG_MESSAGES = {
    FLAG_MIXED_CURRENCY: (
        "Lots in more than one currency, or without a currency, are not added up "
        "because PIP does not convert currencies."
    ),
    FLAG_SHORT_POSITION: "Short positions are listed but not given a return.",
    FLAG_MISSING_COST_BASIS: (
        "A positive cost basis is unavailable for at least one lot, so no return is shown."
    ),
    FLAG_MISSING_ENTRY_DATE: (
        "An entry date is unavailable for at least one lot, so holding time is incomplete."
    ),
    FLAG_MISSING_MARKET_VALUE: (
        "A market value is unavailable for at least one lot, so the value and return are withheld."
    ),
}

HOLDINGS_NOTES = (
    "Values are as of the last import or sync; PIP does not fetch live prices.",
    "Returns are price-only because dividends received are not part of imported positions.",
    "This view only reads saved data. PIP never places or transmits orders.",
)
TRUNCATED_NOTE = (
    "The position list was longer than the page limit, so some holdings are not shown."
)


@dataclass(frozen=True)
class HoldingSummary:
    symbol: str
    currency: str | None
    quantity: float
    lot_count: int
    cost_basis: float | None
    market_value: float | None
    price_return_percent: float | None
    entry_date: str | None
    days_held: int | None
    flags: tuple[str, ...]


@dataclass(frozen=True)
class CurrencyTotal:
    currency: str
    holdings: int
    market_value: float
    priced_holdings: int
    cost_basis: float
    costed_holdings: int


@dataclass(frozen=True)
class FlagSummary:
    flag: str
    message: str
    count: int


@dataclass(frozen=True)
class HoldingsOverview:
    as_of: str | None
    lots: int
    holdings: tuple[HoldingSummary, ...]
    totals: tuple[CurrencyTotal, ...]
    flags: tuple[FlagSummary, ...]
    truncated: bool
    notes: tuple[str, ...]


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _text(value: Any) -> str:
    return str(value or "").strip().upper()


def _entry_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        stamp = value
    else:
        try:
            stamp = datetime.fromisoformat(str(value).strip())
        except ValueError:
            return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _summarize(
    symbol: str,
    rows: list[tuple[Mapping[str, Any], float]],
    today: date,
) -> HoldingSummary:
    currencies = {_text(row.get("currency")) for row, _ in rows}
    mixed = len(currencies) != 1 or "" in currencies
    short = any(quantity < 0 for _, quantity in rows)

    costs: list[float | None] = []
    values: list[float | None] = []
    entry_dates: list[date | None] = []
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
        entry_dates.append(_entry_date(row.get("entry_date")))

    bad_cost = any(cost is None or (cost <= 0 and not short) for cost in costs)
    missing_value = any(value is None for value in values)
    known_dates = [entered for entered in entry_dates if entered is not None]
    cost_basis = None if mixed or any(cost is None for cost in costs) else sum(costs)
    market_value = None if mixed or missing_value else sum(values)
    price_return = None
    if cost_basis is not None and market_value is not None and not short and not bad_cost:
        price_return = (market_value / cost_basis - 1) * 100

    flags = []
    if mixed:
        flags.append(FLAG_MIXED_CURRENCY)
    if short:
        flags.append(FLAG_SHORT_POSITION)
    if bad_cost:
        flags.append(FLAG_MISSING_COST_BASIS)
    if len(known_dates) != len(entry_dates):
        flags.append(FLAG_MISSING_ENTRY_DATE)
    if missing_value:
        flags.append(FLAG_MISSING_MARKET_VALUE)

    earliest = min(known_dates) if known_dates else None
    return HoldingSummary(
        symbol=symbol,
        currency=None if mixed else next(iter(currencies)),
        quantity=sum(quantity for _, quantity in rows),
        lot_count=len(rows),
        cost_basis=cost_basis,
        market_value=market_value,
        price_return_percent=price_return,
        entry_date=earliest.isoformat() if earliest else None,
        days_held=max(0, (today - earliest).days) if earliest else None,
        flags=tuple(flags),
    )


def _totals(holdings: Iterable[HoldingSummary]) -> tuple[CurrencyTotal, ...]:
    by_currency: dict[str, list[HoldingSummary]] = {}
    for holding in holdings:
        if holding.currency:
            by_currency.setdefault(holding.currency, []).append(holding)
    totals = []
    for currency, items in sorted(by_currency.items()):
        priced = [item.market_value for item in items if item.market_value is not None]
        costed = [item.cost_basis for item in items if item.cost_basis is not None]
        totals.append(
            CurrencyTotal(
                currency=currency,
                holdings=len(items),
                market_value=sum(priced),
                priced_holdings=len(priced),
                cost_basis=sum(costed),
                costed_holdings=len(costed),
            )
        )
    return tuple(totals)


def summarize_holdings(
    positions: Iterable[Mapping[str, Any]],
    *,
    truncated: bool = False,
    today: date | None = None,
) -> HoldingsOverview:
    """Group open position rows by symbol without converting or inventing values."""
    today = today or datetime.now(timezone.utc).date()
    grouped: dict[str, list[tuple[Mapping[str, Any], float]]] = {}
    stamps: list[datetime] = []
    for row in positions:
        symbol = _text(row.get("symbol"))
        quantity = _to_float(row.get("quantity"))
        if not symbol or not quantity:
            continue
        grouped.setdefault(symbol, []).append((row, quantity))
        stamp = _timestamp(row.get("last_updated"))
        if stamp is not None:
            stamps.append(stamp)

    holdings = tuple(_summarize(symbol, grouped[symbol], today) for symbol in sorted(grouped))
    flags = tuple(
        FlagSummary(flag, FLAG_MESSAGES[flag], count)
        for flag in FLAG_MESSAGES
        if (count := sum(1 for holding in holdings if flag in holding.flags))
    )
    return HoldingsOverview(
        as_of=max(stamps).astimezone(timezone.utc).isoformat() if stamps else None,
        lots=sum(holding.lot_count for holding in holdings),
        holdings=holdings,
        totals=_totals(holdings),
        flags=flags,
        truncated=truncated,
        notes=HOLDINGS_NOTES + ((TRUNCATED_NOTE,) if truncated else ()),
    )
