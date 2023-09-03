import re
import time
from datetime import datetime

import serial
from collections.abc import Callable
from collections import deque
from contextlib import suppress

from astropy import units as u
from rich import print

from aag.commands import WeatherCommand, WeatherResponseCodes
from aag.settings import WeatherSettings, WhichUnits, Thresholds


class CloudSensor(object):
    def __init__(self, connect: bool = True, **kwargs):
        """ A class to read the cloud sensor.

        Args:
            connect: Whether to connect to the sensor on init.
            **kwargs: Keyword arguments for the WeatherSettings class.
        """
        self.config = WeatherSettings(**kwargs)

        try:
            self._sensor: serial.Serial = serial.serial_for_url(self.config.serial_port,
                                                                baudrate=9600,
                                                                timeout=1,
                                                                do_not_open=True
                                                                )
            if connect:
                self._sensor.open()
                self._sensor.reset_input_buffer()
                self._sensor.reset_output_buffer()
        except serial.serialutil.SerialException as e:
            print(f'[red]Unable to connect to weather sensor. Check the port. {e}')
            raise e

        self.handshake_block = r'\x11\s{12}0'

        # Set up a queue for readings
        self.readings = deque(maxlen=self.config.num_readings)

        self.name: str = 'CloudWatcher'
        self.firmware: str | None = None
        self.serial_number: str | None = None
        self.has_anemometer: bool = False

        self._is_connected: bool = False

        if connect:
            self._is_connected = self.connect()

    @property
    def is_connected(self) -> bool:
        """ Is the sensor connected?"""
        return self._is_connected

    @property
    def thresholds(self) -> Thresholds:
        """Thresholds for the safety checks."""
        return self.config.thresholds

    @property
    def status(self) -> dict:
        """Returns the most recent reading and safety value."""
        return self.readings[-1]

    @property
    def is_safe(self) -> bool:
        """Is the sensor safe?"""
        return self.status['is_safe']

    def connect(self, raise_exceptions: bool = True) -> bool:
        """ Connect to the sensor.

        Args:
            raise_exceptions: Whether to raise exceptions, default True.

        Returns:
            True if connected, False otherwise.
        """
        try:
            self._sensor.is_open or self._sensor.open()

            # Initialize and get static values.
            self.name = self.query(WeatherCommand.GET_INTERNAL_NAME)
            self.firmware = self.query(WeatherCommand.GET_FIRMWARE)
            self.serial_number = self.query(WeatherCommand.GET_SERIAL_NUMBER, parse_type=str)[0:4]

            # Check if we have wind speed.
            self.has_anemometer = self.query(WeatherCommand.CAN_GET_WINDSPEED, parse_type=bool)

            # Set the PWM to the minimum to start.
            self.set_pwm(self.config.heater.min_power)

            self._is_connected = True
        except Exception as e:
            print(f'[red]Unable to connect to weather sensor. Check the port. {e}')
            if raise_exceptions:
                raise e
            self._is_connected = False

        return self._is_connected

    def capture(self, callback: Callable | None = None, units: WhichUnits = 'none') -> None:
        """Captures readings continuously.

        Args:
            callback: A function to call with each reading.
        """
        try:
            while True:
                reading = self.get_reading(units=units)

                if callback is not None:
                    callback(reading)

                time.sleep(self.config.capture_delay)
        except KeyboardInterrupt:
            pass

    def get_reading(self, units: WhichUnits = 'none', get_errors: bool = False, avg_times: int = 3) -> dict:
        """ Get a single reading of all values.

        Args:
            units: The astropy units to return the reading in, default 'none',
                can be 'metric' or 'imperial'.
            get_errors: Whether to get the internal errors, default False.
            avg_times: The number of times to average the readings, default 3.

        Returns:
            A dictionary of readings.
        """

        def avg_times(fn, n=avg_times):
            return round(sum(fn() for _ in range(n)) / n, 3)

        reading = {
            'timestamp': datetime.now().isoformat(),
            'ambient_temp': avg_times(self.get_ambient_temperature),
            'sky_temp': avg_times(self.get_sky_temperature),
            'wind_speed': avg_times(self.get_wind_speed),
            'rain_frequency': avg_times(self.get_rain_frequency),
            'pwm': self.get_pwm(),
        }

        if get_errors:
            reading.update(**{f'error_{i:02d}': err for i, err in enumerate(self.get_errors())})

        # Add the safety values.
        reading = self.get_safe_reading(reading)

        # Add astropy units if requested.
        if units != 'none':
            # First make them metric units.
            reading['ambient_temp'] *= u.Celsius
            reading['sky_temp'] *= u.Celsius
            reading['wind_speed'] *= u.m / u.s
            reading['pwm'] *= u.percent
            # Then convert if needed.
            if units == 'imperial':
                reading['ambient_temp'] = reading['ambient_temp'].to(u.imperial.deg_F, equivalencies=u.temperature())
                reading['sky_temp'] = reading['sky_temp'].to(u.imperial.deg_F, equivalencies=u.temperature())
                reading['wind_speed'] = reading['wind_speed'].to(u.imperial.mile / u.hour)

        self.readings.append(reading)

        return reading

    def get_safe_reading(self, reading: dict) -> dict:
        """ Checks the reading against the thresholds.

        Args:
            reading: The reading to check.

        Returns:
            The reading with the safety values added.
        """
        reading['cloud_condition'] = 'unknown'
        temp_diff = reading['sky_temp'] - reading['ambient_temp']
        if temp_diff >= self.thresholds.very_cloudy:
            reading['cloud_condition'] = 'very cloudy'
        elif temp_diff >= self.thresholds.cloudy:
            reading['cloud_condition'] = 'cloudy'
        else:
            reading['cloud_condition'] = 'clear'

        reading['wind_condition'] = 'unknown'
        if reading['wind_speed'] is not None:
            if reading['wind_speed'] >= self.thresholds.very_gusty:
                reading['wind_condition'] = 'very gusty'
            elif reading['wind_speed'] >= self.thresholds.gusty:
                reading['wind_condition'] = 'gusty'
            elif reading['wind_speed'] >= self.thresholds.very_windy:
                reading['wind_condition'] = 'very windy'
            elif reading['wind_speed'] >= self.thresholds.windy:
                reading['wind_condition'] = 'windy'
            else:
                reading['wind_condition'] = 'calm'

        reading['rain_condition'] = 'unknown'
        if reading['rain_frequency'] <= self.thresholds.rainy:
            reading['rain_condition'] = 'rainy'
        elif reading['rain_frequency'] <= self.thresholds.wet:
            reading['rain_condition'] = 'wet'
        else:
            reading['rain_condition'] = 'dry'

        reading['cloud_safe'] = True if reading['cloud_condition'] == 'clear' else False
        reading['wind_safe'] = True if reading['wind_condition'] == 'calm' else False
        reading['rain_safe'] = True if reading['rain_condition'] == 'dry' else False

        reading['is_safe'] = True if reading['cloud_safe'] and reading['wind_safe'] and reading['rain_safe'] else False

        return reading

    def get_errors(self) -> list[int]:
        """Gets the number of internal errors

        Returns:
            A list of integer error codes.
        """
        responses = self.query(WeatherCommand.GET_INTERNAL_ERRORS, return_codes=True)

        for i, response in enumerate(responses.copy()):
            responses[i] = int(response[2:])

        return responses

    def get_sky_temperature(self) -> float:
        """Gets the latest IR sky temperature reading.

        Returns:
            The sky temperature in Celsius.
        """
        return self.query(WeatherCommand.GET_SKY_TEMP) / 100.

    def get_ambient_temperature(self) -> float:
        """Gets the latest ambient temperature reading.

        Returns:
            The ambient temperature in Celsius.
        """
        return self.query(WeatherCommand.GET_SENSOR_TEMP) / 100.

    def get_rain_sensor_values(self) -> list[float]:
        """Gets the latest sensor values.

        Returns:
            A list of rain sensor values.
        """
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
        """Gets the rain frequency.

        Returns:
            The rain frequency in Hz (?).
        """
        return self.query(WeatherCommand.GET_RAIN_FREQUENCY, parse_type=int)

    def get_pwm(self) -> float:
        """Gets the latest PWM reading.

        Returns:
            The PWM value as a percentage.
        """
        return self.query(WeatherCommand.GET_PWM, parse_type=int) / 1023 * 100

    def set_pwm(self, percent: float) -> bool:
        """Sets the PWM value.

        Returns:
            True if successful, False otherwise.
        """
        percent = min(100, max(0, int(percent)))
        percent = int(percent * 1023 / 100)
        return self.query(WeatherCommand.SET_PWM, cmd_params=f'{percent:04d}')

    def get_wind_speed(self) -> float | None:
        """ Gets the wind speed.

        Returns:
            The wind speed in km/h.
        """
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

        Args:
            cmd: The command to send to the sensor.
            return_codes: Whether to return the response codes, default False.
            parse_type: The type to parse the response as, default float.
            *args: Additional arguments to pass to `write` and `read`.
            **kwargs: Additional keyword arguments to pass to `write` and `read`.

        Returns:
            The response from the sensor.
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

    def write(self, cmd: WeatherCommand, cmd_params: str = '', cmd_delim: str = '!', *args, **kwargs) -> int:
        """Writes a command to the sensor.

        Appends the command delimiter and carriage return to the command and
        writes it to the sensor.

        Args:
            cmd: The command to send to the sensor.
            cmd_params: Any parameters to send with the command.
            cmd_delim: The command delimiter, default '!'.

        Returns:
            The number of bytes written.
        """
        full_cmd = f'{cmd.value}{cmd_params}{cmd_delim}'
        return self._sensor.write(full_cmd.encode())

    def read(self, return_raw: bool = False, verbose: bool = False, *args, **kwargs) -> list:
        """Reads a response from the sensor.

        The CloudWatcher always returns blocks of 15 characters, with each command
        returning one or more information blocks followed by a handshake block.

        Most commands return just two blocks, including the handshake. The
        `GET_VALUES` and `GET_INTERNAL_ERRORS` command return 4 blocks. The
        `RESET_RS232` command returns just the handshake block.

        If `return_raw` is False (default) then the blocks are parsed into a
        dictionary with the keys being the response code and the values being the
        data. Otherwise, the raw response is returned, including the handshake.

        Args:
            return_raw: Whether to return the raw response, default False.
            verbose: Whether to print the raw response, default False.

        Returns:
            The response from the sensor.
        """
        response = self._sensor.read_until(self.handshake_block).decode()
        if verbose:
            print(f'Raw response: {response!r}')

        if not return_raw:
            # Split into a list of blocks, with each item containing both the
            # response code and the data.
            response = re.findall(r"!(.{14})", response)

            # Check that the handshake block is valid.
            handshake_block = response.pop()
            if re.match(self.handshake_block, handshake_block) is None:
                raise ValueError(f'Invalid handshake block {handshake_block!r}')

        return response

    def __str__(self):
        return f'CloudSensor({self.name}, FW={self.firmware}, SN={self.serial_number}, port={self.config.serial_port})'

    def __del__(self):
        print('[red]Closing serial connection')
        self._sensor.close()
