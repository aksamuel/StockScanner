"""Check that a stored market-price snapshot is fresh and has real fallback coverage."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def snapshot_health(payload, *, now=None, max_age_minutes=75):
    generated_text = str(payload.get("generated_at") or "").strip()
    try:
        generated_at = datetime.fromisoformat(generated_text)
    except ValueError:
        generated_at = None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if generated_at is not None and generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    age_minutes = None if generated_at is None else max(
        0.0, (current - generated_at.astimezone(current.tzinfo)).total_seconds() / 60
    )
    counts = payload.get("provider_counts") or {}
    alpaca_count = int(counts.get("Alpaca") or 0)
    statuses = payload.get("provider_status") or {}
    alpaca_status = str((statuses.get("Alpaca") or {}).get("status") or "")
    if not alpaca_status:
        alpaca_status = "ok" if alpaca_count > 0 else "unavailable"
    return {
        "fresh": age_minutes is not None and age_minutes <= max_age_minutes,
        "age_minutes": age_minutes,
        "alpaca_ready": alpaca_count > 0,
        "alpaca_count": alpaca_count,
        "alpaca_status": alpaca_status,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--max-age-minutes", type=int, default=75)
    parser.add_argument("--github-output")
    args = parser.parse_args(argv)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    result = snapshot_health(payload, max_age_minutes=args.max_age_minutes)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as output:
            for key, value in result.items():
                formatted = str(value).lower() if isinstance(value, bool) else value
                output.write(f"{key}={formatted if formatted is not None else ''}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
