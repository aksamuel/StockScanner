from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import parse_qs, urlparse, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

NYC = ZoneInfo("America/New_York")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hour_slot(dt: Optional[datetime] = None) -> datetime:
    value = (dt or utcnow()).astimezone(timezone.utc).astimezone(NYC)
    return value.replace(minute=0, second=0, microsecond=0)


def hour_slot_key(dt: Optional[datetime] = None) -> str:
    return hour_slot(dt).strftime("%Y-%m-%dT%H:00")


def daily_seed_key(dt: Optional[datetime] = None) -> str:
    value = (dt or utcnow()).astimezone(timezone.utc).astimezone(NYC)
    return value.strftime("%Y-%m-%d")


class SupabaseTransport:
    def request(self, method: str, url: str, *, headers: Optional[Mapping[str, str]] = None, payload: Optional[Any] = None):
        raise NotImplementedError


class UrllibSupabaseTransport(SupabaseTransport):
    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def request(self, method: str, url: str, *, headers: Optional[Mapping[str, str]] = None, payload: Optional[Any] = None):
        if payload is not None and not isinstance(payload, (bytes, bytearray)):
            payload = json.dumps(payload).encode("utf-8")
        req = Request(url, data=payload, headers=headers or {}, method=method)
        with urlopen(req, timeout=self.timeout) as response:
            body = response.read()
            if not body:
                return None
            try:
                return json.loads(body.decode("utf-8"))
            except Exception:
                return body.decode("utf-8")


class SupabaseRESTClient:
    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
        *,
        transport: Optional[SupabaseTransport] = None,
        timeout: int = 15,
    ):
        self.base_url = (url or os.getenv("SUPABASE_URL") or "").rstrip("/")
        self.key = key or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY")
        self.transport = transport or UrllibSupabaseTransport(timeout=timeout)
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.key:
            headers["apikey"] = self.key
            headers["Authorization"] = f"Bearer {self.key}"
        return headers

    def request_json(self, method: str, table_or_path: str, *, payload: Optional[Any] = None, params: Optional[Mapping[str, Any]] = None):
        if not self.base_url:
            raise ValueError("SUPABASE_URL is not configured. Set SUPABASE_URL before using Supabase persistence.")
        if not table_or_path.startswith("/"):
            table_or_path = f"/rest/v1/{table_or_path}"
        query = ""
        if params:
            query = "?" + urlencode({str(k): str(v) for k, v in params.items() if v is not None})
        url = f"{self.base_url}{table_or_path}{query}"
        return self.transport.request(method, url, headers=self._headers(), payload=payload)

    def select(self, table: str, *, filters: Optional[Sequence[Sequence[Any]]] = None, select: str = "*", limit: Optional[int] = None):
        params: Dict[str, Any] = {"select": select}
        if limit is not None:
            params["limit"] = limit
        if filters:
            for field, op, value in filters:
                if op != "eq":
                    raise ValueError("Unsupported Supabase filter operator: " + str(op))
                params[field] = "eq." + str(value)
        result = self.request_json("GET", table, params=params)
        if result is None:
            return []
        return result if isinstance(result, list) else [result]

    def insert(self, table: str, rows: Sequence[Mapping[str, Any]]):
        result = self.request_json("POST", table, payload=list(rows))
        if result is None:
            return []
        return result if isinstance(result, list) else [result]

    def upsert(self, table: str, rows: Sequence[Mapping[str, Any]], *, on_conflict: Optional[str] = None):
        params = {"on_conflict": on_conflict} if on_conflict else None
        result = self.request_json("POST", table, payload=list(rows), params=params)
        if result is None:
            return []
        return result if isinstance(result, list) else [result]

    def patch(self, table: str, row_id: Any, update: Mapping[str, Any]):
        result = self.request_json("PATCH", f"{table}?id=eq.{row_id}", payload=update)
        if result is None:
            return []
        return result if isinstance(result, list) else [result]

    def delete(self, table: str, row_id: Any):
        return self.request_json("DELETE", f"{table}?id=eq.{row_id}")


class SupabaseSnapshotStore:
    def __init__(self, client: Optional[SupabaseRESTClient] = None, *, clock: Optional[Callable[[], datetime]] = None):
        self.client = client or SupabaseRESTClient()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        return self.clock()

    def ensure_run(self, run_kind: str, slot_key: str, *, status: str = "pending") -> Dict[str, Any]:
        existing = self.client.select(
            "scan_runs",
            filters=[("run_kind", "eq", run_kind), ("slot_key", "eq", slot_key)],
            select="*",
            limit=1,
        )
        if existing:
            return existing[0]
        row = {
            "run_kind": run_kind,
            "slot_key": slot_key,
            "status": status,
            "total_tickers": 0,
            "collected_tickers": 0,
            "remaining_tickers": 0,
            "created_at": self._now().isoformat(),
            "updated_at": self._now().isoformat(),
        }
        created = self.client.insert("scan_runs", [row])
        return created[0]

    def seed_daily_universe(self, tickers: Iterable[str], *, seed_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        seed_key = daily_seed_key(seed_date)
        self.ensure_run("daily_seed", seed_key, status="pending")
        seen = set()
        unique: List[str] = []
        for symbol in tickers:
            ticker = str(symbol).strip().upper()
            if ticker and ticker not in seen:
                seen.add(ticker)
                unique.append(ticker)

        added: List[Dict[str, Any]] = []
        for ticker in unique:
            existing = self.client.select(
                "scan_tickers",
                filters=[("slot_key", "eq", seed_key), ("ticker", "eq", ticker)],
                select="*",
                limit=1,
            )
            if existing:
                added.append(existing[0])
                continue
            row = {
                "slot_key": seed_key,
                "ticker": ticker,
                "status": "pending",
                "attempt_count": 0,
                "claimed_by": None,
                "claimed_at": None,
                "created_at": self._now().isoformat(),
                "updated_at": self._now().isoformat(),
            }
            created = self.client.insert("scan_tickers", [row])
            added.append(created[0])
        return added

    def _ticker_rows_for_slot(self, slot_key: str) -> List[Dict[str, Any]]:
        return self.client.select("scan_tickers", filters=[("slot_key", "eq", slot_key)], select="*")

    def get_pending_tickers(self, slot_key: str) -> List[Dict[str, Any]]:
        rows = self._ticker_rows_for_slot(slot_key)
        return [row for row in rows if str(row.get("status", "")).lower() in {"pending", "failed", "retry"}]

    def claim_pending_tickers(self, slot_key: str, *, batch_size: int = 25, claimed_by: str = "cli") -> List[Dict[str, Any]]:
        rows = self.get_pending_tickers(slot_key)[:batch_size]
        claimed: List[Dict[str, Any]] = []
        for row in rows:
            updated = dict(row)
            updated["status"] = "claimed"
            updated["attempt_count"] = int(row.get("attempt_count", 0)) + 1
            updated["claimed_by"] = claimed_by
            updated["claimed_at"] = self._now().isoformat()
            updated["updated_at"] = self._now().isoformat()
            self.client.patch("scan_tickers", row["id"], updated)
            claimed.append(updated)
        return claimed

    def release_ticker(self, slot_key: str, ticker: str, *, reason: str = "retry") -> Dict[str, Any]:
        rows = self.client.select(
            "scan_tickers",
            filters=[("slot_key", "eq", slot_key), ("ticker", "eq", ticker)],
            select="*",
            limit=1,
        )
        if not rows:
            raise KeyError(f"Ticker {ticker} not found for slot {slot_key}")
        row = dict(rows[0])
        row["status"] = "pending" if reason == "retry" else "failed"
        row["claimed_by"] = None
        row["claimed_at"] = None
        row["updated_at"] = self._now().isoformat()
        self.client.patch("scan_tickers", row["id"], row)
        return row

    def mark_collected(self, slot_key: str, ticker: str, *, price: float, snapshot_ts: Optional[datetime] = None, source: str = "yfinance") -> Dict[str, Any]:
        rows = self.client.select(
            "scan_tickers",
            filters=[("slot_key", "eq", slot_key), ("ticker", "eq", ticker)],
            select="*",
            limit=1,
        )
        if not rows:
            raise KeyError(f"Ticker {ticker} not found for slot {slot_key}")
        ticker_row = dict(rows[0])
        snapshot_time = (snapshot_ts or self._now()).isoformat()
        snapshot = {
            "slot_key": slot_key,
            "ticker": ticker,
            "price": float(price),
            "snapshot_time": snapshot_time,
            "source": source,
            "created_at": snapshot_time,
        }
        existing = self.client.select(
            "price_snapshots",
            filters=[("slot_key", "eq", slot_key), ("ticker", "eq", ticker)],
            select="*",
            limit=1,
        )
        if existing:
            self.client.patch("price_snapshots", existing[0]["id"], snapshot)
        else:
            self.client.insert("price_snapshots", [snapshot])

        updated = dict(ticker_row)
        updated["status"] = "collected"
        updated["last_price"] = float(price)
        updated["updated_at"] = self._now().isoformat()
        updated["collected_at"] = snapshot_time
        self.client.patch("scan_tickers", ticker_row["id"], updated)
        return updated

    def collect_hourly_snapshot(
        self,
        slot_key: Optional[str] = None,
        *,
        tickers: Optional[Sequence[str]] = None,
        batch_size: int = 25,
        downloader: Optional[Callable[[str], Dict[str, Any]]] = None,
        source: str = "yfinance",
    ) -> Dict[str, Any]:
        slot = slot_key or hour_slot_key(self._now())
        self.ensure_run("hourly_collection", slot, status="pending")

        if tickers is None:
            daily = self.client.select(
                "scan_tickers",
                filters=[("slot_key", "eq", daily_seed_key(self._now()))],
                select="*",
            )
            if daily:
                tickers = [row["ticker"] for row in daily]

        if tickers:
            for ticker in tickers:
                existing = self.client.select(
                    "scan_tickers",
                    filters=[("slot_key", "eq", slot), ("ticker", "eq", ticker)],
                    select="*",
                    limit=1,
                )
                if not existing:
                    self.client.insert("scan_tickers", [{
                        "slot_key": slot,
                        "ticker": ticker,
                        "status": "pending",
                        "attempt_count": 0,
                        "claimed_by": None,
                        "claimed_at": None,
                        "created_at": self._now().isoformat(),
                        "updated_at": self._now().isoformat(),
                    }])

        claimed = self.claim_pending_tickers(slot, batch_size=batch_size)
        if not claimed:
            collected_total = len(self.client.select("price_snapshots", filters=[("slot_key", "eq", slot)], select="*"))
            if collected_total > 0:
                return {"slot_key": slot, "status": "complete", "collected": collected_total, "remaining": 0, "snapshot": True}
            return {"slot_key": slot, "status": "no_snapshot", "collected": 0, "remaining": 0, "snapshot": False}

        collected = 0
        for row in claimed:
            ticker = str(row["ticker"]).upper()
            if downloader is None:
                raise ValueError("downloader must be supplied for hourly collection")
            try:
                payload = downloader(ticker)
            except Exception:
                self.release_ticker(slot, ticker, reason="retry")
                continue
            if not payload or payload.get("price") is None:
                self.release_ticker(slot, ticker, reason="retry")
                continue
            self.mark_collected(slot, ticker, price=float(payload["price"]), source=source)
            collected += 1

        all_rows = self._ticker_rows_for_slot(slot)
        remaining = sum(1 for row in all_rows if str(row.get("status", "")).lower() != "collected")
        if collected > 0 and remaining == 0:
            status = "complete"
        elif collected > 0:
            status = "partial"
        else:
            status = "no_snapshot"
        return {"slot_key": slot, "status": status, "collected": collected, "remaining": remaining, "snapshot": collected > 0}


class MockSupabaseTransport(SupabaseTransport):
    def __init__(self):
        self.tables = {"scan_runs": [], "scan_tickers": [], "price_snapshots": []}

    def _find(self, table: str, filters: Optional[Sequence[Sequence[Any]]] = None):
        rows = list(self.tables.get(table, []))
        if filters:
            for field, op, value in filters:
                rows = [row for row in rows if str(row.get(field)) == str(value)]
        return rows

    def request(self, method: str, url: str, *, headers: Optional[Mapping[str, str]] = None, payload: Optional[Any] = None):
        parsed = urlparse(url)
        table = parsed.path.split("/rest/v1/")[-1].split("?")[0]
        query = parse_qs(parsed.query)
        if method == "GET":
            filters = []
            for key, values in query.items():
                if key in {"select", "limit"}:
                    continue
                if values and values[0].startswith("eq."):
                    filters.append((key, "eq", values[0][3:]))
                    continue
                if "=" in key and key.split("=", 1)[1].startswith("eq."):
                    field = key.split("=", 1)[0]
                    raw = key.split("=", 1)[1]
                    filters.append((field, "eq", raw.split(".", 1)[1]))
            return self._find(table, filters)
        if method == "POST":
            rows = payload if payload is not None else []
            if isinstance(rows, (bytes, bytearray)):
                rows = json.loads(rows.decode("utf-8"))
            created = []
            for record in rows:
                item = dict(record)
                item.setdefault("id", f"{table}-{len(self.tables.get(table, [])) + 1}")
                self.tables.setdefault(table, []).append(item)
                created.append(item)
            return created
        if method == "PATCH":
            row_id = None
            for key, values in query.items():
                if key == "id":
                    row_id = values[0].split(".", 1)[1]
            patch = payload if payload is not None else {}
            if isinstance(patch, (bytes, bytearray)):
                patch = json.loads(patch.decode("utf-8"))
            matches = [row for row in self.tables.setdefault(table, []) if row.get("id") == row_id]
            for row in matches:
                row.update(patch)
            return matches
        if method == "DELETE":
            row_id = None
            for key, values in query.items():
                if key == "id":
                    row_id = values[0].split(".", 1)[1]
            self.tables[table] = [row for row in self.tables.get(table, []) if row.get("id") != row_id]
            return []
        raise ValueError(f"Unsupported method: {method}")


__all__ = [
    "SupabaseRESTClient",
    "SupabaseSnapshotStore",
    "SupabaseTransport",
    "MockSupabaseTransport",
    "daily_seed_key",
    "hour_slot",
    "hour_slot_key",
    "utcnow",
]
