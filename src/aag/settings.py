from enum import StrEnum
from typing import TypedDict

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["WeatherSettings", "WeatherReading", "Thresholds", "Heater", "WhichUnits"]


class WhichUnits(StrEnum):
    metric = "metric"
    imperial = "imperial"
    none = "none"


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
    min_power: float = 0
    low_temp: float = 0
    low_delta: float = 6
    high_temp: float = 20
    high_delta: float = 4
    impulse_temp: float = 10
    impulse_duration: float = 60
    impulse_cycle: int = 600


class WeatherSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AAG_",
        env_file="config.env",
        env_nested_delimiter="__",
    )

    serial_port: str = "/dev/ttyUSB0"
    safety_delay: float = Field(default=15, description="Safety delay in minutes")
    capture_delay: float = Field(default=30, description="Delay between readings in seconds")
    num_readings: int = 10
    ignore_unsafe: list[str] | None = Field(
        default=None,
        description="Conditions to ignore when computing is_safe, e.g. ['rain', 'cloud', 'wind']",
    )
    thresholds: Thresholds = Thresholds()
    heater: Heater = Heater()


class WeatherReading(TypedDict, total=False):
    """Shape of a single weather reading dict."""

    timestamp: str
    ambient_temp: float
    sky_temp: float
    wind_speed: float | None
    rain_frequency: int
    pwm: float
    cloud_condition: str
    wind_condition: str
    rain_condition: str
    cloud_safe: bool
    wind_safe: bool
    rain_safe: bool
    is_safe: bool


class WeatherPlotter(BaseModel):
    ambient_temp: tuple[int, int] = (-5, 45)  # celsius
    cloudiness: tuple[int, int] = (-45, 5)
    wind: tuple[int, int] = (0, 50)  # kph
    rain: tuple[int, int] = (700, 7000)
    pwm: tuple[int, int] = (-5, 105)  # percent


class Location(BaseModel):
    name: str = "AAG CloudWatcher"
    elevation: float = 100.0  # meters
    latitude: float = 19.54  # degrees
    longitude: float = -155.58  # degrees
    timezone: str = "US/Hawaii"
