"""Refresh the public price snapshot used by the static Technical page."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, time
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

from .market_data import download_intraday_snapshot


NEW_YORK = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
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
):
    local = _new_york_time(generated_at)
    yahoo_time = _parse_price_timestamp(price_timestamp)
    normalized = {
        str(symbol).strip().upper(): price
        for symbol, value in prices.items()
        if (price := _valid_price(value)) is not None
    }
    return {
        "schema_version": 1,
        "generated_at": local.isoformat(),
        "generated_at_new_york": local.strftime("%d %B %Y, %I:%M %p %Z"),
        "price_timestamp": yahoo_time.isoformat() if yahoo_time else None,
        "price_timestamp_new_york": (
            yahoo_time.strftime("%d %B %Y, %I:%M %p %Z")
            if yahoo_time
            else None
        ),
        "timezone": "America/New_York",
        "source": source,
        "symbol_count": len(normalized),
        "prices": dict(sorted(normalized.items())),
        "failures": dict(sorted((failures or {}).items())),
    }


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
    report_paths=None,
):
    """Refresh displayed symbols during market hours, preserving failed values."""
    local = _new_york_time(now)
    if not is_regular_market_session(local):
        return {
            "published": False,
            "reason": "outside_regular_market_session",
            "generated_at_new_york": local.strftime("%d %B %Y, %I:%M %p %Z"),
        }

    previous = load_snapshot(path)
    prior_prices = (
        previous["prices"] if previous is not None else bootstrap_prices(report_paths)
    )
    prices = dict(prior_prices)
    failures = {}
    updated = []
    price_timestamps = []

    for symbol in sorted(prior_prices):
        try:
            result = downloader(symbol, now=local)
            price = _valid_price(result.get("price") if isinstance(result, dict) else None)
            if price is None:
                failures[symbol] = "Yahoo returned no valid intraday price"
                continue
            prices[symbol] = price
            updated.append(symbol)
            timestamp = _parse_price_timestamp(result.get("timestamp"))
            if timestamp is not None:
                price_timestamps.append(timestamp)
        except (LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
            failures[symbol] = f"{type(exc).__name__}: {exc}"

    for symbol, message in failures.items():
        print(f"Price refresh failed for {symbol}: {message}", file=sys.stderr)
    if not updated:
        raise SnapshotError(
            "Yahoo returned no valid intraday prices; the prior snapshot was preserved"
        )

    payload = _snapshot_payload(
        prices,
        local,
        source="hourly_yahoo",
        failures=failures,
        price_timestamp=max(price_timestamps) if price_timestamps else None,
    )
    payload["updated_symbols"] = updated
    _write_snapshot(payload, path)

    return {
        "published": True,
        "updated": len(updated),
        "failed": len(failures),
        "symbols": len(prices),
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
    args = parser.parse_args(argv)
    try:
        result = refresh_snapshot(args.output)
    except SnapshotError as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
