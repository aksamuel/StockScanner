"""Coordinate idempotent hourly and closing-price collection slots."""

from __future__ import annotations

import argparse
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class PriceRunStateError(RuntimeError):
    """Raised when a price collection lease cannot be updated."""


def _rpc(name, payload, *, supabase_url, secret_key, opener=urlopen, timeout=30):
    if not supabase_url:
        raise PriceRunStateError("SUPABASE_URL is required")
    if not secret_key:
        raise PriceRunStateError("SUPABASE_SECRET_KEY is required")
    headers = {
        "apikey": secret_key,
        "Content-Type": "application/json",
        "User-Agent": "StockScanner-GitHub-Actions/1.0",
    }
    if not secret_key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {secret_key}"
    request = Request(
        f"{supabase_url.rstrip('/')}/rest/v1/rpc/{name}",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PriceRunStateError(f"Supabase returned HTTP {exc.code}: {detail}") from exc
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise PriceRunStateError(f"Unable to update the price run state: {exc}") from exc
    if not isinstance(result, bool):
        raise PriceRunStateError("Supabase returned an invalid run-state result")
    return result


def acquire_slot(*, slot, market_date, workflow_run_id, supabase_url, secret_key, **kwargs):
    return _rpc(
        "acquire_price_collection_slot",
        {
            "p_slot": slot,
            "p_market_date": market_date,
            "p_workflow_run_id": int(workflow_run_id),
        },
        supabase_url=supabase_url,
        secret_key=secret_key,
        **kwargs,
    )


def finish_slot(*, slot, workflow_run_id, status, supabase_url, secret_key, **kwargs):
    if status not in {"completed", "failed"}:
        raise PriceRunStateError("status must be completed or failed")
    return _rpc(
        "finish_price_collection_slot",
        {
            "p_slot": slot,
            "p_workflow_run_id": int(workflow_run_id),
            "p_status": status,
        },
        supabase_url=supabase_url,
        secret_key=secret_key,
        **kwargs,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("acquire", "finish"))
    parser.add_argument("--slot", required=True)
    parser.add_argument("--market-date")
    parser.add_argument("--workflow-run-id", required=True, type=int)
    parser.add_argument("--status", choices=("completed", "failed"))
    parser.add_argument("--github-output")
    args = parser.parse_args(argv)
    credentials = {
        "supabase_url": os.environ.get("SUPABASE_URL", ""),
        "secret_key": os.environ.get("SUPABASE_SECRET_KEY", ""),
    }
    try:
        if args.command == "acquire":
            if not args.market_date:
                parser.error("acquire requires --market-date")
            changed = acquire_slot(
                slot=args.slot,
                market_date=args.market_date,
                workflow_run_id=args.workflow_run_id,
                **credentials,
            )
            key = "acquired"
        else:
            if not args.status:
                parser.error("finish requires --status")
            changed = finish_slot(
                slot=args.slot,
                workflow_run_id=args.workflow_run_id,
                status=args.status,
                **credentials,
            )
            key = "finished"
    except PriceRunStateError as exc:
        parser.error(str(exc))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as output:
            output.write(f"{key}={str(changed).lower()}\n")
    print(json.dumps({key: changed, "slot": args.slot}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
