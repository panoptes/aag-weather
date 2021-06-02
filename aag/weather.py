import re
import sys
import time
from datetime import datetime as dt

import numpy as np
import astropy.units as u
from loguru import logger
from panoptes.utils.rs232 import SerialData
from panoptes.utils.utils import listify
from .PID import PID


def movingaverage(interval, window_size):
    """ A simple moving average function """
    window = np.ones(int(window_size)) / float(window_size)
    return np.convolve(interval, window, 'same')


# -----------------------------------------------------------------------------
# AAG Cloud Sensor Class
# -----------------------------------------------------------------------------
class AAGCloudSensor(object):
    """
    This class is for the AAG Cloud Sensor device which can be communicated with
    via serial commands.

    https://www.aagware.eu/aag/cloudwatcherNetwork/TechInfo/Rs232_Comms_v100.pdf
    https://www.aagware.eu/aag/cloudwatcherNetwork/TechInfo/Rs232_Comms_v110.pdf
    https://www.aagware.eu/aag/cloudwatcherNetwork/TechInfo/Rs232_Comms_v120.pdf

    Command List (from Rs232_Comms_v100.pdf)
    !A = Get internal name (receives 2 blocks)
    !B = Get firmware version (receives 2 blocks)
    !C = Get values (receives 5 blocks)
         Zener voltage, Ambient Temperature, Ambient Temperature, Rain Sensor Temperature, HSB
    !D = Get internal errors (receives 5 blocks)
    !E = Get rain frequency (receives 2 blocks)
    !F = Get switch status (receives 2 blocks)
    !G = Set switch open (receives 2 blocks)
    !H = Set switch closed (receives 2 blocks)
    !Pxxxx = Set PWM value to xxxx (receives 2 blocks)
    !Q = Get PWM value (receives 2 blocks)
    !S = Get sky IR temperature (receives 2 blocks)
    !T = Get sensor temperature (receives 2 blocks)
    !z = Reset RS232 buffer pointers (receives 1 blocks)
    !K = Get serial number (receives 2 blocks)

    Return Codes
    '1 '    Infra red temperature in hundredth of degree Celsius
    '2 '    Infra red sensor temperature in hundredth of degree Celsius
    '3 '    Analog0 output 0-1023 => 0 to full voltage (Ambient Temp NTC)
    '4 '    Analog2 output 0-1023 => 0 to full voltage (LDR ambient light)
    '5 '    Analog3 output 0-1023 => 0 to full voltage (Rain Sensor Temp NTC)
    '6 '    Analog3 output 0-1023 => 0 to full voltage (Zener Voltage reference)
    'E1'    Number of internal errors reading infra red sensor: 1st address byte
    'E2'    Number of internal errors reading infra red sensor: command byte
    'E3'    Number of internal errors reading infra red sensor: 2nd address byte
    'E4'    Number of internal errors reading infra red sensor: PEC byte NB: the error
            counters are reset after being read.
    'N '    Internal Name
    'V '    Firmware Version number
    'Q '    PWM duty cycle
    'R '    Rain frequency counter
    'X '    Switch Opened
    'Y '    Switch Closed

    Advice from the manual:

    * When communicating with the device send one command at a time and wait for
    the respective reply, checking that the correct number of characters has
    been received.

    * Perform more than one single reading (say, 5) and apply a statistical
    analysis to the values to exclude any outlier.

    * The rain frequency measurement is the one that takes more time - 280 ms

    * The following reading cycle takes just less than 3 seconds to perform:
        * Perform 5 times:
            * get IR temperature
            * get Ambient temperature
            * get Values
            * get Rain Frequency
        * get PWM value
        * get IR errors
        * get SWITCH Status

    """

    def __init__(self, config, serial_address=None, *args, **kwargs):
        self.config = config
        self.safety_delay = self.config.get('safety_delay', 15.)

        # Initialize Serial Connection
        serial_address = serial_address or self.config.get('serial_port', '/dev/ttyUSB0')
        logger.debug(f'Using serial address: {serial_address}')

        self.aag_device = None
        logger.info('Connecting to AAG Cloud Sensor')
        try:
            self.aag_device = SerialData(serial_address, baudrate=9600, timeout=2)
            logger.info(f'Connected to Cloud Sensor on {serial_address}')
        except BaseException as e:
            logger.error('Unable to connect to AAG Cloud Sensor: {e!r}')

        # Initialize Values
        self.last_update = None
        self.safe = None
        self.ambient_temp = None
        self.sky_temp = None
        self.wind_speed = None
        self.internal_voltage = None
        self.ldr_resistance = None
        self.rain_sensor_temp = None
        self.PWM = None
        self.errors = None
        self.switch = None
        self.safe_dict = None
        self.hibernate = 0.500  # time to wait after failed query

        # Set Up Heater
        if 'heater' in self.config:
            self.heater_cfg = self.config['heater']
        else:
            self.heater_cfg = {
                'low_temp': 0,
                'low_delta': 6,
                'high_temp': 20,
                'high_delta': 4,
                'min_power': 10,
                'impulse_temp': 10,
                'impulse_duration': 60,
                'impulse_cycle': 600,
            }
        self.heater_pid = PID(Kp=3.0, Ki=0.02, Kd=200.0,
                              max_age=300,
                              output_limits=[self.heater_cfg['min_power'], 100])

        self.impulse_heating = None
        self.impulse_start = None

        # Command Translation
        self.commands = {'!A': 'Get internal name',
                         '!B': 'Get firmware version',
                         '!C': 'Get values',
                         '!D': 'Get internal errors',
                         '!E': 'Get rain frequency',
                         '!F': 'Get switch status',
                         '!G': 'Set switch open',
                         '!H': 'Set switch closed',
                         'P\d\d\d\d!': 'Set PWM value',
                         '!Q': 'Get PWM value',
                         '!S': 'Get sky IR temperature',
                         '!T': 'Get sensor temperature',
                         '!z': 'Reset RS232 buffer pointers',
                         '!K': 'Get serial number',
                         'v!': 'Query if anemometer enabled',
                         'V!': 'Get wind speed',
                         'M!': 'Get electrical constants',
                         '!Pxxxx': 'Set PWM value to xxxx',
                         }
        self.expects = {'!A': '!N\s+(\w+)!',
                        '!B': '!V\s+([\d\.\-]+)!',
                        '!C': '!6\s+([\d\.\-]+)!4\s+([\d\.\-]+)!5\s+([\d\.\-]+)!',
                        '!D': '!E1\s+([\d\.]+)!E2\s+([\d\.]+)!E3\s+([\d\.]+)!E4\s+([\d\.]+)!',
                        '!E': '!R\s+([\d\.\-]+)!',
                        '!F': '!Y\s+([\d\.\-]+)!',
                        'P\d\d\d\d!': '!Q\s+([\d\.\-]+)!',
                        '!Q': '!Q\s+([\d\.\-]+)!',
                        '!S': '!1\s+([\d\.\-]+)!',
                        '!T': '!2\s+([\d\.\-]+)!',
                        '!K': '!K(\d+)\s*\\x00!',
                        'v!': '!v\s+([\d\.\-]+)!',
                        'V!': '!w\s+([\d\.\-]+)!',
                        'M!': '!M(.{12})',
                        }
        self.delays = {
            '!E': 0.350,
            'P\d\d\d\d!': 0.750,
            'V!': 0.4,
        }

        self._wind_speed_enabled = None
        self.rain_frequency = None

        self.weather_entries = list()

        if self.aag_device:
            # Query Device Name
            result = self.query('!A')
            if result:
                self.name = result[0].strip()
                logger.info(f'Device Name is "{self.name}"')
            else:
                self.name = ''
                logger.warning('  Failed to get Device Name')
                sys.exit(1)

            # Query Firmware Version
            result = self.query('!B')
            if result:
                self.firmware_version = float(result[0].strip())
                logger.info(f'Firmware Version = {self.firmware_version}')
            else:
                self.firmware_version = ''
                logger.warning('  Failed to get Firmware Version')
                sys.exit(1)

            # Query Serial Number if firmware requires.
            if self.firmware_version < 5.6:
                result = self.query('!K')
                if result:
                    self.serial_number = result[0].strip()
                    logger.info(f'Serial Number: {self.serial_number}')
                else:
                    logger.warning('  Failed to get required Serial Number')
                    sys.exit(1)
            else:
                self.serial_number = ''

    def send(self, send, delay=0.100):

        found_command = False
        for cmd in self.commands.keys():
            if re.match(cmd, send):
                logger.debug(f'Sending command: {self.commands[cmd]}')
                found_command = True
                break
        if not found_command:
            logger.warning(f'Unknown command: "{send}"')
            return None

        logger.debug('  Clearing buffer')
        cleared = self.aag_device.read(self.aag_device.ser.in_waiting)
        if len(cleared) > 0:
            logger.debug(f'  Cleared: "{cleared}"')

        self.aag_device.write(send)
        time.sleep(delay)

        result = None
        try:
            response = self.aag_device.read(self.aag_device.ser.in_waiting)
        except UnicodeDecodeError:
            logger.debug("Error reading from serial line")
        else:
            logger.debug(f'Response: "{response}"')
            response_match = re.match(r'(!.*)\\x11\s{12}0', response)
            if response_match:
                result = response_match.group(1)
            else:
                result = response

        return result

    def query(self, send, maxtries=5):
        if send in self.delays.keys():
            logger.debug(f'Waiting delay time of {self.delays[send]:.3f} s')
            delay = self.delays[send]
        else:
            delay = 0.200

        expect = self.expects[send]

        count = 0
        result = None
        while not result and (count <= maxtries):
            count += 1
            result = self.send(send, delay=delay)

            match_expect = re.match(expect, result)
            if not match_expect:
                logger.debug(f'Did not find {expect} in response "{result}"')
                result = None
                time.sleep(self.hibernate)
            else:
                logger.debug(f'Found {expect} in response "{result}"')
                result = match_expect.groups()
        return result

    def get_ambient_temperature(self, n=5):
        """
        Populates the self.ambient_temp property

        Calculation is taken from Rs232_Comms_v100.pdf section "Converting values
        sent by the device to meaningful units" item 5.
        """
        logger.debug('Getting ambient temperature')
        values = []

        for i in range(0, n):
            try:
                value = float(self.query('!T')[0])
                ambient_temp = value / 100.
            except Exception:
                pass
            else:
                logger.debug(f'Ambient Temperature Query = {value:.1f}\t{ambient_temp:.1f}')
                values.append(ambient_temp)

        if len(values) >= n - 1:
            self.ambient_temp = np.median(values) * u.Celsius
            logger.debug(f'Ambient Temperature = {self.ambient_temp:.1f}')
        else:
            self.ambient_temp = None
            logger.debug('  Failed to Read Ambient Temperature')

        return self.ambient_temp

    def get_sky_temperature(self, n=9):
        """
        Populates the self.sky_temp property

        Calculation is taken from Rs232_Comms_v100.pdf section "Converting values
        sent by the device to meaningful units" item 1.

        Does this n times as recommended by the "Communication operational
        recommendations" section in Rs232_Comms_v100.pdf
        """
        logger.debug('Getting sky temperature')
        values = []
        for i in range(0, n):
            try:
                value = float(self.query('!S')[0]) / 100.
            except Exception:
                pass
            else:
                logger.debug(f'Sky Temperature Query = {value:.1f}')
                values.append(value)
        if len(values) >= n - 1:
            self.sky_temp = np.median(values) * u.Celsius
            logger.debug(f'Sky Temperature = {self.sky_temp:.1f}')
        else:
            self.sky_temp = None
            logger.debug('  Failed to Read Sky Temperature')
        return self.sky_temp

    def get_values(self, n=5):
        """
        Populates the self.internal_voltage, self.ldr_resistance, and
        self.rain_sensor_temp properties

        Calculation is taken from Rs232_Comms_v100.pdf section "Converting values
        sent by the device to meaningful units" items 4, 6, 7.
        """
        logger.debug('Getting "values"')
        zener_constant = 3
        ldr_pullup_resistance = 56.
        rain_pull_up_resistance = 1
        rain_res_at25 = 1
        rain_beta = 3450.
        abszero = 273.15
        internal_voltages = []
        ldr_resistances = []
        rain_sensor_temps = []
        for i in range(0, n):
            responses = self.query('!C')
            try:
                internal_voltage = 1023 * zener_constant / float(responses[0])
                internal_voltages.append(internal_voltage)
                ldr_resistance = ldr_pullup_resistance / ((1023. / float(responses[1])) - 1.)
                ldr_resistances.append(ldr_resistance)
                r = np.log((rain_pull_up_resistance /
                            ((1023. / float(responses[2])) - 1.)) / rain_res_at25)
                rain_sensor_temp = 1. / ((r / rain_beta) + (1. / (abszero + 25.))) - abszero
                rain_sensor_temps.append(rain_sensor_temp)
            except Exception:
                pass

        # Median Results
        if len(internal_voltages) >= n - 1:
            self.internal_voltage = np.median(internal_voltages) * u.volt
            logger.debug(f'Internal Voltage = {self.internal_voltage:.2f}')
        else:
            self.internal_voltage = None
            logger.debug('  Failed to read Internal Voltage')

        if len(ldr_resistances) >= n - 1:
            self.ldr_resistance = np.median(ldr_resistances) * u.kohm
            logger.debug(f'LDR Resistance = {self.ldr_resistance:.0f}')
        else:
            self.ldr_resistance = None
            logger.debug('  Failed to read LDR Resistance')

        if len(rain_sensor_temps) >= n - 1:
            self.rain_sensor_temp = np.median(rain_sensor_temps) * u.Celsius
            logger.debug(f'Rain Sensor Temp = {self.rain_sensor_temp:.1f}')
        else:
            self.rain_sensor_temp = None
            logger.debug('  Failed to read Rain Sensor Temp')

        return self.internal_voltage, self.ldr_resistance, self.rain_sensor_temp

    def get_rain_frequency(self, n=5):
        """
        Populates the self.rain_frequency property
        """
        logger.debug('Getting rain frequency')
        values = []
        for i in range(0, n):
            try:
                value = float(self.query('!E')[0])
                logger.debug(f'Rain Freq Query = {value:.1f}')
                values.append(value)
            except Exception:
                pass
        if len(values) >= n - 1:
            self.rain_frequency = np.median(values)
            logger.debug(f'Rain Frequency = {self.rain_frequency:.1f}')
        else:
            self.rain_frequency = None
            logger.debug('  Failed to read Rain Frequency')
        return self.rain_frequency

    def get_PWM(self):
        """
        Populates the self.PWM property.

        Calculation is taken from Rs232_Comms_v100.pdf section "Converting values
        sent by the device to meaningful units" item 3.
        """
        logger.debug('Getting PWM value')
        try:
            value = self.query('!Q')[0]
            self.PWM = float(value) * 100. / 1023.
            logger.debug(f'PWM Value = {self.PWM:.1f}')
        except Exception:
            self.PWM = None
            logger.debug('  Failed to read PWM Value')
        return self.PWM

    def set_pwm(self, percent, ntries=15):
        """
        """
        count = 0
        success = False
        if percent < 0.:
            percent = 0.
        if percent > 100.:
            percent = 100.
        while not success and count <= ntries:
            logger.debug(f'Setting PWM value to {percent:.1f} %')
            send_digital = int(1023. * float(percent) / 100.)
            send_string = f'P{send_digital:04d}!'
            try:
                result = self.query(send_string)
            except Exception:
                result = None
            count += 1
            if result is not None:
                self.PWM = float(result[0]) * 100. / 1023.
                if abs(self.PWM - percent) > 5.0:
                    logger.debug('  Failed to set PWM value!')
                    time.sleep(2)
                else:
                    success = True
                logger.debug(f'PWM Value = {self.PWM:.1f}')

    def get_errors(self):
        """
        Populates the self.IR_errors property
        """
        logger.debug('Getting errors')
        response = self.query('!D')
        if response:
            self.errors = {'error_1': str(int(response[0])),
                           'error_2': str(int(response[1])),
                           'error_3': str(int(response[2])),
                           'error_4': str(int(response[3]))}
            logger.debug("  Internal Errors: {} {} {} {}".format(
                self.errors['error_1'],
                self.errors['error_2'],
                self.errors['error_3'],
                self.errors['error_4'],
            ))

        else:
            self.errors = {'error_1': None,
                           'error_2': None,
                           'error_3': None,
                           'error_4': None}
        return self.errors

    def get_switch(self, maxtries=3):
        """
        Populates the self.switch property

        Unlike other queries, this method has to check if the return matches a
        !X or !Y pattern (indicating open and closed respectively) rather than
        read a value.
        """
        logger.debug('Getting switch status')
        self.switch = None
        tries = 0
        status = None
        while not status:
            tries += 1
            response = self.send('!F')
            if re.match(r'!Y {12}1!', response):
                status = 'OPEN'
            elif re.match(r'!X {12}1!', response):
                status = 'CLOSED'
            else:
                status = None
            if not status and tries >= maxtries:
                status = 'UNKNOWN'
        self.switch = status
        logger.debug(f'Switch Status = {self.switch}')
        return self.switch

    @property
    def wind_speed_enabled(self):
        """
        Method returns true or false depending on whether the device supports
        wind speed measurements.
        """
        if self._wind_speed_enabled is None:
            logger.debug('Checking if wind speed is enabled')
            try:
                enabled = bool(self.query('v!')[0])
                if enabled:
                    logger.debug('  Anemometer enabled')
                    self._wind_speed_enabled = True
                else:
                    logger.debug('  Anemometer not enabled')
                    self._wind_speed_enabled = False
            except Exception as e:
                logger.warning(f'Error checking the wind speed: {e!r}')

        return self._wind_speed_enabled

    def get_wind_speed(self, n=3):
        """
        Populates the self.wind_speed property

        Based on the information in Rs232_Comms_v120.pdf document

        Medians n measurements.  This isn't mentioned specifically by the manual
        but I'm guessing it won't hurt.
        """
        logger.debug('Getting wind speed')
        if self.wind_speed_enabled:
            values = []
            for i in range(0, n):
                result = self.query('V!')
                if result:
                    value = float(result[0])
                    logger.debug(f'Wind Speed Query = {value:.1f}')
                    values.append(value)
            if len(values) >= 3:
                self.wind_speed = np.median(values) * u.km / u.hr
                logger.debug(f'Wind speed = {self.wind_speed:.1f}')
            else:
                self.wind_speed = None
        else:
            self.wind_speed = None
        return self.wind_speed

    def capture(self, **kwargs):
        """Query the CloudWatcher

        Returns:
            dict: Captured data.
        """

        logger.debug("Updating weather")

        data = {
            'weather_sensor_name': self.name,
            'weather_sensor_firmware_version': self.firmware_version,
            'weather_sensor_serial_number': self.serial_number,
            'sky_temp_C': None,
            'ambient_temp_C': None,
            'internal_voltage_V': None,
            'ldr_resistance_Ohm': None,
            'rain_sensor_temp_C': None,
            'rain_frequency': None,
            'pwm_value': None,
            'errors': None,
            'wind_speed_KPH': None,
            'safe': False,
            'date': dt.utcnow(),
            'sky_condition': None,
            'wind_condition': None,
            'gust_condition': None,
            'rain_condition': None,
        }

        if self.get_sky_temperature() is not None:
            data['sky_temp_C'] = self.sky_temp.value
        if self.get_ambient_temperature() is not None:
            data['ambient_temp_C'] = self.ambient_temp.value
        self.get_values()
        if self.internal_voltage is not None:
            data['internal_voltage_V'] = self.internal_voltage.value
        if self.ldr_resistance is not None:
            data['ldr_resistance_Ohm'] = self.ldr_resistance.value
        if self.rain_sensor_temp is not None:
            data['rain_sensor_temp_C'] = round(self.rain_sensor_temp.value, 2)
        if self.get_rain_frequency() is not None:
            data['rain_frequency'] = self.rain_frequency
        if self.get_PWM() is not None:
            data['pwm_value'] = self.PWM
        if self.get_errors() is not None:
            data['errors'] = self.errors
        if self.get_wind_speed() is not None:
            data['wind_speed_KPH'] = self.wind_speed.value

        # Make Safety Decision
        if self.config.get('ignore') is not None:
            self.safe_dict = self.make_safety_decision(data, self.config.get('ignore'))
        else:
            self.safe_dict = self.make_safety_decision(data)

        data['safe'] = self.safe_dict['Safe']
        data['sky_condition'] = self.safe_dict['Sky']
        data['wind_condition'] = self.safe_dict['Wind']
        data['gust_condition'] = self.safe_dict['Gust']
        data['rain_condition'] = self.safe_dict['Rain']

        # If we get over a certain amount of entries, trim the earliest
        # Todo: change this to a streamz
        self.weather_entries.append(data)
        if len(self.weather_entries) > int(self.safety_delay):
            del self.weather_entries[:1]

        self.calculate_and_set_pwm()

        return data

    def get_heater_pwm(self, target, last_entry, scaling=0.5):
        """Get new PWM value based on target and last entry.

        Uses the algorithm described in RainSensorHeaterAlgorithm.pdf to
        determine PWM value.

        Values are for the default read cycle of 10 seconds.
        """
        delta_t = last_entry['rain_sensor_temp_C'] - target
        delta_pwm = 1 * scaling
        if delta_t > 8.:
            delta_pwm = -40 * scaling
        elif delta_t > 4.:
            delta_pwm = -20 * scaling
        elif delta_t > 3.:
            delta_pwm = -10 * scaling
        elif delta_t > 2.:
            delta_pwm = -6 * scaling
        elif delta_t > 1.:
            delta_pwm = -4 * scaling
        elif delta_t > 0.5:
            delta_pwm = -2 * scaling
        elif delta_t > 0.3:
            delta_pwm = -1 * scaling
        elif delta_t < -0.3:
            delta_pwm = 1 * scaling
        elif delta_t < -0.5:
            delta_pwm = 2 * scaling
        elif delta_t < -1.:
            delta_pwm = 4 * scaling
        elif delta_t < -2.:
            delta_pwm = 6 * scaling
        elif delta_t < -3.:
            delta_pwm = 10 * scaling
        elif delta_t < -4.:
            delta_pwm = 20 * scaling
        elif delta_t < -8.:
            delta_pwm = 40 * scaling

        return int(delta_pwm)

    def calculate_and_set_pwm(self):
        """
        Uses the algorithm described in RainSensorHeaterAlgorithm.pdf to decide
        whether to use impulse heating mode, then determines the correct PWM
        value.
        """
        logger.debug('Calculating new PWM Value')
        # Get Last n minutes of rain history
        now = dt.utcnow()

        entries = self.weather_entries

        logger.debug(
            f'{len(entries)} entries in last {int(self.heater_cfg["impulse_cycle"]):d} sec')

        last_entry = self.weather_entries[-1]
        rain_history = [x['rain_safe'] for x in entries if 'rain_safe' in x.keys()]

        if 'ambient_temp_C' not in last_entry and last_entry['ambient_temp_C'] is not None:
            logger.warning('No Ambient Temperature measurement. Can not determine PWM value.')
        elif 'rain_sensor_temp_C' not in last_entry and last_entry[
                'rain_sensor_temp_C'] is not None:
            logger.warning('No Rain Sensor Temperature measurement. Can not determine PWM value.')
        else:
            # Decide whether to use the impulse heating mechanism
            if len(rain_history) > 3 and not np.any(rain_history):
                logger.debug('  Consistent wet/rain in history.  Using impulse heating.')
                if self.impulse_heating:
                    impulse_time = (now - self.impulse_start).total_seconds()
                    if impulse_time > float(self.heater_cfg['impulse_duration']):
                        logger.debug('Impulse heating on for > {:.0f} s. Turning off.', float(
                            self.heater_cfg['impulse_duration']))
                        self.impulse_heating = False
                        self.impulse_start = None
                    else:
                        logger.debug(f'Impulse heating has been on for {impulse_time:.0f} seconds')
                else:
                    logger.debug('  Starting imgitpulse heating sequence.')
                    self.impulse_start = now
                    self.impulse_heating = True
            else:
                logger.debug('  No impulse heating needed.')
                self.impulse_heating = False
                self.impulse_start = None

            # Set PWM Based on Impulse Method or Normal Method
            if self.impulse_heating:
                target_temp = float(last_entry['ambient_temp_C']) + \
                    float(self.heater_cfg['impulse_temp'])
                if last_entry['rain_sensor_temp_C'] < target_temp:
                    logger.debug('  Rain sensor temp < target.  Setting heater to 100 %.')
                    self.set_pwm(100)
                else:
                    new_pwm = self.get_heater_pwm(target_temp, last_entry)
                    logger.debug(f'Rain sensor temp > target.  Setting heater to {new_pwm:d} %.')
                    self.set_pwm(new_pwm)
            else:
                if last_entry['ambient_temp_C'] < self.heater_cfg['low_temp']:
                    delta_t = self.heater_cfg['low_delta']
                elif last_entry['ambient_temp_C'] > self.heater_cfg['high_temp']:
                    delta_t = self.heater_cfg['high_delta']
                else:
                    frac = (last_entry['ambient_temp_C'] - self.heater_cfg['low_temp']) / \
                           (self.heater_cfg['high_temp'] - self.heater_cfg['low_temp'])
                    delta_t = self.heater_cfg['low_delta'] + frac * \
                        (self.heater_cfg['high_delta'] - self.heater_cfg['low_delta'])
                target_temp = last_entry['ambient_temp_C'] + delta_t
                new_pwm = int(self.heater_pid.recalculate(float(last_entry['rain_sensor_temp_C']),
                                                          new_set_point=target_temp))
                logger.debug(f'last PID interval = {self.heater_pid.last_interval:.1f} s')

                actual_temp = float(last_entry['rain_sensor_temp_C'])
                pid_p = self.heater_pid.Kp * self.heater_pid.Pval
                pid_i = self.heater_pid.Ki * self.heater_pid.Ival
                pid_d = self.heater_pid.Kd * self.heater_pid.Dval
                logger.debug(f'{target_temp=:4.1f} {actual_temp=:4.1f} '
                             f'{new_pwm=:3.0f} P={pid_p:+3.0f} I={pid_i:+3.0f} '
                             f'({len(self.heater_pid.history):2d}) D={pid_d:+3.0f}')

                self.set_pwm(new_pwm)

    def make_safety_decision(self, current_values, ignore=None):
        """
        Method makes decision whether conditions are safe or unsafe.

        ignore: list of safety params to ignore. Can be 'rain', 'wind', 'gust' or 'cloud'. If None (default) nothing is ignored.
        """
        logger.debug('Making safety decision')
        logger.debug(f'Found {len(self.weather_entries)} weather entries '
                     f'in last {self.safety_delay:.0f} minutes')

        # Tuple with condition,safety
        cloud = self._get_cloud_safety(current_values)

        try:
            wind, gust = self._get_wind_safety(current_values)
        except Exception as e:
            logger.warning(f'Problem getting wind safety: {e!r}')
            wind = ['N/A', False]
            gust = ['N/A', False]

        rain = self._get_rain_safety(current_values)

        saftey_params = {'cloud': cloud[1], 'wind': wind[1], 'gust': gust[1], 'rain': rain[1]}

        if ignore is not None:
            for weather_to_ignore in listify(ignore):
                ignored_value = safety_params.pop(weather_to_ignore)

                # Warn if ignoring an unsafe value.
                if ignored_value is False:
                    logger.warning(f'Ignored unsafe value: {weather_to_ignore}={ignored_value}')

        # Do final safety check.
        safe = all(safety_params.values())

        logger.debug(f'Weather Safe: {safe}')

        return {'Safe': safe,
                'Sky': cloud[0],
                'Wind': wind[0],
                'Gust': gust[0],
                'Rain': rain[0]}

    def _get_cloud_safety(self, current_values):
        safety_delay = self.safety_delay

        entries = self.weather_entries
        threshold_cloudy = self.config.get('threshold_cloudy', -22.5)
        threshold_very_cloudy = self.config.get('threshold_very_cloudy', -15.)

        sky_diff = [x['sky_temp_C'] - x['ambient_temp_C']
                    for x in entries
                    if ('ambient_temp_C' and 'sky_temp_C') in x.keys()]

        if len(sky_diff) == 0:
            logger.warning('  UNSAFE: no sky temperatures found')
            sky_safe = False
            cloud_condition = 'Unknown'
        else:
            if max(sky_diff) > threshold_cloudy:
                logger.warning(f'UNSAFE: Cloudy in last {safety_delay} min. '
                               f'Max sky diff {max(sky_diff):.1f} C')
                sky_safe = False
            else:
                sky_safe = True

            last_cloud = current_values['sky_temp_C'] - current_values['ambient_temp_C']
            if last_cloud > threshold_very_cloudy:
                cloud_condition = 'Very Cloudy'
            elif last_cloud > threshold_cloudy:
                cloud_condition = 'Cloudy'
            else:
                cloud_condition = 'Clear'
            logger.debug(f'Cloud Condition: {cloud_condition} (Sky-Amb={sky_diff[-1]:.1f} C)')

        return cloud_condition, sky_safe

    def _get_wind_safety(self, current_values):
        safety_delay = self.safety_delay
        entries = self.weather_entries

        end_time = dt.utcnow()

        threshold_windy = self.config.get('threshold_windy', 20.)
        threshold_very_windy = self.config.get('threshold_very_windy', 30)

        threshold_gusty = self.config.get('threshold_gusty', 40.)
        threshold_very_gusty = self.config.get('threshold_very_gusty', 50.)

        # Wind (average and gusts)
        wind_speed = [x['wind_speed_KPH']
                      for x in entries
                      if 'wind_speed_KPH' in x.keys()]

        if len(wind_speed) == 0:
            logger.debug('  UNSAFE: no wind speed readings found')
            wind_safe = False
            gust_safe = False
            wind_condition = 'Unknown'
            gust_condition = 'Unknown'
        else:
            start_time = entries[0]['date']
            # if type(start_time) == str:
            #    start_time = date_parser(entries[0]['date'])

            typical_data_interval = (end_time - start_time).total_seconds() / len(entries)

            mavg_count = int(np.ceil(120. / typical_data_interval))  # What is this 120?
            wind_mavg = movingaverage(wind_speed, mavg_count)

            # Windy?
            if max(wind_mavg) > threshold_very_windy:
                logger.debug(f'UNSAFE:  Very windy in last {safety_delay:.0f} min. '
                             f'Max wind speed {max(wind_mavg):.1f} kph')
                wind_safe = False
            else:
                wind_safe = True

            if wind_mavg[-1] > threshold_very_windy:
                wind_condition = 'Very Windy'
            elif wind_mavg[-1] > threshold_windy:
                wind_condition = 'Windy'
            else:
                wind_condition = 'Calm'
            logger.debug(f'Wind Condition: {wind_condition} ({wind_mavg[-1]:.1f} km/h)')

            # Gusty?
            if max(wind_speed) > threshold_very_gusty:
                logger.debug(f'UNSAFE:  Very gusty in last {safety_delay:.0f} min. '
                             f'Max gust speed {max(wind_speed):.1f} kph')
                gust_safe = False
            else:
                gust_safe = True

            current_wind = current_values.get('wind_speed_KPH', 0.0)
            if current_wind > threshold_very_gusty:
                gust_condition = 'Very Gusty'
            elif current_wind > threshold_gusty:
                gust_condition = 'Gusty'
            else:
                gust_condition = 'Calm'

            logger.debug(f'Gust Condition: {gust_condition} ({wind_speed[-1]:.1f} km/h)')

        return (wind_condition, wind_safe), (gust_condition, gust_safe)

    def _get_rain_safety(self, current_values):
        safety_delay = self.safety_delay
        entries = self.weather_entries
        threshold_wet = self.config.get('threshold_wet', 2000.)
        threshold_rain = self.config.get('threshold_rainy', 1700.)

        # Rain
        rf_value = [x['rain_frequency'] for x in entries if 'rain_frequency' in x.keys()]

        if len(rf_value) == 0:
            rain_safe = False
            rain_condition = 'Unknown'
        else:
            # Check current values
            if current_values['rain_frequency'] <= threshold_rain:
                rain_condition = 'Rain'
                rain_safe = False
            elif current_values['rain_frequency'] <= threshold_wet:
                rain_condition = 'Wet'
                rain_safe = False
            else:
                rain_condition = 'Dry'
                rain_safe = True

            # If safe now, check last 15 minutes
            if rain_safe:
                if min(rf_value) <= threshold_rain:
                    logger.debug(f'UNSAFE:  Rain in last {safety_delay:.0f} min.')
                    rain_safe = False
                elif min(rf_value) <= threshold_wet:
                    logger.debug(f'UNSAFE:  Wet in last {safety_delay:.0f} min.')
                    rain_safe = False
                else:
                    rain_safe = True

            logger.debug(f'Rain Condition: {rain_condition}')

        return rain_condition, rain_safe
