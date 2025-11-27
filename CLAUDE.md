# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ClimeCapsule is a weather data management system that collects and stores weather observations from Weather Underground API. It fetches real-time and historical weather data, aggregates hourly observations into daily summaries, stores them in SQLite, and provides a FastAPI-based REST API for querying weather data and comparing current conditions with historical patterns.

## Development Commands

### Environment Setup
```bash
# Project uses uv for dependency management (Python 3.13+)
pip install -r requirements.txt  # If requirements.txt exists
# OR install from pyproject.toml dependencies
```

### Configuration
Before running the application, copy and configure `config.ini`:
```bash
cp config.ini.example config.ini
# Edit config.ini with:
# - api_key: Weather Underground API key
# - station_id: Weather station ID
# - earliest_observation: Start date for historical data (YYYY-MM-DD)
# - db_name: SQLite database name
```

### Database Initialization
```bash
# Initialize database and populate with historical data
python db_setup.py
```

### Running the API
```bash
# Run with auto-reload for development
uvicorn api:app --reload

# API documentation available at:
# - http://localhost:8000/docs (Swagger UI)
# - http://localhost:8000/redoc (ReDoc)
```

### Testing
```bash
# Run tests (pytest is configured in pyproject.toml)
pytest
```

### Code Quality
```bash
# Linting (ruff is configured in dependencies)
ruff check .
```

## Architecture

### Core Components

**ClimeCapsule (weather/clime_capsule.py)**
- Singleton class that manages Weather Underground API interactions
- Implements rate limiting (30 calls per 60 seconds) with backoff retry logic using decorators: `@sleep_and_retry`, `@on_exception(expo, RateLimitException)`, `@limits(calls=30, period=60)`
- Key methods:
  - `fetch_historical_hourly_data()`: Fetches hourly data for date ranges
  - `fetch_current_hourly_data()`: Gets today's hourly observations
  - `fetch_current_data()`: Gets current station conditions
  - `compile_daily_data()`: Aggregates hourly observations into DailyObservation objects
- The `through` parameter in `compile_daily_data()` allows partial day aggregation (filtering observations up to a specific hour) for fair comparison between current and historical data

**WeatherDB (weather/db.py)**
- Manages SQLite database operations
- Schema: `weather_data` table with hourly observations (station_id, obs_time_local UNIQUE, temperature metrics, wind metrics, precipitation)
- Two insert methods:
  - `insert_observations()`: For historical hourly data (uses fields like tempHigh, tempLow, tempAvg)
  - `insert_current_observations()`: For current conditions (uses single temp value for all three fields)
- `query_by_date()`: Returns all hourly observations for a given date
- Uses UNIQUE constraint on `obs_time_local` to prevent duplicates; violations are caught and logged

**FastAPI Application (api.py)**
- Uses class-based views with `@cbv` decorator and dependency injection via `Depends(get_controller)`
- Lifespan context manager initializes database on startup
- Key endpoints:
  - `/`: HTML home page (uses Jinja2 templates)
  - `/health`: Health check
  - `/current`: Fetches latest conditions and stores in DB
  - `/historical/{date_str}`: Returns compiled daily observation for specific date
  - `/today_plus_history?years_back=N`: HTML page comparing today with past N years (same date)
- The `/today_plus_history` endpoint compiles historical data using the `through` parameter to only include observations up to the current hour for fair comparison

### Data Flow

1. **Initial Setup**: `db_setup.py` creates database and populates with historical data from `earliest_observation` config value to present
2. **API Requests**: Weather Underground API returns observations with imperial units (nested under "imperial" key)
3. **Data Storage**: Hourly observations stored in SQLite with UNIQUE constraint on timestamp
4. **Data Aggregation**: `compile_daily_data()` iterates hourly observations to calculate daily highs, lows, and averages
5. **API Response**: FastAPI endpoints return DailyObservation Pydantic models or rendered HTML templates

### Important Patterns

**Singleton Pattern**: ClimeCapsule uses a custom `@singleton` decorator to ensure only one instance exists across the application lifecycle.

**Rate Limiting**: The Weather Underground API has strict rate limits. All API calls go through `make_api_call()` which is decorated with rate limiting and exponential backoff.

**Data Model Differences**: The API returns different field structures for current vs. historical data:
- Historical hourly: `tempHigh`, `tempLow`, `tempAvg`, `windspeedHigh`, etc.
- Current conditions: `temp`, `windSpeed`, `windChill`, etc.

**Template Rendering**: The application uses Jinja2 templates (in `templates/`) with static assets (in `static/`) for HTML responses.

## Configuration Notes

- `config.ini` is gitignored; use `config.ini.example` as template
- Database file (default: `weather_data`) is gitignored
- Weather Underground API base URL: `https://api.weather.com/v2/pws`
- All API requests use imperial units (`units=e`)
