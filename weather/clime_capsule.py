import configparser
import os
from datetime import datetime, timedelta
from typing import List, Dict

import requests
from backoff import on_exception, expo
from pydantic import BaseModel
from ratelimit import sleep_and_retry, limits, RateLimitException

from weather.db import WeatherDB


class DailyObservation(BaseModel):
    station_id: str
    obs_time_local: str
    friendly_date: str
    temp_high: float
    temp_low: float
    temp_avg: float
    windspeed_high: float
    windspeed_low: float
    windspeed_avg: float
    wind_chill_high: float
    wind_chill_low: float
    wind_chill_avg: float
    precip_rate: float
    precip_avg: float


def singleton(cls):
    instances = {}

    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance


@singleton
class ClimeCapsule:
    def __init__(self):
        config = configparser.ConfigParser()
        config.read("config.ini")

        self.base_url = config["weather-underground"]["base_url"]
        self.wu_api_key: str = config["weather-underground"]["api_key"]
        self.wu_station_id: str = config["weather-underground"]["station_id"]
        self.earliest_observation: str = config["weather-underground"]["earliest_observation"]

        self.db_name: str = config["database"]["db_name"]
        self.db: WeatherDB = WeatherDB(self.db_name)

    def init_db(self):
        if not os.path.exists(self.db_name):
            self.db.init_db()

            # Since the DB did not exist, populate with historical data
            today: datetime = datetime.now()
            start = self.earliest_observation
            end = today.strftime("%Y-%m-%d")
            observations = self.fetch_historical_hourly_data(start, end)
            self.db.insert_observations(observations)
        else:
            print(f"Using existing DB at {self.db_name}...")

    @sleep_and_retry
    @on_exception(expo, RateLimitException, max_tries=3)
    @limits(calls=30, period=60)
    def make_api_call(self, url: str, params: Dict[str, str]) -> List:
        if "date" in params.keys():
            print(f"Fetching weather data for {params['date']}...")
        else:
            print("Fetching current weather data...")

        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        return data.get("observations", [])

    @staticmethod
    def compile_daily_data(observations: List[Dict]) -> DailyObservation:
        # Iterate over the list of daily observations (each representing an hour)
        # and average them out into a single daily observation

        high_temp: float = 0
        low_temp: float = 150
        total_avg_temp: float = 0
        high_windspeed: float = 0
        low_windspeed: float = 150
        total_avg_windspeed: float = 0
        high_wind_chill: float = 0
        low_wind_chill: float = 150
        total_avg_windchill: float = 0
        high_precip_rate: float = 0
        precip_rate_avg: float = 0
        observation_count: int = 0

        if len(observations) != 0:
            # Grab the station ID and observation time (date) from the first observation
            # These will remain the same across all observations, since this list represents
            # a single station on a single day
            dt: datetime = datetime.strptime(observations[-1]["obsTimeLocal"], "%Y-%m-%d %H:%M:%S")
            date_str: str = dt.strftime("%Y-%m-%d")
            station_id: str = observations[0]["stationID"]

            for obs in observations:
                if obs["imperial"]["tempHigh"] > high_temp:
                    high_temp = obs["imperial"]["tempHigh"]

                if obs["imperial"]["tempLow"] < low_temp:
                    low_temp = obs["imperial"]["tempLow"]

                total_avg_temp += obs["imperial"]["tempAvg"]

                if obs["imperial"]["windspeedHigh"] > high_windspeed:
                    high_windspeed = obs["imperial"]["windspeedHigh"]

                if obs["imperial"]["windspeedLow"] < low_windspeed:
                    low_windspeed = obs["imperial"]["windspeedLow"]

                total_avg_windspeed += obs["imperial"]["windspeedAverage"]

                if obs["imperial"]["windchillHigh"] > high_wind_chill:
                    high_wind_chill = obs["imperial"]["windchillHigh"]

                if obs["imperial"]["windchillLow"] < low_wind_chill:
                    low_wind_chill = obs["imperial"]["windchillLow"]

                total_avg_windchill += obs["imperial"]["windchillAverage"]

                if obs["imperial"]["precipRate"] > high_precip_rate:
                    high_precip_rate = obs["imperial"]["precipRate"]

                precip_rate_avg += obs["imperial"]["precipAverage"]
                observation_count += 1

            # Create and return a new DailyObservation object from the compiled data
            return DailyObservation(
                station_id=station_id,
                obs_time_local=date_str,
                friendly_date=dt.strftime("%B %d, %Y"),
                temp_high=high_temp,
                temp_low=low_temp,
                temp_avg=round(total_avg_temp / observation_count, 2),
                windspeed_high=high_windspeed,
                windspeed_low=low_windspeed,
                windspeed_avg=round(total_avg_windspeed / observation_count, 2),
                wind_chill_high=high_wind_chill,
                wind_chill_low=low_wind_chill,
                wind_chill_avg=round(total_avg_windchill / observation_count, 2),
                precip_rate=high_precip_rate,
                precip_avg=round(precip_rate_avg / observation_count, 2)
            )
        else:
            return DailyObservation()

    def fetch_historical_hourly_data(self, start_date: str, end_date: str | None) -> List[Dict]:
        """
        Fetch hourly data for all dates in the provided date range
        USed for initially filling the DB with historical data, or for filling in missing date ranges
        :param start_date:
        :param end_date:
        :return:
        """
        # If end_date is None, default to start date, which will retrieve data for just a single day
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
        if end_date is None:
            end_date = start_date
        elif isinstance(end_date, str):
            end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

        observations: List[Dict] = []
        endpoint: str = "/history/hourly"

        while start_date <= end_date:
            url = f"{self.base_url}{endpoint}"

            params = {
                "apiKey": self.wu_api_key,
                "stationId": self.wu_station_id,
                "format": "json",
                "units": "e",  # Imperial
                "date": start_date.strftime("%Y%m%d")
            }

            data: List = self.make_api_call(url, params)
            observations.extend(data)
            start_date += timedelta(days=1)

        return observations

    def fetch_current_hourly_data(self) -> List[Dict]:
        """
        Gets the current, up to date, hourly data for today
        This will return a variable number of hourly observations depending on when its called (min: 1, max: 24)
        Observations that have already been recorded will be ignored when writing this data to the DB
        :return:
        """
        observations: List[Dict] = []
        endpoint: str = "/history/hourly"

        url = f"{self.base_url}{endpoint}"

        params = {
            "apiKey": self.wu_api_key,
            "stationId": self.wu_station_id,
            "format": "json",
            "units": "e",  # Imperial
            "date": datetime.today().strftime("%Y-%m-%d").replace("-", "")
        }

        data: List = self.make_api_call(url, params)
        observations.extend(data)

        return observations

    def fetch_current_data(self) -> List[Dict]:
        # Fetches the current conditions from the station
        observations: List[Dict] = []
        endpoint: str = "/observations/current"

        url = f"{self.base_url}{endpoint}"

        params = {
            "apiKey": self.wu_api_key,
            "stationId": self.wu_station_id,
            "format": "json",
            "units": "e",  # Imperial
        }

        data: List = self.make_api_call(url, params)
        observations.extend(data)

        return observations