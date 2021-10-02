import os
from fastapi import FastAPI
from pathlib import Path

from panoptes.utils.serializers import from_yaml


app = FastAPI()
weather_file = Path(os.getenv('WEATHER_JSON_FILE', 'current_weather.json'))

@app.get('/current')
def current_reading():
    """Gets the current weather reading."""
    reading = dict()
    with weather_file.open('r') as f:
        reading = from_yaml(f.read())

    return reading
