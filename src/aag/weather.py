import re
import time
from datetime import datetime,timezone
import math # 导入 math 模块

import serial
from collections.abc import Callable
from collections import deque
from contextlib import suppress

from astropy import units as u
from rich import print

from aag.commands import WeatherCommand, WeatherResponseCodes
from aag.settings import WeatherSettings, WhichUnits, Thresholds,Location


class CloudSensor(object):
    def __init__(self, connect: bool = True, **kwargs):
        """ A class to read the cloud sensor.

        Args:
            connect: Whether to connect to the sensor on init.
            **kwargs: Keyword arguments for the WeatherSettings class.
        """
        self.config = WeatherSettings(**kwargs)
        self._verbose_logging = self.config.verbose_logging  # 从配置获取详细日志开关

        try:
            self._sensor: serial.Serial = serial.serial_for_url(self.config.serial_port,
                                                                baudrate=9600,
                                                                timeout=1,
                                                                do_not_open=True
                                                                )
            if connect:
                if not self._sensor.is_open:
                    self._sensor.open()
                # 根据文档 v1.30 (pocketCW支持)，打开端口后可以稍作延时
                time.sleep(getattr(self.config, 'serial_port_open_delay_seconds', 2))    
                self._sensor.reset_input_buffer()
                self._sensor.reset_output_buffer()

        except serial.serialutil.SerialException as e:
            print(f'[red]Unable to connect to weather sensor. Check the port. {e}')
            raise e

        self.handshake_block_content = chr(0x11) + (' ' * 12) + '0'
        self._sensor.read_until_terminator = self.handshake_block_content.encode()


        self.handshake_block = r'\x11\s{12}0'
        #self.handshake_block = r'^\x11\s*0?\s*$'

        # Set up a queue for readings
        self.readings = deque(maxlen=self.config.num_readings)

        self.name: str = 'CloudWatcher'
        self.firmware: str | None = None
        self.serial_number: str | None = None
        self.has_anemometer: bool = False
        self.has_heater: bool = False #有没有加热器

        self._is_connected: bool = False

        if connect:
            self._is_connected = self.connect()

    @property
    def is_connected(self) -> bool:
        """ Is the sensor connected?"""
        return self._is_connected

    @property
    def location(self) -> Location:
        """location """
        return self.config.location

    @property
    def thresholds(self) -> Thresholds:
        """Thresholds for the safety checks."""
        return self.config.thresholds

    @property
    def status(self) -> dict:
        """Returns the most recent reading and safety value."""
        if not self.readings:
            if self._verbose_logging: print("[yellow]警告: 尚无读数可获取状态。")
            return {} 
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
            if not self._sensor.is_open:
                self._sensor.open()
                time.sleep(getattr(self.config, 'serial_port_open_delay_seconds', 2))
            
            self._sensor.reset_input_buffer()
            self._sensor.reset_output_buffer()

            # 初始化并获取静态值。
            name_resp = self.query(WeatherCommand.GET_INTERNAL_NAME, parse_type=str)
            self.name = name_resp if isinstance(name_resp, str) else 'CloudWatcher'
            
            firmware_resp = self.query(WeatherCommand.GET_FIRMWARE, parse_type=str)

            match = re.search(r"(\d+\.\d+)", firmware_resp)
            if match:
                version_number = match.group(1)  # group(1) 获取第一个捕获组的内容
                self.firmware = version_number 
                self._verbose_logging: print(f"提取到的版本号是: {version_number}")
            else:
                self._verbose_logging: print("未能找到版本号")            
            
            sn_resp = self.query(WeatherCommand.GET_SERIAL_NUMBER, parse_type=str,return_codes = True)
            self.serial_number = sn_resp[1:5] if isinstance(sn_resp, str) and len(sn_resp) >=4 else None  # !Kxxxx

            # 检查是否有风速计
            # AAG 'v!' command tells if anemometer is present.
            # query should return True/False for CAN_GET_WINDSPEED
            can_get_wind = self.query(WeatherCommand.CAN_GET_WINDSPEED, parse_type=str) # 'v!' returns '!v Y' or '!v N'
            self.has_anemometer = True if isinstance(can_get_wind, str) and 'Y' in can_get_wind.upper() else False

            self.has_heater = self.config.have_heater  #如果没有加热器，就不用处理PWM了。

            # 启动时将PWM设置为最小值。
            self.set_pwm(self.config.heater.min_power)

            self._is_connected = True
        except Exception as e:
            if self._verbose_logging: print(f'[red]连接天气传感器失败。检查端口。 {e}')
            if raise_exceptions:
                raise e
            self._is_connected = False
        return self._is_connected

    def capture(self, callback: Callable | None = None, units: WhichUnits = 'none', verbose: bool = False) -> None:
        """连续捕获读数。"""
        current_verbose = verbose or self._verbose_logging
        try:
            while True:
                if not self.is_connected:
                    if current_verbose: print("[yellow]传感器未连接，尝试重新连接...")
                    if not self.connect(raise_exceptions=False):
                        if current_verbose: print("[red]重新连接失败，等待后重试...")
                        time.sleep(self.config.capture_delay * 2) # 连接失败时等待更长时间
                        continue
                    if current_verbose: print("[green]传感器重新连接成功。")

                reading = self.get_reading(units=units, verbose=current_verbose) # 将verbose传递下去

                if callback is not None:
                    callback(reading)

                time.sleep(self.config.capture_delay)
        except KeyboardInterrupt:
            if current_verbose: print("\n[yellow]捕获已由用户中断。")
            pass
        except Exception as e:
            if current_verbose: print(f"[red]在捕获循环中发生错误: {e}")

    def get_reading(self, units: WhichUnits = 'none', get_errors: bool = False, avg_times: int = 1, verbose: bool = False) -> dict: # avg_times 默认改为1，与server.py一致
        """ Get a single reading of all values.

        Args:
            units: The astropy units to return the reading in, default 'none',
                can be 'metric' or 'imperial'.
            get_errors: Whether to get the internal errors, default False.
            avg_times: The number of times to average the readings, default 3.

        Returns:
            A dictionary of readings.
        """
        # 决定实际使用的 verbose 级别
        current_verbose = verbose or self._verbose_logging
        
        def avg_readings(fn_to_avg: Callable, n: int = avg_times, skip_avg: bool = False) -> float | int | None:
            if skip_avg or n <= 1: # 如果n为1或skip_avg为True，则只读取一次
                val = fn_to_avg()
                if val is not None:
                    try:
                        return round(float(val), 3)
                    except (ValueError, TypeError):
                        if current_verbose: print(f"[yellow]警告: {fn_to_avg.__name__} 的单次读取值无法转换为浮点数: {val!r}")
                        return None
                return None

            values = []
            for _ in range(n):
                val = fn_to_avg()
                if val is not None:
                    try:
                        values.append(float(val))
                    except (ValueError, TypeError):
                        if current_verbose: print(f"[yellow]警告: {fn_to_avg.__name__} 的平均过程中遇到非数字值: {val!r}")
                elif current_verbose:
                     print(f"[grey]调试: avg_readings 从 {fn_to_avg.__name__} 获得了 None")

            if not values:
                if current_verbose: print(f"[yellow]警告: {fn_to_avg.__name__} 的所有 {n} 次读数均无效或为 None。")
                return None
            return round(sum(values) / len(values), 3)

        def avg_times(fn, n=avg_times):
            return round(sum(fn() for _ in range(n)) / n, 3)

        # 首先获取 "C!" 命令返回的所有值
        # 这很重要，因为其他计算可能依赖这些值，或者新的传感器数据在这里
        c_command_data = self.get_rain_sensor_values() # <--- 在这里调用   

        reading = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'sky_temp': avg_readings(self.get_sky_temperature),
            'wind_speed': avg_readings(lambda: self.get_wind_speed(skip_averaging=True)), # 使用 lambda
            'rain_frequency': avg_readings(self.get_rain_frequency),
            'humidity':avg_readings(self.get_humidity),
            'pressure':avg_readings(self.get_pressure),
            'RH_sensor_temp':avg_readings(self.get_rh_sensor_temp), # 使用 get_rh_sensor_temp
            'pressure_temp':avg_readings(self.get_pressure_temp),
            "switch":self.get_switch_status_custom(),
            'pwm': self.get_pwm(),
        }

        # 环境温度直接取RH传感器温度  根据文档，RH温度传感器更加准确。
        if reading.get('RH_sensor_temp') is not None:
            reading['ambient_temp'] = reading['RH_sensor_temp']
        else: # 如果RH_sensor_temp为None，尝试使用旧的get_ambient_temperature (IR sensor temp)
            reading['ambient_temp'] = avg_readings(self.get_ambient_temperature) # IR sensor temp
            reading['RH_sensor_temp'] = reading['ambient_temp'] 
            if current_verbose: print("[yellow]警告: RH_sensor_temp 不可用，ambient_temp 使用 IR 传感器温度作为备用。")

        # 从 c_command_data 提取原始值，使用 get_values_raw (它处理None并返回哨兵值)
        # get_values_raw 的第二个参数期望是 WeatherResponseCodes 枚举成员
        #亮度传感器高精度 原始值
        reading['light_sensor_period_raw'] = self.get_values_raw(c_command_data, WeatherResponseCodes.GET_VALUES_LIGHT_SENSOR, verbose=current_verbose)
        #环境温度传感器 NTC 电压值（Ambient Temp NTC) 0-1023
        reading['ambient_temp_ntc_raw'] = self.get_values_raw(c_command_data, WeatherResponseCodes.GET_VALUES_AMBIENT, verbose=current_verbose)
        #LDR环境亮度 0-1023
        reading['ambient_ldr_voltage_raw'] = self.get_values_raw(c_command_data, WeatherResponseCodes.GET_VALUES_LDR_VOLTAGE, verbose=current_verbose) # 已修正
        #Zener Voltage reference 齐纳电压 0-1023
        reading['zener_voltage_raw'] = self.get_values_raw(c_command_data, WeatherResponseCodes.GET_VALUES_ZENER_VOLTAGE, verbose=current_verbose)
        #雨量传感器 电压值
        reading['rain_sensor_temp_ntc_raw'] = self.get_values_raw(c_command_data, WeatherResponseCodes.GET_VALUES_SENSOR_TEMP, verbose=current_verbose)


        # 取相对气压
        # 先获取依赖值
        current_pressure_val = reading['pressure']
        pressure_temp_val = reading['pressure_temp']
        # 然后传递这些值来计算 pres_pressure ,是根据 实际气压 和温度 计算的，不需要再算平均值了
        if current_pressure_val is not None and pressure_temp_val is not None:
            try:
                reading['pres_pressure'] = round(self.get_pres_pressure(current_pressure_val, pressure_temp_val, verbose=current_verbose), 3)
            except Exception as e:
                if current_verbose: print(f"[yellow]计算相对气压时出错: {e}")
                reading['pres_pressure'] = None
        else:
            reading['pres_pressure'] = current_pressure_val
            if current_verbose: print("[yellow]跳过相对气压计算：绝对气压或其温度为 None。")


        # 计算露点
        ambient_temp_for_dew = reading['ambient_temp'] # 使用最佳的环境温度源,用湿度传感器温度计替代，手册上说更加准确
        humidity_for_dew = reading['humidity']
        if ambient_temp_for_dew is not None and humidity_for_dew is not None:
            try:
                T = float(ambient_temp_for_dew)
                RH = float(humidity_for_dew)
                if RH <= 0 or RH > 150: 
                    if current_verbose: print(f"[yellow]跳过露点计算：湿度值 ({RH}%) 无效。")
                    reading['dew_point'] = None
                else:
                    RH_actual = min(RH, 100.0) # 将湿度限制在100%以内进行计算
                    # 使用 Magnus-Tetens 公式 (适用于水面和冰面)
                    # 参数来源: Alduchov, O.A. and Eskridge, R.E., 1996:
                    # Improved Magnus form approximation of saturation vapor pressure. Journal of Applied Meteorology, 35(4), pp.601-609.
                    # (公式适用于水面 T > 0°C, 过冷水 T < 0°C)
                    # 对于冰面 (T < 0°C)，有不同的参数，但AAG通常用于液态水环境
                    A = 17.625 # (有些文献用17.27或17.62)
                    B = 243.04 # (有些文献用237.7或243.12)

                    alpha = math.log(RH_actual / 100.0) + (A * T) / (B + T)
                    dew_point_val = (B * alpha) / (A - alpha)
                    reading['dew_point'] = round(dew_point_val, 3)
            except (ValueError, TypeError, ZeroDivisionError, OverflowError) as e:
                if current_verbose: print(f"[yellow]警告：计算露点时出错: {e}")
                reading['dew_point'] = None
        else:
            reading['dew_point'] = None
            if current_verbose: print("[yellow]跳过露点计算：环境温度或湿度为 None。")
    

        # 添加 MPSAS 天空质量
        raw_period_for_mpsas = reading.get('light_sensor_period_raw') 
        # 确保 raw_period_for_mpsas 不是哨兵值 -99
        if raw_period_for_mpsas == -99: raw_period_for_mpsas = None

        ambient_temp_for_mpsas = reading['ambient_temp'] 
        reading['sky_quality_mpsas'] = None 

        if raw_period_for_mpsas is not None and ambient_temp_for_mpsas is not None:
            try:
                reading['sky_quality_mpsas'] = self._calculate_mpsas(raw_period_for_mpsas, ambient_temp_for_mpsas)
            except Exception as e:
                 if current_verbose: print(f"[red]计算 MPSAS 时发生错误: {e}")
        elif raw_period_for_mpsas is not None and current_verbose: 
             print("[yellow]MPSAS 计算跳过：环境温度为 None，但原始周期值可用。")
        elif current_verbose: 
            print("[grey]MPSAS 计算跳过：原始周期值或环境温度为 None。")


        if get_errors:
            errors_list = self.get_errors()
            if errors_list is not None and isinstance(errors_list, list) :
                reading.update(**{f'error_{i:02d}': err for i, err in enumerate(errors_list)})
            elif errors_list is not None: 
                reading['error_00'] = errors_list

        # Add the safety values.
        reading = self.get_safe_reading(reading)

        # Add astropy units if requested.
        if units != 'none':
            metric_fields_units = {
                'ambient_temp': u.Celsius, 'sky_temp': u.Celsius,
                'RH_sensor_temp': u.Celsius, 'pressure_temp': u.Celsius,
                'dew_point': u.Celsius,
                'wind_speed': u.m / u.s,
                'pwm': u.percent,
                'pressure': u.Pa, 
                'pres_pressure': u.Pa 
            }
            for field, unit in metric_fields_units.items():
                if reading.get(field) is not None and reading.get(field) != -99: # 不为哨兵值才加单位
                    try:
                        reading[field] = float(reading[field]) * unit
                    except (ValueError, TypeError):
                        if current_verbose: print(f"[yellow]警告：无法为字段 '{field}' 应用单位，值：{reading.get(field)!r}")

            if units == 'imperial':
                with suppress(AttributeError, ValueError, TypeError): 
                    if reading.get('ambient_temp') is not None and isinstance(reading['ambient_temp'], u.Quantity): 
                        reading['ambient_temp'] = reading['ambient_temp'].to(u.imperial.deg_F, equivalencies=u.temperature())
                    if reading.get('sky_temp') is not None and isinstance(reading['sky_temp'], u.Quantity): 
                        reading['sky_temp'] = reading['sky_temp'].to(u.imperial.deg_F, equivalencies=u.temperature())
                    if reading.get('RH_sensor_temp') is not None and isinstance(reading['RH_sensor_temp'], u.Quantity): 
                        reading['RH_sensor_temp'] = reading['RH_sensor_temp'].to(u.imperial.deg_F, equivalencies=u.temperature())
                    if reading.get('pressure_temp') is not None and isinstance(reading['pressure_temp'], u.Quantity): 
                        reading['pressure_temp'] = reading['pressure_temp'].to(u.imperial.deg_F, equivalencies=u.temperature())
                    if reading.get('dew_point') is not None and isinstance(reading['dew_point'], u.Quantity): 
                        reading['dew_point'] = reading['dew_point'].to(u.imperial.deg_F, equivalencies=u.temperature())
                    if reading.get('wind_speed') is not None and isinstance(reading['wind_speed'], u.Quantity): 
                        reading['wind_speed'] = reading['wind_speed'].to(u.imperial.mile / u.hour)
                    if reading.get('pressure') is not None and isinstance(reading['pressure'], u.Quantity): 
                        reading['pressure'] = reading['pressure'].to(u.imperial.in_Hg)
                    if reading.get('pres_pressure') is not None and isinstance(reading['pres_pressure'], u.Quantity): 
                        reading['pres_pressure'] = reading['pres_pressure'].to(u.imperial.in_Hg)

        final_reading = {}
        for key, value in reading.items():
            if isinstance(value, u.Quantity):
                final_reading[key] = value.value 
            else:
                final_reading[key] = value
        
        self.readings.append(final_reading) 
        return final_reading

    def get_safe_reading(self, reading: dict) -> dict:
        """ Checks the reading against the thresholds.

        Args:
            reading: The reading to check.

        Returns:
            The reading with the safety values added.
        """
        # 云况判断
        reading['cloud_condition'] = 'unknown'
        if reading.get('sky_temp') is not None and reading.get('ambient_temp') is not None:
            try:
                temp_diff = float(reading['sky_temp']) - float(reading['ambient_temp'])
                if temp_diff >= self.thresholds.very_cloudy: # very_cloudy 通常是小的负数或接近0
                    reading['cloud_condition'] = 'very cloudy'
                elif temp_diff >= self.thresholds.cloudy: # cloudy 是比 very_cloudy 更负的数
                    reading['cloud_condition'] = 'cloudy'
                else: # temp_diff 远小于0，表示晴朗
                    reading['cloud_condition'] = 'clear'
            except (ValueError, TypeError):
                print("[yellow]警告: 计算温差时 sky_temp 或 ambient_temp 无效。")
                reading['cloud_condition'] = 'unknown'
        else:
            reading['cloud_condition'] = 'unknown'


        # 风况判断
        reading['wind_condition'] = 'unknown'
        wind_speed_val = reading.get('wind_speed')
        if wind_speed_val is not None:
            try:
                ws = float(wind_speed_val)
                # 注意阈值顺序，从最强风开始判断
                if ws >= self.thresholds.very_gusty: # 假设这是最高风速阈值
                    reading['wind_condition'] = 'very gusty'
                elif ws >= self.thresholds.gusty:
                    reading['wind_condition'] = 'gusty'
                elif ws >= self.thresholds.very_windy:
                    reading['wind_condition'] = 'very windy'
                elif ws >= self.thresholds.windy:
                    reading['wind_condition'] = 'windy'
                else:
                    reading['wind_condition'] = 'calm'
            except (ValueError, TypeError):
                print("[yellow]警告: 风速值无效。")
                reading['wind_condition'] = 'unknown'
        else:
            reading['wind_condition'] = 'unknown'



        # 雨况判断
        reading['rain_condition'] = 'unknown'
        rain_freq_val = reading.get('rain_frequency')
        if rain_freq_val is not None:
            try:
                rf = float(rain_freq_val)
                if rf <= self.thresholds.rainy: # 频率越低越湿/雨
                    reading['rain_condition'] = 'rainy'
                elif rf <= self.thresholds.wet:
                    reading['rain_condition'] = 'wet'
                else:
                    reading['rain_condition'] = 'dry'
            except (ValueError, TypeError):
                print("[yellow]警告: 雨水频率值无效。")
                reading['rain_condition'] = 'unknown'
        else:
            reading['rain_condition'] = 'unknown'

       # 安全标志
        # 确保在所有条件都已知的情况下才判断安全
        cloud_cond = reading['cloud_condition']
        wind_cond = reading['wind_condition']
        rain_cond = reading['rain_condition']


        reading['cloud_safe'] = True if cloud_cond == 'clear' else False
        reading['wind_safe'] = True if wind_cond == 'calm' else False # 或者根据配置允许一定的风速
        reading['rain_safe'] = True if rain_cond == 'dry' else False

        # 如果任何一个条件是 'unknown'，则整体不安全
        if 'unknown' in [cloud_cond, wind_cond, rain_cond]:
            reading['is_safe'] = False
        else:
            reading['is_safe'] = reading['cloud_safe'] and reading['wind_safe'] and reading['rain_safe']

        # 根据配置中的 ignore_unsafe 列表覆盖安全判断
        if self.config.ignore_unsafe:
            original_is_safe = reading['is_safe']
            temp_cloud_safe = reading['cloud_safe']
            temp_wind_safe = reading['wind_safe']
            temp_rain_safe = reading['rain_safe']

            if 'cloud' in self.config.ignore_unsafe: temp_cloud_safe = True
            if 'wind' in self.config.ignore_unsafe: temp_wind_safe = True
            if 'rain' in self.config.ignore_unsafe: temp_rain_safe = True
            
            # 只有在所有未被忽略的条件都安全时，才认为是安全的
            # 并且，如果原始是安全的，那么忽略不应该使其变得不安全
            # 如果原始是不安全的，忽略某些条件可能使其变为安全
            if original_is_safe: # 如果本来就安全，忽略不会改变
                 reading['is_safe'] = True
            else: # 如果本来不安全，看忽略后是否安全
                 reading['is_safe'] = temp_cloud_safe and temp_wind_safe and temp_rain_safe

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

    def _calculate_mpsas(self, raw_period: int | None, ambient_temp_celsius: float | None) -> float | None:
        """根据原始周期和环境温度计算 MPSAS。

        Args:
            raw_period: 新光传感器的原始周期值。
            ambient_temp_celsius: 用于校正的环境温度（摄氏度）。

        Returns:
            计算出的 MPSAS 值，或在无法计算时为 None。
        """
        if raw_period is None or raw_period <= 0:
            # print("[yellow]MPSAS 计算跳过：无效或缺失的原始周期值。") # 可选的详细日志
            return None
        if ambient_temp_celsius is None:
            # print("[yellow]MPSAS 计算跳过：环境温度不可用，无法进行校正。") # 可选的详细日志
            return None

        try:
            # 公式来自 Rs232_Comms_v140.pdf 第2页
            # sq_reference 可以从配置中获取，如果未配置则使用默认值 19.6
            sq_reference = self.config.sq_reference

            period_val = float(raw_period) # 确保是浮点数进行除法

            # 检查除数是否为零或负数，避免 math.log10 域错误
            term_for_log = 250000.0 / period_val
            if term_for_log <= 0:
                if self._verbose_logging: print(f"[yellow]警告：MPSAS 计算中 log10 的参数 ({term_for_log:.3f}) 无效。")
                return None

            mpsas = sq_reference - (2.5 * math.log10(term_for_log))

            # Rs232_Comms_v140.pdf 第2页的温度校正公式
            mpsas_corrected = (mpsas - 0.042) + (0.00212 * float(ambient_temp_celsius))

            return round(mpsas_corrected, 3) # 保留三位小数
        except (ValueError, TypeError, OverflowError, ZeroDivisionError, AttributeError) as e:
            if self._verbose_logging: print(f"[red]计算 MPSAS 时出错: {e}")
            return None



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
    
    def get_humidity(self) -> float:
        """Gets the latest relative humidity reading (in %).

        Returns:
            The humidity in %.
        """
        return round((self.query(WeatherCommand.GET_HUMIDITY) * 125.0 / 65536.0 ) -6.0 ,3)
    
    def get_pressure(self) -> float:
        """Gets the latest Absolute pressure in Pa reading.

        Returns:
            The Absolute pressure in Pa.
        """
        return round(self.query(WeatherCommand.GET_PRESSURE) / 16.0 ,3)


    def get_pres_pressure(self, current_absolute_pressure: float | None, 
                          pressure_sensor_temp_c: float | None, 
                          verbose: bool = False) -> float | None:
        """
        根据绝对气压、传感器温度和海拔计算相对（海平面）气压。
        公式参考 Rs232_Comms_v130.pdf。
        如果无法正确计算，则返回传入的绝对气压值。

        Args:
            current_absolute_pressure: 当前站点绝对气压 (单位: 帕斯卡, Pa)。
            pressure_sensor_temp_c: 大气压传感器的温度 (单位: 摄氏度, °C)。
            verbose: 是否打印详细的调试或警告信息。

        Returns:
            计算出的海平面气压 (单位: 帕斯卡, Pa)，或在无法计算时返回传入的绝对气压值
            (如果绝对气压本身无效，则返回 None)。
        """
        # 检查主要输入 current_absolute_pressure
        if current_absolute_pressure is None:
            if verbose: print("[yellow]获取海平面气压警告: 当前绝对气压为 None。将返回 None。")
            return None # 如果绝对气压就是None，无法返回它作为备用

        # 尝试将 current_absolute_pressure 转换为浮点数，后续备用返回时使用这个转换后的值
        try:
            abs_pres_pa = float(current_absolute_pressure)
        except (ValueError, TypeError) as e:
            if verbose: print(f"[red]获取海平面气压错误: 输入的绝对气压 '{current_absolute_pressure}' 类型无效: {e}。将返回 None。")
            return None # 如果绝对气压无法转换为浮点数，则无法作为备用返回

        # 检查其他必要的输入
        if pressure_sensor_temp_c is None:
            if verbose: print("[yellow]获取海平面气压警告: 气压传感器温度为 None。将返回绝对气压。")
            return abs_pres_pa # 返回已验证的绝对气压
        if self.location is None or self.location.elevation is None:
            if verbose: print("[yellow]获取海平面气压警告: 位置或海拔信息未配置。将返回绝对气压。")
            return abs_pres_pa # 返回已验证的绝对气压

        try:
            # temp_c 和 hasl_m 的转换也需要错误处理
            temp_c = float(pressure_sensor_temp_c)
            if isinstance(self.location.elevation, u.Quantity):
                hasl_m = self.location.elevation.to_value(u.m)
            else: 
                hasl_m = float(self.location.elevation)
        except (ValueError, TypeError, AttributeError) as e: # 添加 AttributeError 以防 location 无 elevation
            if verbose: print(f"[red]获取海平面气压错误: 温度或海拔参数类型无效: {e}。将返回绝对气压。")
            return abs_pres_pa # 返回已验证的绝对气压
        
        # --- 开始计算 ---
        # denominator_term_in_formula = temp_c + (0.0065 * hasl_m) + 273.15 # 这是 Rs232_Comms_v130.pdf 中的形式
        # 使用更标准的国际气压高度公式中的温度项 T0' = T_station_kelvin / (1 - L*h/T_station_kelvin) 形式的变体
        # 或者直接使用文档中的分母： T_celsius_at_station + L_rate * altitude_meters + Kelvin_offset
        
        # 公式中的分母项: Temp_C_at_station + 0.0065 * HASL_meters + 273.15 
        denominator_term_in_formula = temp_c + (0.0065 * hasl_m) + 273.15

        if abs(denominator_term_in_formula) < 1e-9: # 避免除以零
            if verbose: print("[yellow]获取海平面气压警告: 计算中分母接近零。将返回绝对气压。")
            return abs_pres_pa # 返回已验证的绝对气压
        
        # base = 1.0 - ( ( lapse_rate * altitude_meters ) / sea_level_reference_temp_kelvin )
        # 这里 L*h / T0' 中的 T0' 是 denominator_term_in_formula
        base = 1.0 - (0.0065 * hasl_m / denominator_term_in_formula)
        
        if base <= 0: # 开负数或零的非整数次方会导致错误
            if verbose: print(f"[yellow]获取海平面气压警告: 计算中 base ({base:.4f}) 无效（小于或等于零）。将返回绝对气压。")
            return abs_pres_pa # 返回已验证的绝对气压
            
        try:
            # 指数 -5.275 (来自AAG文档，近似于标准大气公式中的 -g*M/(R*L))
            relative_pressure_pa = round(abs_pres_pa * (base ** (-5.275)), 3)
            return relative_pressure_pa # 成功计算，返回相对气压
        except (ValueError, OverflowError) as e: # 数学运算错误
            if verbose: print(f"[red]计算海平面气压时发生数学错误: {e}。将返回绝对气压。")
            return abs_pres_pa # 返回已验证的绝对气压
    
    def get_values_raw(self, sensor_data_dict: dict, key_to_extract: WeatherResponseCodes, verbose: bool = False) -> int:
        """
        从包含传感器值的字典中提取指定键的值，并尝试将其转换为整数。
        这个方法假设 sensor_data_dict 中的值如果存在，应该是可以直接转换为整数的，
        或者是已经是数字类型。

        Args:
            sensor_data_dict: 一个字典，通常是 get_rain_sensor_values() 方法的返回值。
                              其键可能是 WeatherResponseCodes 枚举成员的名称 (字符串)
                              或枚举成员本身 (取决于 get_rain_sensor_values 的实现)。
            key_to_extract:   要从 sensor_data_dict 中提取的键 (字符串或枚举成员)。
            verbose:          是否打印调试/警告信息 (可选)。

        Returns:
            对应的整数值。如果键未找到、值本身为 None、或值无法转换为有效整数数，
            则返回 -99.0 作为哨兵值。
        """
        VALUE_ERROR_SENTINEL = -99 
        if not isinstance(sensor_data_dict, dict):
            if verbose: print(f"[yellow]警告: 传入 get_values_raw 的参数 sensor_data_dict 不是一个字典。")
            return VALUE_ERROR_SENTINEL
        
        extracted_value = sensor_data_dict.get(key_to_extract) # key_to_extract 是枚举成员

        if extracted_value is not None:
            try:
                return int(extracted_value)
            except (ValueError, TypeError) as e:
                if verbose: print(f"[yellow]警告: 键 '{key_to_extract.name}' 对应的值 '{extracted_value}' 无法转换为有效的整数: {e}")
                return VALUE_ERROR_SENTINEL
        else:
            if verbose: print(f"[grey]调试: 在传入的字典中未找到键 '{key_to_extract.name}' 或其值为 None。")
            return VALUE_ERROR_SENTINEL

    def get_rh_sensor_temp(self) -> float:
        """Gets the latest HR sensor temperature reading.

        Returns:
            The HR sensor temprature  in Celsius.
        """
        return (self.query(WeatherCommand.GET_RH_SENSOR_TEMP) * 172.72 / 65536.0 ) - 46.85

    def get_pressure_temp(self) -> float:
        """Gets the latest pressure sensor temperature reading.

        Returns:
            The pressure sensor temprature  in Celsius.
        """
        return self.query(WeatherCommand.GET_PRESSURE_TEMP) / 100.00

    def get_rain_sensor_values(self) -> dict: # 返回类型现在是 Dict[WeatherResponseCodes, int | None] 或类似
        """
        获取最新的传感器原始值 (来自 'C!' 命令)。
        解析 "C!" 命令返回的多个数据块，并根据块标识符进行区分。

        Returns:
            一个包含已解析传感器原始值的字典，键是 WeatherResponseCodes 枚举成员本身，
            值为对应的整数值。例如：
            {
                WeatherResponseCodes.GET_VALUES_ZENER_VOLTAGE: 957, 
                WeatherResponseCodes.GET_VALUES_AMBIENT: 647,
                # ...
            }
            如果出错或未收到有效数据块，则相关键可能缺失或值为 None。
        """
        block_contents = self.query(WeatherCommand.GET_VALUES, return_codes=True) # 返回 "XXyyyyyyyyyyyy" 字符串的列表

        parsed_values = {} # 初始化为空字典
        if not block_contents or not isinstance(block_contents, list):
            print("[yellow]警告：未从 GET_VALUES (C!) 命令收到数据块。")
            return parsed_values

        # 创建一个从块标识符字符串 (例如 "6 ") 到相应 WeatherResponseCodes 枚举成员的映射
        # 这有助于我们从字符串标识符反向查找到枚举成员用作键
        identifier_to_enum_member_map = {
            code.value: code for code in WeatherResponseCodes 
            if code.name.startswith("GET_VALUES_") # 只包含与 "C!" 命令相关的代码
        }
        # 例如, identifier_to_enum_member_map['6 '] 会是 WeatherResponseCodes.GET_VALUES_ZENER_VOLTAGE

        for content in block_contents:  # content 的格式是 "XXyyyyyyyyyyyy"
            if len(content) != 14:
                print(f"[yellow]警告: 无效的数据块内容长度: {content!r}")
                continue

            identifier_xx_with_space = content[0:2]  # 前两个字符是 XX (例如 "3 ", "8 ")
            value_str = content[2:].strip()          # 剩余部分是 yyyyyyyyyyyy，去除前后空格
            
            enum_member_key = identifier_to_enum_member_map.get(identifier_xx_with_space)

            if enum_member_key:
                try:
                    # 根据AAG文档，"C!"命令返回的这些 xxxx 值是整数 (ADC读数或计数)
                    parsed_values[enum_member_key] = int(value_str)
                except (ValueError, TypeError) as e:
                    print(f"[yellow]警告：无法将标识符 '{identifier_xx_with_space}' 的值 '{value_str}' 解析为整数: {e}")
                    parsed_values[enum_member_key] = None # 解析失败则存入 None
            else:
                # 如果 verbose 标志可用，可以在这里打印未处理的标识符
                # print(f"[grey]调试: 在 'C!' 命令响应中遇到未知或未处理的块标识符: '{identifier_xx_with_space}'")
                pass
        
        return parsed_values


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
        if not self.has_heater: return None
        
        return self.query(WeatherCommand.GET_PWM, parse_type=int) / 1023 * 100

    def set_pwm(self, percent: float) -> bool:
        """Sets the PWM value.

        Returns:
            True if successful, False otherwise.
        """
        percent = min(100, max(0, int(percent)))
        percent = int(percent * 1023 / 100)
        return self.query(WeatherCommand.SET_PWM, cmd_params=f'{percent:04d}')


    def set_switch(self, percent: str) -> bool:
        """Sets the PWM value.

        Returns:
            True if successful, False otherwise.
        """
        if percent == WeatherCommand.SET_SWITCH_OPEN or percent == WeatherCommand.SETITCH_CLOSED :
            return self.query(percent)
        else:
            return None

    def get_wind_speed(self, skip_averaging: bool = False) -> float | None: # skip_averaging 已存在
        if not self.has_anemometer: return None
        raw_val = self.query(WeatherCommand.GET_WINDSPEED)
        if raw_val is not None:
            try:
                ws_val = float(raw_val)
                if ws_val == 0: return 0.0
                # 假设是新型号风速计
                return (ws_val * 0.84) + 3.0 # km/h
            except (ValueError, TypeError): return None
        return None

    def get_switch_status_custom(self) -> str | None: # F!
        """Get the switch value.
        Returns:
            open,close,None.
        """
        return self.query(WeatherCommand.GET_SWITCH_STATUS) 

    def format_reading_for_solo_dict(self, current_reading_dict: dict | None = None) -> dict:
        # (保持之前的稳健实现)
        if current_reading_dict is None: current_reading_dict = self.status 
        if not current_reading_dict: 
            if self._verbose_logging: print("[yellow]警告: format_reading_for_solo_dict 中没有可用的当前读数。")
            return {
                "dataGMTTime": datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M:%S"),
                "cwinfo": f"Serial: {self.serial_number or 'N/A'}, FW: {self.firmware or 'N/A'}",
                "clouds": 0.0, "temp": 0.0, "wind": 0.0, "gust": 0.0, "rain": 0,
                "lightmpsas": 0.0, "switch": 0, "safe": 0, "hum": 0, "dewp": 0.0,
                "rawir": 0.0, "abspress": 0.0, "relpress": 0.0, "error": "No data"
            }
        data_gmt_time_str = "N/A"
        timestamp_iso = current_reading_dict.get('timestamp')
        if timestamp_iso:
            try:
                dt_object_utc = datetime.fromisoformat(str(timestamp_iso).replace('Z', '+00:00'))
                dt_object_utc = dt_object_utc.astimezone(timezone.utc)
                data_gmt_time_str = dt_object_utc.strftime("%Y/%m/%d %H:%M:%S")
            except (ValueError, TypeError) as e:
                if self._verbose_logging: print(f"[yellow]警告：转换SOLO时间戳时出错 '{timestamp_iso}': {e}。")
                data_gmt_time_str = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M:%S") 
        sn_str = self.serial_number if self.serial_number else "N/A"
        fw_str = self.firmware if self.firmware else "N/A"
        cwinfo_str = f"Serial: {sn_str}, FW: {fw_str}"
        
        clouds_val = 0.0 
        sky_t_val = current_reading_dict.get('sky_temp')
        amb_t_val = current_reading_dict.get('ambient_temp')
        if sky_t_val is not None and amb_t_val is not None:
            try: clouds_val = round(float(sky_t_val) - float(amb_t_val), 3)
            except (ValueError, TypeError): pass

        temp_val_get = current_reading_dict.get('ambient_temp')
        temp_val = round(temp_val_get if temp_val_get is not None else 0.0, 3)
        
        wind_val_get = current_reading_dict.get('wind_speed')
        wind_val = round(wind_val_get if wind_val_get is not None else 0.0, 3) 
        
        gust_val = wind_val # 沿用风速值作为阵风值
        
        rain_val_get = current_reading_dict.get('rain_frequency')
        rain_val = int(rain_val_get if rain_val_get is not None else 0)

        lightmpsas_val_get = current_reading_dict.get('sky_quality_mpsas')
        lightmpsas_val = round(lightmpsas_val_get if lightmpsas_val_get is not None else 0.0, 3)
        
        # Switch: open / close /none
  
        switch_val = current_reading_dict.get('switch')

        safe_val = 1 if current_reading_dict.get('is_safe', False) else 0
        
        hum_val_get = current_reading_dict.get('humidity')
        hum_val = round(hum_val_get if hum_val_get is not None else 0.0, 3)
        
        dewp_val_get = current_reading_dict.get('dew_point')
        dewp_val = round(dewp_val_get if dewp_val_get is not None else 0.0, 3)

        rawir_val_get = current_reading_dict.get('sky_temp')
        rawir_val = round(rawir_val_get if rawir_val_get is not None else 0.0, 3)

        abspress_hpa = 0.0
        abs_p_pa = current_reading_dict.get('pressure')
        if abs_p_pa is not None:
            try: abspress_hpa = round(float(abs_p_pa) / 100.0, 3)
            except (ValueError, TypeError): 
                 if self._verbose_logging: print(f"[yellow]警告：无法转换绝对气压值 '{abs_p_pa}' for SOLO")
        
        relpress_hpa = 0.0
        rel_p_pa = current_reading_dict.get('pres_pressure')
        if rel_p_pa is not None:
            try: relpress_hpa = round(float(rel_p_pa) / 100.0, 3)
            except (ValueError, TypeError): 
                if self._verbose_logging: print(f"[yellow]警告：无法转换相对气压值 '{rel_p_pa}' for SOLO")

        solo_data = {
            "dataGMTTime": data_gmt_time_str, "cwinfo": cwinfo_str, "clouds": clouds_val,
            "temp": temp_val, "wind": wind_val, "gust": gust_val, "rain": int(rain_val),
            "lightmpsas": lightmpsas_val, "switch": switch_val, "safe": safe_val,
            "hum": int(hum_val), "dewp": dewp_val, "rawir": rawir_val,
            "abspress": abspress_hpa, "relpress": relpress_hpa
        }
        return solo_data

    def query(self, cmd: WeatherCommand, return_codes: bool = False, parse_type: type = float, cmd_params: str = '', verbose: bool = False) -> list | str | float | int | bool | None:
        # (使用之前讨论的、能处理多块响应的 query 版本)
        effective_verbose = verbose or self._verbose_logging
        self.write(cmd, cmd_params=cmd_params) # write 现在不带 *args, **kwargs
        response_data_parts = self.read(verbose=effective_verbose) # read 现在不带 *args, **kwargs

        if isinstance(response_data_parts, str): # 如果 read 返回了原始字符串
            return response_data_parts

        if not response_data_parts: # 空列表
            return None

        # 对于预期返回多个数据块的命令 (如 "C!", "D!")
        if cmd in [WeatherCommand.GET_VALUES, WeatherCommand.GET_INTERNAL_ERRORS]:
            return response_data_parts 

        # 对于预期返回单个数据块/值的命令
        if len(response_data_parts) == 1:
            single_block_content = response_data_parts[0]  # "XXyyyyyyyyyyyy"
            if return_codes:
                return single_block_content
            else:
                value_str = single_block_content[2:].strip() # "yyyyyyyyyyyy"
                
                    # 特殊处理布尔型命令的响应 (例如开关状态)
                if cmd == WeatherCommand.GET_SWITCH_STATUS:
                    # 'X' for Open, 'Y' for Closed
                    if single_block_content[0:2] == WeatherResponseCodes.SWITCH_OPEN.value: # Compare 'X'
                        return "open" # Open
                    elif single_block_content[0:2] == WeatherResponseCodes.SWITCH_CLOSED.value: # Compare 'Y'
                        return "close" # Closed
                    else:
                        if effective_verbose: print(f"[yellow]未知的开关状态响应: {single_block_content!r}")
                        return None
                
                # 特殊处理 CAN_GET_WINDSPEED ('v!') -> '!v Y' or '!v N'
                if cmd == WeatherCommand.CAN_GET_WINDSPEED:
                    return 'Y' in value_str.upper() # value_str here is "Y" or "N" (after strip)

                try:
                    return parse_type(value_str)
                except (ValueError, TypeError):
                    if effective_verbose: print(f"[yellow]无法将 '{value_str}' 解析为 {parse_type} (命令: {cmd.name})")
                    return value_str # 返回原始字符串如果解析失败
        
        if effective_verbose: print(f"[yellow]命令 {cmd.name} 预期单个数据块，但收到多个: {response_data_parts}。将尝试返回第一个。")
        if response_data_parts: # 尝试返回第一个块的值作为备用
            try: return parse_type(response_data_parts[0][2:].strip())
            except: return response_data_parts[0][2:].strip()
        return None

    def write(self, cmd: WeatherCommand, cmd_params: str = '', cmd_delim: str = '!') -> int:
        # (使用之前讨论的 write 版本)
        full_cmd = f'{cmd.value}{cmd_params}{cmd_delim}'
        if not self._sensor.is_open:
            try:
                self._sensor.open()
                time.sleep(0.05) # 短暂延时确保端口准备好
            except serial.SerialException as e:
                if self._verbose_logging: print(f"[red]写入前打开串口失败: {e}")
                return 0
        try:
            self._sensor.reset_input_buffer()
            self._sensor.reset_output_buffer()
            num_bytes = self._sensor.write(full_cmd.encode())
            self._sensor.flush() # 确保数据已发送
            return num_bytes
        except serial.SerialException as e:
            if self._verbose_logging: print(f"[red]写入命令 '{full_cmd}' 到串口时发生错误: {e}")
            return 0

    def read(self, return_raw: bool = False, verbose: bool = False) -> list | str:
        # (使用之前讨论的、能处理多块响应的 read 版本)
        effective_verbose = verbose or self._verbose_logging
        if not self._sensor.is_open:
            if effective_verbose: print("[red]读取错误: 串口未打开。")
            return [] if not return_raw else ""
        
        full_response_decoded = ""
        all_data_blocks_content = [] # 存储 "XXyyyyyyyyyyyy" 格式的块内容

        try:
            # 循环读取，直到遇到完整的握手块或超时
            # AAG 设备通常以 "!" + handshake_block_content 结束一次完整的响应
            # read_until 会读取到terminator并包含它
            
            # We set self._sensor.read_until_terminator in __init__
            # However, read_until in pyserial might not work as expected with complex multi-byte terminators
            # or if the device sends data slowly. A more robust way is to read in chunks or by expected length.
            # For AAG, we know responses are multiples of 15 bytes ending with the handshake.
            
            # Let's try a slightly different read strategy: read all available, then parse.
            # This assumes the device sends all blocks for a command relatively quickly.
            
            # Wait briefly for data to arrive after a write
            time.sleep(0.2) # Adjust as needed; depends on device response time
            
            buffer = b''
            # Read until the specific handshake sequence is found at the end of a 15-byte block
            # The full handshake block is "!<XON><12 spaces>0"
            full_handshake_bytes = b"!" + self.handshake_block_content.encode()

            # Read in a loop until handshake is detected or timeout occurs (implicit via serial timeout)
            max_attempts = 10 # Try to read a few times to assemble the full response
            for _ in range(max_attempts):
                if self._sensor.in_waiting > 0:
                    buffer += self._sensor.read(self._sensor.in_waiting)
                
                # Check if the complete handshake is at the end of the buffer
                if buffer.endswith(full_handshake_bytes):
                    break
                time.sleep(0.05) # Small delay before checking again
            
            full_response_decoded = buffer.decode(errors='ignore')

            if effective_verbose:
                print(f'读取的原始响应 (解码后): {full_response_decoded!r}')

            if return_raw:
                return full_response_decoded

            if full_response_decoded:
                # 移除末尾的握手块 (包括 '!')
                data_to_parse = full_response_decoded
                if data_to_parse.endswith(full_handshake_bytes.decode(errors='ignore')):
                    data_to_parse = data_to_parse[:-len(full_handshake_bytes)]
                
                idx = 0
                while (idx + 15) <= len(data_to_parse):
                    block = data_to_parse[idx:idx + 15]
                    if not block.startswith('!'):
                        if effective_verbose: print(f"[yellow]预期数据块以 '!' 开始，但得到: {block!r}")
                        break 
                    all_data_blocks_content.append(block[1:]) # 存储 "XXyyyyyyyyyyyy"
                    idx += 15
                
                if idx < len(data_to_parse) and effective_verbose:
                     print(f"[yellow]解析数据块后仍有剩余字符: {data_to_parse[idx:]!r}")
            
            return all_data_blocks_content

        except serial.SerialException as e:
            if effective_verbose: print(f"[red]串口读取错误: {e}")
            return [] if not return_raw else ""
        except Exception as e:
            if effective_verbose: print(f"[red]读取或解析传感器响应时发生意外错误: {e}")
            return [] if not return_raw else ""

    def __str__(self):
        return f'CloudSensor({self.name}, FW={self.firmware}, SN={self.serial_number}, port={self.config.serial_port})'

    def __del__(self):
        if hasattr(self, '_sensor') and self._sensor and self._sensor.is_open:
            if self._verbose_logging: print('[grey]CloudSensor 对象销毁，关闭串口连接...')
            try:
                self._sensor.close()
            except Exception as e:
                if self._verbose_logging: print(f"[red]关闭串口时发生错误: {e}")
