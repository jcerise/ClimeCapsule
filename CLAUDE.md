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
uv run pytest                      # tests (in tests/, pythonpath set in pyproject.toml)
```

`config.ini` and the `weather_data` DB file are gitignored. `tests/` used to be as well;
it is tracked now, and `tests/conftest.py` holds the observation builders and fixtures.

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
- `precip_cycle_start(observations)` — **module-level function, not a method**, because
  `@singleton` makes `ClimeCapsule.<anything>` unreachable at runtime. Returns the index of
  the first observation in a day's own precipitation cycle. See the carryover rule below.
- `get_ytd_precipitation(target_date, target_day_total)` — Jan 1 → `target_date` precip.
  Sums complete prior days via `db.sum_daily_precipitation()` and adds the caller-supplied
  (possibly hour-truncated) total for the target day, rather than recomputing it.

`DailyObservation` (Pydantic) — every field defaults to zero/empty so a day with no data
still renders the template instead of raising. Fields: station/date, `year`, temp
high/low/avg, windspeed high/low/avg, wind chill high/low/avg, `precip_rate`,
`precip_total`, `precip_ytd`.

`year` is set by `/today_plus_history` from the loop counter rather than parsed out of the
observation, so a historical column still shows the right year when that year has no
stored data at all. `wind_chill_*` and `precip_rate` are computed and stored but no longer
displayed anywhere, which puts them alongside `humidity`.

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
- `sum_daily_precipitation(start, end)` — one query summing per-day precipitation totals.
  WU's `precipTotal` is cumulative-so-far within a day, so a day's total is its max — but
  see the carryover rule below, because a plain `MAX()` over the calendar day is wrong.

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
| `/today_plus_history?years_back=N` | The dashboard. `years_back` defaults to 3. The display requests the bare URL, so the default is what it gets |

`/today_plus_history` flow: fetch current conditions → `insert_current_observations` →
compile today with `through=None` → for each of the last N years, `query_by_date` on the
same month/day (with a Feb 29 → Feb 28 fallback) and compile with `through=today.hour` →
attach `year` and `precip_ytd` to every column → render `weather.html`.

### Templates and styling

- `templates/weather.html` — the dashboard. Four columns: Today plus three years. Each
  leads with the average temperature as one large figure plus an `H: … / L: …` range, then
  four rows — Wind, Wind High, Total Precip, YTD — identical in both column types.
- **Row alignment is load-bearing.** Only the Today column prints labels; the historical
  columns print values alone and are read off Today's labels by sitting at the same
  height. Every `.column` is a CSS grid sharing one explicit `grid-template-rows`
  (`28px 34px 150px repeat(4, 1fr)`), which is what guarantees that. The metric rows are
  `1fr` so they share out whatever height is left and the column bottoms out exactly on
  the 480px edge; that is still an explicit, identical track, not auto sizing. Do not
  switch them to `auto`, and do not give one column type a row the other lacks: the
  columns would drift apart and the historical numbers would lose their only label.
- `.column-header` is `display: flex; align-items: center` rather than a plain block. A
  block places the `h2` by its own line box, so any difference in font size between the
  column types shows up as headers sitting at visibly different heights.
- There is **no footer row**. "Updated hourly" used to sit at the bottom of the Today
  column; it was stale (the display refreshes roughly every ten minutes) and it left the
  three historical columns with ~50px of dead space, so the metric rows took it instead.
- There are **no charts or comparison bars**. An earlier layout had them with fixed
  ceilings; `e85af59` ("Changed layout to be more e-ink friendly") removed them in favour
  of plain numbers, which hold up better on a low-refresh panel.
- `static/style.css` — fixed 800×480, `overflow: hidden`, e-ink oriented.
- **Jinja `max` filter gotcha** — relevant again the moment anything needs clamping. Jinja's
  `max` takes an *iterable* and reads its first argument as `case_sensitive`, so
  `{{ [100, x]|min|max(0) }}` raises `TypeError: 'float' object is not iterable` on every
  render. The working form nests the lists: `{{ [0, [100, x]|min]|max }}`. That bug shipped
  in `18a7236` and broke the deployed display; the fix had already existed on the `refactor`
  branch since `58b29d5` but had never been merged.
- `preview.html` — a standalone static mockup with inlined CSS and hard-coded values, for
  layout work without hitting the API. **It has drifted badly** and is now misleading:
  three columns instead of four, labels repeated in every column, a "Precipitation" row the
  template no longer has, and no YTD row. `templates/weather.html` + `static/style.css` are
  the truth. To see the real thing, render the template and screenshot it at 800×480
  (`firefox --headless --window-size=800,480 --screenshot out.png file://…`).

## The precipitation carryover rule

WU reports `precipTotal` as a total running from the start of the local day, so a day's
total is the maximum of that running figure. The catch is that the **current-conditions
endpoint keeps serving yesterday's figure for an hour or two past local midnight**. Taking
a plain `MAX()` over the calendar day therefore makes each day inherit the whole of the
previous day's rain, and the same rain lands in the YTD sum twice.

The drop back toward zero marks the real reset. Everything before that first drop belongs
to yesterday. Both aggregation paths apply this:

- `precip_cycle_start()` + `compile_daily_data()` for a single day's `precip_total`
- the `windowed` / `cycle_start` CTEs in `sum_daily_precipitation()` for the YTD sum

This only affects `precip_total`. Temperature, wind and `precipRate` are instantaneous
readings and remain valid before the reset, so they still use every observation in range.

Two properties of the real data make the rule safe, both verified over 1375 days: the
reset only ever lands in hours 00–02, never mid-day, and no day contains more than one
drop. The known limitation is a day whose reset was never observed — if the service is
down across midnight there is no drop to key off, and that day still inherits.

Measured on the production database, the old behaviour overstated 2026's YTD by 74%
(15.50 in reported against 8.92 in actual) and 2025's by 70%. Days sourced from
`/history/hourly` were unaffected, which is why 2023 and 2024 were correct and the
comparison looked lopsided.

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
- **Coverage is narrow.** The suite covers precipitation accounting and the daily
  aggregation; the API endpoints, the WU client and the template have no tests.

## Branches and deploying

`main` is the only live branch and now contains everything. The `refactor` and `templates`
branches are fully merged into it and can be deleted; do not resume work on them. Keeping
display work on a side branch is what caused the Jinja clamp bug to ship twice — the fix
existed on `refactor` for nearly a year while `main` stayed broken.

The Raspberry Pi tracks `main` and runs the app under a systemd unit. **Restart the unit
after every pull.** Jinja2 re-reads templates from disk on each render, but Python modules
are only loaded at process start, so a pull without a restart renders the new template
against the old `DailyObservation` and fails with
`UndefinedError: ... has no attribute '<field>'`. That exact mismatch broke a deploy.

## Conventions

- Implementation plans live in `plans/`, following the plan-architect / plan-executor
  workflow — see `plans/001-show-total-precipitation.md` for the expected format.
- Any dashboard change must fit 800×480 with no scrolling and stay e-ink legible.
- Prefer keeping WU's imperial units end to end; the DB, model and template are all imperial.
