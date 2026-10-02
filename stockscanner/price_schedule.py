"""Resolve retryable market-price collection slots in New York time."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")
HOURLY_START = time(8, 45)
MARKET_CLOSE = time(16, 0)
CLOSE_RETRY_END = time(20, 0)


def _new_york_time(moment=None):
    moment = moment or datetime.now(NEW_YORK)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=NEW_YORK)
    return moment.astimezone(NEW_YORK)


def resolve_collection_window(moment=None, requested_mode="auto"):
    """Return the latest due hourly slot or the single closing slot.

    Frequent scheduler attempts share one slot, so retries are cheap and a
    successfully completed interval cannot be collected twice.
    """
    local = _new_york_time(moment)
    local_time = local.time().replace(tzinfo=None)
    if requested_mode not in {"auto", "hourly", "close"}:
        raise ValueError("requested_mode must be auto, hourly, or close")

    mode = requested_mode
    if mode == "auto":
        mode = "close" if local_time >= MARKET_CLOSE else "hourly"

    valid = local.weekday() < 5 and (
        HOURLY_START <= local_time < MARKET_CLOSE
        if mode == "hourly"
        else MARKET_CLOSE <= local_time <= CLOSE_RETRY_END
    )
    if mode == "close":
        slot = f"{local.date().isoformat()}:close"
    else:
        due = local.replace(minute=45, second=0, microsecond=0)
        if local_time.minute < 45:
            due -= timedelta(hours=1)
        slot = f"{due.date().isoformat()}:{due.strftime('%H:%M')}"
    return {
        "valid": valid,
        "mode": mode,
        "market_date": local.date().isoformat(),
        "slot": slot,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("auto", "hourly", "close"), default="auto")
    parser.add_argument("--github-output")
    args = parser.parse_args(argv)
    result = resolve_collection_window(requested_mode=args.mode)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as output:
            for key, value in result.items():
                output.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
