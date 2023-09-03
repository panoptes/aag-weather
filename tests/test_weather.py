import os
import pytest

from aag.weather import CloudSensor


def test_create_sensor():
    os.environ['AAG_SERIAL_PORT'] = 'loop://'
    sensor = CloudSensor(connect=False)
    assert isinstance(sensor, CloudSensor)
    assert not sensor.is_connected
    assert sensor.connect(raise_exceptions=False) is False


def test_bad_port():
    os.environ['AAG_SERIAL_PORT'] = 'bad://'

    # Should raise an exception
    with pytest.raises(Exception):
        CloudSensor(connect=False)


def test_connect_loop():
    with pytest.raises(Exception):
        CloudSensor(connect=True, serial_port='loop://')

    sensor = CloudSensor(connect=False, serial_port='loop://')
    is_connected = sensor.connect(raise_exceptions=False)
    assert isinstance(sensor, CloudSensor)
    assert is_connected is False
    assert sensor.is_connected is False


def test_get_safe_reading():
    os.environ['AAG_SERIAL_PORT'] = 'loop://'
    sensor = CloudSensor(connect=False)
    assert isinstance(sensor, CloudSensor)
    assert not sensor.is_connected
    assert sensor.connect(raise_exceptions=False) is False

    # Make a fake reading entry.
    reading = {
        'wind_speed': 10,
        'ambient_temp': 20,
        'sky_temp': 10,
        'timestamp': '2021-01-01T00:00:00',
        'rain_frequency': 2500,
        'pwm': 0,
    }

    # Check safety.
    reading = sensor.get_safe_reading(reading=reading)
    assert reading['is_safe'] is False
    assert reading['cloud_safe'] is False
    assert reading['cloud_condition'] == 'very cloudy'

    # Make safe
    reading['ambient_temp'] = 20
    reading['sky_temp'] = -20
    print(reading)
    reading = sensor.get_safe_reading(reading=reading)
    print(reading)
    assert reading['is_safe'] is True
    assert reading['cloud_safe'] is True
    assert reading['cloud_condition'] == 'clear'

    # Make windy
    reading['wind_speed'] = 51
    reading = sensor.get_safe_reading(reading=reading)
    assert reading['is_safe'] is False
    assert reading['wind_safe'] is False
    assert reading['wind_condition'] == 'windy'

    reading['wind_speed'] = 76
    reading = sensor.get_safe_reading(reading=reading)
    assert reading['wind_condition'] == 'very windy'

    reading['wind_speed'] = 101
    reading = sensor.get_safe_reading(reading=reading)
    assert reading['wind_condition'] == 'gusty'

    reading['wind_speed'] = 126
    reading = sensor.get_safe_reading(reading=reading)
    assert reading['wind_condition'] == 'very gusty'

    # Make rainy
    reading['rain_frequency'] = 2000
    reading = sensor.get_safe_reading(reading=reading)
    assert reading['is_safe'] is False
    assert reading['rain_safe'] is False
    assert reading['rain_condition'] == 'wet'

    reading['rain_frequency'] = 1700
    reading = sensor.get_safe_reading(reading=reading)
    assert reading['is_safe'] is False
    assert reading['rain_safe'] is False
    assert reading['rain_condition'] == 'rainy'

    # Make dry
    reading['rain_frequency'] = 2300
    reading = sensor.get_safe_reading(reading=reading)
    assert reading['rain_condition'] == 'dry'
