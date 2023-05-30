import re
import time
from datetime import datetime

import serial
from collections.abc import Callable
from collections import deque
from contextlib import suppress
from logging import getLogger

from astropy import units as u

from aag.commands import WeatherCommand, WeatherResponseCodes
from aag.settings import WeatherSettings, WhichUnits

logger = getLogger(__name__)


class CloudSensor(object):
    def __init__(self):
        """ A class to read the cloud sensor """
        self.config = WeatherSettings()

        self._sensor: serial.Serial = serial.serial_for_url(self.config.serial_port,
                                                            baudrate=9600,
                                                            timeout=1)
        self._sensor.reset_input_buffer()
        self._sensor.reset_output_buffer()

        self.handshake_block = r'\x11\s{12}0'

        # Initialize and get static values.
        self.name = self.query(WeatherCommand.GET_INTERNAL_NAME)
        self.firmware = self.query(WeatherCommand.GET_FIRMWARE)
        self.serial_number = self.query(WeatherCommand.GET_SERIAL_NUMBER, parse_type=str)[0:4]

        # Check if we have wind speed.
        self.has_anemometer = self.query(WeatherCommand.CAN_GET_WINDSPEED, parse_type=bool)

        # Set up a queue for readings
        self.readings = deque(maxlen=self.config.num_readings)

        # Set the PWM to the minimum to start.
        self.set_pwm(self.config.heater.min_power)

    def capture(self, callback: Callable | None = None, units: WhichUnits = 'none'):
        """Captures readings continuously."""
        try:
            while True:
                reading = self.get_reading(units=units)

                if callback is not None:
                    callback(reading)

                time.sleep(self.config.capture_delay)
        except KeyboardInterrupt:
            pass

    def get_reading(self, enqueue: bool = True, units: WhichUnits = 'none') -> dict:
        """ Get a single reading of all values.

        If enqueue is True (default), the reading is added to the queue.
        If with_units is True, the reading is returned with units.
        """
        readings = {
            'timestamp': datetime.now().isoformat(),
            'ambient_temp': self.get_ambient_temperature(),
            'sky_temp': self.get_sky_temperature(),
            'wind_speed': self.get_wind_speed(),
            'rain_frequency': self.get_rain_frequency(),
            'pwm': self.get_pwm(),
            **{f'error_{i}': err for i, err in enumerate(self.get_errors())}
        }

        if units != 'none':
            # First make them metric units.
            readings['ambient_temp'] *= u.Celsius
            readings['sky_temp'] *= u.Celsius
            readings['wind_speed'] *= u.m / u.s
            readings['pwm'] *= u.percent
            # Then convert if needed.
            if units == 'imperial':
                readings['ambient_temp'] = readings['ambient_temp'].to(u.imperial.deg_F, equivalencies=u.temperature())
                readings['sky_temp'] = readings['sky_temp'].to(u.imperial.deg_F, equivalencies=u.temperature())
                readings['wind_speed'] = readings['wind_speed'].to(u.imperial.mile / u.hour)

        if enqueue:
            self.readings.append(readings)

        return readings

    def get_errors(self):
        """Gets the number of internal errors"""
        responses = self.query(WeatherCommand.GET_INTERNAL_ERRORS, return_codes=True)

        for i, response in enumerate(responses.copy()):
            responses[i] = int(response[2:])

        return responses

    def get_sky_temperature(self) -> float:
        """Gets the latest IR sky temperature reading."""
        return self.query(WeatherCommand.GET_SKY_TEMP) / 100.

    def get_ambient_temperature(self) -> float:
        """Gets the latest ambient temperature reading."""
        return self.query(WeatherCommand.GET_SENSOR_TEMP) / 100.

    def get_rain_sensor_values(self):
        """Gets the latest sensor values."""
        responses = self.query(WeatherCommand.GET_VALUES, return_codes=True)

        for i, response in enumerate(responses.copy()):
            if response.startswith(WeatherResponseCodes.GET_VALUES_AMBIENT):
                responses[i] = response[2:] / 100.
            elif response.startswith(WeatherResponseCodes.GET_VALUES_LDR_VOLTAGE):
                responses[i] = response[2:]
            elif response.startswith(WeatherResponseCodes.GET_VALUES_SENSOR_TEMP):
                responses[i] = float(response[2:]) / 100.
            elif response.startswith(WeatherResponseCodes.GET_VALUES_ZENER_VOLTAGE):
                responses[i] = response[2:]

        return responses

    def get_rain_frequency(self) -> int:
        """Gets the rain frequency."""
        return self.query(WeatherCommand.GET_RAIN_FREQUENCY, parse_type=int)

    def get_pwm(self):
        """Gets the latest PWM reading."""
        return self.query(WeatherCommand.GET_PWM, parse_type=int) / 1023 * 100

    def set_pwm(self, percent: float):
        """Sets the PWM value."""
        percent = min(100, max(0, int(percent)))
        percent = int(percent * 1023 / 100)
        return self.query(WeatherCommand.SET_PWM, cmd_params=f'{percent:04d}')

    def get_wind_speed(self) -> float | None:
        """ Gets the wind speed. """
        if self.has_anemometer:
            ws = self.query(WeatherCommand.GET_WINDSPEED)
            ws *= 0.84
            # The manual says to add 3 km/h to the reading but that seems off.
            # ws += 3 * u.km / u.hour
            return ws
        else:
            return None

    def query(self, cmd: WeatherCommand,
              return_codes: bool = False,
              parse_type: type = float, *args, **kwargs) -> list | str | float | int | bool:
        """ Queries the sensor for the current values.

         This combines the `write` and `read` methods into a single method and
         checks that the response is valid.
         """
        self.write(cmd, *args, **kwargs)
        response = self.read(*args, **kwargs)

        if len(response) == 1:
            response = response[0]

        if return_codes is False:
            response = re.sub(WeatherResponseCodes[cmd.name], '', response)
            with suppress(ValueError):
                response = parse_type(response)

        return response

    def write(self, cmd: WeatherCommand, cmd_params: str = '', cmd_delim: str = '!', *args,
              **kwargs):
        """Writes a command to the sensor.

        Appends the command delimiter and carriage return to the command and
        writes it to the sensor.
        """
        full_cmd = f'{cmd.value}{cmd_params}{cmd_delim}'
        logger.debug(f'Writing command {full_cmd!r}')
        return self._sensor.write(full_cmd.encode())

    def read(self, return_raw: bool = False, *args, **kwargs) -> list:
        """Reads a response from the sensor.

        The CloudWatcher always returns blocks of 15 characters, with each command
        returning one or more information blocks followed by a handshake block.

        Most commands return just two blocks, including the handshake. The
        `GET_VALUES` and `GET_INTERNAL_ERRORS` command return 4 blocks. The
        `RESET_RS232` command returns just the handshake block.

        If `return_raw` is False (default) then the blocks are parsed into a
        dictionary with the keys being the response code and the values being the
        data. Otherwise, the raw response is returned, including the handshake.
        """
        response = self._sensor.read_until(self.handshake_block).decode()
        logger.debug(f'Read response {response!r}')

        if not return_raw:
            # Split into a list of blocks, with each item containing both the
            # response code and the data.
            response = re.findall(r"!(.{14})", response)
            logger.debug(f'{response=!r}')

            # Check that the handshake block is valid.
            handshake_block = response.pop()
            if re.match(self.handshake_block, handshake_block) is None:
                raise ValueError(f'Invalid handshake block {handshake_block!r}')

        return response

    def __str__(self):
        return f'CloudSensor({self.name}, FW={self.firmware}, SN={self.serial_number}, port={self.config.serial_port})'

    def __del__(self):
        logger.debug('Closing serial connection')
        self._sensor.close()
