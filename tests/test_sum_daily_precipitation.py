"""sum_daily_precipitation() adds up per-day totals over an inclusive date range."""
from datetime import datetime

from conftest import wu_hourly


def ramp_day(day, step):
    """A day whose running total climbs by `step` every hour."""
    return [wu_hourly(day, hour, round(hour * step, 2)) for hour in range(24)]


def carryover_rows(day, inherited, own_totals):
    rows = [wu_hourly(day, 0, inherited, minute=minute) for minute in (0, 5, 10)]
    rows += [wu_hourly(day, hour, total) for hour, total in own_totals]
    return rows


def test_empty_database(db):
    assert db.sum_daily_precipitation(datetime(2026, 1, 1), datetime(2026, 12, 31)) == 0.0


def test_end_before_start(db):
    db.insert_observations(ramp_day("2026-05-04", 0.02))
    assert db.sum_daily_precipitation(datetime(2026, 5, 5), datetime(2026, 5, 1)) == 0.0


def test_single_plain_day(db):
    db.insert_observations(ramp_day("2026-05-04", 0.02))
    total = db.sum_daily_precipitation(datetime(2026, 5, 4), datetime(2026, 5, 4))
    assert round(total, 2) == 0.46


def test_sums_several_days(db):
    db.insert_observations(ramp_day("2026-05-01", 0.01))
    db.insert_observations(ramp_day("2026-05-02", 0.02))
    db.insert_observations(ramp_day("2026-05-03", 0.03))
    total = db.sum_daily_precipitation(datetime(2026, 5, 1), datetime(2026, 5, 3))
    assert round(total, 2) == 0.23 + 0.46 + 0.69


def test_range_is_inclusive_and_excludes_everything_outside(db):
    db.insert_observations(ramp_day("2026-04-30", 0.05))   # before
    db.insert_observations(ramp_day("2026-05-01", 0.01))
    db.insert_observations(ramp_day("2026-05-02", 0.02))
    db.insert_observations(ramp_day("2026-06-01", 0.05))   # after
    total = db.sum_daily_precipitation(datetime(2026, 5, 1), datetime(2026, 5, 2))
    assert round(total, 2) == 0.69


def test_carryover_day_is_not_double_counted(db):
    """The regression: yesterday's 0.66 in must be counted once, not twice.

    2026-05-04 finished on 0.66 in. 2026-05-05 kept reporting 0.66 until the
    station reset, then recorded 0.04 in of its own.
    """
    db.insert_observations(ramp_day("2026-05-04", 0.66 / 23))
    db.insert_observations(carryover_rows("2026-05-05", 0.66, [(1, 0.02), (14, 0.03), (19, 0.04)]))

    just_the_fourth = db.sum_daily_precipitation(datetime(2026, 5, 4), datetime(2026, 5, 4))
    just_the_fifth = db.sum_daily_precipitation(datetime(2026, 5, 5), datetime(2026, 5, 5))
    both = db.sum_daily_precipitation(datetime(2026, 5, 4), datetime(2026, 5, 5))

    assert round(just_the_fourth, 2) == 0.66
    assert round(just_the_fifth, 2) == 0.04
    assert round(both, 2) == 0.70


def test_carryover_day_whose_own_rain_is_heavier(db):
    db.insert_observations(carryover_rows("2026-08-31", 0.20, [(1, 0.0), (9, 0.35), (15, 0.63)]))
    total = db.sum_daily_precipitation(datetime(2026, 8, 31), datetime(2026, 8, 31))
    assert round(total, 2) == 0.63


def test_each_day_resets_independently(db):
    """Three carryover days in a row: none of them inherits its neighbour."""
    db.insert_observations(carryover_rows("2026-05-05", 0.66, [(1, 0.01), (12, 0.10)]))
    db.insert_observations(carryover_rows("2026-05-06", 0.10, [(1, 0.00), (12, 0.20)]))
    db.insert_observations(carryover_rows("2026-05-07", 0.20, [(1, 0.00), (12, 0.30)]))
    total = db.sum_daily_precipitation(datetime(2026, 5, 5), datetime(2026, 5, 7))
    assert round(total, 2) == 0.60


def test_missing_days_are_simply_absent(db):
    """No interpolation, no fallback -- a gap contributes nothing."""
    db.insert_observations(ramp_day("2026-05-01", 0.01))
    db.insert_observations(ramp_day("2026-05-05", 0.01))
    total = db.sum_daily_precipitation(datetime(2026, 5, 1), datetime(2026, 5, 5))
    assert round(total, 2) == 0.46
