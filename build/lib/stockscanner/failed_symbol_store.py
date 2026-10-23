"""Persist per-run failed-symbol lists for the admin dashboard."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")
DEFAULT_TIMEOUT_SECONDS = 30


class FailedSymbolStoreError(RuntimeError):
    """Raised when failed-symbol history cannot be persisted."""


def _headers(secret_key):
    if not secret_key:
        raise FailedSymbolStoreError("SUPABASE_SECRET_KEY is required")
    headers = {
        "apikey": secret_key,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
        "User-Agent": "StockScanner-GitHub-Actions/1.0",
    }
    if not secret_key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {secret_key}"
    return headers


def _normalize_symbols(symbols):
    if not isinstance(symbols, list):
        raise FailedSymbolStoreError("failed_symbols must be a JSON array")
    normalized = {}
    for item in symbols:
        if not isinstance(item, dict):
            raise FailedSymbolStoreError("Each failed symbol must be an object")
        symbol = str(item.get("symbol", "")).strip().upper()
        reason = str(item.get("reason", "")).strip()
        if not symbol:
            raise FailedSymbolStoreError("A failed symbol is missing its symbol")
        normalized[symbol] = {"symbol": symbol, "reason": reason}
    return [normalized[symbol] for symbol in sorted(normalized)]


def record_failed_symbol_scan(
    *,
    scan_type,
    workflow_run_id,
    failed_symbols,
    attempted_symbols=None,
    supabase_url,
    secret_key,
    scan_at=None,
    opener=urlopen,
    timeout=DEFAULT_TIMEOUT_SECONDS,
):
    """Upsert one immutable scan list, keyed by run type and GitHub run ID."""
    if scan_type not in {"daily", "hourly"}:
        raise FailedSymbolStoreError("scan_type must be daily or hourly")
    if not supabase_url:
        raise FailedSymbolStoreError("SUPABASE_URL is required")
    try:
        run_id = int(workflow_run_id)
    except (TypeError, ValueError) as exc:
        raise FailedSymbolStoreError("workflow_run_id must be an integer") from exc

    scanned = scan_at or datetime.now(NEW_YORK)
    if scanned.tzinfo is None:
        raise FailedSymbolStoreError("scan_at must be timezone-aware")
    scanned = scanned.astimezone(NEW_YORK)
    normalized_failures = _normalize_symbols(failed_symbols)
    if attempted_symbols is not None and not isinstance(attempted_symbols, list):
        raise FailedSymbolStoreError("attempted_symbols must be a JSON array")
    attempted = sorted({
        str(symbol).strip().upper()
        for symbol in (attempted_symbols if attempted_symbols is not None else [
            item["symbol"] for item in normalized_failures
        ])
        if str(symbol).strip()
    })
    rows = [{
        "market_date": scanned.date().isoformat(),
        "scan_type": scan_type,
        "workflow_run_id": run_id,
        "scan_at": scanned.isoformat(),
        "attempted_symbols": attempted,
        "failed_symbols": normalized_failures,
    }]
    request = Request(
        f"{supabase_url.rstrip('/')}/rest/v1/rpc/record_failed_symbol_scan",
        data=json.dumps({
            "p_market_date": rows[0]["market_date"],
            "p_scan_type": scan_type,
            "p_workflow_run_id": run_id,
            "p_scan_at": scanned.isoformat(),
            "p_attempted_symbols": attempted,
            "p_failed_symbols": normalized_failures,
        }).encode("utf-8"),
        headers={**_headers(secret_key), "Prefer": "return=minimal"},
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise FailedSymbolStoreError(
            f"Supabase returned HTTP {exc.code}: {detail}"
        ) from exc
    except (OSError, URLError) as exc:
        raise FailedSymbolStoreError(
            f"Unable to persist failed-symbol history: {exc}"
        ) from exc
    return rows[0]


def load_pending_failed_symbols(
    *,
    scan_type,
    before_market_date,
    supabase_url,
    secret_key,
    opener=urlopen,
    timeout=DEFAULT_TIMEOUT_SECONDS,
):
    """Load unresolved symbols last failed before the current market date."""
    if scan_type not in {"daily", "hourly"}:
        raise FailedSymbolStoreError("scan_type must be daily or hourly")
    if not supabase_url:
        raise FailedSymbolStoreError("SUPABASE_URL is required")
    if not secret_key:
        raise FailedSymbolStoreError("SUPABASE_SECRET_KEY is required")
    try:
        market_date = datetime.fromisoformat(before_market_date).date().isoformat()
    except (TypeError, ValueError) as exc:
        raise FailedSymbolStoreError(
            "before_market_date must be an ISO date"
        ) from exc
    params = {
        "select": "scan_type,symbol,last_failed_market_date,last_reason",
        "status": "eq.pending",
        "last_failed_market_date": f"lt.{market_date}",
        "order": "last_failed_market_date.asc,symbol.asc",
    }
    params["scan_type"] = f"eq.{scan_type}"
    request = Request(
        f"{supabase_url.rstrip('/')}/rest/v1/failed_symbol_queue?{urlencode(params)}",
        headers=_headers(secret_key),
        method="GET",
    )
    try:
        with opener(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise FailedSymbolStoreError(
            f"Supabase returned HTTP {exc.code}: {detail}"
        ) from exc
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise FailedSymbolStoreError(
            f"Unable to load pending failed symbols: {exc}"
        ) from exc
    if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
        raise FailedSymbolStoreError("Supabase returned invalid pending symbols")
    return [
        {
            "symbol": str(row["symbol"]).strip().upper(),
            "reason": str(row.get("last_reason") or ""),
            "scan_type": row["scan_type"],
            "last_failed_market_date": row["last_failed_market_date"],
        }
        for row in result
        if row.get("symbol") and row.get("scan_type") in {"daily", "hourly"}
    ]


def read_failed_symbols(path):
    """Read failed-symbol rows from scanner output or a price snapshot."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FailedSymbolStoreError(f"Unable to read failed-symbol input: {exc}") from exc

    symbols = payload.get("failed_symbols") if isinstance(payload, dict) else None
    if symbols is None and isinstance(payload, dict):
        failures = payload.get("failures", {})
        if not isinstance(failures, dict):
            raise FailedSymbolStoreError("Snapshot failures must be a JSON object")
        symbols = [
            {"symbol": symbol, "reason": reason}
            for symbol, reason in failures.items()
        ]
    return _normalize_symbols(symbols or [])


def read_attempted_symbols(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FailedSymbolStoreError(f"Unable to read failed-symbol input: {exc}") from exc
    if not isinstance(payload, dict):
        raise FailedSymbolStoreError("Failed-symbol input must be a JSON object")
    symbols = payload.get("attempted_symbols", [])
    if not isinstance(symbols, list):
        raise FailedSymbolStoreError("attempted_symbols must be a JSON array")
    return sorted({
        str(symbol).strip().upper()
        for symbol in symbols
        if str(symbol).strip()
    })


def read_scan_timestamp(path):
    """Read the source scan's timestamp when it was captured at scan start."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FailedSymbolStoreError(f"Unable to read failed-symbol input: {exc}") from exc
    value = payload.get("scanned_at") if isinstance(payload, dict) else None
    if value is None:
        return None
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise FailedSymbolStoreError("scanned_at must be a valid ISO timestamp") from exc
    if timestamp.tzinfo is None:
        raise FailedSymbolStoreError("scanned_at must include a timezone")
    return timestamp


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_file", type=Path, nargs="?")
    parser.add_argument("--scan-type", choices=("daily", "hourly"), required=True)
    parser.add_argument("--workflow-run-id", type=int)
    parser.add_argument("--before-market-date")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        credentials = {
            "supabase_url": os.environ.get("SUPABASE_URL", ""),
            "secret_key": os.environ.get("SUPABASE_SECRET_KEY", ""),
        }
        if args.before_market_date:
            if not args.output:
                raise FailedSymbolStoreError("pending lookup requires --output")
            pending = load_pending_failed_symbols(
                scan_type=args.scan_type,
                before_market_date=args.before_market_date,
                **credentials,
            )
            args.output.write_text(
                json.dumps({"symbols": pending}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(json.dumps({"pending_count": len(pending)}, sort_keys=True))
            return 0
        if args.source_file is None or args.workflow_run_id is None:
            raise FailedSymbolStoreError(
                "recording requires a source file and --workflow-run-id"
            )
        payload = json.loads(args.source_file.read_text(encoding="utf-8"))
        attempted = payload.get("attempted_symbols", []) if isinstance(payload, dict) else []
        row = record_failed_symbol_scan(
            scan_type=args.scan_type,
            workflow_run_id=args.workflow_run_id,
            failed_symbols=read_failed_symbols(args.source_file),
            attempted_symbols=read_attempted_symbols(args.source_file) or attempted,
            **credentials,
            scan_at=read_scan_timestamp(args.source_file),
        )
    except FailedSymbolStoreError as exc:
        parser.error(str(exc))
    print(json.dumps({
        "market_date": row["market_date"],
        "scan_type": row["scan_type"],
        "failed_count": len(row["failed_symbols"]),
        "workflow_run_id": row["workflow_run_id"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
