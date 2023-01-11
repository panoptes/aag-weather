from pydantic import BaseSettings, BaseModel


class Thresholds(BaseModel):
    cloudy: float = -25
    very_cloudy: float = -15
    windy: float = 50
    very_windy: float = 75
    gusty: float = 100
    very_gusty: float = 125
    wet: int = 2200
    rainy: int = 1800


class Heater(BaseModel):
    min_power: float = 10
    low_temp: float = 0
    low_delta: float = 6
    high_temp: float = 20
    high_delta: float = 4
    impulse_temp: float = 10
    impulse_duration: float = 60
    impulse_cycle: int = 600


class WeatherSettings(BaseSettings):
    serial_port: str = '/dev/ttyUSB0'
    safety_delay: float = 15  # minutes
    capture_delay: float = 5  # seconds
    num_readings: int = 10
    ignore_unsafe: bool | None = None  # None, otherwise can be a list, e.g. 'rain','cloud','gust','wind'
    thresholds = Thresholds()
    heater = Heater()
