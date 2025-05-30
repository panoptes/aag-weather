print("--- SERVER.PY VERSION CHECK: v5.0 - FINAL CHECK MAY 29 ---") # <--- 使用一个全新的标记!
import json # 导入 json 模块
import asyncio # 导入 asyncio
from pathlib import Path # 导入 Path 模块
from typing import Optional, Any, List as PyList # Renamed List to PyList to avoid conflict with Pydantic
from datetime import datetime, timezone # 导入 timezone
from fastapi import FastAPI, HTTPException # 导入 HTTPException
#from fastapi_utils.tasks import repeat_every
from pydantic import BaseModel # For new /state response model
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError # 导入 zoneinfo

# 从 aag.weather 导入增强后的 CloudSensor 和新的 ConnectionStatus 枚举
from aag.weather import CloudSensor, ConnectionStatus, SensorCommunicationError  # 假设 CloudSensor 在 aag.weather 中
# from aag.solo_formatter import format_reading_for_solo # 如果您将辅助函数放在单独文件
# 从 aag.settings 导入 WeatherSettings 以便在模块加载时读取配置
from aag.settings import WeatherSettings

app = FastAPI()

sensor: Optional[CloudSensor] = None

PERIODIC_TASK_INTERVAL_SECONDS = 30  # Default value
try:
    # 尝试加载配置以获取任务执行间隔
    # 这将在服务启动时从环境变量或 .env 文件读取
    _task_settings = WeatherSettings()
    # 使用现有的 capture_delay 作为周期任务的执行间隔
    PERIODIC_TASK_INTERVAL_SECONDS = _task_settings.capture_delay
    print(f"[info]Periodic task interval set to: {PERIODIC_TASK_INTERVAL_SECONDS} seconds (from configuration).")
except NameError as ne:
    # 特别捕获 NameError
    print(f"[yellow]Warning: 'WeatherSettings' is not defined when trying to configure task interval at module level. This might be due to an import cycle or an issue within 'settings.py'. Using default task interval {PERIODIC_TASK_INTERVAL_SECONDS}s. Specific error: {ne}")
except Exception as e_cfg:
    # 如果加载配置失败（非 NameError），使用默认值并打印警告
    print(f"[yellow]Warning: Could not load WeatherSettings for task interval (Error type: {type(e_cfg).__name__}), using default {PERIODIC_TASK_INTERVAL_SECONDS}s. Error: {e_cfg}")
    
# 新增：用于 /state 端点的 Pydantic 响应模型
class SensorStateResponse(BaseModel):
    service_status: str 
    sensor_name: Optional[str] = None
    serial_port: Optional[str] = None
    firmware_version: Optional[str] = None
    serial_number: Optional[str] = None
    last_successful_reading_at: Optional[datetime] = None 
    last_error_message: Optional[str] = None
    last_connection_attempt_at: Optional[datetime] = None 
    current_server_time: datetime 
    capture_delay_seconds: Optional[float] = None 
    readings_buffer_size: Optional[int] = None
    readings_in_buffer: Optional[int] = None

# 这个函数不再是启动事件，只是一个普通的初始化函数
def do_init_sensor():
    global sensor
    if sensor is None:
        print("[cyan]Attempting to initialize CloudSensor for the first time or after a previous failure...")
    else:
        print("[cyan]Attempting to re-initialize existing CloudSensor object (unexpected)...")

    try:
        sensor = CloudSensor(connect=True) 
        if sensor.is_connected: 
            print(f"[green]CloudSensor initialized and connected successfully. Status: {sensor.connection_status.value}")
        else:
            print(f"[red]CloudSensor initialization finished but sensor not connected. Status: {sensor.connection_status.value if sensor else 'N/A'}, Error: {sensor.last_error_message if sensor else 'Sensor object is None during init else clause'}")
            sensor = None 
    except SensorCommunicationError as e: 
        print(f"[red]SensorCommunicationError during CloudSensor initialization: {e}")
        sensor = None 
    except Exception as e:
        print(f"[red]Unexpected critical error during CloudSensor initialization: {e}")
        import traceback
        traceback.print_exc()
        sensor = None 



#@app.on_event('startup')
#@repeat_every(seconds=PERIODIC_TASK_INTERVAL_SECONDS, wait_first=True) # wait_first=True 表示启动时会立即执行一次
async def periodic_sensor_reading_task():
    """一个无限循环的后台任务，用于周期性地读取传感器数据。"""
    print("--- Background task `periodic_sensor_reading_task` has started. ---")
    while True:
        current_time_utc_for_log = datetime.now(timezone.utc)
        print(f"DEBUG: periodic_sensor_reading_task loop entered at {current_time_utc_for_log.isoformat()}")

        global sensor
        verbose_logging_enabled = False 

        if sensor is None:
            print(f"[{current_time_utc_for_log.isoformat()}] server.py: Sensor object is None. Attempting to re-initialize...")
            do_init_sensor() 
            if sensor is None: 
                print(f"[{datetime.now(timezone.utc).isoformat()}] server.py: Sensor re-initialization failed. Waiting for next cycle.")
                await asyncio.sleep(PERIODIC_TASK_INTERVAL_SECONDS)
                continue # 继续下一次循环
            else:
                print(f"[{datetime.now(timezone.utc).isoformat()}] server.py: Sensor re-initialized. Current status: {sensor.connection_status.value}")

        if hasattr(sensor, 'config') and sensor.config is not None:
            verbose_logging_enabled = getattr(sensor.config, 'verbose_logging', False)

        if sensor.connection_status != ConnectionStatus.CONNECTED:
            if sensor.connection_status != ConnectionStatus.ATTEMPTING_RECONNECT:
                if verbose_logging_enabled: 
                    print(
                        f"[{current_time_utc_for_log.isoformat()}] server.py: Sensor not connected.\n"
                        f"    - Status: {sensor.connection_status.value}\n"
                        f"    - LastError: {sensor.last_error_message}\n"
                        f"    - Attempting to reconnect..."
                    )
       
            reconnected = sensor.connect(raise_exceptions=False) 
            
            if verbose_logging_enabled:
                print(f"DEBUG SERVER: sensor.connect() call returned: {reconnected}. New sensor status: {sensor.connection_status.value}")
            
            if not reconnected:
                if verbose_logging_enabled or sensor.connection_status != ConnectionStatus.ATTEMPTING_RECONNECT : 
                    print(f"[{datetime.now(timezone.utc).isoformat()}] server.py: Sensor reconnection failed. Status: {sensor.connection_status.value}, Error: {sensor.last_error_message}")
                await asyncio.sleep(PERIODIC_TASK_INTERVAL_SECONDS)
                continue # 重连失败，继续下一次循环

        # 如果到这里，传感器应该是已连接状态
        if sensor.connection_status == ConnectionStatus.CONNECTED:
            if verbose_logging_enabled:
                print(f"[{current_time_utc_for_log.isoformat()}] server.py: >>> Sensor connected. Calling sensor.get_reading()...")
            
            #计算耗时用
            start_time = datetime.now(timezone.utc)
            
            try:
                new_reading_data = sensor.get_reading(avg_times=1, units='none', verbose=verbose_logging_enabled)
                
                end_time = datetime.now(timezone.utc)
                duration = (end_time - start_time).total_seconds()
                
                if new_reading_data is not None:
                    if verbose_logging_enabled:
                        print(f"[{end_time.isoformat()}] server.py: <<< sensor.get_reading() successful in {duration:.2f} seconds.")
                    
                    if hasattr(sensor.config, 'solo_data_file_path') and sensor.config.solo_data_file_path:
                        # (SOLO文件写入逻辑保持不变)
                        try:
                            solo_output_dict = sensor.format_reading_for_solo_dict(new_reading_data) 
                            output_path = Path(sensor.config.solo_data_file_path)
                            output_path.parent.mkdir(parents=True, exist_ok=True)
                            temp_file_path = output_path.with_suffix(output_path.suffix + '.tmp')
                            with open(temp_file_path, 'w', encoding='utf-8') as f:
                                json.dump(solo_output_dict, f, indent=None, separators=(',', ':'))
                            temp_file_path.replace(output_path)
                            if verbose_logging_enabled:
                                print(f"[{datetime.now(timezone.utc).isoformat()}] server.py: SOLO format data successfully written to {output_path}")
                        except Exception as e_solo:
                            print(f"[red][{datetime.now(timezone.utc).isoformat()}] server.py: Error writing SOLO data: {e_solo}")
                else:
                    if verbose_logging_enabled:
                        print(
                            f"[{datetime.now(timezone.utc).isoformat()}] server.py: <<< sensor.get_reading() returned None (no valid data obtained this cycle).\n"
                            f"    - Duration: {duration:.2f} seconds.\n" # 添加耗时
                            f"    - Sensor Status: {sensor.connection_status.value}\n"
                            f"    - Last Error: {sensor.last_error_message}"
                        )

            except Exception as e_get_reading: 
                end_time = datetime.now(timezone.utc)
                duration = (end_time - start_time).total_seconds()
                print(
                    f"[red][{end_time.isoformat()}] server.py: !!! Unexpected error during sensor.get_reading() call after {duration:.2f} seconds.\n"
                    f"    - Error: {e_get_reading}[/red]"
                )
                import traceback
                traceback.print_exc()
                if sensor: 
                     sensor._connection_status = ConnectionStatus.ERROR 
                     sensor.last_error_message = f"Unexpected error in get_reading task: {e_get_reading}"
        
        # 等待下一个周期
        await asyncio.sleep(PERIODIC_TASK_INTERVAL_SECONDS)

# --- 新增：新的启动事件，负责初始化和启动后台任务 ---
@app.on_event("startup")
async def startup_event():
    """在应用启动时执行。"""
    print("Application startup event triggered.")
    do_init_sensor() # 首先执行同步的初始化函数
    print("Background task scheduling...")
    asyncio.create_task(periodic_sensor_reading_task()) # 创建并启动后台任务
    print("Background task scheduled.")


# weather/state API 端点
@app.get('/weather/state', response_model=SensorStateResponse, summary="获取传感器和服务的当前状态")
def get_sensor_state():
    global sensor
    local_tz = timezone.utc 
    if sensor and hasattr(sensor, 'config') and sensor.config and hasattr(sensor.config, 'location') and sensor.config.location:
        try:
            local_tz = ZoneInfo(sensor.config.location.timezone)
        except ZoneInfoNotFoundError:
            if sensor and getattr(sensor, '_verbose_logging', False): 
                print(f"[yellow]Warning: Configured timezone '{sensor.config.location.timezone}' for /state endpoint not found. Falling back to UTC.[/yellow]")
        except Exception as tz_err:
            if sensor and getattr(sensor, '_verbose_logging', False):
                print(f"[red]Error setting timezone for /state endpoint: {tz_err}. Falling back to UTC.[/red]")

    current_server_time_local = datetime.now(local_tz)

    if sensor is None:
        return SensorStateResponse(
            service_status="NOT_INITIALIZED", 
            last_error_message="Sensor object is None. Service might be starting or failed to initialize.",
            current_server_time=current_server_time_local 
        )

    # 确保 sensor.config 存在
    capture_delay_val = None 
    serial_p = None
    if hasattr(sensor, 'config') and sensor.config is not None:
        capture_delay_val = getattr(sensor.config, 'capture_delay', None)
        serial_p = getattr(sensor.config, 'serial_port', None)

    last_successful_reading_local = None
    if sensor.last_successful_read_timestamp: 
        try:
            last_successful_reading_local = sensor.last_successful_read_timestamp.astimezone(local_tz)
        except Exception as e_tz_conv_succ:
             if getattr(sensor, '_verbose_logging', False): print(f"[red]Error converting last_successful_read_timestamp to local_tz: {e_tz_conv_succ}")


    last_connection_attempt_local = None
    if sensor.last_connection_attempt_timestamp: 
        try:
            last_connection_attempt_local = sensor.last_connection_attempt_timestamp.astimezone(local_tz)
        except Exception as e_tz_conv_att:
            if getattr(sensor, '_verbose_logging', False): print(f"[red]Error converting last_connection_attempt_timestamp to local_tz: {e_tz_conv_att}")

    return SensorStateResponse(
        service_status=sensor.connection_status.value,
        sensor_name=sensor.name,
        serial_port=serial_p,
        firmware_version=sensor.firmware,
        serial_number=sensor.serial_number,
        last_successful_reading_at=last_successful_reading_local, 
        last_error_message=sensor.last_error_message,
        last_connection_attempt_at=last_connection_attempt_local, 
        current_server_time=current_server_time_local, 
        capture_delay_seconds=capture_delay_val, 
        readings_buffer_size=sensor.readings.maxlen if hasattr(sensor, 'readings') and sensor.readings else None,
        readings_in_buffer=len(sensor.readings) if hasattr(sensor, 'readings') and sensor.readings else 0
    )


@app.get('/weather', summary="获取原始格式的最新天气数据列表")
def get_all_weather_readings() -> PyList[dict]: 
    global sensor
    if sensor is None:
        raise HTTPException(status_code=503, detail="天气传感器服务未正确初始化 (Sensor object is None)。")
    
    # 检查 readings 属性是否存在且不为 None
    if not hasattr(sensor, 'readings') or sensor.readings is None:
        # 这种情况理论上不应发生，如果 sensor 对象已创建
        raise HTTPException(status_code=500, detail="传感器数据队列 (readings) 未初始化。")

    if not sensor.readings: 
        # readings 队列为空，表示没有有效的历史数据
        # 可以返回空列表，让客户端判断
        return [] 
        
    return list(sensor.readings)


@app.get('/weather/latest', summary="获取原始格式的最新一条天气数据")
def get_latest_weather_reading():
    global sensor
    if sensor is None:
        raise HTTPException(status_code=503, detail="天气传感器服务未正确初始化 (Sensor object is None)。")

    if not hasattr(sensor, 'status'): 
         raise HTTPException(status_code=500, detail="传感器 'status' 属性不存在。")

    latest_reading = sensor.status # sensor.status 从 sensor.readings[-1] 获取
    
    if not latest_reading: # 如果 sensor.readings 为空，status 会返回 {}
        # 返回 404 表示资源未找到 (没有最新的天气数据)
        raise HTTPException(status_code=404, detail="尚无有效天气数据可用。")
    return latest_reading


@app.get('/weather/solo', summary="获取 SOLO 格式的最新天气数据")
async def serve_weather_solo_format():
    global sensor
    if sensor is None: 
        raise HTTPException(status_code=503, detail="天气传感器服务未正确初始化 (Sensor object is None)。")
    
    if not hasattr(sensor, 'status'): 
         raise HTTPException(status_code=500, detail="传感器 'status' 属性不存在。")

    latest_panoptes_reading = sensor.status 
    
    if not latest_panoptes_reading: 
        # 如果没有最新的有效读数，则无法生成SOLO格式
        # format_reading_for_solo_dict 在这种情况下会返回带错误信息的默认结构
        # 但从API角度，返回404更合适
        raise HTTPException(status_code=404, detail="尚无有效天气数据以生成SOLO格式。")
        
    try:
        # format_reading_for_solo_dict 内部会处理 current_reading_dict 为空的情况
        # 但我们已在此之前检查了 latest_panoptes_reading
        solo_output = sensor.format_reading_for_solo_dict(latest_panoptes_reading)
        return solo_output
    except Exception as e:
        print(f"[red]生成 SOLO 格式数据时发生错误: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取 SOLO 天气数据时发生内部错误: {str(e)}")

