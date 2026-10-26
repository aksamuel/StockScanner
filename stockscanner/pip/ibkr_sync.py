from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Protocol, TextIO

from .models import PositionRecord


def mask_account_identifier(identifier: Any) -> str | None:
    """Return a safe display form without retaining an unmasked account identifier."""
    value = re.sub(r"\s+", "", str(identifier or ""))
    if not value:
        return None
    return f"***{value[-4:]}" if len(value) > 4 else "*" * len(value)


def _field(row: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    lowered = {str(key).strip().lower().replace(" ", "").replace("_", ""): value for key, value in row.items()}
    for name in names:
        key = name.strip().lower().replace(" ", "").replace("_", "")
        if key in lowered and lowered[key] not in (None, ""):
            return lowered[key]
    return default


def _number(value: Any, field_name: str, default: float | None = None) -> float | None:
    if value is None or str(value).strip() == "":
        return default
    try:
        number = float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field_name} in portfolio input") from exc
    if not isfinite(number):
        raise ValueError(f"Invalid {field_name} in portfolio input")
    return number


def _date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    for format_string in ("%Y-%m-%d", "%d/%b/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10], format_string).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise ValueError("Invalid date in portfolio input") from exc


class PortfolioDataSource(Protocol):
    def load_portfolio(self) -> "PortfolioData": ...


@dataclass(frozen=True)
class PortfolioData:
    accounts: list[dict[str, Any]] = field(default_factory=list)
    positions: list[dict[str, Any]] = field(default_factory=list)
    transactions: list[dict[str, Any]] = field(default_factory=list)
    dividends: list[dict[str, Any]] = field(default_factory=list)


class FixturePortfolioDataSource:
    """Recorded fixture source for deterministic tests and offline runs."""

    def __init__(self, data: PortfolioData | Mapping[str, Any]):
        self.data = data if isinstance(data, PortfolioData) else PortfolioData(
            accounts=list(data.get("accounts", [])),
            positions=list(data.get("positions", [])),
            transactions=list(data.get("transactions", [])),
            dividends=list(data.get("dividends", [])),
        )

    def load_portfolio(self) -> PortfolioData:
        return self.data


class CSVPortfolioDataSource:
    """Read existing IBKR CSV/Flex exports without making a network request."""

    def __init__(
        self,
        path: str | Path | TextIO,
        account_name: str = "IBKR",
        default_currency: str | None = "USD",
    ):
        self.account_name = account_name
        self.csv_stream = path if hasattr(path, "read") else None
        self.path = None if self.csv_stream is not None else Path(path)
        if default_currency is not None and not re.fullmatch(r"[A-Za-z]{3}", default_currency.strip()):
            raise ValueError("Default currency must be a three-letter code")
        self.default_currency = default_currency.strip().upper() if default_currency else None

    def load_portfolio(self) -> PortfolioData:
        if self.csv_stream is not None:
            rows = list(csv.DictReader(self.csv_stream))
        else:
            assert self.path is not None
            with self.path.open("r", newline="", encoding="utf-8-sig") as csv_file:
                rows = list(csv.DictReader(csv_file))
        if not rows:
            return PortfolioData()
        if len(rows) > 1000:
            raise ValueError("A portfolio CSV import is limited to 1000 rows")

        positions: list[dict[str, Any]] = []
        transactions: list[dict[str, Any]] = []
        dividends: list[dict[str, Any]] = []
        accounts: dict[str, dict[str, Any]] = {}
        for row in rows:
            currency = str(_field(row, "currency", default=self.default_currency) or "").strip().upper()
            if not re.fullmatch(r"[A-Z]{3}", currency):
                raise ValueError("Currency is missing or invalid in portfolio input")
            symbol = _field(row, "symbol", "ticker")
            account = _field(row, "accountId", "clientAccountId", "account")
            if account:
                masked = mask_account_identifier(account)
                accounts[masked or ""] = {
                    "account_name": self.account_name,
                    "masked_account_id": masked,
                    "currency": currency,
                }
            transaction_date = _field(row, "tradeDate", "trade_date", "date")
            transaction_type = _field(row, "transactionType", "transaction_type", "type")
            if symbol and transaction_date and transaction_type:
                transactions.append({
                    "symbol": symbol,
                    "transaction_type": transaction_type,
                    "quantity": _field(row, "quantity", "shares"),
                    "price": _field(row, "price", "tradePrice"),
                    "trade_date": transaction_date,
                    "currency": currency,
                })
            amount = _field(row, "dividendAmount", "dividend_amount", "amount")
            ex_date = _field(row, "exDate", "ex_date")
            pay_date = _field(row, "payDate", "pay_date")
            if symbol and amount is not None and (ex_date or pay_date):
                dividends.append({
                    "symbol": symbol,
                    "amount": amount,
                    "ex_date": ex_date,
                    "pay_date": pay_date,
                    "currency": currency,
                })
            quantity = _field(row, "quantity", "position")
            if symbol and quantity is not None:
                positions.append({
                    "symbol": symbol,
                    "account_id": account,
                    "quantity": quantity,
                    "average_cost": _field(row, "averageCost", "average_cost", "costBasisPrice", "buy_price"),
                    "market_price": _field(row, "marketPrice", "market_price", "current_price"),
                    "market_value": _field(row, "marketValue", "market_value"),
                    "currency": currency,
                    "entry_date": _field(row, "openDateTime", "entry_date", "buy_date"),
                })
        return PortfolioData(accounts=list(accounts.values()), positions=positions, transactions=transactions, dividends=dividends)


class IBKRPortfolioSyncService:
    """Normalize read-only portfolio sources for the PIP repository."""

    def __init__(self, repository: Any = None, clock=lambda: datetime.now(timezone.utc)):
        self.repository = repository
        self.clock = clock

    def normalize_position(self, raw_position: Mapping[str, Any]) -> PositionRecord:
        symbol = str(_field(raw_position, "symbol", "ticker", default="")).strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,29}", symbol):
            raise ValueError("Invalid symbol in portfolio input")
        quantity = _number(_field(raw_position, "quantity"), "quantity")
        if quantity is None:
            raise ValueError("Position requires a quantity")
        average_cost = _number(_field(raw_position, "average_cost", "averageCost", "buy_price"), "average cost")
        market_price = _number(_field(raw_position, "market_price", "marketPrice", "current_price"), "market price")
        market_value = _number(_field(raw_position, "market_value", "marketValue"), "market value")
        if market_value is None and market_price is not None:
            market_value = quantity * market_price
        cost_basis = quantity * average_cost if average_cost is not None else None
        entry_date_value = _field(raw_position, "entry_date", "openDateTime", "buy_date")
        entry_date = _date(entry_date_value)
        return PositionRecord(
            symbol=symbol,
            account_id=mask_account_identifier(_field(raw_position, "account_id", "accountId", "clientAccountId")),
            portfolio_id=str(_field(raw_position, "portfolio_id") or "") or None,
            quantity=quantity,
            average_cost=average_cost,
            market_price=market_price,
            market_value=market_value,
            currency=str(_field(raw_position, "currency", default="USD")).upper(),
            cost_basis=cost_basis,
            entry_date=datetime.combine(entry_date, datetime.min.time(), tzinfo=timezone.utc) if entry_date else None,
            last_updated=self.clock(),
            notes={"source": str(_field(raw_position, "source", default="ibkr"))},
        )

    def normalize_transaction(self, raw: Mapping[str, Any], portfolio_id: str) -> dict[str, Any]:
        symbol = str(_field(raw, "symbol", "ticker", default="")).strip().upper()
        trade_date = _date(_field(raw, "trade_date", "tradeDate", "date"))
        if not symbol or trade_date is None:
            raise ValueError("Transaction requires a symbol and valid trade date")
        return {
            "portfolio_id": portfolio_id,
            "symbol": symbol,
            "transaction_type": str(_field(raw, "transaction_type", "transactionType", "type", default="")).strip().lower(),
            "quantity": _number(_field(raw, "quantity", "shares"), "transaction quantity", 0.0),
            "price": _number(_field(raw, "price", "tradePrice"), "transaction price"),
            "trade_date": trade_date.isoformat(),
            "metadata": {"currency": str(_field(raw, "currency", default="USD")).upper()},
        }

    def normalize_dividend(self, raw_dividend: Mapping[str, Any]) -> dict[str, Any]:
        symbol = str(_field(raw_dividend, "symbol", "ticker", default="")).strip().upper()
        if not symbol:
            raise ValueError("Dividend requires a symbol")
        return {
            "symbol": symbol,
            "amount": _number(_field(raw_dividend, "amount", "dividend_amount", "dividendAmount"), "dividend amount", 0.0),
            "ex_date": _date(_field(raw_dividend, "ex_date", "exDate")),
            "pay_date": _date(_field(raw_dividend, "pay_date", "payDate")),
            "account_id": mask_account_identifier(_field(raw_dividend, "account_id", "accountId")),
            "portfolio_id": _field(raw_dividend, "portfolio_id"),
            "currency": str(_field(raw_dividend, "currency", default="USD")).upper(),
            "metadata": {},
        }

    def sync_portfolio(self, raw_positions: list[dict[str, Any]]) -> list[PositionRecord]:
        return [self.normalize_position(position) for position in raw_positions]

    def sync_dividends(self, raw_dividends: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.normalize_dividend(dividend) for dividend in raw_dividends]

    def sync(self, source: PortfolioDataSource, portfolio_id: str) -> dict[str, list[Any]]:
        data = source.load_portfolio()
        accounts = [
            {
                "portfolio_id": portfolio_id,
                "account_name": str(_field(account, "account_name", default="IBKR")),
                "masked_account_id": mask_account_identifier(_field(account, "masked_account_id", "account_id")),
                "currency": str(_field(account, "currency", default="USD")).upper(),
            }
            for account in data.accounts
        ]
        positions = self.sync_portfolio(data.positions)
        for position in positions:
            position.portfolio_id = portfolio_id
        transactions = [self.normalize_transaction(row, portfolio_id) for row in data.transactions]
        dividends = [self.normalize_dividend(row) for row in data.dividends]
        for dividend in dividends:
            dividend["portfolio_id"] = portfolio_id

        if self.repository is not None:
            for method_name, payload in (
                ("upsert_accounts", accounts),
                ("upsert_positions", positions),
                ("upsert_transactions", transactions),
                ("upsert_dividends", dividends),
            ):
                method = getattr(self.repository, method_name, None)
                if method is not None:
                    method(portfolio_id, payload)
        return {
            "accounts": accounts,
            "positions": positions,
            "transactions": transactions,
            "dividends": dividends,
        }

    def persist_positions(self, portfolio_id: str, positions: list[PositionRecord]) -> list[PositionRecord]:
        for position in positions:
            position.portfolio_id = portfolio_id
        if self.repository is not None:
            return self.repository.upsert_positions(portfolio_id, positions)
        return positions
