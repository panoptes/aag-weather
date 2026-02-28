from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from aag.weather import CloudSensor


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.sensor = CloudSensor()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/weather")
def main(request: Request):
    return list(request.app.state.sensor.readings)
