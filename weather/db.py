import sqlite3
from datetime import datetime, timedelta
from typing import List

class WeatherDB:

    def __init__(self, db_file: str):
        self.db_file: str = db_file

    def init_db(self) -> None:
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS weather_data(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id TEXT,
                obs_time_local TEXT UNIQUE,
                temperature_high REAL,
                temperature_low REAL,
                temperature_average REAL,
                humidity REAL,
                wind_speed_high REAL,
                wind_speed_low REAL,
                wind_speed_average REAL,
                windchill_high REAL,
                windchill_low REAL,
                windchill_average REAL,
                precip_rate REAL,
                precip_total REAL
            )
        """)
        conn.commit()
        conn.close()

    def insert_observations(self, observations):
        """
        Insert a list of observation records into the database.
        `observations` should be a list of dicts with the relevant keys.
        """
        conn = sqlite3.connect(self.db_file)
        c = conn.cursor()

        for obs in observations:
            try:
                c.execute("""
                    INSERT INTO weather_data (
                        station_id, 
                        obs_time_local, 
                        temperature_high, 
                        temperature_low, 
                        temperature_average, 
                        humidity, 
                        wind_speed_high,
                        wind_speed_low,
                        wind_speed_average,
                        windchill_high,
                        windchill_low,
                        windchill_average,
                        precip_rate, 
                        precip_total
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    obs["stationID"],
                    obs["obsTimeLocal"],
                    obs.get("imperial", {}).get("tempHigh", None),
                    obs.get("imperial", {}).get("tempLow", None),
                    obs.get("imperial", {}).get("tempAvg", None),
                    obs.get("humidityAvg", None),
                    obs.get("imperial", {}).get("windspeedHigh", None),
                    obs.get("imperial", {}).get("windspeedLow", None),
                    obs.get("imperial", {}).get("windspeedAvg", None),
                    obs.get("imperial", {}).get("windchillHigh", None),
                    obs.get("imperial", {}).get("windchillLow", None),
                    obs.get("imperial", {}).get("windchillAvg", None),
                    obs.get("imperial", {}).get("precipRate", None),
                    obs.get("imperial", {}).get("precipTotal", None)
                ))
            except sqlite3.IntegrityError:
                # A uniqueness constraint is in violation, print a friendly message and move on
                print(f"Entry for {obs['stationID']} at {obs['obsTimeLocal']} already exists. Skipping.")

        conn.commit()
        conn.close()

    def insert_current_observations(self, observations):
        """
        Insert a list of observation records into the database.
        `observations` should be a list of dicts with the relevant keys.
        """
        conn = sqlite3.connect(self.db_file)
        c = conn.cursor()

        for obs in observations:
            try:
                c.execute("""
                    INSERT INTO weather_data (
                        station_id, 
                        obs_time_local, 
                        temperature_high, 
                        temperature_low, 
                        temperature_average, 
                        humidity, 
                        wind_speed_high,
                        wind_speed_low,
                        wind_speed_average,
                        windchill_high,
                        windchill_low,
                        windchill_average,
                        precip_rate, 
                        precip_total
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    obs["stationID"],
                    obs["obsTimeLocal"],
                    obs.get("imperial", {}).get("temp", None),
                    obs.get("imperial", {}).get("temp", None),
                    obs.get("imperial", {}).get("temp", None),
                    obs.get("humidity", None),
                    obs.get("imperial", {}).get("windSpeed", None),
                    obs.get("imperial", {}).get("windSpeed", None),
                    obs.get("imperial", {}).get("windSpeed", None),
                    obs.get("imperial", {}).get("windChill", None),
                    obs.get("imperial", {}).get("windChill", None),
                    obs.get("imperial", {}).get("windChill", None),
                    obs.get("imperial", {}).get("precipRate", None),
                    obs.get("imperial", {}).get("precipTotal", None)
                ))
            except sqlite3.IntegrityError:
                # A uniqueness constraint is in violation, print a friendly message and move on
                print(f"Entry for {obs['stationID']} at {obs['obsTimeLocal']} already exists. Skipping.")

        conn.commit()
        conn.close()

    def query_by_date(self, date_str: str) -> List[dict]:
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        dt = datetime.strptime(date_str, "%Y-%m-%d")
        start_ts = dt.strftime("%Y-%m-%d 00:00:00")
        end_ts = (dt + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")

        query = """
            SELECT
                station_id, 
                obs_time_local, 
                temperature_high, 
                temperature_low, 
                temperature_average, 
                humidity, 
                wind_speed_high,
                wind_speed_low,
                wind_speed_average,
                windchill_high,
                windchill_low,
                windchill_average,
                precip_rate, 
                precip_total
            FROM weather_data
            WHERE obs_time_local >= ? AND obs_time_local < ?
            ORDER BY obs_time_local ASC
        """

        cursor.execute(query, (start_ts, end_ts))
        rows = cursor.fetchall()

        conn.close()

        observations = []
        for row in rows:
            observations.append({
                "stationID": row[0],
                "obsTimeLocal": row[1],
                "imperial": {
                    "tempHigh": row[2],
                    "tempLow": row[3],
                    "tempAvg": row[4],
                    "humidity": row[5],
                    "windspeedHigh": row[6],
                    "windspeedLow": row[7],
                    "windspeedAverage": row[8],
                    "windchillHigh": row[9],
                    "windchillLow": row[10],
                    "windchillAverage": row[11],
                    "precipRate": row[12],
                    "precipAverage": row[13]
                },
            })
        return observations




