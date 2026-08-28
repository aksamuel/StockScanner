"""Persist generated price snapshots to the StockScanner Supabase project."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_TIMEOUT_SECONDS = 30


class SupabaseSnapshotError(RuntimeError):
    """Raised when a snapshot cannot be stored in Supabase."""


def snapshot_record(payload):
    """Convert a prices.json payload into one database record."""
    if not isinstance(payload, dict):
        raise SupabaseSnapshotError("Snapshot payload must be a JSON object")

    prices = payload.get("prices")
    failures = payload.get("failures", {})
    if not isinstance(prices, dict) or not prices:
        raise SupabaseSnapshotError("Snapshot must contain a non-empty prices object")
    if not isinstance(failures, dict):
        raise SupabaseSnapshotError("Snapshot failures must be a JSON object")
    if not payload.get("generated_at") or not payload.get("source"):
        raise SupabaseSnapshotError("Snapshot requires generated_at and source")
    if payload["source"] != "hourly_yahoo":
        raise SupabaseSnapshotError(
            "Supabase stores only the latest hourly_yahoo price snapshot"
        )

    updated_symbols = payload.get("updated_symbols", [])
    return {
        "generated_at": payload["generated_at"],
        "price_timestamp": payload.get("price_timestamp"),
        "timezone": payload.get("timezone", "America/New_York"),
        "source": payload["source"],
        "symbol_count": len(prices),
        "updated_count": len(updated_symbols) if isinstance(updated_symbols, list) else 0,
        "failed_count": len(failures),
        "prices": prices,
        "failures": failures,
    }


def store_snapshot(
    payload,
    *,
    supabase_url,
    secret_key,
    opener=urlopen,
    timeout=DEFAULT_TIMEOUT_SECONDS,
):
    """Replace the singleton snapshot through Supabase's REST Data API."""
    if not supabase_url:
        raise SupabaseSnapshotError("SUPABASE_URL is required")
    if not secret_key:
        raise SupabaseSnapshotError("SUPABASE_SECRET_KEY is required")

    endpoint = f"{supabase_url.rstrip('/')}/rest/v1/price_snapshots"
    headers = {
        "apikey": secret_key,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
        "User-Agent": "StockScanner-GitHub-Actions/1.0",
    }
    # Legacy service_role keys are JWTs and still require Authorization. New
    # sb_secret_* keys must be sent only through the apikey header.
    if not secret_key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {secret_key}"

    encoded = json.dumps(snapshot_record(payload)).encode("utf-8")

    def send(request):
        try:
            with opener(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SupabaseSnapshotError(
                f"Supabase returned HTTP {exc.code}: {detail}"
            ) from exc
        except (OSError, URLError) as exc:
            raise SupabaseSnapshotError(f"Unable to reach Supabase: {exc}") from exc
        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise SupabaseSnapshotError("Supabase returned invalid JSON") from exc
        if not isinstance(result, list):
            raise SupabaseSnapshotError("Supabase returned an invalid record list")
        return result

    # Updating the known singleton avoids PostgREST's on_conflict schema-cache
    # dependency. The workflow is serialized, so an insert is required only
    # when the table has not yet been initialized.
    stored = send(
        Request(
            f"{endpoint}?source=eq.hourly_yahoo",
            data=encoded,
            headers=headers,
            method="PATCH",
        )
    )
    if not stored:
        stored = send(
            Request(endpoint, data=encoded, headers=headers, method="POST")
        )
    if not stored:
        raise SupabaseSnapshotError("Supabase did not confirm the stored snapshot")
    return stored[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        stored = store_snapshot(
            payload,
            supabase_url=os.environ.get("SUPABASE_URL", ""),
            secret_key=os.environ.get("SUPABASE_SECRET_KEY", ""),
        )
    except (OSError, json.JSONDecodeError, SupabaseSnapshotError) as exc:
        parser.error(str(exc))

    print(
        json.dumps(
            {
                "stored": True,
                "id": stored.get("id"),
                "generated_at": stored.get("generated_at"),
                "symbol_count": stored.get("symbol_count"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
