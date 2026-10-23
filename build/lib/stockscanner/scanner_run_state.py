"""Coordinate one successful production universe scan per New York market date."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")
DEFAULT_TIMEOUT_SECONDS = 30


class ScannerRunStateError(RuntimeError):
    """Raised when the backend-only scanner run state cannot be updated."""


def _headers(secret_key):
    if not secret_key:
        raise ScannerRunStateError("SUPABASE_SECRET_KEY is required")
    headers = {
        "apikey": secret_key,
        "Content-Type": "application/json",
        "User-Agent": "StockScanner-GitHub-Actions/1.0",
    }
    if not secret_key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {secret_key}"
    return headers


def _rpc(name, payload, *, supabase_url, secret_key, opener, timeout):
    if not supabase_url:
        raise ScannerRunStateError("SUPABASE_URL is required")
    request = Request(
        f"{supabase_url.rstrip('/')}/rest/v1/rpc/{name}",
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(secret_key),
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ScannerRunStateError(
            f"Supabase returned HTTP {exc.code}: {detail}"
        ) from exc
    except (OSError, URLError) as exc:
        raise ScannerRunStateError(f"Unable to reach Supabase: {exc}") from exc
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ScannerRunStateError("Supabase returned invalid JSON") from exc
    if not isinstance(result, bool):
        raise ScannerRunStateError("Supabase returned an invalid run-state result")
    return result


def acquire_daily_run(
    *,
    market_date,
    workflow_run_id,
    trigger_source,
    force=False,
    supabase_url,
    secret_key,
    opener=urlopen,
    timeout=DEFAULT_TIMEOUT_SECONDS,
):
    """Atomically acquire the singleton daily universe-scan lease."""
    return _rpc(
        "acquire_daily_scanner_run",
        {
            "p_market_date": market_date,
            "p_workflow_run_id": int(workflow_run_id),
            "p_trigger_source": trigger_source,
            "p_force": bool(force),
        },
        supabase_url=supabase_url,
        secret_key=secret_key,
        opener=opener,
        timeout=timeout,
    )


def finish_daily_run(
    *,
    market_date,
    workflow_run_id,
    status,
    error=None,
    supabase_url,
    secret_key,
    opener=urlopen,
    timeout=DEFAULT_TIMEOUT_SECONDS,
):
    """Mark the matching acquired run completed or failed."""
    if status not in {"completed", "failed"}:
        raise ScannerRunStateError("status must be completed or failed")
    return _rpc(
        "finish_daily_scanner_run",
        {
            "p_market_date": market_date,
            "p_workflow_run_id": int(workflow_run_id),
            "p_status": status,
            "p_error": error,
        },
        supabase_url=supabase_url,
        secret_key=secret_key,
        opener=opener,
        timeout=timeout,
    )


def _write_output(path, values):
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("acquire", "finish"))
    parser.add_argument("--market-date")
    parser.add_argument("--workflow-run-id", required=True, type=int)
    parser.add_argument("--trigger-source", default="unknown")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--status", choices=("completed", "failed"))
    parser.add_argument("--error")
    parser.add_argument("--github-output")
    args = parser.parse_args(argv)

    market_date = args.market_date or datetime.now(NEW_YORK).date().isoformat()
    credentials = {
        "supabase_url": os.environ.get("SUPABASE_URL", ""),
        "secret_key": os.environ.get("SUPABASE_SECRET_KEY", ""),
    }
    try:
        if args.command == "acquire":
            changed = acquire_daily_run(
                market_date=market_date,
                workflow_run_id=args.workflow_run_id,
                trigger_source=args.trigger_source,
                force=args.force,
                **credentials,
            )
            result = {"acquired": changed, "market_date": market_date}
        else:
            if not args.status:
                parser.error("finish requires --status")
            changed = finish_daily_run(
                market_date=market_date,
                workflow_run_id=args.workflow_run_id,
                status=args.status,
                error=args.error,
                **credentials,
            )
            result = {"finished": changed, "market_date": market_date}
    except ScannerRunStateError as exc:
        parser.error(str(exc))

    _write_output(args.github_output, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
