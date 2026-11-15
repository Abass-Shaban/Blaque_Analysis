# BLAQUE ANALYSIS

**Football intelligence, quantified.**

BLAQUE ANALYSIS is a full-stack football analytics platform. It ingests **real** fixtures, results, standings and match statistics from ESPN's public soccer API and turns them into transparent, reproducible match predictions: 1X2, double chance, BTTS, over/under goals (0.5–4.5), expected goals, correct scores, first team to score and corner markets.

> Predictions are statistical estimates, not guarantees. The app never fabricates live scores or historical results: if the provider has no data, the UI says so.

---

## Highlights

- **Live football dashboard** — today's fixtures, live scores, upcoming matches, recent results, league pulse and 30-day competition analytics.
- **Match analysis** — full prediction suite with model transparency, rolling form (last 5/10/15), home/away splits, head-to-head, corner projections and boxscore stats.
- **Prediction board** — model picks for the next scheduled fixtures across every tracked competition, filterable by league, form window and horizon.
- **Leagues & teams** — official standings, league scoring/corner baselines, team form profiles and upcoming fixtures.
- **Accounts** — secure JWT authentication, profile management, password change, favourite teams and fixtures.
- **Saved predictions** — snapshot each pick with its model version, refresh it later, and settle it automatically against the final score.
- **Admin dashboard** — data coverage, manual ESPN syncs, model training/reload, cache control, user roles/status, runtime settings and a full audit trail.
- **Premium dark UI** — custom design system, Sora/Inter typography, Chart.js visualisations, responsive layout and mobile bottom navigation.

---

## Tech stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.11, FastAPI, Uvicorn |
| Data | SQLAlchemy 2, SQLite (default) or PostgreSQL |
| Analytics | pandas, NumPy, scikit-learn, joblib |
| Frontend | Vanilla ES-module SPA, HTML5, CSS3, Chart.js |
| Auth | JWT (PyJWT), PBKDF2-SHA256 password hashing |
| Data source | ESPN public soccer API (no API key required) |

---

## Quick start

### Windows (PowerShell)

```powershell
.\run.ps1
```

### macOS / Linux

```bash
chmod +x run.sh
./run.sh
```

Both scripts create `.venv`, install dependencies, copy `.env.example` to `.env`, run a first real-data sync and start the server at **http://localhost:8000**.

### Manual setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt

cp .env.example .env            # optional; defaults work out of the box

python -m backend.app.cli sync --months-back 15 --months-ahead 1
python -m backend.app.cli train-model
python -m uvicorn backend.app.main:app --reload
```

### Docker (app + PostgreSQL)

```bash
docker compose up --build
```

The app runs on **http://localhost:8000**. Set `SECRET_KEY` (and optionally `ADMIN_EMAIL` / `ADMIN_PASSWORD`) in the environment or a `.env` file before starting.

---

## First account becomes administrator

On a fresh database the first registered account is promoted to **administrator** automatically. You can also bootstrap one:

```bash
python -m backend.app.cli create-admin --email admin@example.com --password "S3curePass1"
```

or set `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `.env`.

---

## Data source & honesty policy

All football data comes from ESPN's public endpoints:

- `site.api.espn.com/apis/site/v2/sports/soccer/...` — scoreboards, summaries, teams
- `site.api.espn.com/apis/v2/sports/soccer/...` — standings

There is **no API key**, and every fixture, score, table row, corner count and shot total shown in the UI is real provider data. Cached responses are stored in the `api_cache` table to protect the upstream service. When a statistic is unavailable the API returns an explicit `unavailable`/`null` response and the UI renders an empty state instead of inventing values.

Featured competitions (configurable): Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Europa League, MLS, Eredivisie, Primeira Liga, Süper Lig, Brasileirão.

---

## Prediction methodology

1. **Rolling form** — recency-weighted goals for/against, points per game, BTTS, clean sheets and corners over the last 5/10/15 matches, split by venue.
2. **Dixon-Coles adjusted Poisson** — team attack/defence strengths are blended with a league baseline (empirical-Bayes shrinkage for small samples). A low-score correction (rho) adjusts 0-0, 1-0, 0-1 and 1-1 outcomes.
3. **Score matrix** — the full Poisson matrix produces 1X2, double chance, BTTS, over/under lines, correct scores and first-to-score probabilities.
4. **scikit-learn classifier** — a trained model (when enough completed matches exist) predicts 1X2 from engineered features and is blended with the Poisson output at a configurable weight (default 0.35).
5. **Corners** — independent Poisson rates from real `wonCorners` boxscore data. If the provider has not published corner statistics, the API returns `available: false` with a reason.
6. **Transparency** — every response includes sample sizes, the model version, blend weight, data-quality warnings and a disclaimer.

---

## Project layout

```
backend/
  app/
    main.py            FastAPI app, security headers, static SPA hosting
    config.py          Environment-driven settings
    database.py        Engine, session factory, SQLite pragmas
    models.py          SQLAlchemy models
    schemas.py         Pydantic request/response models
    security.py        JWT, password hashing, login rate limiting
    deps.py            Auth dependencies and audit helper
    errors.py          Typed application errors
    cli.py             sync / train-model / create-admin / status
    data/leagues.py    Featured competition catalogue
    routers/           auth, public, user, admin
    services/
      provider/        Provider abstraction + ESPN adapter + DB cache
      ingest.py        Fixture/team/standing ingestion
      analytics.py     Form profiles, baselines, H2H, match context
      predictor.py     Dixon-Coles Poisson + market blend
      ml.py            scikit-learn training and inference
      dashboard.py     Dashboard aggregation
      serialize.py     JSON serializers
frontend/
  index.html           SPA entry
  css/styles.css       Design system
  js/                  api, state, router, components, charts, pages
  assets/              Logo and favicon
  vendor/              Chart.js (vendored)
data/                  SQLite database + trained model artefacts
scripts/               Development inspection helpers
```

---

## API overview

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Service, database, provider and model health |
| GET | `/api/meta` | App metadata, leagues, counts, model status |
| GET | `/api/dashboard` | Dashboard aggregation (`?date=YYYY-MM-DD`) |
| GET | `/api/fixtures` | Fixture search and pagination |
| GET | `/api/fixtures/{id}` | Fixture detail with H2H and odds |
| GET | `/api/analysis/{id}` | Full model analysis (`?window=5|10|15`) |
| GET | `/api/predictions/board` | Model picks for upcoming fixtures |
| GET | `/api/leagues` | Competition list with counters |
| GET | `/api/leagues/{slug}` | Standings, fixtures, results, baselines |
| GET | `/api/teams/{id}` | Team form dashboard |
| GET | `/api/search` | Teams, leagues and fixtures |
| POST | `/api/auth/register` | Create account |
| POST | `/api/auth/login` | Sign in (JWT) |
| GET/PATCH | `/api/auth/me` | Read/update profile |
| POST | `/api/auth/change-password` | Change password |
| GET/POST/DELETE | `/api/favorites/...` | Favourite teams and fixtures |
| GET/POST/DELETE | `/api/predictions/saved...` | Saved prediction workspace |
| GET | `/api/predictions/summary` | User accuracy summary |
| GET | `/api/admin/*` | Stats, users, sync, model, settings, audit |

Interactive documentation: **http://localhost:8000/docs**.

---

## Maintenance CLI

```bash
python -m backend.app.cli status
python -m backend.app.cli sync --months-back 15 --months-ahead 1
python -m backend.app.cli sync --leagues eng.1 esp.1 --months-back 3
python -m backend.app.cli train-model
python -m backend.app.cli create-admin --email admin@example.com --password "S3curePass1"
```

---

## Automatic data updates

BLAQUE ANALYSIS keeps its ESPN snapshot current in three ways:

1. **On boot** — when `SYNC_ON_STARTUP=true`, a background thread refreshes the featured leagues (one month back, one month ahead) and today's scoreboard. The API stays available while it runs.
2. **While people use the site** — the dashboard refreshes today's scoreboard on demand, at most once every 60 seconds, so live scores and results stay current during match windows.
3. **Every day** — the built-in scheduler wakes at **03:00 UTC** (`DAILY_SYNC_HOUR_UTC` / `DAILY_SYNC_MINUTE_UTC`), refreshes the featured leagues and today's scoreboard, and records a `SyncRun` with scope `daily` so it appears in the admin dashboard.

`GET /api/health` and `GET /api/meta` expose the scheduler state:

```json
"scheduler": { "enabled": true, "running": false, "next_run": "2026-11-14T03:00:00Z", "last_run": "2026-11-13T03:00:04Z", "last_status": "completed" }
```

### Always-on hosts (VPS, Docker, dedicated server)

Nothing to do. Keep `DAILY_SYNC_ENABLED=true` and run **one** uvicorn worker (`--workers 1`); with multiple workers each process would start its own scheduler.

### Hosts that sleep when idle (free tiers, laptops)

An in-process thread cannot run while the machine is asleep. Disable it and trigger the CLI from an external scheduler:

```bash
DAILY_SYNC_ENABLED=false
```

**Linux/macOS cron** (03:00 server time):

```cron
0 3 * * * cd /path/to/blaque-analysis && .venv/bin/python -m backend.app.cli sync >> data/sync.log 2>&1
```

**Windows Task Scheduler** (daily at 03:00):

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\path\to\blaque-analysis\.venv\Scripts\python.exe" `
           -Argument "-m backend.app.cli sync" -WorkingDirectory "C:\path\to\blaque-analysis"
$trigger = New-ScheduledTaskTrigger -Daily -At 3:00AM
Register-ScheduledTask -TaskName "BLAQUE daily sync" -Action $action -Trigger $trigger -RunLevel Highest
```

`python -m backend.app.cli sync` performs the same featured-league refresh as the scheduler and also records the run.

### Freshness expectations

- Fixtures and results update on the next sync (daily, or when the dashboard refreshes today's scoreboard).
- Standings and team/league pages are fetched from ESPN with a short-lived cache (6 hours by default).
- Predictions are pre-kick-off snapshots and are not recalculated by the sync.

---

## Publishing to GitHub

The project folder contains two things that must **not** go into the repository:

- `.venv/` — the local Python virtual environment (~14,600 files)
- `data/` — the SQLite database (~67 MB) and trained model

`.gitignore` already excludes both. The important detail is **how you upload**: GitHub's
browser uploader copies every file you drag and ignores `.gitignore`, which is why it reports
thousands of files. Use Git instead, and only ~77 source files (under 1 MB) are published.

```bash
git init -b main
git add .
git commit -m "Initial commit: BLAQUE ANALYSIS"
git remote add origin https://github.com/<your-user>/<your-repo>.git
git push -u origin main
```

Verify what will be published before pushing:

```bash
git status --short
git ls-files | wc -l        # ~77 files
```

If the repository already contains `.venv/` or `data/`, remove them from Git **without
deleting your local copies**:

```bash
git rm -r --cached .venv .pytest_cache data
git commit -m "Remove local environment and generated data from version control"
git push
```

After cloning on another machine, recreate what was excluded:

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt   # Windows
python -m backend.app.cli sync --months-back 15 --months-ahead 1
python -m backend.app.cli train-model
python -m uvicorn backend.app.main:app --workers 1
```

---

## Configuration

All settings are environment variables (see `.env.example`). The important ones:

| Variable | Default | Notes |
| --- | --- | --- |
| `SECRET_KEY` | dev value | **Must** be changed in production |
| `DATABASE_URL` | `sqlite:///data/blaque.db` | PostgreSQL: `postgresql+psycopg://...` |
| `ENVIRONMENT` | `development` | `production` enforces a strong secret |
| `FEATURED_LEAGUES` | 12 competitions | Comma-separated ESPN slugs |
| `SYNC_ON_STARTUP` | `true` | Background warm-up sync on boot |
| `SYNC_MONTHS_BACK` | `1` | Months of history refreshed per sync |
| `DAILY_SYNC_ENABLED` | `true` | In-process daily refresh thread |
| `DAILY_SYNC_HOUR_UTC` | `3` | Hour (UTC) of the daily refresh |
| `DAILY_SYNC_MINUTE_UTC` | `0` | Minute of the daily refresh |
| `MODEL_BLEND_WEIGHT` | `0.35` | ML contribution when trained |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | empty | Optional bootstrap admin |

---

## Security notes

- Passwords are hashed with PBKDF2-SHA256 and per-user salts.
- JWT access tokens expire after 8 hours by default.
- Login attempts are rate-limited per IP + email.
- Strict Content-Security-Policy (`script-src 'self'`), no inline scripts.
- All admin routes require the `admin` role; audit logging records privileged actions.
- Input validation is enforced with Pydantic on every mutating endpoint.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Dashboard is empty on first boot | A background sync is warming the database. Wait a minute or run `python -m backend.app.cli sync`. |
| `database is locked` during a sync | Use `--workers 1` with SQLite (the default). The engine uses WAL and a 30s busy timeout. |
| Team logos do not load | ESPN CDN images are blocked by your network; the UI falls back to initials. |
| `SECRET_KEY must be set` | You are running with `ENVIRONMENT=production`; set a strong `SECRET_KEY`. |
| Model shows “statistical only” | Train it with `python -m backend.app.cli train-model` once enough completed matches exist. |
| `DLL load failed ... blocked by Application Control` | A Windows Code Integrity policy is blocking unsigned compiled wheels. SQLAlchemy ships pure-Python fallbacks: rename its `.pyd` files (`Get-ChildItem .venv\Lib\site-packages\sqlalchemy -Recurse -Filter *.pyd \| Rename-Item -NewName { "$($_.Name).blocked" }`). The model then trains with logistic regression; gradient boosting is skipped automatically if its extension is unavailable. |

---

## License

Built for educational and analytical use. Football data © ESPN. BLAQUE ANALYSIS is not affiliated with ESPN or any competition organiser.
