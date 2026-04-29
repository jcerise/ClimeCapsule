---
id: show-total-precipitation
title: "Show daily total + year-to-date precipitation on the weather history screen"
status: complete
priority: 1
created: 2026-04-28
steps_completed: 6
steps_total: 6
tags: [weather, precipitation, ui, bugfix]
---

# Show daily total + year-to-date precipitation on the weather history screen

## Summary

The `/today_plus_history` dashboard currently shows a "Precipitation" value in each column (today, 1yr ago, 2yr ago) that is computed by averaging Weather Underground's running daily-cumulative `precipTotal` across the day's hourly observations — a meaningless number. This plan does two things: (a) replaces that broken aggregation with the actual daily total (the maximum cumulative value seen during the day), and (b) adds a new year-to-date precipitation row to each column showing the total rain accumulated from January 1 of that column's year through that column's date at the current hour. No schema change is required; the data is already stored.

## Context

**Relevant files:**
- `weather/db.py` — `WeatherDB.query_by_date` (line 136 onward) returns hourly rows as dicts. Line 187 mislabels the `precip_total` column as `"precipAverage"` in its dict mapping.
- `weather/clime_capsule.py` — `DailyObservation` Pydantic model (lines 14–28) and `compile_daily_data` (lines 84–166) aggregate hourly observations into a daily summary. Precipitation aggregation lives in lines 98–99 (init), 142–145 (loop), and 162–163 (return).
- `templates/weather.html` — Renders the dashboard. Today's column references `today_observation.precip_avg` at lines 79 and 88; the historical loop references `hist.precip_avg` at lines 156 and 165. The metric-header label "Precipitation" appears at lines 75 and 153.

**Patterns and conventions in use:**
- `DailyObservation` is a Pydantic `BaseModel` with default values (zeroed) so empty-day cases still render the template without errors.
- `compile_daily_data` accepts a `through: int|None` cutoff hour to truncate today's partial day for fair year-over-year comparison. The cutoff uses `continue` (line 116), so observations after the cutoff are skipped but iteration continues — `max(precipTotal)` across the loop will correctly reflect only pre-cutoff values.
- Imperial-units field names from WU's API are passed through as nested keys under `obs["imperial"]` (e.g., `tempHigh`, `precipTotal`).
- Daily-total semantics: WU's `precipTotal` per hourly observation is the running cumulative for the day at that observation time. Therefore the day's total is `max(precipTotal)` across the day's rows. The same is true for the current-conditions insert path (`insert_current_observations`) which writes `precipTotal` from the current observation.

**Prerequisites:** None. No new dependencies, no database migration.

## Steps

### Step 1: Fix the mislabeled dict key in `query_by_date`

**Files:** `weather/db.py`
**Requires review:** false

In `WeatherDB.query_by_date` (around line 187), the row mapping currently emits `"precipAverage": row[13]`. `row[13]` is the `precip_total` column from the SELECT. Rename the key so the data is labeled truthfully:

```python
"precipTotal": row[13]
```

This is the only consumer-affecting change in this file. No callers rely on the old key name *correctly* — the only caller (`compile_daily_data`) reads it under the wrong assumption and is being rewritten in Step 2.

**Acceptance criteria:**
- [ ] `query_by_date` returns each observation dict with `imperial["precipTotal"]` populated from the `precip_total` column.
- [ ] No remaining reference to the key `"precipAverage"` in `weather/db.py`.

---

### Step 2: Replace `precip_avg` with `precip_total` on `DailyObservation` and rewrite the aggregation

**Files:** `weather/clime_capsule.py`
**Requires review:** false

Two coupled changes in the same file:

**2a. `DailyObservation` model (lines 14–28):** Replace the `precip_avg` field with `precip_total`:

```python
class DailyObservation(BaseModel):
    station_id: str = ""
    obs_time_local: str = ""
    friendly_date: str = ""
    temp_high: float = 0.0
    temp_low: float = 0.0
    temp_avg: float = 0.0
    windspeed_high: float = 0.0
    windspeed_low: float = 0.0
    windspeed_avg: float = 0.0
    wind_chill_high: float = 0.0
    wind_chill_low: float = 0.0
    wind_chill_avg: float = 0.0
    precip_rate: float = 0.0
    precip_total: float = 0.0
```

Keep `precip_rate` — it's still meaningful as "highest instantaneous rate seen during the day" and is shown as a secondary metric.

**2b. `compile_daily_data` (lines 84–166):** Rewrite the precipitation aggregation:

- In the variable-init block (lines 98–99 area), replace `precip_rate_avg: float = 0` with `max_precip_total: float = 0`. Keep `high_precip_rate`.
- In the loop body (lines 142–145 area), keep the `high_precip_rate` update logic. Replace the `precip_rate_avg += obs["imperial"]["precipAverage"]` line with:

  ```python
  if obs["imperial"]["precipTotal"] > max_precip_total:
      max_precip_total = obs["imperial"]["precipTotal"]
  ```

- In the return statement (lines 162–163 area), replace `precip_avg=round(precip_rate_avg / observation_count, 2)` with `precip_total=round(max_precip_total, 2)`. Keep `precip_rate=high_precip_rate`.

The `through` cutoff at line 114–116 uses `continue`, so post-cutoff observations are skipped before the precipitation update — `max_precip_total` correctly reflects only pre-cutoff hours. No additional handling needed.

The empty-day fallback at line 166 (`return DailyObservation()`) still works: `precip_total` defaults to `0.0` from the model.

**Acceptance criteria:**
- [ ] `DailyObservation` exposes `precip_total: float` and no longer exposes `precip_avg`.
- [ ] `compile_daily_data` reads `obs["imperial"]["precipTotal"]` (matching the corrected key from Step 1) and returns the daily maximum on `precip_total`.
- [ ] When called with `through=N`, `precip_total` reflects only observations at or before hour N.
- [ ] Empty observation lists still return a `DailyObservation()` with `precip_total == 0.0`.
- [ ] No remaining references to `precip_avg`, `precip_rate_avg`, or `precipAverage` in this file.

---

### Step 3: Update `weather.html` to display the daily total honestly

**Files:** `templates/weather.html`
**Requires review:** false

Four edits in this template, plus a label update:

**3a. Today column metric-header label (line 75):**
Change `<span>Precipitation</span>` to `<span>Total Precip</span>`.

**3b. Today column primary value (line 79):**
Change `{{ "%.2f"|format(today_observation.precip_avg) }}` to `{{ "%.2f"|format(today_observation.precip_total) }}`.

**3c. Today column comparison-bar (line 88):**
Change `today_observation.precip_avg * 100 / 2` to `today_observation.precip_total * 100 / 2`. The `2` denominator (2-inch ceiling for a fully-filled bar) is preserved — see Notes for how to revisit it later.

**3d. Historical column metric-header label (line 153):**
Change `<span>Precipitation</span>` to `<span>Total Precip</span>`.

**3e. Historical column primary value (line 156):**
Change `{{ "%.2f"|format(hist.precip_avg) }}` to `{{ "%.2f"|format(hist.precip_total) }}`.

**3f. Historical column comparison-bar (line 165):**
Change `hist.precip_avg * 100 / 2` to `hist.precip_total * 100 / 2`.

The "Rate" secondary metric (lines 82–86 and 159–163) reads `precip_rate` and stays unchanged — it's still the highest instantaneous rate seen during the day.

**Acceptance criteria:**
- [ ] Both the today and historical columns render a "Total Precip" header.
- [ ] Both columns show the correct daily total (in inches, two decimals) sourced from `precip_total`.
- [ ] Both `comparison-bar` widths scale from `precip_total`, not `precip_avg`.
- [ ] No remaining references to `precip_avg` in the template.

---

### Step 4: Add a SQL helper to sum daily precipitation across a date range

**Files:** `weather/db.py`
**Requires review:** false

Add a new method `sum_daily_precipitation(start_date, end_date)` to `WeatherDB`. It returns the sum of `MAX(precip_total)` per day across an inclusive date range, executed in a single SQL query (no per-day round-trips). This is the building block for year-to-date totals over the "complete days" portion of the year.

```python
def sum_daily_precipitation(self, start_date: datetime, end_date: datetime) -> float:
    """
    Sum of per-day MAX(precip_total) across the inclusive date range
    [start_date, end_date]. Returns 0.0 if end_date < start_date or no
    matching observations exist. Missing days within the range are simply
    absent from the sum (no fallback / no interpolation).
    """
    if end_date < start_date:
        return 0.0

    conn = sqlite3.connect(self.db_file)
    cursor = conn.cursor()

    start_ts = start_date.strftime("%Y-%m-%d 00:00:00")
    end_ts = (end_date + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")

    cursor.execute("""
        SELECT COALESCE(SUM(daily_max), 0.0) FROM (
            SELECT MAX(precip_total) AS daily_max
            FROM weather_data
            WHERE obs_time_local >= ? AND obs_time_local < ?
            GROUP BY DATE(obs_time_local)
        )
    """, (start_ts, end_ts))
    result = cursor.fetchone()[0]
    conn.close()
    return result or 0.0
```

The grouping uses SQLite's `DATE()` function on the `obs_time_local` text column (format `YYYY-MM-DD HH:MM:SS`), which extracts the `YYYY-MM-DD` portion correctly.

**Acceptance criteria:**
- [ ] `sum_daily_precipitation` returns the sum of per-day maxes across the inclusive range.
- [ ] Returns `0.0` when `end_date < start_date`.
- [ ] Returns `0.0` when the date range contains no observations.
- [ ] Single SQL query executed — no per-day Python loops.

---

### Step 5: Add `precip_ytd` to `DailyObservation` and a YTD helper on `ClimeCapsule`

**Files:** `weather/clime_capsule.py`
**Requires review:** false

Two coupled changes:

**5a. Extend `DailyObservation` (the model edited in Step 2):** Add a new field after `precip_total`:

```python
precip_ytd: float = 0.0
```

Default 0.0 keeps the empty-day fallback safe.

**5b. Add a method on `ClimeCapsule`:**

```python
def get_ytd_precipitation(self, target_date: datetime, target_day_total: float) -> float:
    """
    Year-to-date total precipitation, in inches, accumulated from Jan 1 of
    target_date.year through target_date. The caller supplies target_day_total
    — the (possibly hour-truncated) precip_total for target_date itself, which
    has already been computed by compile_daily_data — so we don't redo that work.
    """
    year_start = datetime(target_date.year, 1, 1)
    day_before_target = target_date - timedelta(days=1)
    complete_days_total = self.db.sum_daily_precipitation(year_start, day_before_target)
    return round(complete_days_total + target_day_total, 2)
```

Rationale for the signature: the caller already has the truncated daily total from `compile_daily_data` (which respects the `through=current_hour` cutoff for historical days). Passing it in avoids a second `query_by_date` + `compile_daily_data` round-trip per column.

Edge case: when `target_date` is January 1, `day_before_target` falls in the prior year and `sum_daily_precipitation` returns 0.0 (per its `end_date < start_date` guard isn't triggered, but the SQL range will simply contain no matching rows for the target year). Result is `target_day_total` alone — correct.

**Acceptance criteria:**
- [ ] `DailyObservation.precip_ytd` defaults to `0.0`.
- [ ] `get_ytd_precipitation(target_date, target_day_total)` returns `complete_days_total + target_day_total` rounded to 2 decimals.
- [ ] When `target_date` is January 1, the returned value equals `target_day_total`.
- [ ] When the DB contains no data for the target year before `target_date`, the returned value equals `target_day_total`.

---

### Step 6: Wire YTD into `/today_plus_history` and surface it in the template

**Files:** `api.py`, `templates/weather.html`
**Requires review:** false

**6a. `api.py` — `today_plus_history` method:**

After the line that computes `current_observation` from `compile_daily_data`, add:

```python
current_observation.precip_ytd = self.controller.get_ytd_precipitation(
    today, current_observation.precip_total
)
```

Inside the `for i in range(1, years_back + 1)` loop, after `summary = self.controller.compile_daily_data(...)` and before `historical_summaries.append(summary)`, add:

```python
summary.precip_ytd = self.controller.get_ytd_precipitation(
    past_date, summary.precip_total
)
```

Note: `past_date` is already computed by the existing leap-day-safe block immediately above; reuse it.

**6b. `templates/weather.html` — extend the precip section's `secondary-metrics` in both columns.**

In the today column (the existing `.metric-section.precip` block, around the secondary-metrics div), replace the single "Rate" entry with two entries:

```html
<div class="secondary-metrics">
  <div class="secondary-item">
    <span class="label">Rate</span>
    <span class="value">{{ "%.2f"|format(today_observation.precip_rate) }} in/hr</span>
  </div>
  <div class="secondary-item">
    <span class="label">YTD</span>
    <span class="value">{{ "%.2f"|format(today_observation.precip_ytd) }} in</span>
  </div>
</div>
```

In the historical loop's precip section, make the equivalent change but reference `hist.precip_rate` and `hist.precip_ytd`:

```html
<div class="secondary-metrics">
  <div class="secondary-item">
    <span class="label">Rate</span>
    <span class="value">{{ "%.2f"|format(hist.precip_rate) }} in/hr</span>
  </div>
  <div class="secondary-item">
    <span class="label">YTD</span>
    <span class="value">{{ "%.2f"|format(hist.precip_ytd) }} in</span>
  </div>
</div>
```

The existing `.secondary-metrics` CSS (a 2-column grid, see `static/style.css` around line 241) already accommodates two items without modification.

**Acceptance criteria:**
- [ ] Each column on `/today_plus_history` shows both a "Rate" and a "YTD" value in its precipitation section.
- [ ] Today's YTD reflects `Jan 1 → today` (no hour cutoff on today, since "now" is the cutoff by definition).
- [ ] Historical YTDs reflect `Jan 1 of past_year → past_date at current hour`, providing fair year-over-year comparison.
- [ ] Empty/missing data renders as `0.00 in` without errors.
- [ ] No additional CSS changes required — layout fits within the existing 800×480 viewport.

---

## Testing

This repo configures `pytest` but has no test files yet, so verification is manual:

1. Run `uvicorn api:app --reload` and load `http://localhost:8000/today_plus_history?years_back=2` in a browser sized to 800×480. Confirm:
   - Each column shows a "Total Precip" header with a sensible inches value.
   - Today's value increases (or stays flat on dry hours) over the course of the day.
   - Historical columns display the cumulative total *truncated to the current hour* (i.e., if it's 10am, you should see only the rain that fell up through 10am on that historical date — not the full day's total).
   - Each column shows a "YTD" entry under the precipitation section.
2. Spot-check one historical date's daily total by querying `http://localhost:8000/historical/{YYYY-MM-DD}` directly and comparing the returned `precip_total` against `SELECT MAX(precip_total) FROM weather_data WHERE obs_time_local LIKE '{date}%'` in the SQLite DB.
3. Spot-check today's YTD against the SQL:
   ```sql
   SELECT SUM(daily_max) FROM (
     SELECT MAX(precip_total) AS daily_max
     FROM weather_data
     WHERE obs_time_local >= 'YYYY-01-01 00:00:00'
       AND obs_time_local < 'YYYY-MM-DD-tomorrow 00:00:00'
     GROUP BY DATE(obs_time_local)
   );
   ```
   The dashboard's today YTD value should match within rounding.
4. Sanity-check the historical YTD: pick a 1-year-ago column and confirm that YTD ≥ that day's total (i.e., the YTD includes the day itself). Confirm YTD ≤ the full year's total for that year.
5. Confirm an empty/missing day still renders with `0.00 in` for both Total Precip and YTD without errors.

## Notes

**Comparison-bar denominator.** The `* 100 / 2` formula assumes a 2-inch daily total fills the bar. This is an absolute scale — for arid climates, most bars will look near-empty; for wet climates, the bar may saturate. A future refinement could scale the denominator to `max(today, hist1, hist2)` so the bars are relative across columns. Out of scope for this plan.

**Why `max()` and not "last observation":** Either approach yields the same answer when the WU station reports continuously through the day. `max()` is more robust against any future schema change where `precip_total` might not be guaranteed monotonic (e.g., if a midnight rollover sneaks into a row), and it costs nothing.

**No DB migration.** The `precip_total` column has been populated correctly going back to `earliest_observation` via both insert paths. The bug was purely in the read/aggregation path, so existing data is fine as-is.

**YTD accuracy is bounded by station uptime.** If the station was offline for any period within the year, those days contribute 0.0 to the YTD sum (no fallback feed by design). For years where the station came online mid-year — i.e., the configured `earliest_observation` falls inside the column's year — the historical YTD will undercount relative to actual precipitation that fell before the station was running. This is an accepted limitation of the single-station data model.

**Why this isn't two plans.** Steps 1–3 (fix the broken daily total) and Steps 4–6 (add the YTD row) operate on the same model, the same template section, and the same aggregation file. Splitting them would force the executor to coordinate two PRs across the same `DailyObservation` definition and the same `.metric-section.precip` block, with no real isolation benefit. They share enough surface area that one plan is the cleaner unit.

**Alternative considered: a denormalized daily-totals table.** We could materialize a `daily_precipitation` table updated on insert. Rejected: 24 rows per day × ~5 years is still a tiny dataset, the SQL grouping query is fast on SQLite, and adding a derived table introduces a consistency-maintenance burden with zero observable performance benefit at this scale.
