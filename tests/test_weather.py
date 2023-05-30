import os

from aag.weather import CloudSensor


def test_create_sensor():
    os.environ['AAG_SERIAL_PORT'] = '/dev/null'
    sensor = CloudSensor(connect=False)
    assert isinstance(sensor, CloudSensor)
    assert not sensor.is_connected
