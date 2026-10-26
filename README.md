# ClimeCapsule

## Overview

ClimeCapsule collects weather observations from a personal weather station (via the
Weather Underground PWS API), stores them in a local SQLite database, and serves a
single-screen HTML dashboard that compares **today's conditions so far** against **the
same calendar day in previous years**.

The dashboard is the point of the project: it is rendered at a fixed **800×480**
viewport and screenshotted by a Raspberry Pi Zero 2 W, which pushes the image to an
e-ink display. The screenshot/display side lives outside this repo — as far as
ClimeCapsule is concerned, it just serves `/today_plus_history` as HTML.

Because the station's own data is only reachable through Weather Underground (not
directly from the device), everything flows through the WU API, which is rate limited
and, historically, somewhat unreliable — hence the retry/backoff machinery and the
local database acting as the durable record.

## What it actually shows

`/today_plus_history?years_back=N` renders `N + 1` columns side by side:

| Column | Source | Rows rendered |
|---|---|---|
| **Today** | Live current conditions from the station, plus every observation stored for today | Wind, Wind High, Total Precip, Precip Rate, YTD |
| **1 Year Ago … N Years Ago** | Stored observations for the same month/day in past years, truncated to the current hour | Wind, Wind High, Total Precip, YTD, Feels Like |

Every column leads with the day's average temperature as a single large figure, with
`H: … / L: …` beneath it. Below that is a flat list of label/value rows — no charts, no
comparison bars. `Total Precip` is the day's cumulative total, `Precip Rate` the peak
hourly rate, and `YTD` the year-to-date total (Jan 1 → that column's date).

Historical columns are truncated at the **current hour** (`through=today.hour`) so a
10am reading today is compared against what had happened by 10am on that date in past
years, rather than against a full 24-hour day.

Note the asymmetry, which runs both ways: Today shows `Precip Rate` but no
`Feels Like` (wind chill), and the historical columns show `Feels Like` but no
`Precip Rate`. That is how the layout currently stands.

## Directory structure

```
weather/
  clime_capsule.py    # ClimeCapsule singleton: WU API access, rate limiting, daily aggregation
  db.py               # WeatherDB: SQLite schema, inserts, per-date and per-range queries
api.py                # FastAPI app + all endpoints
db_setup.py           # One-shot: create the DB and backfill it with historical data
templates/
  weather.html        # The 800x480 dashboard (the thing the e-ink display screenshots)
  index.html          # Placeholder page served at /
static/style.css      # Dashboard styling, fixed 800x480, e-ink oriented
preview.html          # Standalone static mockup of the dashboard (see caveat below)
tests/                # pytest suite; conftest.py holds the observation builders
plans/                # Implementation plans (plan-architect / plan-executor workflow)
config.ini.example    # Template for the gitignored config.ini
```

> **Caveat on `preview.html`:** it is a self-contained copy of the dashboard with
> inlined CSS and hard-coded values, used for tweaking layout without hitting the API.
> It has drifted — it still shows the old "Precipitation" section and lacks the
> year-to-date row. Treat `templates/weather.html` + `static/style.css` as the truth.

## Installation

The project uses [uv](https://docs.astral.sh/uv/) and requires Python 3.13+.
`pyproject.toml` and `uv.lock` are the dependency source of truth — there is no
`requirements.txt`.

```shell
git clone <repository-url>
cd ClimeCapsule
uv sync
```

Configure:

```shell
cp config.ini.example config.ini
```

Fill in:

```ini
[weather-underground]
base_url = https://api.weather.com/v2/pws
api_key = <YOUR_API_KEY>
station_id = <YOUR_STATION_ID>
earliest_observation = <EARLIEST_STATION_DATA>   # YYYY-MM-DD

[database]
db_name = weather_data
```

- `api_key` — Weather Underground PWS API key.
- `station_id` — your station's ID.
- `earliest_observation` — the first date to backfill from, in `YYYY-MM-DD`.
- `db_name` — SQLite file path (relative to the working directory).

Both `config.ini` and the `weather_data` database file are gitignored.

Initialize the database:

```shell
uv run python db_setup.py
```

This is a **long, rate-limited operation on first run**: it walks one day at a time
from `earliest_observation` to today, one API call per day, capped at 30 calls per
60 seconds. Several years of history takes a while. If the database file already
exists, `init_db()` prints a message and does nothing else — it never backfills gaps
in an existing database.

Run the API:

```shell
uv run uvicorn api:app --reload
```

Docs at `http://localhost:8000/docs` (Swagger) and `/redoc`.

## Endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/` | Placeholder HTML page (`index.html`, "Hello from FastAPI!") — not a real landing page |
| GET | `/health` | `{"status": "ok"}` |
| GET | `/current` | Fetches current conditions from WU and writes them to the DB — see Known issues |
| GET | `/historical/{date_str}` | Full-day aggregated `DailyObservation` for one `YYYY-MM-DD`; 400 on a malformed date, 404 when the day has no data |
| GET | `/today_plus_history?years_back=N` | The dashboard HTML. `years_back` defaults to `2` |

Examples:

```shell
curl http://localhost:8000/health
curl http://localhost:8000/current
curl 'http://localhost:8000/today_plus_history?years_back=2'
```

## Architecture

### `ClimeCapsule` (`weather/clime_capsule.py`)

A `@singleton`-decorated class holding config, the `WeatherDB` handle, and all WU API
access. Every outbound call goes through `make_api_call()`, stacked with
`@sleep_and_retry`, `@on_exception(expo, RateLimitException, max_tries=3)` and
`@limits(calls=30, period=60)`.

- `init_db()` — creates the schema and backfills history, but only if the DB file is absent.
- `fetch_historical_hourly_data(start, end)` — one `/history/hourly` call per day in the range.
- `fetch_current_hourly_data()` — today's hourly observations. **Currently unused**: the
  call site in `/today_plus_history` is commented out, because WU stores data in UTC but
  queries it in local time, so after ~5pm MST the request would need tomorrow's date and errors.
- `fetch_current_data()` — `/observations/current`, the station's latest reading.
- `compile_daily_data(observations, through)` — a `@staticmethod` that folds a day's hourly
  rows into one `DailyObservation`: max/min/mean for temperature, wind speed and wind chill;
  peak `precipRate`; and `max(precipTotal)` as the day's total. Rows whose hour is greater
  than `through` are skipped; `through=None` means the whole day.
- `get_ytd_precipitation(target_date, target_day_total)` — Jan 1 → `target_date` total, built
  from `sum_daily_precipitation()` for the complete days plus the caller-supplied total for
  the target day itself (which may already be hour-truncated).

`DailyObservation` is a Pydantic model with all fields defaulting to zero/empty, so a day
with no data still renders the template rather than blowing up.

### `WeatherDB` (`weather/db.py`)

Plain `sqlite3`, one connection opened and closed per call, no ORM.

Table `weather_data`: `id`, `station_id`, `obs_time_local` (**UNIQUE**),
`temperature_high/low/average`, `humidity`, `wind_speed_high/low/average`,
`windchill_high/low/average`, `precip_rate`, `precip_total`.

- `insert_observations(obs)` — for **historical hourly** payloads (`tempHigh`, `tempLow`,
  `tempAvg`, `windspeedHigh`, …). `IntegrityError` on the unique timestamp is caught and
  logged, so re-inserting an overlapping range is safe.
- `insert_current_observations(obs)` — for **current-conditions** payloads, whose shape is
  different (`temp`, `windSpeed`, `windChill`). The single instantaneous value is written to
  all three of the high/low/average columns.
- `query_by_date(date_str)` — all rows for one day, re-shaped back into the WU-style nested
  `{"imperial": {...}}` dicts that `compile_daily_data` expects.
- `sum_daily_precipitation(start, end)` — one SQL query summing per-day precipitation
  totals across an inclusive range; missing days simply contribute nothing. It skips the
  rows at the start of a day that still report the previous day's running total — see
  [The precipitation carryover rule](#the-precipitation-carryover-rule).

The `humidity` column is populated and read back, but nothing in the dashboard displays it.

### `api.py`

FastAPI with `fastapi_utils`' `@cbv` class-based view and `Depends(get_controller)`
injection. A `lifespan` context manager calls `controller.init_db()` at startup.

### Data flow

1. `db_setup.py` (or first app start) backfills hourly history from WU into SQLite.
2. A dashboard request fetches current conditions and writes them via `insert_current_observations`.
3. Today's rows and each past year's rows are read back with `query_by_date`.
4. `compile_daily_data` aggregates each day; `get_ytd_precipitation` adds the YTD figure.
5. `weather.html` renders the columns.

## Known issues / rough edges

These are accurate as of now and are the natural targets for cleanup:

- **`/current` writes half-empty rows that poison the day.** It calls `insert_observations()`
  (the *historical* shape) with a current-conditions payload. Precipitation survives
  (`precipRate`/`precipTotal` are spelled the same in both shapes), but temperature, wind
  and wind chill all resolve to `NULL`. A single such row makes `compile_daily_data` raise
  `TypeError: '>' not supported between instances of 'NoneType' and 'float'` for that entire
  day, taking the dashboard down with it. `/today_plus_history` does this correctly with
  `insert_current_observations()`.
- **`compile_daily_data` can divide by zero.** If a day has rows but every row is filtered
  out by `through`, `observation_count` stays `0` and the averaging raises.
- **Sentinel low values.** `low_temp`, `low_windspeed` and `low_wind_chill` initialize to
  `150`, so a day with no valid readings would report `150` as its low — though in practice
  `NULL` rows crash the comparison before the sentinel is ever shown.
- **Dead code.** `fetch_current_hourly_data()` has no live caller, and `/today_plus_history`
  carries a large commented-out block from the UTC workaround.
- **Test coverage is narrow.** `tests/` covers precipitation accounting and the daily
  aggregation. The API endpoints, the Weather Underground client and the template are
  untested.
- **`preview.html` is stale** relative to the live template (see caveat above).
- **`index.html` is a placeholder** with hard-coded "Hello from FastAPI!" content.

## The precipitation carryover rule

Weather Underground reports `precipTotal` as a total running from the start of the local
day, so a day's rainfall is the maximum of that running figure. But the current-conditions
endpoint keeps reporting **yesterday's** figure for an hour or two past local midnight:

```
2026-10-22 23:50   total 0.44   <- the 22nd finishes on 0.44 in
2026-10-23 00:05   total 0.44   <- still yesterday's number
2026-10-23 00:20   total 0.00   <- reset, 20 minutes late
```

A plain maximum over the calendar day would score the 23rd at 0.44 in when 0.01 in fell,
counting the same rain on both days and again in the year-to-date total. So both
aggregation paths ignore the rows before the day's first drop in the running total:
`precip_cycle_start()` for a single day, and the `cycle_start` CTE in
`sum_daily_precipitation()` for a range.

Only `precip_total` is treated this way. Temperature, wind and `precipRate` are
instantaneous readings that stay valid before the reset.

One limitation: if the service is down across midnight the reset is never recorded, so
there is no drop to detect and the day inherits as before.

## Development

```shell
uv run uvicorn api:app --reload   # dev server with reload
uv run ruff check .               # lint
uv run pytest                     # run the test suite
```

Implementation plans live in `plans/` and follow the plan-architect / plan-executor
workflow — see `plans/001-show-total-precipitation.md` for the format.

## Possible future work

- Backfill gaps in an existing database (today `init_db` only populates a brand-new file).
- Surface humidity, which is already stored.
- Reintroduce some visual comparison between columns. An earlier layout drew bars with
  fixed ceilings (50 mph wind, 2 in precip); the current e-ink layout dropped them in
  favour of plain numbers. If they come back, scale them relative to the columns shown.
- Additional dashboard screens driven by the button strip in the template, which is
  currently decorative.
