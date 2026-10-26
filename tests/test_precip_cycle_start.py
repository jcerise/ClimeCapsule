"""precip_cycle_start() locates the midnight reset in a day's running precip total."""
from conftest import reading

from weather.clime_capsule import precip_cycle_start


def test_empty_day():
    assert precip_cycle_start([]) == 0


def test_single_observation():
    assert precip_cycle_start([reading("2026-05-05", 0, 0.1)]) == 0


def test_dry_day_has_no_reset():
    rows = [reading("2026-05-05", hour, 0.0) for hour in range(24)]
    assert precip_cycle_start(rows) == 0


def test_monotonic_day_has_no_reset():
    rows = [reading("2026-05-04", hour, round(hour * 0.02, 2)) for hour in range(24)]
    assert precip_cycle_start(rows) == 0


def test_reset_to_zero():
    rows = [
        reading("2026-10-23", 0, 0.44, minute=0),
        reading("2026-10-23", 0, 0.44, minute=10),
        reading("2026-10-23", 0, 0.00, minute=20),
        reading("2026-10-23", 1, 0.01),
    ]
    assert precip_cycle_start(rows) == 2


def test_reset_to_a_nonzero_value():
    """The first reading after midnight can already include new rain."""
    rows = [
        reading("2026-05-05", 0, 0.66, minute=5),
        reading("2026-05-05", 0, 0.02, minute=59),
        reading("2026-05-05", 5, 0.02),
    ]
    assert precip_cycle_start(rows) == 1


def test_first_drop_wins():
    rows = [
        reading("2026-05-05", 0, 0.66),
        reading("2026-05-05", 1, 0.02),
        reading("2026-05-05", 2, 0.05),
        reading("2026-05-05", 3, 0.01),
    ]
    assert precip_cycle_start(rows) == 1


def test_reset_on_the_very_first_pair():
    rows = [reading("2026-05-05", 0, 0.30), reading("2026-05-05", 1, 0.00)]
    assert precip_cycle_start(rows) == 1
