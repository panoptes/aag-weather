import pytest

from aag.weather import CloudSensor


def test_create_sensor():
    sensor = CloudSensor(connect=False)
    assert isinstance(sensor, CloudSensor)
    assert not sensor.is_connected
