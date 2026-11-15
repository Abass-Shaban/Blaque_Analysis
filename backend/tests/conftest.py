"""Shared pytest fixtures for the BLAQUE ANALYSIS backend.

The application is configured through environment variables *before* any
``backend.app`` module is imported, so the tests run against a throwaway SQLite
database with no trained model and no outbound network access.
"""
from __future__ import annotations

import os
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="blaque-tests-"))
_DB_FILE = _TMP / "blaque-test.db"

os.environ.update(
    ENVIRONMENT="development",
    DEBUG="false",
    DATABASE_URL=f"sqlite:///{_DB_FILE.as_posix()}",
    SECRET_KEY="test-secret-key-for-blaque-analysis-only",
    SYNC_ON_STARTUP="false",
    SYNC_MONTHS_BACK="0",
    SYNC_MONTHS_AHEAD="0",
    DAILY_SYNC_ENABLED="false",
    MODEL_PATH=str(_TMP / "absent-model.joblib"),
    MODEL_META_PATH=str(_TMP / "absent-model-meta.json"),
    ADMIN_EMAIL="",
    ADMIN_PASSWORD="",
    FEATURED_LEAGUES="eng.1,esp.1",
    LOGIN_RATE_LIMIT="500",
)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from backend.app.database import Base, SessionLocal, engine  # noqa: E402
from backend.app.errors import ProviderError  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.models import Fixture, League, Team, User, utcnow  # noqa: E402
from backend.app.services.ingest import seed_leagues  # noqa: E402

#: IDs used by the seeded test data.
TEAM_IDS = (101, 102, 103, 104)
MAIN_TEAM = 101
RIVAL_TEAM = 102


class OfflineProvider:
    """Provider stand-in that never touches the network."""

    name = "offline"
    capabilities = {
        "live_scores": False,
        "fixtures": False,
        "standings": False,
        "match_summary": False,
        "h2h": False,
        "odds": False,
        "corners": False,
        "team_schedule": False,
    }

    def __getattr__(self, _name: str):
        def _fail(*_args, **_kwargs):
            raise ProviderError("The data provider is disabled during tests.")

        return _fail


@pytest.fixture(scope="session", autouse=True)
def offline_provider():
    """Replace every provider entry point with an offline stub."""
    from backend.app.routers import public
    from backend.app.services import analytics, dashboard, ingest

    stub = OfflineProvider()
    patches = {
        (analytics, "get_provider"): lambda: stub,
        (public, "get_provider"): lambda: stub,
        (ingest, "get_provider"): lambda: stub,
        (public, "sync_date"): lambda *_a, **_k: 0,
        (dashboard, "refresh_today"): lambda *_a, **_k: 0,
    }
    originals = {(module, name): getattr(module, name) for module, name in patches}
    for (module, name), value in patches.items():
        setattr(module, name, value)
    try:
        yield stub
    finally:
        for (module, name), value in originals.items():
            setattr(module, name, value)


def _seed(db) -> None:
    """Insert a small, deterministic league with real-shaped fixtures."""
    seed_leagues(db)
    league = db.get(League, "eng.1")
    assert league is not None
    league.is_featured = True
    league.season = "2026"

    teams = [
        Team(
            id=101,
            league_slug="eng.1",
            name="Northbridge United",
            short_name="Northbridge",
            abbreviation="NBU",
            color="#25d162",
            venue="Northbridge Stadium",
        ),
        Team(
            id=102,
            league_slug="eng.1",
            name="Riverside City",
            short_name="Riverside",
            abbreviation="RVC",
            color="#4d8dff",
            venue="Riverside Park",
        ),
        Team(
            id=103,
            league_slug="eng.1",
            name="Ashford Athletic",
            short_name="Ashford",
            abbreviation="ASH",
            color="#ffb648",
            venue="Ashford Lane",
        ),
        Team(
            id=104,
            league_slug="eng.1",
            name="Kingsmead Rovers",
            short_name="Kingsmead",
            abbreviation="KMR",
            color="#ff5f62",
            venue="Kingsmead Ground",
        ),
    ]
    db.add_all(teams)
    db.flush()

    now = utcnow()
    pairs = [(101, 102), (103, 104), (101, 103), (102, 104), (101, 104), (102, 103)]
    for round_index in range(6):
        base = now - timedelta(days=30 - round_index * 5)
        for match_index, (home_id, away_id) in enumerate(pairs):
            home_goals = (round_index + match_index) % 4
            away_goals = (round_index * 2 + match_index) % 3
            db.add(
                Fixture(
                    league_slug="eng.1",
                    home_team_id=home_id,
                    away_team_id=away_id,
                    kickoff=base + timedelta(hours=match_index * 3),
                    season="2026",
                    round=f"Round {round_index + 1}",
                    status="finished",
                    status_detail="Full time",
                    minute="90'",
                    home_score=home_goals,
                    away_score=away_goals,
                    venue="Test Ground",
                    city="Test City",
                    neutral_site=False,
                    home_corners=4 + (round_index + match_index) % 6,
                    away_corners=3 + (round_index * 2 + match_index) % 5,
                    home_shots=10 + match_index,
                    away_shots=8 + round_index,
                    home_shots_on_target=4 + match_index % 3,
                    away_shots_on_target=3 + round_index % 3,
                    home_possession=52.0,
                    away_possession=48.0,
                    home_fouls=11,
                    away_fouls=12,
                    home_yellow_cards=1,
                    away_yellow_cards=2,
                    home_red_cards=0,
                    away_red_cards=0,
                )
            )

    db.add(
        Fixture(
            league_slug="eng.1",
            home_team_id=101,
            away_team_id=102,
            kickoff=now + timedelta(days=2),
            season="2026",
            round="Round 7",
            status="scheduled",
            status_detail="Scheduled",
            venue="Northbridge Stadium",
            city="Test City",
            neutral_site=False,
        )
    )
    db.commit()


@pytest.fixture(scope="session")
def seeded_db(offline_provider):  # noqa: ARG001 - ordering dependency
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.get(Team, MAIN_TEAM) is None:
            _seed(db)
    yield


@pytest.fixture(scope="session")
def client(seeded_db):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db_session():
    with SessionLocal() as session:
        yield session


@pytest.fixture()
def scheduled_fixture_id(db_session) -> int:
    fixture = (
        db_session.query(Fixture)
        .filter(Fixture.status == "scheduled")
        .order_by(Fixture.kickoff.asc())
        .first()
    )
    assert fixture is not None
    return fixture.id


@pytest.fixture()
def finished_fixture_id(db_session) -> int:
    fixture = (
        db_session.query(Fixture)
        .filter(Fixture.status == "finished")
        .order_by(Fixture.kickoff.desc())
        .first()
    )
    assert fixture is not None
    return fixture.id


@pytest.fixture()
def clean_users():
    """Remove every account so role-bootstrap behaviour can be tested."""
    with SessionLocal() as db:
        db.execute(delete(User))
        db.commit()
    yield
