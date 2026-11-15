"""Public read-only API: dashboard, fixtures, analysis, leagues and teams."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from ..data.leagues import LEAGUES
from ..config import settings
from ..database import get_db
from ..deps import get_optional_user
from ..errors import AuthError, NotFoundError, ProviderError
from ..models import Fixture, League, SavedPrediction, SyncRun, Team, User, utcnow
from ..services.analysis import analyze_fixture
from ..services.analytics import (
    _merge_h2h,
    _provider_h2h,
    build_match_context,
    h2h_matches,
    league_baseline,
    team_dashboard,
)
from ..services.predictor import predict_match
from ..services.dashboard import build_dashboard
from ..services.ingest import refresh_today, seed_leagues, sync_date, sync_featured
from ..services.ml import model_status
from ..services.provider.cache import cache_stats
from ..services.provider.factory import get_provider
from ..services.scheduler import scheduler_status
from ..services.serialize import fixture_dict, iso_utc, league_dict, team_dict

router = APIRouter(prefix="/api", tags=["public"])

logger = logging.getLogger("blaque.public")


def _standing_rows(rows: list) -> list[dict]:
    return [
        {
            "rank": row.rank,
            "team": {
                "id": row.team.id,
                "name": row.team.name,
                "short_name": row.team.short_name,
                "abbreviation": row.team.abbreviation,
                "logo": row.team.logo,
                "color": row.team.color,
            },
            "played": row.played,
            "wins": row.wins,
            "draws": row.draws,
            "losses": row.losses,
            "goals_for": row.goals_for,
            "goals_against": row.goals_against,
            "goal_diff": row.goal_diff,
            "points": row.points,
            "form": row.form,
            "note": row.note,
            "group": row.group,
        }
        for row in rows
    ]


def _form_map(
    db: Session, slug: str, team_ids: set[int], limit: int = 5
) -> dict[int, str]:
    """Build a recent-results string (newest first) from stored fixtures.

    The provider's standings payload does not always include form, so the
    league table is completed from the same real results the model uses.
    """
    if not team_ids:
        return {}
    rows = db.execute(
        select(
            Fixture.home_team_id,
            Fixture.away_team_id,
            Fixture.home_score,
            Fixture.away_score,
        )
        .where(
            Fixture.league_slug == slug,
            Fixture.status == "finished",
            Fixture.home_score.is_not(None),
            Fixture.away_score.is_not(None),
        )
        .order_by(Fixture.kickoff.desc())
        .limit(max(len(team_ids) * limit * 4, 100))
    ).all()
    form: dict[int, list[str]] = defaultdict(list)
    for home_id, away_id, home_score, away_score in rows:
        if home_id in team_ids and len(form[home_id]) < limit:
            form[home_id].append(
                "W" if home_score > away_score else "D" if home_score == away_score else "L"
            )
        if away_id in team_ids and len(form[away_id]) < limit:
            form[away_id].append(
                "W" if away_score > home_score else "D" if away_score == home_score else "L"
            )
    return {team_id: "".join(results) for team_id, results in form.items()}


def _attach_form(db: Session, slug: str, standings: dict | None) -> dict | None:
    if not standings:
        return standings
    rows = standings.get("rows") or []
    team_ids = {row["team"]["id"] for row in rows if row.get("team")}
    forms = _form_map(db, slug, team_ids)
    for row in rows:
        if not row.get("form"):
            row["form"] = forms.get(row["team"]["id"])
    return standings


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
    except Exception:  # noqa: BLE001
        database_ok = False
    provider = get_provider()
    return {
        "status": "ok" if database_ok else "degraded",
        "database": "ok" if database_ok else "unavailable",
        "provider": provider.name,
        "capabilities": provider.capabilities,
        "cache": cache_stats(),
        "model": model_status(),
        "scheduler": scheduler_status(),
        "time": iso_utc(utcnow()),
    }


@router.get("/cron/sync")
@router.post("/cron/sync")
def cron_sync(request: Request, db: Session = Depends(get_db)) -> dict:
    """Endpoint triggered by Vercel Cron or an external scheduler."""
    import os
    cron_secret = os.getenv("CRON_SECRET", "").strip()
    if cron_secret:
        auth_header = request.headers.get("Authorization", "")
        if auth_header != f"Bearer {cron_secret}":
            raise AuthError("Invalid cron secret.")

    run = SyncRun(scope="cron", status="running", triggered_by="vercel-cron")
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        result = sync_featured(
            months_back=max(settings.sync_months_back, 1),
            months_ahead=max(settings.sync_months_ahead, 1),
        )
        refresh_today()
        run.status = "completed"
        run.detail = result
        run.finished_at = utcnow()
        db.commit()
        return {"status": "ok", "fixtures": result.get("fixtures", 0)}
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.finished_at = utcnow()
        db.commit()
        logger.exception("Cron sync failed")
        return {"status": "error", "message": str(exc)}


@router.get("/meta")
def meta(db: Session = Depends(get_db)) -> dict:
    seed_leagues(db)
    provider = get_provider()
    last_sync = db.scalar(
        select(SyncRun).where(SyncRun.status == "completed").order_by(SyncRun.id.desc()).limit(1)
    )
    leagues = list(
        db.scalars(select(League).order_by(League.sort_order.asc()))
    )
    counts = {
        "leagues": db.scalar(select(func.count()).select_from(League)) or 0,
        "teams": db.scalar(select(func.count()).select_from(Team)) or 0,
        "fixtures": db.scalar(select(func.count()).select_from(Fixture)) or 0,
        "saved_predictions": db.scalar(select(func.count()).select_from(SavedPrediction)) or 0,
    }
    return {
        "app": {
            "name": "BLAQUE ANALYSIS",
            "tagline": "Football intelligence, quantified.",
            "version": "1.0.0",
            "environment": settings.environment,
        },
        "provider": {
            "name": provider.name,
            "display_name": "ESPN Soccer",
            "capabilities": provider.capabilities,
            "attribution": "Live fixtures, results and statistics provided by ESPN.",
            "key_required": False,
        },
        "counts": {key: int(value) for key, value in counts.items()},
        "leagues": [league_dict(league) for league in leagues],
        "featured": [league_dict(league) for league in leagues if league.is_featured],
        "model": model_status(),
        "sync": {
            "last_run": iso_utc(last_sync.finished_at) if last_sync else None,
            "last_status": last_sync.status if last_sync else None,
        },
        "scheduler": scheduler_status(),
        "server_time": iso_utc(utcnow()),
        "timezone": "UTC",
        "analysis_windows": [5, 10, 15],
        "disclaimer": (
            "BLAQUE ANALYSIS provides statistical estimates, not guarantees. "
            "Always use predictions responsibly."
        ),
    }


@router.get("/dashboard")
def dashboard(
    day: date | None = Query(default=None, alias="date"),
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    return build_dashboard(db, day, refresh=refresh)


@router.get("/fixtures")
def fixtures(
    day: date | None = Query(default=None, alias="date"),
    league: str | None = None,
    status: Literal["scheduled", "live", "finished", "postponed", "canceled", "suspended"] | None = None,
    team: int | None = None,
    q: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=40, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    conditions = []
    if day:
        start = datetime.combine(day, datetime.min.time())
        conditions.extend([Fixture.kickoff >= start, Fixture.kickoff < start + timedelta(days=1)])
    if league:
        conditions.append(Fixture.league_slug == league)
    if status:
        conditions.append(Fixture.status == status)
    if team:
        conditions.append(or_(Fixture.home_team_id == team, Fixture.away_team_id == team))
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(
                Fixture.home_team.has(Team.name.ilike(pattern)),
                Fixture.away_team.has(Team.name.ilike(pattern)),
            )
        )

    if day and not q and not team and not league:
        existing = db.scalar(
            select(func.count())
            .select_from(Fixture)
            .where(
                Fixture.kickoff >= datetime.combine(day, datetime.min.time()),
                Fixture.kickoff < datetime.combine(day, datetime.min.time()) + timedelta(days=1),
            )
        ) or 0
        if existing == 0 and abs((day - utcnow().date()).days) <= 45:
            try:
                sync_date(day)
            except ProviderError:
                pass

    stmt = select(Fixture)
    if conditions:
        stmt = stmt.where(*conditions)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(
            stmt.order_by(Fixture.kickoff.asc()).offset(offset).limit(limit)
        ).unique()
    )
    return {
        "items": [fixture_dict(row) for row in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "date": day.isoformat() if day else None,
    }


@router.get("/fixtures/{fixture_id}")
def fixture_detail(fixture_id: int, db: Session = Depends(get_db)) -> dict:
    fixture = db.get(Fixture, fixture_id)
    if fixture is None:
        raise NotFoundError("Fixture not found.")
    stored_h2h = h2h_matches(db, fixture.home_team_id, fixture.away_team_id, fixture.kickoff)
    provider_summary = None
    warnings: list[str] = []
    try:
        provider_summary = get_provider().summary(fixture.league_slug, fixture.id)
    except ProviderError as exc:
        warnings.append(exc.message)
    h2h = stored_h2h
    if provider_summary:
        h2h = _merge_h2h(
            stored_h2h,
            _provider_h2h(db, provider_summary.h2h, fixture.home_team_id, fixture.away_team_id),
        )
    return {
        "fixture": fixture_dict(fixture),
        "h2h": h2h,
        "summary": {
            "odds": provider_summary.odds if provider_summary else fixture.odds_json,
            "venue": provider_summary.venue if provider_summary else fixture.venue,
            "attendance": provider_summary.attendance if provider_summary else None,
        },
        "warnings": warnings,
    }


def _analysis_response(db: Session, fixture_id: int, window: int, user: User | None) -> dict:
    return analyze_fixture(db, fixture_id, window, user=user, record=user is not None)


@router.get("/analysis/{fixture_id}")
def analysis(
    fixture_id: int,
    window: int = Query(default=10, ge=5, le=15),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> dict:
    return _analysis_response(db, fixture_id, window, user)


@router.get("/fixtures/{fixture_id}/analysis")
def analysis_alias(
    fixture_id: int,
    window: int = Query(default=10, ge=5, le=15),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> dict:
    return _analysis_response(db, fixture_id, window, user)


@router.get("/predictions/board")
def prediction_board(
    window: int = Query(default=10, ge=5, le=15),
    league: str | None = None,
    days: int = Query(default=10, ge=1, le=30),
    limit: int = Query(default=12, ge=1, le=30),
    db: Session = Depends(get_db),
) -> dict:
    """Pre-computed model snapshot for the next scheduled fixtures.

    Runs the same Dixon-Coles/ML pipeline as the match page but without
    provider summaries, so the prediction board stays fast and offline-safe.
    """
    now = utcnow()
    stmt = select(Fixture).where(
        Fixture.status == "scheduled",
        Fixture.kickoff >= now,
        Fixture.kickoff <= now + timedelta(days=days),
    )
    if league:
        stmt = stmt.where(Fixture.league_slug == league)
    fixtures = list(
        db.scalars(stmt.order_by(Fixture.kickoff.asc()).limit(limit)).unique()
    )

    items: list[dict] = []
    for fixture in fixtures:
        try:
            context = build_match_context(
                db, fixture, window, include_summary=False, apply_summary=False
            )
            prediction = predict_match(context)
        except Exception:  # noqa: BLE001
            logger.warning("Board prediction failed for fixture %s", fixture.id, exc_info=True)
            continue
        items.append({"fixture": fixture_dict(fixture), "prediction": prediction})

    return {
        "items": items,
        "total": len(items),
        "window": window,
        "days": days,
        "league": league,
    }


@router.get("/leagues")
def leagues(db: Session = Depends(get_db)) -> dict:
    seed_leagues(db)
    now = utcnow()
    rows = list(db.scalars(select(League).order_by(League.sort_order.asc())))
    output = []
    for league in rows:
        total = db.scalar(
            select(func.count()).select_from(Fixture).where(Fixture.league_slug == league.slug)
        ) or 0
        upcoming = db.scalar(
            select(func.count())
            .select_from(Fixture)
            .where(
                Fixture.league_slug == league.slug,
                Fixture.status == "scheduled",
                Fixture.kickoff >= now,
            )
        ) or 0
        live = db.scalar(
            select(func.count())
            .select_from(Fixture)
            .where(
                Fixture.league_slug == league.slug,
                Fixture.status.in_(["live", "suspended"]),
                Fixture.kickoff <= now + timedelta(minutes=15),
            )
        ) or 0
        output.append(
            {
                **league_dict(league),
                "fixtures": int(total),
                "upcoming": int(upcoming),
                "live": int(live),
            }
        )
    return {"items": output, "total": len(output)}


@router.get("/leagues/{slug}")
def league_detail(slug: str, db: Session = Depends(get_db)) -> dict:
    seed_leagues(db)
    league = db.get(League, slug)
    if league is None:
        meta_info = LEAGUES.get(slug)
        if meta_info is None:
            raise NotFoundError("League not found.")
        league = League(
            slug=slug,
            name=meta_info.name,
            short_name=meta_info.short_name,
            country=meta_info.country,
            logo=meta_info.logo,
            sort_order=meta_info.sort_order,
        )
        db.add(league)
        db.commit()
        db.refresh(league)

    provider = get_provider()
    standings = None
    warnings: list[str] = []
    try:
        table = provider.standings(slug)
        standings = _attach_form(
            db,
            slug,
            {
                "season": table.get("season"),
                "groups": table.get("groups") or [],
                "rows": _standing_rows(table.get("rows") or []),
            },
        )
        if table.get("season"):
            league.season = str(table["season"])
            db.commit()
    except ProviderError as exc:
        warnings.append(exc.message)

    now = utcnow()
    upcoming = list(
        db.scalars(
            select(Fixture)
            .where(
                Fixture.league_slug == slug,
                Fixture.status == "scheduled",
                Fixture.kickoff >= now - timedelta(hours=2),
            )
            .order_by(Fixture.kickoff.asc())
            .limit(10)
        ).unique()
    )
    recent = list(
        db.scalars(
            select(Fixture)
            .where(Fixture.league_slug == slug, Fixture.status == "finished")
            .order_by(Fixture.kickoff.desc())
            .limit(10)
        ).unique()
    )
    baseline = league_baseline(db, slug, now)
    return {
        "league": league_dict(league),
        "standings": standings,
        "upcoming": [fixture_dict(f) for f in upcoming],
        "recent": [fixture_dict(f) for f in recent],
        "stats": baseline,
        "warnings": warnings,
    }


@router.get("/leagues/{slug}/standings")
def league_standings(slug: str, db: Session = Depends(get_db)) -> dict:
    seed_leagues(db)
    if db.get(League, slug) is None and slug not in LEAGUES:
        raise NotFoundError("League not found.")
    table = get_provider().standings(slug)
    rows = _standing_rows(table.get("rows") or [])
    _attach_form(db, slug, {"rows": rows})
    return {
        "league": league_dict(db.get(League, slug)),
        "season": table.get("season"),
        "groups": table.get("groups") or [],
        "rows": rows,
    }


@router.get("/leagues/{slug}/fixtures")
def league_fixtures(
    slug: str,
    status: Literal["scheduled", "live", "finished"] | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Fixture).where(Fixture.league_slug == slug)
    if status:
        stmt = stmt.where(Fixture.status == status)
    rows = list(db.scalars(stmt.order_by(Fixture.kickoff.desc()).limit(limit)).unique())
    return {"items": [fixture_dict(row) for row in rows], "total": len(rows)}


@router.get("/teams/{team_id}")
def team(
    team_id: int,
    window: int = Query(default=10, ge=5, le=15),
    db: Session = Depends(get_db),
) -> dict:
    return team_dashboard(db, team_id, window)


@router.get("/teams/{team_id}/history")
def team_history(
    team_id: int,
    window: int = Query(default=10, ge=5, le=15),
    db: Session = Depends(get_db),
) -> dict:
    data = team_dashboard(db, team_id, window)
    return {
        "team": data["team"],
        "league": data["league"],
        "window": window,
        "profile": data["profiles"][str(window)],
        "profiles": data["profiles"],
        "position": data["position"],
    }


@router.get("/teams/{team_id}/h2h/{opponent_id}")
def team_h2h(
    team_id: int,
    opponent_id: int,
    db: Session = Depends(get_db),
) -> dict:
    if db.get(Team, team_id) is None or db.get(Team, opponent_id) is None:
        raise NotFoundError("Team not found.")
    now = utcnow()
    games = h2h_matches(db, team_id, opponent_id, now)
    if not games:
        fixture = db.scalar(
            select(Fixture)
            .where(
                or_(
                    (Fixture.home_team_id == team_id) & (Fixture.away_team_id == opponent_id),
                    (Fixture.home_team_id == opponent_id) & (Fixture.away_team_id == team_id),
                )
            )
            .order_by(Fixture.kickoff.desc())
            .limit(1)
        )
        if fixture:
            try:
                summary = get_provider().summary(fixture.league_slug, fixture.id)
                games = _merge_h2h(
                    [],
                    _provider_h2h(db, summary.h2h, team_id, opponent_id),
                )
            except ProviderError:
                pass
    return {
        "team_id": team_id,
        "opponent_id": opponent_id,
        "games": games,
        "total": len(games),
    }


@router.get("/search")
def search(
    q: str = Query(min_length=2, max_length=80),
    db: Session = Depends(get_db),
) -> dict:
    pattern = f"%{q.strip()}%"
    teams = list(db.scalars(select(Team).where(Team.name.ilike(pattern)).limit(8)))
    leagues = list(
        db.scalars(
            select(League)
            .where(or_(League.name.ilike(pattern), League.country.ilike(pattern)))
            .limit(5)
        )
    )
    fixtures = list(
        db.scalars(
            select(Fixture)
            .where(
                Fixture.status.in_(["scheduled", "live"]),
                Fixture.kickoff >= utcnow() - timedelta(days=1),
                or_(
                    Fixture.home_team.has(Team.name.ilike(pattern)),
                    Fixture.away_team.has(Team.name.ilike(pattern)),
                ),
            )
            .order_by(Fixture.kickoff.asc())
            .limit(10)
        ).unique()
    )
    return {
        "teams": [team_dict(t) for t in teams],
        "leagues": [league_dict(l) for l in leagues],
        "fixtures": [fixture_dict(f) for f in fixtures],
    }
