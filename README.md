
# ClimeCapsule

## Overview

ClimeCapsule is a weather data management system that collects and stores weather observations, ranging from historical to real-time data. It provides an interface for querying historical data, real-time conditions, and performing comparisons with past observations. The system interacts with the Weather Underground API to fetch and store weather station data and allows for historical analysis by aggregating daily weather patterns.

## Features

- Fetches **real-time**, **hourly**, and **historical** weather data from Weather Underground API.
- Aggregates hourly weather observations into daily summaries.
- Stores weather data in a local SQLite database.
- Provides a REST API for retrieving weather data, including:
  - Current weather.
  - Historical weather for specific days.
  - Yearly comparisons for a specific date across multiple years.
- Initialization of the database with historical weather data.
- API rate limiting and retry mechanism using `backoff` and `ratelimit`.

## Directory Structure

```
- weather/
  - clime_capsule.py      # Core application logic for fetching, processing, and storing weather data.
  - db.py                 # Database management for weather data.
- api.py                  # FastAPI-based RESTful API.
- db_setup.py             # Script for initializing and populating the database.
- config.ini.example      # Example configuration file with API and database settings.
```

## Installation

1. Clone the repository:
```shell script
git clone <repository-url>
   cd <repository-directory>
```

2. Install project dependencies:
```shell script
pip install -r requirements.txt
```

3. Configure the application:
   - Copy the example configuration file:
```shell script
cp config.ini.example config.ini
```
   - Fill in the values for:
     - `api_key` (Weather Underground API key)
     - `station_id` (Weather station ID)
     - `earliest_observation` (Start date for fetching historical data, in `YYYY-MM-DD` format)
     - `db_name` (Name of the SQLite database, e.g., `weather_data`)

4. Initialize the database:
```shell script
python db_setup.py
```

5. Launch the API:
```shell script
uvicorn api:app --reload
```

## Configuration

The application requires a `config.ini` file, with the following sections:
```ini
[weather-underground]
base_url = https://api.weather.com/v2/pws
api_key = <YOUR_API_KEY>
station_id = <YOUR_STATION_ID>
earliest_observation = <EARLIEST_STATION_DATA>

[database]
db_name = weather_data
```

- **Weather Underground settings**:
  - `api_key`: The Weather Underground API Key.
  - `station_id`: The weather station ID.
  - `earliest_observation`: The start date (e.g., 2020-01-01) for historical data fetching.  

- **Database setting**:
  - `db_name`: SQLite database file name.

## Components

### 1. ClimeCapsule (`clime_capsule.py`)

- **Purpose**: The core class that handles communication with the Weather Underground API, aggregates weather data, and interacts with the SQLite database.
- **Key Responsibility**:
  - Fetches hourly and daily weather data.
  - Provides functions for fetching and aggregating data.
  - Handles database initialization and population with historical data.
  - Implements singleton pattern to ensure only one instance of ClimeCapsule.

### 2. Database Management (`db.py`)

- **Purpose**: Contains the `WeatherDB` class which manages SQLite database interactions.
- **Features**:
  - Creates database tables (`weather_data`) if not already present.
  - Inserts weather observation data.
  - Queries weather data for specific dates.

### 3. REST API (`api.py`)

- **Purpose**: Exposes the functionalities of ClimeCapsule via a FastAPI-based RESTful API.
- **Endpoints**:
  - `/` - Welcome message.
  - `/health` - Health check endpoint.
  - `/current` - Fetches and stores the latest weather observations.
  - `/historical/{date_str}` - Returns historical aggregated data for a specific date.
  - `/today_plus_history` - Provides current and past observations over multiple years for the same date.

### 4. Database Initialization (`db_setup.py`)

- **Purpose**: Initializes the SQLite database, and fetches historical weather data to populate it.

### 5. Example Config (`config.ini.example`)

Provides a template for the required configuration file.

## API Usage

Once the API is running, you can use tools like `curl`, Postman, or a web browser to interact with it.

### Example Endpoints:

1. **Health Check**
```shell script
curl http://localhost:8000/health
```

2. **Fetch Today's Data**
```shell script
curl http://localhost:8000/current
```

3. **Fetch Historical Data**
```shell script
curl http://localhost:8000/historical/2023-09-15
```

4. **Comparison of Today with Historical Data**
```shell script
curl 'http://localhost:8000/today_plus_history?years_back=3'
```

## Error Handling

- **Invalid Date Format**: If an invalid date (e.g., `23/09/2023`) is passed to a historical endpoint, you will receive a `400 Bad Request` response.
- **Data Not Found**: If no weather data is available for the requested date, you will receive a `404 Not Found` response.
- **API Rate Limits**: If the Weather Underground API rate limit is exceeded, the backoff and retry mechanism will handle retries automatically.

## Dependencies

- **Python Libraries**:
  - `requests`: To perform HTTP requests.
  - `sqlite3`: For interacting with the SQLite database.
  - `fastapi`: To build the RESTful API.
  - `uvicorn`: For running FastAPI.
  - `pydantic`: For data validation.
  - `backoff` & `ratelimit`: To handle API rate limits and retries.

## Development and Testing

1. **Run Unit Tests**:
   Use `pytest` to test the core functionalities.
```shell script
pytest
```

2. **Run API Server in Development Mode**:
   Use FastAPI's built-in `uvicorn` to enable live reloading.
```shell script
uvicorn api:app --reload
```

3. **API Documentation**:
   FastAPI automatically generates Swagger documentation.
   Visit:
   - Swagger UI: `http://localhost:8000/docs`
   - ReDoc: `http://localhost:8000/redoc`

## Future Improvements

- Add more weather data sources beyond Weather Underground.
- Add user authentication to restrict API usage.
- Implement caching to reduce API calls and improve response times.
- Support more advanced statistical analysis and weather insights.

---

The ClimeCapsule project provides a well-rounded solution to managing weather data for development and analysis purposes. If you encounter any issues, feel free to submit a bug report or contribute to the project.
