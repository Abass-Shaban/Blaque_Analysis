"""Public read-only API: fixtures, analysis, board, leagues, teams and search."""
from __future__ import annotations

from sqlalchemy import func, select

from backend.app.models import PredictionRecord


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["provider"] == "offline"
    assert body["model"]["available"] is False


def test_meta(client):
    response = client.get("/api/meta")
    assert response.status_code == 200
    body = response.json()
    assert body["app"]["name"] == "BLAQUE ANALYSIS"
    assert body["counts"]["teams"] == 4
    assert body["counts"]["fixtures"] >= 37
    assert body["analysis_windows"] == [5, 10, 15]
    slugs = {league["slug"] for league in body["leagues"]}
    assert "eng.1" in slugs


def test_fixtures_listing_and_filters(client):
    response = client.get("/api/fixtures", params={"league": "eng.1", "status": "finished", "limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 36
    assert len(body["items"]) == 5
    assert all(item["status"] == "finished" for item in body["items"])

    search = client.get("/api/fixtures", params={"q": "Northbridge"})
    assert search.status_code == 200
    assert search.json()["total"] > 0

    scheduled = client.get("/api/fixtures", params={"status": "scheduled"})
    assert scheduled.status_code == 200
    assert scheduled.json()["total"] == 1

    invalid = client.get("/api/fixtures", params={"status": "nonsense"})
    assert invalid.status_code == 422


def test_fixture_detail(client, scheduled_fixture_id):
    response = client.get(f"/api/fixtures/{scheduled_fixture_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["fixture"]["id"] == scheduled_fixture_id
    # The provider is offline, so the endpoint must degrade with a warning.
    assert body["warnings"]
    assert body["summary"]["odds"] is None

    missing = client.get("/api/fixtures/999999")
    assert missing.status_code == 404


def test_analysis_payload(client, scheduled_fixture_id):
    response = client.get(f"/api/analysis/{scheduled_fixture_id}", params={"window": 10})
    assert response.status_code == 200
    body = response.json()

    prediction = body["prediction"]
    probabilities = prediction["probabilities"]
    assert set(probabilities) == {"home", "draw", "away"}
    assert abs(sum(probabilities.values()) - 1.0) < 0.01

    assert prediction["most_likely"]["outcome"] in {"home", "draw", "away"}
    assert prediction["most_likely"]["probability"] == max(probabilities.values())
    assert prediction["model"]["version"] == "poisson-dc"
    assert prediction["model"]["ml"]["available"] is False
    assert len(prediction["goals_over_under"]) == 5
    assert [line["line"] for line in prediction["goals_over_under"]] == [0.5, 1.5, 2.5, 3.5, 4.5]
    for line in prediction["goals_over_under"]:
        assert abs(line["over"] + line["under"] - 1.0) < 0.01

    assert abs(prediction["btts"]["yes"] + prediction["btts"]["no"] - 1.0) < 0.01
    assert prediction["expected"]["total_goals"] > 0
    assert prediction["is_pre_match"] is True
    assert prediction["data_quality"]["home_sample"] >= 15
    assert prediction["data_quality"]["away_sample"] >= 15

    corners = prediction["corners"]
    assert "available" in corners
    if corners["available"]:
        assert corners["expected_total"] is not None

    # Match context exposes rolling form windows for both teams.
    context = body["context"]
    assert set(context["home"]["profiles"]) >= {"5", "10", "15"}

    missing = client.get("/api/analysis/999999")
    assert missing.status_code == 404


def test_analysis_window_bounds(client, scheduled_fixture_id):
    assert client.get(f"/api/analysis/{scheduled_fixture_id}", params={"window": 4}).status_code == 422
    assert client.get(f"/api/analysis/{scheduled_fixture_id}", params={"window": 16}).status_code == 422


def test_prediction_board_is_read_only(client, db_session, scheduled_fixture_id):
    before = db_session.scalar(select(func.count()).select_from(PredictionRecord))
    response = client.get("/api/predictions/board", params={"days": 7, "limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert body["window"] == 10

    item = next(entry for entry in body["items"] if entry["fixture"]["id"] == scheduled_fixture_id)
    assert item["fixture"]["status"] == "scheduled"
    assert abs(sum(item["prediction"]["probabilities"].values()) - 1.0) < 0.01

    db_session.expire_all()
    after = db_session.scalar(select(func.count()).select_from(PredictionRecord))
    assert after == before


def test_leagues_index_and_detail(client):
    index = client.get("/api/leagues")
    assert index.status_code == 200
    leagues = {item["slug"]: item for item in index.json()["items"]}
    assert "eng.1" in leagues
    assert leagues["eng.1"]["fixtures"] == 37
    assert leagues["eng.1"]["upcoming"] == 1

    detail = client.get("/api/leagues/eng.1")
    assert detail.status_code == 200
    body = detail.json()
    assert body["league"]["slug"] == "eng.1"
    assert body["standings"] is None
    assert body["warnings"]
    assert body["stats"]["sample_size"] == 36
    assert len(body["recent"]) == 10
    assert len(body["upcoming"]) == 1

    missing = client.get("/api/leagues/not-a-league")
    assert missing.status_code == 404


def test_team_dashboard(client):
    response = client.get("/api/teams/101", params={"window": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["team"]["id"] == 101
    assert set(body["profiles"]) == {"5", "10", "15"}
    profile = body["profiles"]["10"]
    assert profile["sample_size"] == 10
    assert profile["complete"] is True
    assert profile["wins"] + profile["draws"] + profile["losses"] == 10
    assert body["position"] is None
    assert body["baseline"]["sample_size"] == 36

    history = client.get("/api/teams/101/history", params={"window": 5})
    assert history.status_code == 200
    assert history.json()["profile"]["sample_size"] == 5

    missing = client.get("/api/teams/999999")
    assert missing.status_code == 404


def test_h2h(client):
    response = client.get("/api/teams/101/h2h/102")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(body["games"]) > 0
    assert body["games"][0]["id"]


def test_form_map_uses_stored_results(db_session):
    from backend.app.routers.public import _form_map

    forms = _form_map(db_session, "eng.1", {101, 102}, limit=5)
    assert set(forms) == {101, 102}
    for team_id in (101, 102):
        assert len(forms[team_id]) == 5
        assert set(forms[team_id]) <= {"W", "D", "L"}


def test_search(client):
    response = client.get("/api/search", params={"q": "Northbridge"})
    assert response.status_code == 200
    body = response.json()
    assert any(team["id"] == 101 for team in body["teams"])
    assert body["fixtures"]

    too_short = client.get("/api/search", params={"q": "N"})
    assert too_short.status_code == 422


def test_dashboard(client):
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["stats"]["tracked_teams"] == 4
    assert body["stats"]["model"]["available"] is False
    charts = body["charts"]
    assert charts["sample_matches"] >= 24
    outcomes = charts["outcomes"]
    assert outcomes["home"] + outcomes["draw"] + outcomes["away"] == charts["sample_matches"]
    assert body["recent"]
