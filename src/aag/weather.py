import re
import time
from datetime import datetime,timezone
import math # 导入 math 模块
from enum import Enum # 导入 Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError # 导入 zoneinfo 用于时区

import serial
from collections.abc import Callable
from collections import deque
from contextlib import suppress

from astropy import units as u
from rich import print

from aag.commands import WeatherCommand, WeatherResponseCodes
from aag.settings import WeatherSettings, WhichUnits, Thresholds,Location

# 新增：自定义异常
class SensorCommunicationError(Exception):
    """自定义异常，表示传感器通信失败。"""
    pass

# 新增：通信错误哨兵对象
COMMUNICATION_ERROR_SENTINEL = object()

# 新增：连接状态枚举
class ConnectionStatus(Enum):
    INITIALIZING = "INITIALIZING"
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    ERROR = "ERROR"
    ATTEMPTING_RECONNECT = "ATTEMPTING_RECONNECT"


class CloudSensor(object):
    def __init__(self, connect: bool = True, **kwargs):
        """ A class to read the cloud sensor.

        Args:
            connect: Whether to connect to the sensor on init.
            **kwargs: Keyword arguments for the WeatherSettings class.
        """

        try:
            # --- 修改：增加详细错误捕获 ---
            if 'verbose_logging' in kwargs: # 如果 kwargs 中有 verbose_logging，优先使用它
                temp_verbose_setting = kwargs['verbose_logging']
            else: # 否则，尝试从 WeatherSettings 的默认值或环境变量获取
                try:
                    # 尝试创建一个临时的 WeatherSettings 实例仅用于获取 verbose_logging
                    # 这本身也可能失败，所以也需要 try-except
                    temp_settings_for_verbose = WeatherSettings()
                    temp_verbose_setting = temp_settings_for_verbose.verbose_logging
                except Exception:
                    temp_verbose_setting = False # 如果无法获取，默认为 False

            self._verbose_logging = temp_verbose_setting # 在 self.config 赋值前设置

            try:
                self.config = WeatherSettings(**kwargs)
            except Exception as e_settings:
                # 打印更详细的错误信息
                print(f"[red]DEBUG: FATAL Error during WeatherSettings instantiation in CloudSensor.__init__[/red]")
                print(f"[red]DEBUG: Exception type: {type(e_settings).__name__}[/red]")
                print(f"[red]DEBUG: Exception message: {e_settings}[/red]")
                import traceback
                print("[red]DEBUG: Full traceback for WeatherSettings error:[/red]")
                traceback.print_exc() # 打印完整的堆栈跟踪
                # 可以选择重新抛出一个更通用的错误，或者让原始错误冒泡
                raise # 重新抛出原始异常，以便服务能感知到初始化失败
            # --- 结束修改 ---
             # --- 结束新增诊断代码 ---       
            # self._verbose_logging = self.config.verbose_logging # 这行现在多余，因为上面已经设置了

        except Exception as e_outer: # 捕获 self.config 设置失败后可能引发的其他问题
             # 如果 self.config 初始化失败，self._verbose_logging 可能未正确设置
            print(f"[red]CRITICAL: Failed to initialize self.config in CloudSensor. Error: {e_outer}[/red]")
            # 对于这种情况，服务无法正常运行，所以应该抛出异常
            # 如果是因为 WeatherSettings 抛出的，上面的 raise 已经处理了
            # 这是一个备用捕获，以防万一
            if not isinstance(e_outer, (SensorCommunicationError, TypeError, ValueError)): # 避免重复包装已知类型
                 raise RuntimeError(f"CloudSensor config initialization failed critically: {e_outer}") from e_outer

        # 新增：状态属性初始化
        self._connection_status: ConnectionStatus = ConnectionStatus.INITIALIZING
        self.last_error_message: str | None = None
        self.last_successful_read_timestamp: datetime | None = None
        self.last_connection_attempt_timestamp: datetime | None = None
        # _is_connected 属性现在通过 property 动态获取


        try:
            self._sensor: serial.Serial = serial.serial_for_url(self.config.serial_port,
                                                                baudrate=9600,
                                                                timeout=1,
                                                                do_not_open=True
                                                                )
         # 注意：实际的 open() 和初始化移至 self.connect()
        except serial.serialutil.SerialException as e:
            self.last_error_message = f"串口初始化失败 (serial_for_url): {e}"
            self._connection_status = ConnectionStatus.ERROR
            if self._verbose_logging:
                print(f'[red]{self.last_error_message}')
            if connect: # 如果要求立即连接但 serial_for_url 失败，则直接抛出
                raise SensorCommunicationError(self.last_error_message) from e

        self.handshake_block_content = chr(0x11) + (' ' * 12) + '0'
        # self._sensor.read_until_terminator = self.handshake_block_content.encode() # 移至 open 之后


        self.handshake_block = r'\x11\s{12}0'
        #self.handshake_block = r'^\x11\s*0?\s*$'

        # Set up a queue for readings
        self.readings = deque(maxlen=self.config.num_readings)

        self.name: str = 'CloudWatcher' # 将在 connect 中实际获取
        self.firmware: str | None = None
        self.serial_number: str | None = None
        self.has_anemometer: bool = False
        self.has_heater: bool = False #有没有加热器

        self._is_connected: bool = False

        if connect:
            self.connect(raise_exceptions=True) # 初始连接失败时应抛出异常

    @property
    def is_connected(self) -> bool:
        """ Is the sensor connected and communication healthy?"""
        return self._connection_status == ConnectionStatus.CONNECTED

    # 新增：获取详细连接状态的属性
    @property
    def connection_status(self) -> ConnectionStatus:
        return self._connection_status

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
        if self._verbose_logging: print(f"[cyan]尝试连接到传感器 (端口: {self.config.serial_port})...")
        self._connection_status = ConnectionStatus.ATTEMPTING_RECONNECT
        self.last_connection_attempt_timestamp = datetime.now(timezone.utc)

        try:
            if not hasattr(self, '_sensor'): # 防御性检查，通常在 __init__ 中已创建
                self._sensor: serial.Serial = serial.serial_for_url(self.config.serial_port,
                                                                baudrate=9600,
                                                                timeout=1,
                                                                do_not_open=True)
            
            if self._sensor.is_open: # 如果之前是打开的，先关闭再重新打开，确保状态干净
                self._sensor.close()
                time.sleep(0.1) # 短暂延时

            self._sensor.open()
            #self._sensor.read_until_terminator = self.handshake_block_content.encode() # 设置 read_until 的终止符 # pyserial 没有这个属性
            time.sleep(getattr(self.config, 'serial_port_open_delay_seconds', 2))    
            
            self._sensor.reset_input_buffer()
            self._sensor.reset_output_buffer()


            # 初始化并获取静态值。
            # query 方法现在可能返回哨兵或抛出 SensorCommunicationError
            name_resp_val = self.query(WeatherCommand.GET_INTERNAL_NAME, parse_type=str)
            if name_resp_val is COMMUNICATION_ERROR_SENTINEL or name_resp_val is None:
                # 如果 query 返回哨兵或 None，说明通信或解析失败
                raise SensorCommunicationError("连接后获取内部名称失败")
            self.name = name_resp_val if isinstance(name_resp_val, str) else 'CloudWatcher'
            
            firmware_resp_val = self.query(WeatherCommand.GET_FIRMWARE, parse_type=str)
            if firmware_resp_val is COMMUNICATION_ERROR_SENTINEL or firmware_resp_val is None:
                 raise SensorCommunicationError("连接后获取固件版本失败")


            match = re.search(r"(\d+\.\d+)", firmware_resp_val)
            if match:
                version_number = match.group(1)  # group(1) 获取第一个捕获组的内容
                self.firmware = version_number 
                self._verbose_logging: print(f"提取到的版本号是: {version_number}")
            else:
                self._verbose_logging: print("未能找到版本号")            
            
            sn_resp_val = self.query(WeatherCommand.GET_SERIAL_NUMBER, parse_type=str, return_codes=True)
            if sn_resp_val is COMMUNICATION_ERROR_SENTINEL or sn_resp_val is None:
                raise SensorCommunicationError("连接后获取序列号失败")
            self.serial_number = sn_resp_val[1:5] if isinstance(sn_resp_val, str) and len(sn_resp_val) >=5 else None # !Kxxxx

            can_get_wind_val = self.query(WeatherCommand.CAN_GET_WINDSPEED, parse_type=str) # 'v!' returns '!v Y' or '!v N'
            if can_get_wind_val is COMMUNICATION_ERROR_SENTINEL: # 这里允许 None，因为 query 对布尔型返回 'Y'/'N'
                raise SensorCommunicationError("连接后检查风速计能力失败")
            self.has_anemometer = True if isinstance(can_get_wind_val, str) and 'Y' in can_get_wind_val.upper() else False

            self.has_heater = self.config.have_heater  #如果没有加热器，就不用处理PWM了。

            # 启动时将PWM设置为最小值。
            if self.has_heater:
                pwm_set_success = self.set_pwm(self.config.heater.min_power)
                if pwm_set_success is COMMUNICATION_ERROR_SENTINEL or not pwm_set_success :
                    if self._verbose_logging: print("[yellow]警告: 连接后设置初始PWM值失败或通信错误。")
                    # 不因此次失败而中断整个连接过程

            self._connection_status = ConnectionStatus.CONNECTED # 所有初始化查询成功后，才标记为已连接
            self.last_error_message = None # 清除旧的错误信息
            if self._verbose_logging: print('[green]传感器连接成功并初始化完成。')
            return True
        except (serial.serialutil.SerialException, SensorCommunicationError, OSError) as e: # OSError for device not configured
            self.last_error_message = f"连接传感器失败: {e}"
            self._connection_status = ConnectionStatus.ERROR
            if self._verbose_logging: print(f'[red]{self.last_error_message}')
            if hasattr(self, '_sensor') and self._sensor.is_open:
                try:
                    self._sensor.close()
                except Exception as close_err:
                    if self._verbose_logging: print(f"[red]关闭失败的串口时发生错误: {close_err}")

            if raise_exceptions:
                # 确保抛出的是 SensorCommunicationError
                if not isinstance(e, SensorCommunicationError):
                    raise SensorCommunicationError(self.last_error_message) from e
                else:
                    raise # 重新抛出已包装的 SensorCommunicationError
            return False

    def capture(self, callback: Callable | None = None, units: WhichUnits = 'none', verbose: bool = False) -> None:
        """连续捕获读数。"""
        # 注意：此方法目前不由 server.py 的周期任务使用，主要用于 cli.py。
        # 如果将来 server.py 也使用此模式，这里的重连逻辑需要与 periodic_task 中的对齐。
        current_verbose = verbose or self._verbose_logging
        try:
            while True:
                if self.connection_status != ConnectionStatus.CONNECTED:
                    if current_verbose: print(f"[yellow]传感器状态: {self.connection_status.value}。尝试重新连接...")
                    if not self.connect(raise_exceptions=False): # 调用修改后的 connect
                        if current_verbose: print(f"[red]重新连接失败 ({self.last_error_message})，等待后重试...")
                        time.sleep(self.config.capture_delay * 2) 
                        continue
                    if current_verbose: print("[green]传感器重新连接成功。")

                # get_reading 现在返回数据或 None (如果当次读取失败)
                reading_data = self.get_reading(units=units, verbose=current_verbose) 

                if reading_data is not None: # 仅当成功获取读数时才回调
                    if callback is not None:
                        callback(reading_data)
                else:
                    if current_verbose: print(f"[yellow]本次读数捕获失败，状态: {self.connection_status.value}, 错误: {self.last_error_message}")
                    # 如果 get_reading 失败，它内部已更新状态，这里不需要额外操作
                    # 等待下次循环尝试（可能包括重连）

                time.sleep(self.config.capture_delay)
        except KeyboardInterrupt:
            if current_verbose: print("\n[yellow]捕获已由用户中断。")
        except Exception as e:
            if current_verbose: print(f"[red]在捕获循环中发生意外错误: {e}")
            self._connection_status = ConnectionStatus.ERROR
            self.last_error_message = f"捕获循环错误: {e}"
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
        
        # 在尝试读取任何数据前，检查连接状态
        if self.connection_status != ConnectionStatus.CONNECTED:
            if current_verbose: print(f"[yellow]get_reading 跳过：传感器未连接 (状态: {self.connection_status.value})。")
            return None

        # 用于跟踪本次 get_reading 期间是否发生通信错误
        communication_error_occured_this_cycle = False

        def avg_readings(fn_to_avg: Callable, n: int = avg_times, skip_avg: bool = False) -> float | int | None | object:
            nonlocal communication_error_occured_this_cycle
            if communication_error_occured_this_cycle: # 如果周期中已有错误，则不再尝试读取
                return COMMUNICATION_ERROR_SENTINEL

            if skip_avg or n <= 1:
                val = fn_to_avg()
                if val is COMMUNICATION_ERROR_SENTINEL:
                    communication_error_occured_this_cycle = True
                    return COMMUNICATION_ERROR_SENTINEL
                if val is not None:
                    try:
                        return round(float(val), 2)
                    except (ValueError, TypeError):
                        if current_verbose: print(f"[yellow]警告: {fn_to_avg.__name__} 的单次读取值无法转换为浮点数: {val!r}")
                        return None
                return None

            values = []
            for i in range(n):
                val = fn_to_avg()
                if val is COMMUNICATION_ERROR_SENTINEL:
                    communication_error_occured_this_cycle = True
                    return COMMUNICATION_ERROR_SENTINEL
                if val is not None:
                    try:
                        values.append(float(val))
                    except (ValueError, TypeError):
                        if current_verbose: print(f"[yellow]警告: {fn_to_avg.__name__} 的平均过程中遇到非数字值 ({i+1}/{n}): {val!r}")
                elif current_verbose:
                     print(f"[grey]调试: avg_readings 从 {fn_to_avg.__name__} 获得了 None ({i+1}/{n})")
                
                if communication_error_occured_this_cycle: # 检查循环内部是否发生错误
                    return COMMUNICATION_ERROR_SENTINEL

            if not values:
                if current_verbose: print(f"[yellow]警告: {fn_to_avg.__name__} 的所有 {n} 次读数均无效或为 None。")
                return None
            return round(sum(values) / len(values), 2)

        # --- 使用配置的时区生成时间戳 ---
        try:
            # 使用配置中定义的时区
            local_tz = ZoneInfo(self.config.location.timezone)
        except ZoneInfoNotFoundError:
            # 如果配置的时区字符串无效，打印警告并回退到UTC
            if self._verbose_logging:
                print(f"[yellow]Warning: Configured timezone '{self.config.location.timezone}' not found. Falling back to UTC.[/yellow]")
            local_tz = timezone.utc
        except Exception as tz_err:
            # 捕获其他可能的时区错误
            if self._verbose_logging:
                print(f"[red]Error setting timezone: {tz_err}. Falling back to UTC.[/red]")
            local_tz = timezone.utc

        timestamp_iso_str = datetime.now(local_tz).isoformat()

        # --- 开始获取读数 ---
        # C! 命令获取的值，如果失败，则整个读数周期失败
        c_command_data_val = self.get_rain_sensor_values()
        #更严格地处理 c_command_data_val
        if c_command_data_val is COMMUNICATION_ERROR_SENTINEL or c_command_data_val is None:
            # 如果是哨兵，错误已在底层设置。如果是 None，说明 query 返回 None (read 返回空列表)
            if c_command_data_val is None and self._connection_status == ConnectionStatus.CONNECTED: # 仅当之前认为是连接的时才更新状态
                self.last_error_message = "获取 C! 命令数据失败 (未收到有效数据块)。"
                self._connection_status = ConnectionStatus.ERROR # 视为错误
                if current_verbose: print(f"[red]{self.last_error_message}")
            elif current_verbose and c_command_data_val is COMMUNICATION_ERROR_SENTINEL:
                 print(f"[red]get_reading 中断：获取 C! 命令数据因通信错误失败。({self.last_error_message})")
            return None 
        
        # 确保 c_command_data_val 是字典，即使 query 成功但解析部分失败也可能返回空字典
        c_command_data = c_command_data_val if isinstance(c_command_data_val, dict) else {}   
        
        reading_values = {} # 使用临时字典存储值
               # 辅助函数检查哨兵并更新 communication_error_occured_this_cycle
        def process_value(key_name, value_or_sentinel):
            nonlocal communication_error_occured_this_cycle
            if value_or_sentinel is COMMUNICATION_ERROR_SENTINEL:
                communication_error_occured_this_cycle = True
                if current_verbose: print(f"[red]通信错误导致获取 {key_name} 失败。")
                return None # 返回 None 表示该值获取失败，但不一定是哨兵
            return value_or_sentinel

        reading_values['sky_temp'] = process_value('sky_temp', avg_readings(self.get_sky_temperature))
        reading_values['wind_speed'] = process_value('wind_speed', avg_readings(lambda: self.get_wind_speed(skip_averaging=True)))
        reading_values['rain_frequency'] = process_value('rain_frequency', avg_readings(self.get_rain_frequency))
        reading_values['humidity'] = process_value('humidity', avg_readings(self.get_humidity))
        reading_values['pressure'] = process_value('pressure', avg_readings(self.get_pressure))
        reading_values['RH_sensor_temp'] = process_value('RH_sensor_temp', avg_readings(self.get_rh_sensor_temp))
        reading_values['pressure_temp'] = process_value('pressure_temp', avg_readings(self.get_pressure_temp))
        reading_values['switch'] = process_value('switch', self.get_switch_status_custom())
        reading_values['pwm'] = process_value('pwm', self.get_pwm())

        if communication_error_occured_this_cycle:
            if current_verbose: print("[red]get_reading 中断：在获取一个或多个基础传感器值时发生通信错误。")
            # 状态已在底层更新
            return None # 本次读数无效

        # --- 后续计算基于已获取的值 ---
        final_reading_dict = {'timestamp': timestamp_iso_str}
        final_reading_dict.update(reading_values)

        # 环境温度直接取RH传感器温度  根据文档，RH温度传感器更加准确。
        if final_reading_dict.get('RH_sensor_temp') is not None:
            final_reading_dict['ambient_temp'] = final_reading_dict['RH_sensor_temp']
        else:
            final_reading_dict['ambient_temp'] = process_value('ambient_temp_fallback', avg_readings(self.get_ambient_temperature))
            if communication_error_occured_this_cycle: return None # 再次检查
            final_reading_dict['RH_sensor_temp'] = final_reading_dict['ambient_temp']
            if current_verbose: print("[yellow]警告: RH_sensor_temp 不可用，ambient_temp 使用 IR 传感器温度作为备用。")

        # 从 c_command_data 提取原始值，使用 get_values_raw (它处理None并返回哨兵值)
        # get_values_raw 的第二个参数期望是 WeatherResponseCodes 枚举成员
        # 从 c_command_data 提取原始值

        final_reading_dict['light_sensor_period_raw'] = self.get_values_raw(c_command_data, WeatherResponseCodes.GET_VALUES_LIGHT_SENSOR, verbose=current_verbose)
        #环境温度传感器 NTC 电压值（Ambient Temp NTC) 0-1023
        final_reading_dict['ambient_temp_ntc_raw'] = self.get_values_raw(c_command_data, WeatherResponseCodes.GET_VALUES_AMBIENT, verbose=current_verbose)
        #LDR环境亮度 0-1023
        final_reading_dict['ambient_ldr_voltage_raw'] = self.get_values_raw(c_command_data, WeatherResponseCodes.GET_VALUES_LDR_VOLTAGE, verbose=current_verbose)
        #Zener Voltage reference 齐纳电压 0-1023        
        final_reading_dict['zener_voltage_raw'] = self.get_values_raw(c_command_data, WeatherResponseCodes.GET_VALUES_ZENER_VOLTAGE, verbose=current_verbose)
        #雨量传感器 电压值        
        final_reading_dict['rain_sensor_temp_ntc_raw'] = self.get_values_raw(c_command_data, WeatherResponseCodes.GET_VALUES_SENSOR_TEMP, verbose=current_verbose)

        # 取相对气压
        # 先获取依赖值
        current_pressure_val = final_reading_dict['pressure']
        pressure_temp_val = final_reading_dict['pressure_temp']
        # 然后传递这些值来计算 pres_pressure ,是根据 实际气压 和温度 计算的，不需要再算平均值了
        if current_pressure_val is not None and pressure_temp_val is not None:
            try:
                # get_pres_pressure 不直接进行 query，所以不需要哨兵检查
                final_reading_dict['pres_pressure'] = round(self.get_pres_pressure(current_pressure_val, pressure_temp_val, verbose=current_verbose), 2)
            except Exception as e:
                if current_verbose: print(f"[yellow]计算相对气压时出错: {e}")
                final_reading_dict['pres_pressure'] = None
        else:
            final_reading_dict['pres_pressure'] = current_pressure_val # 或 None
            if current_verbose: print("[yellow]跳过相对气压计算：绝对气压或其温度为 None。")


        # 计算露点
        # 使用最佳的环境温度源,用湿度传感器温度计替代，手册上说更加准确
        ambient_temp_for_dew = final_reading_dict['ambient_temp']
        humidity_for_dew = final_reading_dict['humidity']
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
                    final_reading_dict['dew_point'] = round(dew_point_val, 2)
            except (ValueError, TypeError, ZeroDivisionError, OverflowError) as e:
                if current_verbose: print(f"[yellow]警告：计算露点时出错: {e}")
                final_reading_dict['dew_point'] = None
        else:
            final_reading_dict['dew_point'] = None
            if current_verbose: print("[yellow]跳过露点计算：环境温度或湿度为 None。")
    

        # 添加 MPSAS 天空质量
        raw_period_for_mpsas = final_reading_dict.get('light_sensor_period_raw')
        # 确保 raw_period_for_mpsas 不是哨兵值 -99
        if raw_period_for_mpsas == -99: raw_period_for_mpsas = None

        ambient_temp_for_mpsas = final_reading_dict['ambient_temp']
        final_reading_dict['sky_quality_mpsas'] = None 

        if raw_period_for_mpsas is not None and ambient_temp_for_mpsas is not None:
            try:
                final_reading_dict['sky_quality_mpsas'] = self._calculate_mpsas(raw_period_for_mpsas, ambient_temp_for_mpsas)
            except Exception as e:
                 if current_verbose: print(f"[red]计算 MPSAS 时发生错误: {e}")
        elif raw_period_for_mpsas is not None and current_verbose: 
             print("[yellow]MPSAS 计算跳过：环境温度为 None，但原始周期值可用。")
        elif current_verbose: 
            print("[grey]MPSAS 计算跳过：原始周期值或环境温度为 None。")


        if get_errors:
            errors_list_val = self.get_errors() # get_errors 内部调用 query
            if errors_list_val is COMMUNICATION_ERROR_SENTINEL:
                communication_error_occured_this_cycle = True
            elif errors_list_val is not None:
                 if isinstance(errors_list_val, list) :
                    final_reading_dict.update(**{f'error_{i:02d}': err for i, err in enumerate(errors_list_val)})
                 else: 
                    final_reading_dict['error_00'] = errors_list_val
        
        if communication_error_occured_this_cycle:
            if current_verbose: print("[red]get_reading 中断：在获取错误代码时发生通信错误。")
            return None # 本次读数无效
        
        # Add the safety values.
        # --- 如果到这里都没有通信错误 ---
        final_reading_dict = self.get_safe_reading(final_reading_dict)

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

            for field, unit in metric_fields_units.items():
                if final_reading_dict.get(field) is not None and final_reading_dict.get(field) != -99: # 不为哨兵值才加单位
                    try:
                        final_reading_dict[field] = float(final_reading_dict[field]) * unit
                    except (ValueError, TypeError):
                        if current_verbose: print(f"[yellow]警告：无法为字段 '{field}' 应用单位，值：{final_reading_dict.get(field)!r}")

            if units == 'imperial':
                with suppress(AttributeError, ValueError, TypeError): 
                    # ... (英制单位转换逻辑保持不变) ...
                    if final_reading_dict.get('ambient_temp') is not None and isinstance(final_reading_dict['ambient_temp'], u.Quantity): 
                        final_reading_dict['ambient_temp'] = final_reading_dict['ambient_temp'].to(u.imperial.deg_F, equivalencies=u.temperature())
                    # ... (其他字段类似)
                    if final_reading_dict.get('sky_temp') is not None and isinstance(final_reading_dict['sky_temp'], u.Quantity): 
                        final_reading_dict['sky_temp'] = final_reading_dict['sky_temp'].to(u.imperial.deg_F, equivalencies=u.temperature())
                    if final_reading_dict.get('RH_sensor_temp') is not None and isinstance(final_reading_dict['RH_sensor_temp'], u.Quantity): 
                        final_reading_dict['RH_sensor_temp'] = final_reading_dict['RH_sensor_temp'].to(u.imperial.deg_F, equivalencies=u.temperature())
                    if final_reading_dict.get('pressure_temp') is not None and isinstance(final_reading_dict['pressure_temp'], u.Quantity): 
                        final_reading_dict['pressure_temp'] = final_reading_dict['pressure_temp'].to(u.imperial.deg_F, equivalencies=u.temperature())
                    if final_reading_dict.get('dew_point') is not None and isinstance(final_reading_dict['dew_point'], u.Quantity): 
                        final_reading_dict['dew_point'] = final_reading_dict['dew_point'].to(u.imperial.deg_F, equivalencies=u.temperature())
                    if final_reading_dict.get('wind_speed') is not None and isinstance(final_reading_dict['wind_speed'], u.Quantity): 
                        final_reading_dict['wind_speed'] = final_reading_dict['wind_speed'].to(u.imperial.mile / u.hour)
                    if final_reading_dict.get('pressure') is not None and isinstance(final_reading_dict['pressure'], u.Quantity): 
                        final_reading_dict['pressure'] = final_reading_dict['pressure'].to(u.imperial.in_Hg)
                    if final_reading_dict.get('pres_pressure') is not None and isinstance(final_reading_dict['pres_pressure'], u.Quantity): 
                        final_reading_dict['pres_pressure'] = final_reading_dict['pres_pressure'].to(u.imperial.in_Hg)

        # 去除 astropy 单位，得到最终的纯数据字典
        processed_final_reading = {}
        for key, value in final_reading_dict.items():
            if isinstance(value, u.Quantity):
                processed_final_reading[key] = value.value
            else:
                processed_final_reading[key] = value
        
        # 只有在完全成功获取和处理所有数据后才更新
        self.readings.append(processed_final_reading)
        self.last_successful_read_timestamp = datetime.now(timezone.utc)
        # 如果之前是 ERROR 或 DISCONNECTED，现在成功读取，则更新状态
        if self._connection_status != ConnectionStatus.CONNECTED:
             if self._verbose_logging: print(f"[green]数据读取成功，传感器状态恢复为 CONNECTED (之前是 {self._connection_status.value})")
        self._connection_status = ConnectionStatus.CONNECTED 
        self.last_error_message = None # 清除错误信息

        #一个读取周期终于完成了
        return processed_final_reading

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

    def get_errors(self) -> list[int] | object: # 可能返回哨兵
        responses_val = self.query(WeatherCommand.GET_INTERNAL_ERRORS, return_codes=True)
        if responses_val is COMMUNICATION_ERROR_SENTINEL:
            return COMMUNICATION_ERROR_SENTINEL
        
        if responses_val is None or not isinstance(responses_val, list): # query 可能返回 None 或非列表
            return [] # 或者根据具体情况处理

        parsed_errors = []
        for i, response_item in enumerate(responses_val):
            if isinstance(response_item, str) and len(response_item) > 2 : # 确保是 "EXX" 格式
                try:
                    parsed_errors.append(int(response_item[2:]))
                except ValueError:
                    if self._verbose_logging: print(f"[yellow]解析错误码失败: {response_item}")
            else:
                 if self._verbose_logging: print(f"[yellow]无效的错误码格式: {response_item}")
        return parsed_errors

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

            return round(mpsas_corrected, 2) 
        except (ValueError, TypeError, OverflowError, ZeroDivisionError, AttributeError) as e:
            if self._verbose_logging: print(f"[red]计算 MPSAS 时出错: {e}")
            return None



    def get_sky_temperature(self) -> float:
        """Gets the latest IR sky temperature reading.

        Returns:
            The sky temperature in Celsius.
        """
        val = self.query(WeatherCommand.GET_SKY_TEMP)
        if val is COMMUNICATION_ERROR_SENTINEL: return COMMUNICATION_ERROR_SENTINEL
        return val / 100. if val is not None else None # query 返回 float 或 None (非通信错误时)

    def get_ambient_temperature(self) -> float:
        """Gets the latest ambient temperature reading.

        Returns:
            The ambient temperature in Celsius.
        """
        val = self.query(WeatherCommand.GET_SENSOR_TEMP)
        if val is COMMUNICATION_ERROR_SENTINEL: return COMMUNICATION_ERROR_SENTINEL
        return val / 100. if val is not None else None
    
    def get_humidity(self) -> float:
        """Gets the latest relative humidity reading (in %).

        Returns:
            The humidity in %.
        """
        val = self.query(WeatherCommand.GET_HUMIDITY)
        if val is COMMUNICATION_ERROR_SENTINEL: return COMMUNICATION_ERROR_SENTINEL
        return round((val * 125.0 / 65536.0 ) -6.0 ,2) if val is not None else None
    
    def get_pressure(self) -> float:
        """Gets the latest Absolute pressure in Pa reading.

        Returns:
            The Absolute pressure in Pa.
        """
        val = self.query(WeatherCommand.GET_PRESSURE)
        if val is COMMUNICATION_ERROR_SENTINEL: return COMMUNICATION_ERROR_SENTINEL
        return round(val / 16.0 ,2) if val is not None else None


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
            relative_pressure_pa = round(abs_pres_pa * (base ** (-5.275)), 2)
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
        val = self.query(WeatherCommand.GET_RH_SENSOR_TEMP)
        if val is COMMUNICATION_ERROR_SENTINEL: return COMMUNICATION_ERROR_SENTINEL
        return round((val * 172.72 / 65536.0 ) - 46.85, 2) if val is not None else None

    def get_pressure_temp(self) -> float:
        """Gets the latest pressure sensor temperature reading.

        Returns:
            The pressure sensor temprature  in Celsius.
        """
        val = self.query(WeatherCommand.GET_PRESSURE_TEMP)
        if val is COMMUNICATION_ERROR_SENTINEL: return COMMUNICATION_ERROR_SENTINEL
        return round(val / 100.00, 2) if val is not None else None

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
        block_contents_val = self.query(WeatherCommand.GET_VALUES, return_codes=True) # 返回 "XXyyyyyyyyyyyy" 字符串的列表
        if block_contents_val is COMMUNICATION_ERROR_SENTINEL:
            return COMMUNICATION_ERROR_SENTINEL 

        parsed_values = {} # 初始化为空字典
        if not block_contents_val or not isinstance(block_contents_val, list):
            if self._verbose_logging: print("[yellow]警告：未从 GET_VALUES (C!) 命令收到数据块或返回类型不正确。")
            return parsed_values # 返回空字典，而不是 None，以便上层处理

        # 创建一个从块标识符字符串 (例如 "6 ") 到相应 WeatherResponseCodes 枚举成员的映射
        # 这有助于我们从字符串标识符反向查找到枚举成员用作键
        identifier_to_enum_member_map = {
            code.value: code for code in WeatherResponseCodes 
            if code.name.startswith("GET_VALUES_") # 只包含与 "C!" 命令相关的代码
        }
        # 例如, identifier_to_enum_member_map['6 '] 会是 WeatherResponseCodes.GET_VALUES_ZENER_VOLTAGE

        for content in block_contents_val:
            if not isinstance(content, str) or len(content) != 14 : # 确保是 "XXyyyyyyyyyyyy"
                if self._verbose_logging: print(f"[yellow]警告: 无效的数据块内容: {content!r}")
                continue

            identifier_xx_with_space = content[0:2]  # 前两个字符是 XX (例如 "3 ", "8 ")
            value_str = content[2:].strip()  # 剩余部分是 yyyyyyyyyyyy，去除前后空格
            enum_member_key = identifier_to_enum_member_map.get(identifier_xx_with_space)

            if enum_member_key:
                try:
                    # 根据AAG文档，"C!"命令返回的这些 xxxx 值是整数 (ADC读数或计数)
                    parsed_values[enum_member_key] = int(value_str)
                except (ValueError, TypeError) as e:
                    if self._verbose_logging: print(f"[yellow]警告：无法将标识符 '{identifier_xx_with_space}' 的值 '{value_str}' 解析为整数: {e}")
                    parsed_values[enum_member_key] = None # 解析失败则存入 None
            else: # 忽略未知标识符
                if self._verbose_logging: print(f"[grey]调试: 在 'C!' 命令响应中遇到未知或未处理的块标识符: '{identifier_xx_with_space}'")

        return parsed_values


    def get_rain_frequency(self) -> int:
        """Gets the rain frequency.

        Returns:
            The rain frequency in Hz (?).
        """
        val = self.query(WeatherCommand.GET_RAIN_FREQUENCY, parse_type=int)
        if val is COMMUNICATION_ERROR_SENTINEL: return COMMUNICATION_ERROR_SENTINEL
        return val # query 返回 int 或 None

    def get_pwm(self) -> float:
        """Gets the latest PWM reading.

        Returns:
            The PWM value as a percentage.
        """
        if not self.has_heater: return None # 如果没有加热器，直接返回 None
        val = self.query(WeatherCommand.GET_PWM, parse_type=int)
        if val is COMMUNICATION_ERROR_SENTINEL: return COMMUNICATION_ERROR_SENTINEL

        return round(val / 1023 * 100, 2) if val is not None else None

    def set_pwm(self, percent: float) -> bool:
        """Sets the PWM value.

        Returns:
            True if successful, False otherwise.
        """
        if not self.has_heater: return True # 如果没有加热器，认为设置成功（无操作）
        percent_val = min(100, max(0, int(percent)))
        percent_cmd_param = int(percent_val * 1023 / 100)
        # query 返回 True/False (来自 SET_PWM 的响应通常是握手，这里假设 query 会处理)
        # 或者 query 返回哨兵
        result = self.query(WeatherCommand.SET_PWM, cmd_params=f'{percent_cmd_param:04d}')
        if result is COMMUNICATION_ERROR_SENTINEL: return COMMUNICATION_ERROR_SENTINEL
        return bool(result) # 如果不是哨兵，则将其转换为布尔值 (例如，如果 query 返回响应字符串则为 True)


    def set_switch(self, command_enum_val: WeatherCommand) -> bool | object: # 参数改为枚举值
        """Sets the PWM value.

        Returns:
            True if successful, False otherwise.
        """
        # 确保传入的是 G 或 H 命令
        if command_enum_val not in [WeatherCommand.SET_SWITCH_OPEN, WeatherCommand.SET_SWITCH_CLOSED]:
            if self._verbose_logging: print(f"[red]无效的 set_switch 命令: {command_enum_val}")
            return False # 或抛出 ValueError

        result = self.query(command_enum_val) # query 会发送 G! 或 H!
        if result is COMMUNICATION_ERROR_SENTINEL: return COMMUNICATION_ERROR_SENTINEL
        # 通常 G! H! 只返回握手。如果 query 成功解析握手并返回（例如）True 或响应块，则认为成功
        return bool(result) # 假设 query 在成功时返回非哨兵的真值

    def get_wind_speed(self, skip_averaging: bool = False) -> float | None: # skip_averaging 已存在
        if not self.has_anemometer: return None
        raw_val = self.query(WeatherCommand.GET_WINDSPEED) # query 返回 float 或哨兵
        if raw_val is COMMUNICATION_ERROR_SENTINEL: return COMMUNICATION_ERROR_SENTINEL
        if raw_val is not None:
            try:
                ws_val = float(raw_val)
                if ws_val == 0: return 0.0
                #按照新型号的风速计处理
                return round((ws_val * 0.84) + 3.0, 2) # km/h
            except (ValueError, TypeError): return None
        return None

    def get_switch_status_custom(self) -> str | None: # F!
        """Get the switch value.
        Returns:
            open,close,None.
        """
        val = self.query(WeatherCommand.GET_SWITCH_STATUS) # query 返回 "open", "close", None, 或哨兵
        if val is COMMUNICATION_ERROR_SENTINEL: return COMMUNICATION_ERROR_SENTINEL
        return val 

    def format_reading_for_solo_dict(self, current_reading_dict: dict | None = None) -> dict:
         # ... (此方法逻辑保持不变，它基于已传入的 reading 字典进行格式化) ...
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
            try: clouds_val = round(float(sky_t_val) - float(amb_t_val), 2)
            except (ValueError, TypeError): pass

        temp_val_get = current_reading_dict.get('ambient_temp')
        temp_val = round(temp_val_get if temp_val_get is not None else 0.0, 2)
        
        wind_val_get = current_reading_dict.get('wind_speed')
        wind_val = round(wind_val_get if wind_val_get is not None else 0.0, 2) 
        
        gust_val = wind_val # 沿用风速值作为阵风值
        
        rain_val_get = current_reading_dict.get('rain_frequency')
        rain_val = int(rain_val_get if rain_val_get is not None else 0)

        lightmpsas_val_get = current_reading_dict.get('sky_quality_mpsas')
        lightmpsas_val = round(lightmpsas_val_get if lightmpsas_val_get is not None else 0.0, 2)
        
        # Switch: open / close /none
  
        switch_val = current_reading_dict.get('switch')

        safe_val = 1 if current_reading_dict.get('is_safe', False) else 0
        
        hum_val_get = current_reading_dict.get('humidity')
        hum_val = round(hum_val_get if hum_val_get is not None else 0.0, 2)
        
        dewp_val_get = current_reading_dict.get('dew_point')
        dewp_val = round(dewp_val_get if dewp_val_get is not None else 0.0, 2)

        rawir_val_get = current_reading_dict.get('sky_temp')
        rawir_val = round(rawir_val_get if rawir_val_get is not None else 0.0, 2)

        abspress_hpa = 0.0
        abs_p_pa = current_reading_dict.get('pressure')
        if abs_p_pa is not None:
            try: abspress_hpa = round(float(abs_p_pa) / 100.0, 2)
            except (ValueError, TypeError): 
                 if self._verbose_logging: print(f"[yellow]警告：无法转换绝对气压值 '{abs_p_pa}' for SOLO")
        
        relpress_hpa = 0.0
        rel_p_pa = current_reading_dict.get('pres_pressure')
        if rel_p_pa is not None:
            try: relpress_hpa = round(float(rel_p_pa) / 100.0, 2)
            except (ValueError, TypeError): 
                if self._verbose_logging: print(f"[yellow]警告：无法转换相对气压值 '{rel_p_pa}' for SOLO")

        solo_data = {
            "dataGMTTime": data_gmt_time_str, "cwinfo": cwinfo_str, "clouds": clouds_val,
            "temp": temp_val, "wind": wind_val, "gust": gust_val, "rain": int(rain_val),
            "lightmpsas": lightmpsas_val, "switch": switch_val, "safe": safe_val,
            "hum": int(hum_val), "dewp": dewp_val, "rawir": rawir_val,
            "abspress": abspress_hpa, "relpress": relpress_hpa
        }
        
        # 根据 SOLO 规范，可能还需要一个 error 字段，如果一切正常可以为 0 或 "OK"
        # solo_data["error"] = 0 # 或者根据实际情况设置

        return solo_data

    def query(self, cmd: WeatherCommand, return_codes: bool = False, parse_type: type = float, cmd_params: str = '', verbose: bool = False) -> list | str | float | int | bool | None | object:
        # (能处理多块响应的 query 版本)
        effective_verbose = verbose or self._verbose_logging

        try:
            # 首先检查 _sensor 对象和串口是否已打开，这是进行任何 I/O 的前提
            if not hasattr(self, '_sensor') or self._sensor is None:
                self.last_error_message = f"Query ({cmd.name}) 错误: _sensor 对象不存在。"
                # 这种情况下，状态应该已经是 ERROR 或 INITIALIZING
                if self._connection_status != ConnectionStatus.ERROR and self._connection_status != ConnectionStatus.INITIALIZING:
                     self._connection_status = ConnectionStatus.ERROR
                return COMMUNICATION_ERROR_SENTINEL

            if not self._sensor.is_open:
                self.last_error_message = f"Query ({cmd.name}) 错误: 串口未打开。"
                # 如果 connect() 正在调用 query，那么串口应该已经被打开了。
                # 如果是其他地方调用，且串口意外关闭，则标记为 DISCONNECTED。
                if self._connection_status == ConnectionStatus.CONNECTED: 
                    self._connection_status = ConnectionStatus.DISCONNECTED
                elif self._connection_status != ConnectionStatus.ATTEMPTING_RECONNECT: # 避免在重连尝试中覆盖为ERROR
                    self._connection_status = ConnectionStatus.ERROR
                return COMMUNICATION_ERROR_SENTINEL

            self.write(cmd, cmd_params=cmd_params) 
            response_data_parts = self.read(verbose=effective_verbose) 

        except SensorCommunicationError as e:
            # write 或 read 方法内部已经更新了 _connection_status 和 last_error_message
            if effective_verbose: print(f"[red]Query ({cmd.name}) 失败 (捕获自 write/read): {e}")
            return COMMUNICATION_ERROR_SENTINEL

        #增加对 response_data_parts 类型的严格检查 ---    
        if response_data_parts is COMMUNICATION_ERROR_SENTINEL: 
             if effective_verbose: print(f"[red]Query ({cmd.name}) 失败，read 方法返回通信错误哨兵。")
             return COMMUNICATION_ERROR_SENTINEL

        if isinstance(response_data_parts, str): # 如果 read 返回了原始字符串
            return response_data_parts #通常不用于常规 query

        # 期望 read() 在成功时返回列表，如果不是列表（且不是哨兵或字符串），则视为错误
        if not isinstance(response_data_parts, list):
            if effective_verbose: print(f"[red]Query ({cmd.name}) 失败，read 方法返回了意外的类型: {type(response_data_parts)}。")
            self.last_error_message = f"Query ({cmd.name}) 内部错误: read返回意外类型 {type(response_data_parts)}"
            # 只有在之前状态是 CONNECTED 时才更新为 ERROR，避免在重连尝试中过早标记
            if self._connection_status == ConnectionStatus.CONNECTED:
                self._connection_status = ConnectionStatus.ERROR
            elif self._connection_status == ConnectionStatus.ATTEMPTING_RECONNECT:
                self._connection_status = ConnectionStatus.ERROR # 在连接尝试中，这也是一个错误
            return COMMUNICATION_ERROR_SENTINEL

        # --- 从这里开始，假设 write 和 read 本身没有抛出 SensorCommunicationError ---
        # 到这里，response_data_parts 必须是一个列表
        if not response_data_parts: # 空列表，表示没有收到有效数据块
            if effective_verbose: print(f"[yellow]Query ({cmd.name}): 未收到有效数据块。")
            # 这不一定是通信中断，可能是设备没有响应特定命令，或者响应格式问题
            # 但为了安全，如果关键命令无响应，也可能视为一种通信问题
            # 暂时返回 None，让上层决定如何处理
            return None 

        # 对于预期返回多个数据块的命令 (如 "C!", "D!")
        if cmd in [WeatherCommand.GET_VALUES, WeatherCommand.GET_INTERNAL_ERRORS]:
            return response_data_parts  # 这些命令预期返回列表

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
                    if parse_type is bool: # 特殊处理布尔型，通常基于字符串内容
                        return value_str.upper() == 'TRUE' or value_str.upper() == 'Y' # 示例
                    return parse_type(value_str)
                except (ValueError, TypeError):
                    if effective_verbose: print(f"[yellow]无法将 '{value_str}' 解析为 {parse_type} (命令: {cmd.name})")
                    return value_str # 返回原始字符串如果解析失败
        
        if effective_verbose: print(f"[yellow]命令 {cmd.name} 预期单个数据块，但收到多个: {response_data_parts}。将尝试返回第一个。")
        if response_data_parts: # 尝试返回第一个块的值作为备用
            try: 
                first_val_str = response_data_parts[0][2:].strip()
                if parse_type is bool: return first_val_str.upper() == 'TRUE' or first_val_str.upper() == 'Y'
                return parse_type(first_val_str)
            except: return response_data_parts[0][2:].strip()

        return None # 如果所有情况都不匹配，返回 None

    def write(self, cmd: WeatherCommand, cmd_params: str = '', cmd_delim: str = '!') -> int:
        # 
        full_cmd = f'{cmd.value}{cmd_params}{cmd_delim}'

        if not hasattr(self, '_sensor') or self._sensor is None: # 检查 _sensor 是否存在
            self.last_error_message = "写入错误: _sensor 对象不存在。"
            self._connection_status = ConnectionStatus.ERROR
            raise SensorCommunicationError(self.last_error_message)


        if not self._sensor.is_open:
            try:
                if self._verbose_logging: print("[grey]写入前串口未打开，尝试打开...")
                # 不应该在 write 中自动打开，连接管理应由 connect() 负责
                # 如果到这里串口还未打开，说明连接已断开或从未成功
                self.last_error_message = f"写入命令 '{full_cmd}' 失败：串口未打开。"
                self._connection_status = ConnectionStatus.DISCONNECTED # 或 ERROR
                raise SensorCommunicationError(self.last_error_message)
            except serial.SerialException as e: # self._sensor.open() 可能抛出
                self.last_error_message = f"写入前重新打开串口失败: {e}"
                self._connection_status = ConnectionStatus.ERROR
                raise SensorCommunicationError(self.last_error_message) from e
        try:
            self._sensor.reset_input_buffer()
            self._sensor.reset_output_buffer()
            num_bytes = self._sensor.write(full_cmd.encode())
            self._sensor.flush()
            return num_bytes
        except serial.SerialException as e:
            self.last_error_message = f"写入命令 '{full_cmd}' 到串口时发生错误: {e}"
            self._connection_status = ConnectionStatus.ERROR # 标记为错误
            if self._verbose_logging: print(f"[red]{self.last_error_message}")
            raise SensorCommunicationError(self.last_error_message) from e
        except Exception as e: # 其他意外错误
            self.last_error_message = f"写入时发生意外错误 ({cmd.name}): {e}"
            self._connection_status = ConnectionStatus.ERROR
            if self._verbose_logging: print(f"[red]{self.last_error_message}")
            raise SensorCommunicationError(self.last_error_message) from e


    def read(self, return_raw: bool = False, verbose: bool = False) -> list | str:
        # (能处理多块响应的 read 版本)
        effective_verbose = verbose or self._verbose_logging
        if not hasattr(self, '_sensor') or self._sensor is None:
            self.last_error_message = "读取错误: _sensor 对象不存在。"
            self._connection_status = ConnectionStatus.ERROR
            raise SensorCommunicationError(self.last_error_message)

        if not self._sensor.is_open:
            self.last_error_message = "读取错误: 串口未打开。"
            # 状态可能已是 DISCONNECTED 或 ERROR，这里再次确认
            if self._connection_status == ConnectionStatus.CONNECTED: # 如果之前认为是连接的，现在发现串口关闭
                self._connection_status = ConnectionStatus.DISCONNECTED
            else:
                self._connection_status = ConnectionStatus.ERROR    
            if effective_verbose: print(f"[red]{self.last_error_message}")
            raise SensorCommunicationError(self.last_error_message)
        
        full_response_decoded = ""
        all_data_blocks_content = [] # 存储 "XXyyyyyyyyyyyy" 格式的块内容

        # Read until the specific handshake sequence is found at the end of a 15-byte block
        # The full handshake block is "!<XON><12 spaces>0"
        buffer = b''
        full_handshake_bytes = b"!" + self.handshake_block_content.encode()

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

            # Read in a loop until handshake is detected or timeout occurs (implicit via serial timeout)
            # 循环读取，直到找到握手或没有更多数据（超时）
            # max_attempts = 10 # 限制尝试次数，防止意外的无限循环
            # for _ in range(max_attempts):
            #     bytes_in_waiting = self._sensor.in_waiting
            #     if bytes_in_waiting > 0:
            #         buffer += self._sensor.read(bytes_in_waiting)
            #     else: # 没有数据了，或者第一次就没数据
            #         if not buffer: # 如果缓冲区为空且没读到数据，可能是超时
            #             break 
            #     # 检查是否已包含完整握手
            #     if full_handshake_bytes in buffer: # 改为检查是否包含，而不仅仅是结尾
            #         break
            #     time.sleep(0.05) # 短暂延时再次检查

            # 使用 read_until，但需要确保它能正确处理

            try:
                buffer = self._sensor.read_until(expected=full_handshake_bytes)
            except serial.SerialTimeoutException: # 虽然 timeout 在 open 时设置，但 read_until 也可能触发
                if effective_verbose: print(f"[yellow]读取时发生串口超时 (read_until)。")
                # buffer 中可能已有部分数据
            
            if not buffer and self._sensor.in_waiting > 0: 
                 if effective_verbose: print(f"[grey]read_until 返回空但 in_waiting ({self._sensor.in_waiting}) > 0, 尝试直接读取...")
                 buffer += self._sensor.read(self._sensor.in_waiting) 

            full_response_decoded = buffer.decode(errors='ignore')

            if effective_verbose: print(f'读取的原始响应 (解码后): {full_response_decoded!r}')

            if return_raw:
                return full_response_decoded

            #如果 read_until() 返回空数据，或者返回的数据不以预期的握手信号结束，这应该被视为一个明确的通信问题（设备未响应或响应不正确）
            if not full_response_decoded or not full_response_decoded.endswith(full_handshake_bytes.decode(errors='ignore')):
                error_msg = "响应为空或未以预期握手结束。"
                if full_response_decoded: # 如果有部分响应，包含在错误信息中
                    error_msg += f" 响应: {full_response_decoded!r}"
                else:
                    error_msg += " (设备无响应或串口超时)"
                
                if effective_verbose: print(f"[yellow]{error_msg}")
                
                # 只有在之前状态是 CONNECTED 时才更新为 ERROR，避免在重连尝试中过早标记
                if self._connection_status == ConnectionStatus.CONNECTED:
                    self.last_error_message = error_msg
                    self._connection_status = ConnectionStatus.ERROR 
                elif self._connection_status == ConnectionStatus.ATTEMPTING_RECONNECT:
                     # 在连接尝试期间，如果 read 失败，也应该认为是错误
                    self.last_error_message = error_msg
                    self._connection_status = ConnectionStatus.ERROR

                return COMMUNICATION_ERROR_SENTINEL # 返回哨兵，指示通信失败

            data_to_parse = full_response_decoded
            # 移除末尾的握手块 (包括 '!')
            data_to_parse = data_to_parse[:-len(full_handshake_bytes)]
            
            idx = 0

            while (idx + 15) <= len(data_to_parse):
                block = data_to_parse[idx:idx + 15]

                if not block.startswith('!'):
                    if effective_verbose: print(f"[yellow]预期数据块以 '!' 开始，但得到: {block!r}")
                    # 如果数据块格式错误，后续解析可能无意义
                    break 
                all_data_blocks_content.append(block[1:])
                idx += 15
            
            if idx < len(data_to_parse) and effective_verbose:
                    print(f"[yellow]解析数据块后仍有剩余字符: {data_to_parse[idx:]!r}")

            return all_data_blocks_content

        except serial.SerialException as e:
            self.last_error_message = f"串口读取错误: {e}"
            self._connection_status = ConnectionStatus.ERROR
            if effective_verbose: print(f"[red]{self.last_error_message}")
            raise SensorCommunicationError(self.last_error_message) from e
        except Exception as e: # 其他意外错误
            self.last_error_message = f"读取或解析传感器响应时发生意外错误: {e}"
            self._connection_status = ConnectionStatus.ERROR
            if effective_verbose: print(f"[red]{self.last_error_message}")
            raise SensorCommunicationError(self.last_error_message) from e

    def __str__(self):
        return f'CloudSensor({self.name}, FW={self.firmware}, SN={self.serial_number}, Port={self.config.serial_port}, Status={self._connection_status.value})'

    def __del__(self):
        if hasattr(self, '_sensor') and self._sensor and self._sensor.is_open:
            if self._verbose_logging: print('[grey]CloudSensor 对象销毁，关闭串口连接...')
            try:
                self._sensor.close()
            except Exception as e: # pylint: disable=broad-except
                if self._verbose_logging: print(f"[red]关闭串口时发生错误: {e}")
