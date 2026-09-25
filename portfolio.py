
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

NYC = ZoneInfo("America/New_York")


def as_utc(dt: Optional[datetime] = None) -> datetime:
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def as_ny(dt: Optional[datetime] = None) -> datetime:
    return as_utc(dt).astimezone(NYC)


def hour_slot(dt: Optional[datetime] = None) -> datetime:
    value = as_ny(dt)
    return value.replace(minute=0, second=0, microsecond=0)


def hour_slot_key(dt: Optional[datetime] = None) -> str:
    return hour_slot(dt).strftime("%Y-%m-%dT%H:00")


def market_is_open(dt: Optional[datetime] = None) -> bool:
    value = as_ny(dt)
    if value.weekday() >= 5:
        return False
    open_time = value.replace(hour=9, minute=30, second=0, microsecond=0)
    close_time = value.replace(hour=20, minute=0, second=0, microsecond=0)
    return open_time <= value <= close_time


def minutes_since(dt: datetime, reference: Optional[datetime] = None) -> float:
    reference_value = as_utc(reference) if reference is not None else datetime.now(timezone.utc)
    return (reference_value - as_utc(dt)).total_seconds() / 60.0


@dataclass
class SnapshotStatus:
    slot_key: str
    status: str
    collected_at: Optional[datetime] = None
    prices_stored: bool = False
    stale: bool = False
    message: str = ""

    @property
    def label(self) -> str:
        if self.prices_stored and not self.stale and self.status == "green":
            return "green"
        return "No snapshot collected"


class SupabaseCollectionLock:
    """In-memory lock for one snapshot collection per hour."""

    def __init__(self, store: Optional[Dict[str, Any]] = None):
        self.store = {} if store is None else store
        self._lock = threading.RLock()

    def try_acquire(self, slot_key: str, owner: str = "scheduler") -> bool:
        with self._lock:
            locks = self.store.setdefault("collection_locks", {})
            if slot_key in locks:
                return False
            locks[slot_key] = {
                "owner": owner,
                "acquired_at": datetime.now(timezone.utc).isoformat(),
                "released": False,
            }
            return True

    def release(self, slot_key: str) -> None:
        with self._lock:
            self.store.setdefault("collection_locks", {}).pop(slot_key, None)

    def is_locked(self, slot_key: str) -> bool:
        with self._lock:
            return slot_key in self.store.setdefault("collection_locks", {})


class YahooCache:
    """Initialize the cache once, then serialize cache-dependent work."""

    def __init__(self, cache: Optional[Dict[str, Any]] = None, retries: int = 3, base_delay: float = 0.25):
        self.cache = {} if cache is None else cache
        self.retries = max(2, retries)
        self.base_delay = base_delay
        self._init_lock = threading.RLock()
        self._work_lock = threading.RLock()

    def initialize(self) -> Dict[str, Any]:
        with self._init_lock:
            self.cache.setdefault("_initialized", True)
            self.cache.setdefault("symbols", {})
            return self.cache

    def fetch_with_retries(self, symbol: str, fetcher: Callable[[str], Any]) -> Any:
        self.initialize()
        last_error: Optional[BaseException] = None
        for attempt in range(1, self.retries + 1):
            try:
                with self._work_lock:
                    value = fetcher(symbol)
                    self.cache.setdefault("symbols", {})[symbol] = value
                    return value
            except Exception as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(self.base_delay * attempt)
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Yahoo cache fetch failed for {symbol!r}")


def open_alert(title: str, message: str, *, alert_type: str = "warning") -> Dict[str, Any]:
    return {
        "title": title,
        "message": message,
        "alert_type": alert_type,
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }


class PortfolioScheduler:
    """Runs hourly snapshot collection and recovers missed slots."""

    def __init__(
        self,
        lock: Optional[SupabaseCollectionLock] = None,
        snapshots: Optional[Dict[str, Any]] = None,
        clock: Optional[Callable[[], datetime]] = None,
        alert_handler: Optional[Callable[..., Dict[str, Any]]] = None,
        collector: Optional[Callable[[str, datetime], Dict[str, Any]]] = None,
    ):
        self.lock = lock or SupabaseCollectionLock()
        self.snapshots = {} if snapshots is None else snapshots
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.alert_handler = alert_handler or open_alert
        self.collector = collector or self._default_collector

    def _default_collector(self, slot_key: str, now: datetime) -> Dict[str, Any]:
        return {
            "slot_key": slot_key,
            "collected_at": as_utc(now).isoformat(),
            "prices_stored": True,
        }

    def latest_snapshot(self) -> Optional[Dict[str, Any]]:
        latest: Optional[Dict[str, Any]] = None
        latest_dt: Optional[datetime] = None
        for record in self.snapshots.values():
            if not isinstance(record, dict):
                continue
            if not record.get("prices_stored"):
                continue
            collected_at = record.get("collected_at")
            if not collected_at:
                continue
            try:
                dt = datetime.fromisoformat(str(collected_at))
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if latest is None or dt > latest_dt:
                latest = record
                latest_dt = dt
        return latest

    def due_slot(self, now: Optional[datetime] = None) -> str:
        return hour_slot_key(now or self.clock())

    def _recover_missing_slots(self, now: Optional[datetime] = None) -> List[str]:
        current = as_ny(now or self.clock())
        current_slot = hour_slot(current)
        saved_slots = sorted(
            slot_key
            for slot_key, record in self.snapshots.items()
            if isinstance(record, dict)
            and record.get("prices_stored")
            and record.get("collected_at")
        )
        if not saved_slots:
            return [hour_slot_key(current)]

        latest_saved = saved_slots[-1]
        try:
            latest_dt = datetime.strptime(latest_saved, "%Y-%m-%dT%H:00").replace(tzinfo=NYC)
        except ValueError:
            return [hour_slot_key(current)]

        missing: List[str] = []
        cursor = latest_dt + timedelta(hours=1)
        while cursor <= current_slot:
            missing.append(cursor.strftime("%Y-%m-%dT%H:00"))
            cursor += timedelta(hours=1)
        if not missing:
            missing.append(hour_slot_key(current))
        return missing

    def _has_closing_snapshot_retry_window(self, slot_key: str, now: datetime) -> bool:
        current = as_ny(now)
        try:
            slot_dt = datetime.strptime(slot_key, "%Y-%m-%dT%H:00").replace(tzinfo=NYC)
        except ValueError:
            return False
        cutoff = current.replace(hour=20, minute=0, second=0, microsecond=0)
        return slot_dt.date() == current.date() and current <= cutoff

    def run_cycle(self, now: Optional[datetime] = None, *, force: bool = False) -> Dict[str, Any]:
        now_utc = as_utc(now or self.clock())
        now_ny = as_ny(now_utc)
        if force or market_is_open(now_utc):
            slots = self._recover_missing_slots(now_utc)
        else:
            slots = [self.due_slot(now_utc)]
        if not slots:
            slots = [self.due_slot(now_utc)]

        results: List[Dict[str, Any]] = []
        for slot_key in slots:
            existing = self.snapshots.get(slot_key)
            if isinstance(existing, dict) and existing.get("prices_stored"):
                results.append({"slot_key": slot_key, "status": "skipped", "reason": "already_saved"})
                continue
            if not force and self.lock.is_locked(slot_key):
                results.append({"slot_key": slot_key, "status": "skipped", "reason": "lock"})
                continue
            if not self.lock.try_acquire(slot_key, owner="scheduler"):
                results.append({"slot_key": slot_key, "status": "skipped", "reason": "lock"})
                continue
            try:
                record = self.collector(slot_key, now_ny)
                self.snapshots[slot_key] = record
                results.append({"slot_key": slot_key, "status": "saved", "record": record})
            except Exception:
                self.lock.release(slot_key)
                retryable = self._has_closing_snapshot_retry_window(slot_key, now_ny)
                results.append({
                    "slot_key": slot_key,
                    "status": "retryable_failure" if retryable else "failed",
                    "reason": "closing_snapshot" if retryable else "collection_failure",
                })
            else:
                # Keep the successful lock for the rest of the slot. A later
                # scheduler run must not save a duplicate snapshot.
                pass

        return {"now": now_utc.isoformat(), "slots": results}

    def check_snapshot_freshness(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        now_value = as_utc(now or self.clock())
        latest = self.latest_snapshot()
        if latest is None:
            if market_is_open(now_value):
                alert = self.alert_handler(
                    "Portfolio snapshot stale",
                    "No snapshot collected during market hours.",
                    alert_type="warning",
                )
                self.run_cycle(now=now_value, force=True)
                return {"status": "stale", "minutes_old": None, "alert": alert, "recovery_run": True}
            return {"status": "idle", "minutes_old": None, "alert": None, "recovery_run": False}

        stored_at = latest.get("collected_at")
        if stored_at is None:
            alert = self.alert_handler("Portfolio snapshot stale", "Missing snapshot timestamp.", alert_type="warning")
            return {"status": "stale", "minutes_old": None, "alert": alert, "recovery_run": True}

        timestamp = datetime.fromisoformat(str(stored_at))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        minutes_old = minutes_since(timestamp, now_value)
        stale = market_is_open(now_value) and minutes_old > 75
        alert = None
        if stale:
            alert = self.alert_handler(
                "Portfolio snapshot stale",
                f"Snapshot is {minutes_old:.1f} minutes old and needs recovery.",
                alert_type="error",
            )
            self.run_cycle(now=now_value, force=True)
        return {"status": "stale" if stale else "fresh", "minutes_old": minutes_old, "alert": alert, "recovery_run": bool(stale)}

    def status_for_record(self, record: Optional[Dict[str, Any]], now: Optional[datetime] = None) -> SnapshotStatus:
        if not record:
            return SnapshotStatus("", "No snapshot collected", prices_stored=False, stale=False, message="No snapshot collected")
        if not record.get("prices_stored"):
            return SnapshotStatus(str(record.get("slot_key") or ""), "No snapshot collected", prices_stored=False, stale=False, message="No snapshot collected")

        collected_at = record.get("collected_at")
        if not collected_at:
            return SnapshotStatus(str(record.get("slot_key") or ""), "No snapshot collected", prices_stored=False, stale=False, message="No snapshot collected")

        collected_dt = datetime.fromisoformat(str(collected_at))
        if collected_dt.tzinfo is None:
            collected_dt = collected_dt.replace(tzinfo=timezone.utc)
        current = as_utc(now or self.clock())
        minutes_old = minutes_since(collected_dt, current)
        stale = market_is_open(current) and minutes_old > 75

        if stale:
            return SnapshotStatus(
                str(record.get("slot_key") or hour_slot_key(collected_dt)),
                "No snapshot collected",
                collected_at=collected_dt,
                prices_stored=True,
                stale=True,
                message=f"Stale prices: {minutes_old:.1f} minutes old",
            )

        return SnapshotStatus(
            str(record.get("slot_key") or hour_slot_key(collected_dt)),
            "green",
            collected_at=collected_dt,
            prices_stored=True,
            stale=False,
            message="Snapshot collected",
        )


class PortfolioAnalysis:
    """Human-readable summary for snapshot freshness."""

    def __init__(self, status: SnapshotStatus):
        self.status = status

    @property
    def summary(self) -> str:
        if not self.status.prices_stored:
            return "No snapshot collected"
        if self.status.stale:
            return self.status.message or "Stale prices"
        return "Snapshot collected"

    def __str__(self) -> str:
        return self.summary


__all__ = [
    "NYC",
    "SnapshotStatus",
    "SupabaseCollectionLock",
    "YahooCache",
    "PortfolioScheduler",
    "PortfolioAnalysis",
    "as_utc",
    "as_ny",
    "hour_slot",
    "hour_slot_key",
    "market_is_open",
    "minutes_since",
    "open_alert",
]
