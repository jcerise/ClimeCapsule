# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ClimeCapsule pulls weather observations for a personal weather station from the Weather
Underground PWS API, stores them in SQLite, and renders a single-screen HTML dashboard
comparing today's conditions against the same calendar day in previous years.

The dashboard is the product. It is laid out for a fixed **800×480** viewport, and a
Raspberry Pi Zero 2 W screenshots `/today_plus_history` and pushes the image to an e-ink
display in the user's office. The screenshot/display tooling is **not in this repo** — this
service only has to serve correct HTML at that exact size. Any layout change must stay
within 800×480 with no scrolling, and must remain legible on a low-refresh e-ink panel
(high contrast, no reliance on subtle color).

The station's data is only reachable via Weather Underground, not directly from the device,
so the WU API is the single upstream, and the local database is the durable record.

## Development Commands

The project uses `uv` and Python 3.13+. `pyproject.toml` + `uv.lock` are the dependency
source of truth — **there is no `requirements.txt`**.

```bash
uv sync                            # install dependencies
cp config.ini.example config.ini   # then fill in api_key, station_id, earliest_observation, db_name
uv run python db_setup.py          # create the DB and backfill history (slow: 1 rate-limited API call per day)
uv run uvicorn api:app --reload    # dev server; docs at /docs and /redoc
uv run ruff check .                # lint
uv run pytest                      # test runner — no test files exist yet
```

`config.ini` and the `weather_data` DB file are gitignored. `tests/` is gitignored too,
which is why `pytest` is a dependency with nothing to run.

## Architecture

### `weather/clime_capsule.py`

`ClimeCapsule` — a `@singleton`-decorated class (custom decorator in this file) holding
config, the `WeatherDB` handle, and every WU API call.

- `make_api_call()` is the single outbound chokepoint, decorated with `@sleep_and_retry`,
  `@on_exception(expo, RateLimitException, max_tries=3)`, `@limits(calls=30, period=60)`.
  All requests use imperial units (`units=e`); responses nest metrics under `"imperial"`.
- `init_db()` — creates the schema and backfills from `earliest_observation` **only if the
  DB file does not exist**. It never fills gaps in an existing database.
- `fetch_historical_hourly_data(start, end)` — one `/history/hourly` call per day in range.
- `fetch_current_hourly_data()` — today's hourly rows. **Dead code**: its only call site (in
  `/today_plus_history`) is commented out. WU stores data in UTC but queries it in local
  time, so past ~5pm MST the call would need tomorrow's date and errors out.
- `fetch_current_data()` — `/observations/current`, the station's latest reading.
- `compile_daily_data(observations, through)` — `@staticmethod`. Folds a day's hourly rows
  into one `DailyObservation`. `through` is an hour-of-day cutoff: rows past it are skipped
  so historical days can be compared fairly against a partial today. `through=None` means
  the full day, which is what `/historical/{date_str}` relies on.
- `get_ytd_precipitation(target_date, target_day_total)` — Jan 1 → `target_date` precip.
  Sums complete prior days via `db.sum_daily_precipitation()` and adds the caller-supplied
  (possibly hour-truncated) total for the target day, rather than recomputing it.

`DailyObservation` (Pydantic) — every field defaults to zero/empty so a day with no data
still renders the template instead of raising. Fields: station/date, temp high/low/avg,
windspeed high/low/avg, wind chill high/low/avg, `precip_rate`, `precip_total`, `precip_ytd`.

### `weather/db.py`

`WeatherDB` — plain `sqlite3`, a connection opened and closed per method, no ORM.

Table `weather_data`: `id`, `station_id`, `obs_time_local` (**UNIQUE**),
`temperature_high/low/average`, `humidity`, `wind_speed_high/low/average`,
`windchill_high/low/average`, `precip_rate`, `precip_total`.

Two insert paths exist because WU returns **different field shapes** for historical vs.
current data — this is the single most important gotcha in the codebase:

| | Historical hourly | Current conditions |
|---|---|---|
| Method | `insert_observations()` | `insert_current_observations()` |
| Temp keys | `tempHigh`, `tempLow`, `tempAvg` | `temp` (written to all three columns) |
| Wind keys | `windspeedHigh/Low/Avg` | `windSpeed` |
| Chill keys | `windchillHigh/Low/Avg` | `windChill` |
| Humidity | `humidityAvg` (top level) | `humidity` (top level) |

Both catch `sqlite3.IntegrityError` on the unique `obs_time_local` and log-and-skip, so
re-inserting overlapping ranges is safe.

- `query_by_date(date_str)` — reshapes rows back into WU-style `{"imperial": {...}}` dicts
  for `compile_daily_data`. Note the read-side key names (`windspeedAverage`,
  `windchillAverage`) differ from the write-side ones; `compile_daily_data` uses the read-side names.
- `sum_daily_precipitation(start, end)` — one query summing per-day `MAX(precip_total)`.
  WU's `precipTotal` is cumulative-so-far within a day, so the day's total is its max.

`humidity` is stored and read back but never displayed.

### `api.py`

FastAPI with `fastapi_utils`' `@cbv` class-based view and `Depends(get_controller)`.
A `lifespan` context manager runs `controller.init_db()` at startup.

| Path | Notes |
|---|---|
| `/` | Placeholder `index.html` ("Hello from FastAPI!") — not a real landing page |
| `/health` | `{"status": "ok"}` |
| `/current` | Fetches current conditions and stores them — **buggy, see below** |
| `/historical/{date_str}` | Full-day aggregate for one `YYYY-MM-DD` (no hour cutoff) |
| `/today_plus_history?years_back=N` | The dashboard. `years_back` defaults to 2. This is the only endpoint the e-ink display uses |

`/today_plus_history` flow: fetch current conditions → `insert_current_observations` →
compile today with `through=None` → for each of the last N years, `query_by_date` on the
same month/day (with a Feb 29 → Feb 28 fallback) and compile with `through=today.hour` →
attach `precip_ytd` to every column → render `weather.html`.

### Templates and styling

- `templates/weather.html` — the dashboard. Today's column renders Temperature, Wind and
  Total Precip; historical columns additionally render a "Feels Like" (wind chill) section.
  Comparison bars use fixed ceilings: 50 mph for wind, 2 in for precipitation.
- `static/style.css` — fixed 800×480, `overflow: hidden`, e-ink oriented.
- **Clamping gotcha:** comparison-bar widths use `{{ [0, [100, x]|min]|max }}`. Do not
  "simplify" this to `|min|max(0)` — Jinja2's `max` filter takes an *iterable* and reads its
  first argument as `case_sensitive`, so that form raises `TypeError: 'float' object is not
  iterable` on every render. That bug shipped in `18a7236` and broke the deployed display.
- `preview.html` — a standalone static mockup with inlined CSS and hard-coded values, for
  layout work without hitting the API. **It has drifted**: still shows the old
  "Precipitation" section, no YTD row. `templates/weather.html` is the truth.

## Known issues

Accurate as of this writing; these are the obvious cleanup targets.

- **`/current` writes half-empty rows that poison the whole day.** It uses
  `insert_observations()` (historical shape) on a current-conditions payload. Precip columns
  survive — `precipRate`/`precipTotal` are spelled identically in both shapes — but temp,
  wind and wind chill land as `NULL`. One such row makes `compile_daily_data` raise
  `TypeError: '>' not supported between instances of 'NoneType' and 'float'` for that day.
  `/today_plus_history` gets this right with `insert_current_observations()`.
- **Divide-by-zero in `compile_daily_data`.** If a day has rows but all are filtered out by
  `through`, `observation_count` stays 0 and the averaging raises.
- **Sentinel lows.** `low_temp`, `low_windspeed`, `low_wind_chill` initialize to `150`; in
  practice `NULL` rows crash the comparison before the sentinel can surface.
- **`@singleton` replaces the class with a function.** `ClimeCapsule` is a closure at
  runtime, not a class, so `isinstance` checks, subclassing, and the `controller: ClimeCapsule`
  annotations are all annotating a function object.
- **Dead code**: `fetch_current_hourly_data()` and the commented-out block in `/today_plus_history`.
- **No tests** despite `pytest` being a dependency (`tests/` is gitignored).

## Conventions

- Implementation plans live in `plans/`, following the plan-architect / plan-executor
  workflow — see `plans/001-show-total-precipitation.md` for the expected format.
- Any dashboard change must fit 800×480 with no scrolling and stay e-ink legible.
- Prefer keeping WU's imperial units end to end; the DB, model and template are all imperial.
