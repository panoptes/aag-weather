from typing import Optional

from fastapi import FastAPI
from fastapi_utils.tasks import repeat_every

from aag.weather import CloudSensor

app = FastAPI()
sensor: Optional[CloudSensor] = None


@app.on_event('startup')
def init_sensor():
    global sensor
    sensor = CloudSensor()


@app.on_event('startup')
@repeat_every(seconds=30, wait_first=True)
def get_reading():
    """ Get a single reading of all values."""
    return sensor.get_reading()


@app.get('/weather')
def main():
    return sensor.readings
