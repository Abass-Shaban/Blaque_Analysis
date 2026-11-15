"""In-process daily data refresh.

The scheduler keeps the stored ESPN snapshot current without requiring an
external cron job.  It wakes once a day at the configured UTC time, refreshes
the featured competitions and today's scoreboard, and records the run in the
``sync_runs`` table so administrators can see it in the dashboard.

For deployments that sleep when idle (for example a free-tier host), disable
this scheduler and trigger ``python -m backend.app.cli sync`` from an external
scheduler instead.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from ..config import settings
from ..database import SessionLocal
from ..models import SyncRun, utcnow
from .ingest import refresh_today, sync_featured

logger = logging.getLogger("blaque.scheduler")

_LOCK = threading.Lock()
_STOP = threading.Event()
_THREAD: threading.Thread | None = None
_STATE: dict[str, object] = {
    "enabled": False,
    "running": False,
    "next_run": None,
    "last_run": None,
    "last_status": None,
}


def _set_state(**values: object) -> None:
    with _LOCK:
        _STATE.update(values)


def _next_run(now: datetime | None = None) -> datetime:
    """Return the next scheduled UTC datetime."""
    now = now or utcnow()
    hour = min(max(int(settings.daily_sync_hour_utc), 0), 23)
    minute = min(max(int(settings.daily_sync_minute_utc), 0), 59)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _run_daily_sync() -> None:
    run_id: int | None = None
    _set_state(running=True, last_status="running")
    try:
        with SessionLocal() as db:
            run = SyncRun(scope="daily", status="running", triggered_by="scheduler")
            db.add(run)
            db.commit()
            db.refresh(run)
            run_id = run.id

        result = sync_featured(
            months_back=max(settings.sync_months_back, 1),
            months_ahead=max(settings.sync_months_ahead, 1),
        )
        refresh_today()

        with SessionLocal() as db:
            run = db.get(SyncRun, run_id)
            if run is not None:
                run.status = "completed"
                run.detail = result
                run.finished_at = utcnow()
                db.commit()
        _set_state(
            running=False,
            last_run=utcnow().isoformat() + "Z",
            last_status="completed",
        )
        logger.info(
            "Daily sync complete: %s fixture rows across %s leagues",
            result.get("fixtures"),
            len(result.get("leagues") or []),
        )
    except Exception:  # noqa: BLE001
        logger.exception("Daily sync failed")
        _set_state(
            running=False,
            last_run=utcnow().isoformat() + "Z",
            last_status="failed",
        )
        try:
            with SessionLocal() as db:
                run = db.get(SyncRun, run_id) if run_id is not None else None
                if run is not None:
                    run.status = "failed"
                    run.finished_at = utcnow()
                    db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("Could not record the failed daily sync")


def _loop() -> None:
    while not _STOP.is_set():
        next_run = _next_run()
        _set_state(next_run=next_run.isoformat() + "Z")
        wait_seconds = max((next_run - utcnow()).total_seconds(), 1.0)
        if _STOP.wait(wait_seconds):
            break
        _run_daily_sync()
    _set_state(running=False, next_run=None)


def start_scheduler() -> bool:
    """Start the background daily refresh thread (idempotent)."""
    global _THREAD
    if not settings.daily_sync_enabled:
        _set_state(enabled=False, running=False, next_run=None)
        logger.info("Daily scheduler disabled")
        return False
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return True
        _STOP.clear()
        _THREAD = threading.Thread(target=_loop, name="blaque-daily-sync", daemon=True)
        _THREAD.start()
        _STATE["enabled"] = True
    logger.info(
        "Daily sync scheduled for %02d:%02d UTC",
        settings.daily_sync_hour_utc,
        settings.daily_sync_minute_utc,
    )
    return True


def stop_scheduler() -> None:
    """Signal the scheduler thread to exit."""
    _STOP.set()
    thread = _THREAD
    if thread is not None and thread.is_alive():
        thread.join(timeout=5)
    _set_state(enabled=False, next_run=None)


def scheduler_status() -> dict:
    with _LOCK:
        return dict(_STATE)
