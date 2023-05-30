import os
import pytest

from aag.weather import CloudSensor


def test_create_sensor():
    os.environ['AAG_SERIAL_PORT'] = 'loop://'
    sensor = CloudSensor(connect=False)
    assert isinstance(sensor, CloudSensor)
    assert not sensor.is_connected
    assert sensor.connect() is False


def test_bad_port():
    os.environ['AAG_SERIAL_PORT'] = 'bad://'

    # Should raise an exception
    with pytest.raises(Exception):
        CloudSensor(connect=False)
