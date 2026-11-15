"""Daily refresh scheduler: next-run calculation and status reporting."""
from __future__ import annotations

from datetime import datetime

from backend.app.config import settings
from backend.app.services import scheduler


def test_next_run_uses_today_when_time_is_ahead(monkeypatch):
    monkeypatch.setattr(settings, "daily_sync_hour_utc", 3)
    monkeypatch.setattr(settings, "daily_sync_minute_utc", 0)

    now = datetime(2026, 11, 13, 2, 30, 15)
    assert scheduler._next_run(now) == datetime(2026, 11, 13, 3, 0, 0)


def test_next_run_rolls_over_to_tomorrow(monkeypatch):
    monkeypatch.setattr(settings, "daily_sync_hour_utc", 3)
    monkeypatch.setattr(settings, "daily_sync_minute_utc", 0)

    now = datetime(2026, 11, 13, 4, 0, 0)
    assert scheduler._next_run(now) == datetime(2026, 11, 14, 3, 0, 0)

    # Exactly on the boundary schedules the following day, not an immediate run.
    boundary = datetime(2026, 11, 13, 3, 0, 0)
    assert scheduler._next_run(boundary) == datetime(2026, 11, 14, 3, 0, 0)


def test_next_run_clamps_out_of_range_settings(monkeypatch):
    monkeypatch.setattr(settings, "daily_sync_hour_utc", 30)
    monkeypatch.setattr(settings, "daily_sync_minute_utc", -5)

    now = datetime(2026, 11, 13, 12, 0, 0)
    assert scheduler._next_run(now) == datetime(2026, 11, 13, 23, 0, 0)


def test_scheduler_disabled_in_tests():
    assert settings.daily_sync_enabled is False
    assert scheduler.start_scheduler() is False
    status = scheduler.scheduler_status()
    assert status["enabled"] is False
    assert status["running"] is False
    assert status["next_run"] is None


def test_health_reports_scheduler(client):
    body = client.get("/api/health").json()
    assert "scheduler" in body
    assert body["scheduler"]["enabled"] is False

    meta = client.get("/api/meta").json()
    assert meta["scheduler"]["enabled"] is False
