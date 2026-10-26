"""End-to-end: the YTD figure the dashboard shows, across a carryover boundary."""
from datetime import datetime

from conftest import wu_hourly


def test_ytd_counts_a_wet_day_once(controller):
    """0.66 in fell on 2026-05-04 and was still being reported on 05-05.

    Before the fix this produced 1.32 in -- the same rain in the prior-days sum
    and again in the target day's own total.
    """
    controller.db.insert_observations(
        [wu_hourly("2026-05-04", hour, round(hour * 0.03, 2)) for hour in range(24)]
    )
    controller.db.insert_observations(
        [wu_hourly("2026-05-05", 0, 0.66, minute=minute) for minute in (0, 5, 10)]
        + [wu_hourly("2026-05-05", 1, 0.02), wu_hourly("2026-05-05", 19, 0.04)]
    )

    fourth = controller.compile_daily_data(controller.db.query_by_date("2026-05-04"))
    fifth = controller.compile_daily_data(controller.db.query_by_date("2026-05-05"))
    assert fourth.precip_total == 0.69
    assert fifth.precip_total == 0.04

    ytd = controller.get_ytd_precipitation(datetime(2026, 5, 5), fifth.precip_total)
    assert ytd == 0.73


def test_ytd_excludes_days_after_the_target(controller):
    controller.db.insert_observations([wu_hourly("2026-01-10", 12, 0.50)])
    controller.db.insert_observations([wu_hourly("2026-03-01", 12, 0.25)])
    controller.db.insert_observations([wu_hourly("2026-09-01", 12, 9.99)])  # later in the year
    controller.db.insert_observations([wu_hourly("2025-03-01", 12, 8.88)])  # wrong year

    assert controller.get_ytd_precipitation(datetime(2026, 3, 1), 0.25) == 0.75


def test_ytd_on_january_first_is_just_that_day(controller):
    """There are no prior days to sum, and the range must not wrap into last year."""
    controller.db.insert_observations([wu_hourly("2025-12-31", 12, 5.00)])
    controller.db.insert_observations([wu_hourly("2026-01-01", 12, 0.12)])

    assert controller.get_ytd_precipitation(datetime(2026, 1, 1), 0.12) == 0.12


def test_ytd_with_no_data_at_all(controller):
    assert controller.get_ytd_precipitation(datetime(2026, 6, 1), 0.0) == 0.0
