from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Dict

from fastapi import FastAPI, HTTPException, APIRouter, Depends
from fastapi_utils.cbv import cbv
from fastapi import Request
from starlette.responses import HTMLResponse
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from weather.clime_capsule import ClimeCapsule, DailyObservation


@asynccontextmanager
async def lifespan(app: FastAPI):
    controller: ClimeCapsule = ClimeCapsule()
    controller.init_db()
    yield
app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
router = APIRouter()

def get_controller() -> ClimeCapsule:
    return ClimeCapsule()

@cbv(router)
class ClimeCapsuleAPI:
    controller: ClimeCapsule = Depends(get_controller)

    @router.get("/", response_class=HTMLResponse)
    async def root(self, request: Request):
        data = {
            "message": "Hello from FastAPI!",
            "title": "My FastAPI Page"
        }
        return templates.TemplateResponse("index.html", {"request": request, "data": data})

    @router.get("/health")
    async def health(self):
        return {"status": "ok"}

    @router.get("/current")
    async def current(self):
        # Reaches out to WeatherUnderground, and returns the current conditions
        # This will cause the current conditions to be stored in the historical DB
        today = datetime.today()
        today_str = today.strftime("%Y-%m-%d")

        # This will make a request to the wunderground API, and retrieve the latest observation for the given
        # weather station. Observations update roughly every hour, so, when this is called, it may produce
        # multiple entries for a given day. This is in intended, and when we retrieve data for this day in the future,
        # we will take the latest observation, as that will be the most accurate for daily observations
        # (Wunderground compiles all data for a "day" based on all observations up to the time the call is made.
        # so, this can result in impartial data if called mid day, and complete observations when called at end of day)
        # Note, this is rate limited to 30 calls every 60 seconds
        # observations = self.controller.fetch_current_data()
        observations = self.controller.fetch_current_data()

        # Attempt to write this observation to the DB
        # This may raise a DB integrity error, in which case, we already have this observation, so we'll just
        # return the observation. The exception is consumed.
        self.controller.db.insert_observations(observations)
        return {"date": today_str, "observations": observations}

    @router.get("/historical/{date_str}")
    async def historical(self, date_str: str):
        """
        Returns historical data for a single date
        :param date_str:
        :return:
        """
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

        # Get a list of hourly observations from the DB for the requested day
        observations: List[Dict] = self.controller.db.query_by_date(date_str)
        if not observations:
            raise HTTPException(status_code=404, detail=f"No data found for {date_str}.")

        # Average and total the hourly observations returned into a single daily observation
        daily_observation: DailyObservation = self.controller.compile_daily_data(observations)

        return {"date": date_str, "observation": daily_observation}

    @router.get("/today_plus_history", response_class=HTMLResponse)
    async def today_plus_history(self, request: Request, years_back: int = 2):
        today = datetime.today()
        today_str = today.strftime("%Y-%m-%d")

        # Attempt to get the most recent hourly data
        # Because of how WU stores data in UTC, but accesses it in local time, we cannot retrieve hourly data
        # past 5pm MST (because we would have to pass in tomorrow's date, which will error out).
        # So, if it is past 5pm MST, grab the current conditions from the weather station and use those
        # if today.hour <= 17:
        #     print("Fetching hourly data...")
        #     hourly_observations = self.controller.fetch_current_hourly_data()
        #     print(hourly_observations)
        #     if not hourly_observations:
        #         raise HTTPException(status_code=404, detail="No data found for provided date.")
        #     # Write the most recent observations for today to the DB
        #     # This will not write duplicates, so depending on when this is called, we may or may not write any data
        #     self.controller.db.insert_observations(hourly_observations)
        # else:
        print("Fetching current weather data...")
        current = self.controller.fetch_current_data()
        if not current:
            raise HTTPException(status_code=404, detail="No data found for current conditions.")
        self.controller.db.insert_current_observations(current)
        # Grab the latest daily data from the DB
        current_observation: DailyObservation = self.controller.compile_daily_data(
            self.controller.db.query_by_date(today_str), None)

        historical_summaries = []
        for i in range(1, years_back + 1):
            # Same day in the past (i years ago)
            past_year = today.year - i

            try:
                past_date = today.replace(year=past_year)
            except ValueError:
                # if today is Feb 29, and we're looking at a non-leap-year
                # fallback to Feb 28 or handle it differently
                past_date = today.replace(year=past_year, day=28)

            past_date_str = past_date.strftime("%Y-%m-%d")
            summary = self.controller.compile_daily_data(self.controller.db.query_by_date(past_date_str), through=today.hour)
            # The daily summary will always return a DailyObservation object, but it may be empty if no data for this
            # date was found. This will ensure our template never breaks, though
            historical_summaries.append(summary)

        weather_data = {
            "today": today_str,
            "today_observation": current_observation,
            "historical_comparisons": historical_summaries
        }
        return templates.TemplateResponse(
            "weather.html",
            {
                "request": request,
                **weather_data
            }
        )

app.include_router(router)



