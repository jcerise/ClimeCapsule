"""compile_daily_data() folds a day's observations into one DailyObservation."""
from conftest import carryover_day, reading


def test_empty_day_returns_defaults(controller):
    """A day with no data still has to render, so every field defaults to zero."""
    summary = controller.compile_daily_data([])
    assert summary.precip_total == 0.0
    assert summary.temp_avg == 0.0
    assert summary.station_id == ""


def test_plain_day_totals_the_running_maximum(controller):
    rows = [reading("2026-05-04", hour, round(hour * 0.02, 2)) for hour in range(24)]
    assert controller.compile_daily_data(rows).precip_total == 0.46


def test_carryover_is_not_counted_as_todays_rain(controller):
    """The regression: a day opening on yesterday's running total must not inherit it.

    Modelled on 2026-10-23, where the station still reported 0.44 in until 00:20
    and only 0.01 in actually fell.
    """
    rows = carryover_day("2026-10-23", 0.44, [(1, 0.0), (6, 0.01), (18, 0.01)])
    assert controller.compile_daily_data(rows).precip_total == 0.01


def test_carryover_day_whose_own_rain_is_heavier(controller):
    """When today out-rains the inherited figure, today's own total still wins."""
    rows = carryover_day("2026-08-31", 0.20, [(1, 0.0), (9, 0.35), (15, 0.63)])
    assert controller.compile_daily_data(rows).precip_total == 0.63


def test_carryover_rows_still_count_toward_other_metrics(controller):
    """Only the running precip total carries across midnight; the rest is live data."""
    rows = carryover_day("2026-10-23", 0.44, [(1, 0.0), (6, 0.01)])
    rows[0]["imperial"]["tempHigh"] = 71.0
    rows[0]["imperial"]["windspeedHigh"] = 33.0

    summary = controller.compile_daily_data(rows)
    assert summary.temp_high == 71.0
    assert summary.windspeed_high == 33.0


def test_precip_rate_is_unaffected_by_the_cycle_start(controller):
    """precipRate is an instantaneous reading, so it is valid before the reset too."""
    rows = carryover_day("2026-10-23", 0.44, [(1, 0.0), (6, 0.01)])
    rows[0]["imperial"]["precipRate"] = 0.12
    assert controller.compile_daily_data(rows).precip_rate == 0.12


def test_through_truncates_the_day(controller):
    rows = [reading("2025-10-23", hour, round(hour * 0.05, 2)) for hour in range(24)]
    assert controller.compile_daily_data(rows, through=12).precip_total == 0.60
    assert controller.compile_daily_data(rows, through=23).precip_total == 1.15


def test_through_defaults_to_the_whole_day(controller):
    """The default /historical relies on: no cutoff at all."""
    rows = [reading("2025-10-23", hour, round(hour * 0.05, 2)) for hour in range(24)]
    assert controller.compile_daily_data(rows).precip_total == 1.15
    assert controller.compile_daily_data(rows, through=None).precip_total == 1.15


def test_through_and_carryover_together(controller):
    """Truncation is applied by hour, the cycle start by position; they compose."""
    rows = carryover_day("2026-10-23", 0.44, [(1, 0.0), (6, 0.01), (18, 0.30)])
    assert controller.compile_daily_data(rows, through=12).precip_total == 0.01
    assert controller.compile_daily_data(rows, through=23).precip_total == 0.30


def test_truncating_before_the_reset_reports_no_rain(controller):
    """Through hour 0 nothing of today's own rain has been recorded yet."""
    rows = carryover_day("2026-10-23", 0.44, [(1, 0.0), (6, 0.01)])
    assert controller.compile_daily_data(rows, through=0).precip_total == 0.0


def test_unobserved_reset_still_inherits(controller):
    """Documented limitation: with no drop in the series there is nothing to key off.

    If the service is down across midnight the reset is never recorded, so the
    day cannot be distinguished from one that simply started wet.
    """
    rows = [reading("2026-10-23", hour, 0.44) for hour in (8, 12, 18)]
    assert controller.compile_daily_data(rows).precip_total == 0.44
