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

    # Should raise an exception
    with pytest.raises(Exception):
        CloudSensor(connect=True)


def test_connect_loop():
    with pytest.raises(Exception):
        CloudSensor(connect=True, serial_port='loop://')

    sensor = CloudSensor(connect=False, serial_port='loop://')
    is_connected = sensor.connect(raise_exceptions=False)
    assert isinstance(sensor, CloudSensor)
    assert is_connected is False
    assert sensor.is_connected is False

def test_str():
    sensor = CloudSensor(connect=False, serial_port='loop://')
    sensor.firmware = '5.12-fake'
    sensor.serial_number = '1234567890'
    assert str(sensor) == 'CloudSensor(CloudWatcher, FW=5.12-fake, SN=1234567890, port=loop://)'


def test_get_safe_reading():
    os.environ['AAG_SERIAL_PORT'] = 'loop://'
    sensor = CloudSensor(connect=False)
    assert isinstance(sensor, CloudSensor)
    assert not sensor.is_connected
    assert sensor.connect(raise_exceptions=False) is False

    # Make a fake reading that's safe.
    reading = {
        'wind_speed': 6,
        'ambient_temp': 20,
        'sky_temp': -20,
        'timestamp': '2021-01-01T00:00:00',
        'rain_frequency': 2600,
        'pwm': 0,
    }
    sensor.readings.append(reading)

    # Check is safe.
    reading = sensor.get_safe_reading(reading=reading)
    print(reading)
    assert sensor.is_safe is True
    assert reading['is_safe'] is True
    assert reading['cloud_safe'] is True
    assert reading['rain_safe'] is True
    assert reading['wind_safe'] is True
    assert reading['cloud_condition'] == 'clear'
    assert reading['rain_condition'] == 'dry'
    assert reading['wind_condition'] == 'calm'

    # Make very cloudy
    reading['ambient_temp'] = 20
    reading['sky_temp'] = 10
    reading = sensor.get_safe_reading(reading=reading)
    assert sensor.is_safe is False
    assert reading['is_safe'] is False
    assert reading['cloud_safe'] is False
    assert reading['cloud_condition'] == 'very cloudy'

    # Make cloudy
    reading['ambient_temp'] = 15
    reading['sky_temp'] = -10
    reading = sensor.get_safe_reading(reading=reading)
    assert sensor.is_safe is False
    assert reading['cloud_condition'] == 'cloudy'

    # Make windy
    reading['wind_speed'] = 51
    reading = sensor.get_safe_reading(reading=reading)
    assert reading['is_safe'] is False
    assert reading['wind_safe'] is False
    assert reading['wind_condition'] == 'windy'
    assert sensor.is_safe is False

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
