"""Shared fixtures and observation builders.

Weather Underground's field names differ between the shape WU returns (and
WeatherDB writes) and the shape WeatherDB.query_by_date reads back -- notably
`windspeedAvg` on the way in versus `windspeedAverage` on the way out. There are
two builders here rather than one that emits both spellings, so a test that uses
the wrong shape fails instead of quietly passing.
"""
import pytest

from weather.clime_capsule import ClimeCapsule
from weather.db import WeatherDB

STATION = "KTEST1"


def wu_hourly(day, hour, precip_total=0.0, minute=59, **overrides):
    """An observation shaped the way WU returns it and insert_observations writes it."""
    imperial = {
        "tempHigh": 60.0,
        "tempLow": 40.0,
        "tempAvg": 50.0,
        "windspeedHigh": 10.0,
        "windspeedLow": 1.0,
        "windspeedAvg": 5.0,
        "windchillHigh": 58.0,
        "windchillLow": 38.0,
        "windchillAvg": 48.0,
        "precipRate": 0.0,
        "precipTotal": precip_total,
    }
    imperial.update(overrides)
    return {
        "stationID": STATION,
        "obsTimeLocal": f"{day} {hour:02d}:{minute:02d}:00",
        "humidityAvg": 40.0,
        "imperial": imperial,
    }


def reading(day, hour, precip_total=0.0, minute=0, **overrides):
    """An observation shaped the way query_by_date returns it and compile_daily_data reads it."""
    imperial = {
        "tempHigh": 60.0,
        "tempLow": 40.0,
        "tempAvg": 50.0,
        "humidity": 40.0,
        "windspeedHigh": 10.0,
        "windspeedLow": 1.0,
        "windspeedAverage": 5.0,
        "windchillHigh": 58.0,
        "windchillLow": 38.0,
        "windchillAverage": 48.0,
        "precipRate": 0.0,
        "precipTotal": precip_total,
    }
    imperial.update(overrides)
    return {
        "stationID": STATION,
        "obsTimeLocal": f"{day} {hour:02d}:{minute:02d}:00",
        "imperial": imperial,
    }


def carryover_day(day, inherited, own_totals):
    """A day that opens still reporting yesterday's total, then resets and accumulates.

    This is the real-world shape that caused precipitation to be double counted:
    WU's current-conditions endpoint keeps serving the previous day's running
    total for an hour or so past local midnight.
    """
    rows = [reading(day, 0, inherited, minute=m) for m in (0, 5, 10)]
    rows += [reading(day, hour, total) for hour, total in own_totals]
    return rows


@pytest.fixture
def db(tmp_path):
    """An empty WeatherDB backed by a throwaway SQLite file."""
    handle = WeatherDB(str(tmp_path / "test.db"))
    handle.init_db()
    return handle


@pytest.fixture
def controller(tmp_path, monkeypatch):
    """A real ClimeCapsule reading a throwaway config.ini, with an empty DB.

    @singleton replaces the class with a closure that caches one instance
    forever, so the cache has to be cleared or every test after the first would
    get the first test's database. Reaching into __closure__ is the only way in.
    """
    (tmp_path / "config.ini").write_text(
        "[weather-underground]\n"
        "base_url = https://example.invalid/v2/pws\n"
        "api_key = NOT_A_REAL_KEY\n"
        f"station_id = {STATION}\n"
        "earliest_observation = 2026-01-01\n"
        "\n"
        "[database]\n"
        "db_name = test.db\n"
    )
    monkeypatch.chdir(tmp_path)

    for cell in ClimeCapsule.__closure__:
        if isinstance(cell.cell_contents, dict):
            cell.cell_contents.clear()

    instance = ClimeCapsule()
    instance.db.init_db()
    return instance
