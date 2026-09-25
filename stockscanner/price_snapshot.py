"""Refresh the public price snapshot used by the static Technical page."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

from .market_data import download_intraday_snapshot
from .display_time import format_new_york_time
from .price_providers import (
    TWELVE_DATA_FREE_SYMBOLS_PER_RUN,
    download_alpaca_snapshots,
    download_twelve_data_snapshots,
)
from .portfolio_symbols import (
    PortfolioSymbolError,
    load_portfolio_symbols,
    normalize_portfolio_symbols,
)


NEW_YORK = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
HOURLY_COLLECTION_START = time(8, 45)
CLOSE_COLLECTION_END = time(18, 0)
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOT_PATH = REPOSITORY_ROOT / "prices.json"


class SnapshotError(ValueError):
    """Raised when a price snapshot cannot be read or validated."""


class _TechnicalReportParser(HTMLParser):
    """Extract symbols and displayed prices from generated report rows."""

    def __init__(self):
        super().__init__()
        self.prices = {}
        self._row_price = None
        self._in_symbol = False
        self._symbol_span_depth = 0
        self._symbol_parts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "tr":
            self._row_price = attributes.get("data-current-price")
        elif tag == "span":
            if self._in_symbol:
                self._symbol_span_depth += 1
            elif "symbol-name" in attributes.get("class", "").split():
                self._in_symbol = True
                self._symbol_span_depth = 1
                self._symbol_parts = []

    def handle_data(self, data):
        if self._in_symbol:
            self._symbol_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "span" and self._in_symbol:
            self._symbol_span_depth -= 1
            if self._symbol_span_depth == 0:
                symbol = "".join(self._symbol_parts).strip().upper()
                price = _valid_price(self._row_price)
                if symbol and price is not None:
                    self.prices.setdefault(symbol, price)
                self._in_symbol = False
        elif tag == "tr":
            self._row_price = None


def _new_york_time(moment=None):
    moment = moment or datetime.now(NEW_YORK)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=NEW_YORK)
    return moment.astimezone(NEW_YORK)


def is_regular_market_session(moment=None):
    """Return whether ``moment`` is within a weekday NYSE regular session."""
    local = _new_york_time(moment)
    return (
        local.weekday() < 5
        and MARKET_OPEN <= local.time().replace(tzinfo=None) <= MARKET_CLOSE
    )


def is_price_collection_window(moment=None, *, close_run=False):
    """Allow hourly snapshots from 08:45 and a dedicated post-close snapshot."""
    local = _new_york_time(moment)
    if local.weekday() >= 5:
        return False
    local_time = local.time().replace(tzinfo=None)
    if close_run:
        return MARKET_CLOSE <= local_time <= CLOSE_COLLECTION_END
    return HOURLY_COLLECTION_START <= local_time < MARKET_CLOSE


def _valid_price(value):
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or price <= 0:
        return None
    return round(price, 4)


def _parse_price_timestamp(value):
    if isinstance(value, datetime):
        return _new_york_time(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return _new_york_time(datetime.fromisoformat(text))
    except ValueError:
        return None


def _snapshot_payload(
    prices,
    generated_at,
    *,
    source,
    failures=None,
    price_timestamp=None,
    previous_close_prices=None,
    market_close_prices=None,
    intraday_series=None,
):
    local = _new_york_time(generated_at)
    yahoo_time = _parse_price_timestamp(price_timestamp)
    normalized = {
        str(symbol).strip().upper(): price
        for symbol, value in prices.items()
        if (price := _valid_price(value)) is not None
    }
    return {
        "schema_version": 3,
        "market_date": local.date().isoformat(),
        "generated_at": local.isoformat(),
        "generated_at_new_york": format_new_york_time(local),
        "price_timestamp": yahoo_time.isoformat() if yahoo_time else None,
        "price_timestamp_new_york": (
            format_new_york_time(yahoo_time)
            if yahoo_time
            else None
        ),
        "timezone": "America/New_York",
        "source": source,
        "symbol_count": len(normalized),
        "prices": dict(sorted(normalized.items())),
        "previous_close_prices": dict(sorted((previous_close_prices or {}).items())),
        "market_close_prices": dict(sorted((market_close_prices or {}).items())),
        # Retained temporarily for older deployed clients. It is explicitly the
        # previous close, not the current trading day's closing price.
        "daily_prices": dict(sorted((previous_close_prices or {}).items())),
        "intraday_series": dict(sorted((intraday_series or {}).items())),
        "failures": dict(sorted((failures or {}).items())),
    }


def _current_intraday_series(previous, updated_results, generated_at):
    """Keep only today's bounded hourly points in the singleton payload."""
    local = _new_york_time(generated_at)
    previous_series = previous.get("intraday_series", {}) if previous else {}
    series = {}
    for symbol, points in previous_series.items():
        if not isinstance(points, list):
            continue
        today_points = []
        for point in points:
            if not isinstance(point, dict):
                continue
            timestamp = _parse_price_timestamp(point.get("timestamp"))
            price = _valid_price(point.get("price"))
            if timestamp and timestamp.date() == local.date() and price is not None:
                today_points.append({"timestamp": timestamp.isoformat(), "price": price})
        if today_points:
            series[symbol] = today_points[-16:]

    for symbol, result in updated_results.items():
        price = _valid_price(result.get("price"))
        if price is None:
            continue
        timestamp = _parse_price_timestamp(result.get("timestamp")) or local
        if timestamp.date() != local.date():
            continue
        point = {"timestamp": timestamp.isoformat(), "price": price}
        points = series.setdefault(symbol, [])
        points = [item for item in points if item["timestamp"] != point["timestamp"]]
        points.append(point)
        series[symbol] = sorted(points, key=lambda item: item["timestamp"])[-16:]
    return series


def _write_snapshot(payload, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_snapshot(path=DEFAULT_SNAPSHOT_PATH):
    """Load and validate a public price snapshot."""
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"Unable to read {path}: {exc}") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("prices"), dict):
        raise SnapshotError(f"{path} must contain a prices object")
    prices = {}
    for symbol, value in payload["prices"].items():
        price = _valid_price(value)
        if not isinstance(symbol, str) or not symbol.strip() or price is None:
            raise SnapshotError(f"{path} contains an invalid symbol or price")
        prices[symbol.strip().upper()] = price
    payload["prices"] = prices
    return payload


def prices_from_report(path):
    """Read the symbol prices embedded in a generated Technical page."""
    parser = _TechnicalReportParser()
    try:
        parser.feed(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise SnapshotError(f"Unable to read report {path}: {exc}") from exc
    return parser.prices


def _report_candidates(root=REPOSITORY_ROOT):
    root = Path(root)
    stable = root / "technical.html"
    candidates = [stable] if stable.exists() else []
    candidates.extend(
        sorted(
            (root / "reports").glob("*/technical.html"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    )
    return candidates


def bootstrap_prices(report_paths: Iterable[Path] | None = None):
    """Get initial symbols/prices from the newest usable generated report."""
    for path in report_paths or _report_candidates():
        prices = prices_from_report(path)
        if prices:
            return prices
    raise SnapshotError(
        "No prices.json or generated Technical report with symbol prices was found"
    )


def write_snapshot_from_results(results, path=DEFAULT_SNAPSHOT_PATH, generated_at=None):
    """Write scanner result prices so hourly refreshes have a stable symbol set."""
    prices = {}
    price_timestamps = []
    records = results.to_dict("records") if hasattr(results, "to_dict") else results
    for row in records:
        symbol = str(row.get("Symbol", "")).strip().upper()
        price = _valid_price(row.get("Current Price"))
        if symbol and price is not None:
            prices[symbol] = price
            timestamp = _parse_price_timestamp(row.get("Price As Of"))
            if timestamp is not None:
                price_timestamps.append(timestamp)
    if not prices:
        raise SnapshotError("Scanner results did not contain any valid symbol prices")
    payload = _snapshot_payload(
        prices,
        generated_at or datetime.now(NEW_YORK),
        source="full_scan",
        price_timestamp=max(price_timestamps) if price_timestamps else None,
    )
    _write_snapshot(payload, path)
    return payload


def refresh_snapshot(
    path=DEFAULT_SNAPSHOT_PATH,
    *,
    now=None,
    downloader: Callable = download_intraday_snapshot,
    alpaca_downloader: Callable = download_alpaca_snapshots,
    twelve_data_downloader: Callable = download_twelve_data_snapshots,
    report_paths=None,
    additional_symbols=None,
    close_run=False,
):
    """Refresh scanner and held-symbol prices through bounded free providers."""
    local = _new_york_time(now)
    if not is_price_collection_window(local, close_run=close_run):
        return {
            "published": False,
            "reason": "outside_price_collection_window",
            "generated_at_new_york": format_new_york_time(local),
        }

    previous = load_snapshot(path)
    prior_prices = (
        previous["prices"] if previous is not None else bootstrap_prices(report_paths)
    )
    prices = dict(prior_prices)
    previous_generated_at = _parse_price_timestamp(
        previous.get("generated_at") if previous else None
    )
    same_market_day = bool(
        previous_generated_at and previous_generated_at.date() == local.date()
    )
    # On a new market date, yesterday's recorded market close becomes today's
    # previous close. Provider daily-close values below fill or correct it.
    previous_close_prices = {}
    if previous:
        if same_market_day:
            previous_close_prices = dict(
                previous.get("previous_close_prices")
                or previous.get("daily_prices", {})
            )
        else:
            previous_close_prices = dict(previous.get("market_close_prices", {}))
    market_close_prices = (
        dict(previous.get("market_close_prices", {}))
        if previous and same_market_day
        else {}
    )
    portfolio_symbols = normalize_portfolio_symbols(additional_symbols or [])
    symbols = sorted(set(prior_prices).union(portfolio_symbols))
    updated_results = {}
    provider_for_symbol = {}
    attempt_errors = {symbol: [] for symbol in symbols}
    price_timestamps = []

    def yahoo_batch(requested, *, now):
        results = {}
        errors = {}
        if not requested:
            return results, errors

        def fetch(symbol):
            return downloader(symbol, now=now)

        # Four workers keep Yahoo pressure modest while preventing one slow
        # symbol from serially delaying the entire half-list.
        with ThreadPoolExecutor(max_workers=min(4, len(requested))) as executor:
            futures = {executor.submit(fetch, symbol): symbol for symbol in requested}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results[symbol] = future.result()
                except (
                    LookupError,
                    OSError,
                    RuntimeError,
                    TypeError,
                    ValueError,
                ) as exc:
                    errors[symbol] = f"{type(exc).__name__}: {exc}"
        return results, errors

    def attempt(provider, requested, fetcher):
        requested = [symbol for symbol in requested if symbol not in updated_results]
        if not requested:
            return
        try:
            response = fetcher(requested, now=local)
            if provider == "Yahoo":
                response, errors = response
            else:
                errors = {}
        except (LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
            response = {}
            errors = {
                symbol: f"{type(exc).__name__}: {exc}" for symbol in requested
            }

        if not isinstance(response, dict):
            response = {}
        for symbol in requested:
            result = response.get(symbol)
            price = _valid_price(
                result.get("price") if isinstance(result, dict) else None
            )
            if price is None:
                detail = errors.get(symbol, "no valid current price")
                attempt_errors[symbol].append(f"{provider}: {detail}")
                continue
            updated_results[symbol] = result
            provider_for_symbol[symbol] = provider

    # Alternate sorted symbols so each primary provider receives half of the
    # list while retaining a stable split between workflow runs.
    alpaca_primary = symbols[::2]
    yahoo_primary = symbols[1::2]
    attempt("Alpaca", alpaca_primary, alpaca_downloader)
    attempt("Yahoo", yahoo_primary, yahoo_batch)

    # Cross-provider fallback: every missing symbol is tried by the other
    # primary provider exactly once. This is bounded to protect free quotas.
    attempt("Alpaca", yahoo_primary, alpaca_downloader)
    attempt("Yahoo", alpaca_primary, yahoo_batch)

    unresolved = [symbol for symbol in symbols if symbol not in updated_results]
    attempt(
        "Twelve Data",
        unresolved[:TWELVE_DATA_FREE_SYMBOLS_PER_RUN],
        twelve_data_downloader,
    )

    failures = {
        symbol: "; ".join(attempt_errors[symbol]) or "No provider returned a price"
        for symbol in symbols
        if symbol not in updated_results
    }
    for symbol, result in updated_results.items():
        prices[symbol] = _valid_price(result.get("price"))
        previous_close = _valid_price(result.get("daily_close"))
        if previous_close is not None:
            previous_close_prices[symbol] = previous_close
        timestamp = _parse_price_timestamp(result.get("timestamp"))
        if timestamp is not None:
            price_timestamps.append(timestamp)
        if close_run and (timestamp is None or timestamp.date() == local.date()):
            market_close_prices[symbol] = prices[symbol]

    for symbol, message in failures.items():
        print(f"Price refresh failed for {symbol}: {message}", file=sys.stderr)
    if not updated_results:
        raise SnapshotError(
            "All free price providers failed; the prior snapshot was preserved"
        )

    # In production, record when collection completed rather than when the
    # potentially long series of Yahoo requests started. Tests and callers
    # that inject ``now`` retain deterministic timestamps.
    generated_at = local if now is not None else datetime.now(NEW_YORK)
    intraday_series = _current_intraday_series(previous, updated_results, generated_at)
    payload = _snapshot_payload(
        prices,
        generated_at,
        source="hourly_yahoo",
        failures=failures,
        price_timestamp=max(price_timestamps) if price_timestamps else None,
        previous_close_prices=previous_close_prices,
        market_close_prices=market_close_prices,
        intraday_series=intraday_series,
    )
    provider_counts = {
        provider: sum(1 for value in provider_for_symbol.values() if value == provider)
        for provider in ("Alpaca", "Yahoo", "Twelve Data")
    }
    payload["collection_strategy"] = "free_split_with_bounded_failover"
    payload["requested_symbol_count"] = len(symbols)
    payload["portfolio_symbol_count"] = len(portfolio_symbols)
    portfolio_updated = sorted(set(portfolio_symbols).intersection(updated_results))
    portfolio_missing = sorted(set(portfolio_symbols).difference(updated_results))
    payload["portfolio_updated_count"] = len(portfolio_updated)
    payload["portfolio_missing_symbols"] = portfolio_missing
    payload["portfolio_coverage_percent"] = round(
        100 * len(portfolio_updated) / len(portfolio_symbols), 2
    ) if portfolio_symbols else 100.0
    payload["provider_counts"] = provider_counts
    payload["provider_by_symbol"] = dict(sorted(provider_for_symbol.items()))
    payload["stale_symbols"] = sorted(
        symbol for symbol in failures if symbol in prices
    )
    payload["collection_kind"] = "market_close" if close_run else "intraday"
    payload["updated_symbols"] = sorted(updated_results)
    _write_snapshot(payload, path)

    return {
        "published": True,
        "updated": len(updated_results),
        "failed": len(failures),
        "symbols": len(prices),
        "provider_counts": provider_counts,
        "portfolio_updated": len(portfolio_updated),
        "portfolio_missing": len(portfolio_missing),
        "collection_kind": payload["collection_kind"],
        "path": str(path),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_SNAPSHOT_PATH,
        help="Snapshot JSON path (default: repository prices.json)",
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "hourly", "close"),
        default="auto",
        help="Collection window; auto uses close mode from 4 PM New York.",
    )
    args = parser.parse_args(argv)
    try:
        supabase_url = os.environ.get("SUPABASE_URL", "")
        secret_key = os.environ.get("SUPABASE_SECRET_KEY", "")
        portfolio_symbols = []
        if supabase_url or secret_key:
            portfolio_symbols = load_portfolio_symbols(
                supabase_url=supabase_url,
                secret_key=secret_key,
            )
        local_now = datetime.now(NEW_YORK)
        close_run = args.mode == "close" or (
            args.mode == "auto" and local_now.time().replace(tzinfo=None) >= MARKET_CLOSE
        )
        result = refresh_snapshot(
            args.output,
            additional_symbols=portfolio_symbols,
            close_run=close_run,
        )
    except (PortfolioSymbolError, SnapshotError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
