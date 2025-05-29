import json # 导入 json 模块
from pathlib import Path # 导入 Path 模块
from typing import Optional, Any, List as PyList # Renamed List to PyList to avoid conflict with Pydantic
from datetime import datetime, timezone # 导入 timezone
from fastapi import FastAPI, HTTPException # 导入 HTTPException
from fastapi_utils.tasks import repeat_every
from pydantic import BaseModel # For new /state response model

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
    last_successful_reading_at_utc: Optional[datetime] = None
    last_error_message: Optional[str] = None
    last_connection_attempt_at_utc: Optional[datetime] = None
    current_server_time_utc: datetime
    capture_delay_seconds: Optional[float] = None
    readings_buffer_size: Optional[int] = None
    readings_in_buffer: Optional[int] = None

@app.on_event('startup')
def init_sensor():
    global sensor
    print("[cyan]Initializing CloudSensor...")
    try:
        # CloudSensor.__init__ 调用 self.connect(raise_exceptions=True)
        # 如果失败，会抛出 SensorCommunicationError
        sensor = CloudSensor(connect=True) 
        if sensor.is_connected: # is_connected 现在基于 ConnectionStatus.CONNECTED
            print(f"[green]CloudSensor initialized and connected successfully. Status: {sensor.connection_status.value}")
        else:
            # 理论上，如果 connect=True 且失败，__init__ 会抛异常，不会到这里。
            # 但为保险起见，记录一下。
            # CloudSensor 的 __init__ 在 connect=True 且失败时会抛出 SensorCommunicationError
            # 所以这里的 else 分支通常不会被执行，除非 CloudSensor 的 __init__ 逻辑改变
            print(f"[red]CloudSensor initialization finished but sensor not connected. Status: {sensor.connection_status.value if sensor else 'N/A'}, Error: {sensor.last_error_message if sensor else 'Sensor object is None'}")
    except SensorCommunicationError as e: # 捕获来自 CloudSensor 的特定初始化错误
        print(f"[red]Critical SensorCommunicationError during CloudSensor initialization: {e}")
        sensor = None # 确保 sensor 为 None
    except Exception as e:
        print(f"[red]Unexpected critical error during CloudSensor initialization: {e}")
        import traceback
        traceback.print_exc()
        sensor = None # 确保 sensor 为 None


@app.on_event('startup')
@repeat_every(seconds=PERIODIC_TASK_INTERVAL_SECONDS, wait_first=True) # wait_first=True 表示启动时会立即执行一次
def periodic_sensor_reading_task():
    global sensor
    current_time_utc = datetime.now(timezone.utc)
    verbose_logging_enabled = False # 默认关闭，除非从 sensor.config 获取

    if sensor is None:
        print(f"[{current_time_utc.isoformat()}] server.py: Sensor object not initialized. Skipping periodic reading.")
        # 可以在这里尝试重新初始化，但这可能导致无限循环，如果初始化持续失败
        # init_sensor() # 谨慎使用，或添加重试次数限制
        return

    # 从 sensor.config 获取 verbose_logging 设置
    # 需要确保 sensor 对象存在才能访问其 config
    if hasattr(sensor, 'config') and sensor.config is not None:
        verbose_logging_enabled = getattr(sensor.config, 'verbose_logging', False)
    else: # 如果 sensor 对象存在但没有 config (理论上不太可能，除非 CloudSensor 构造不完整)
        if verbose_logging_enabled: # 使用上面定义的默认值
             print(f"[{current_time_utc.isoformat()}] server.py: Warning - sensor.config not found, using default verbose_logging ({verbose_logging_enabled})")


    # 检查连接状态，如果未连接则尝试重连
    if sensor.connection_status != ConnectionStatus.CONNECTED:
        # 只有在状态不是 ATTEMPTING_RECONNECT 时才打印“尝试重连”，避免重复日志
        if sensor.connection_status != ConnectionStatus.ATTEMPTING_RECONNECT:
            print(f"[{current_time_utc.isoformat()}] server.py: Sensor not connected (Status: {sensor.connection_status.value}, LastError: {sensor.last_error_message}). Attempting to reconnect...")
        
        reconnected = sensor.connect(raise_exceptions=False) # 在周期任务中不应抛出致命异常
        
        if reconnected:
            print(f"[{datetime.now(timezone.utc).isoformat()}] server.py: Sensor reconnected successfully. Status: {sensor.connection_status.value}")
        else:
            # connect 方法内部会更新 last_error_message 和 connection_status
            if verbose_logging_enabled or sensor.connection_status != ConnectionStatus.ATTEMPTING_RECONNECT : # 避免在快速重试时过多日志
                print(f"[{datetime.now(timezone.utc).isoformat()}] server.py: Sensor reconnection failed. Status: {sensor.connection_status.value}, Error: {sensor.last_error_message}")
            return # 重连失败，则本次不尝试读取

    # 如果传感器已连接 (或刚刚重连成功)
    if sensor.connection_status == ConnectionStatus.CONNECTED:
        if verbose_logging_enabled:
            print(f"[{current_time_utc.isoformat()}] server.py: >>> Sensor connected. Calling sensor.get_reading()...")
        
        start_time = datetime.now(timezone.utc)
        try:
            # get_reading 现在返回 None 如果当次读取因通信问题失败 (并且不会更新 sensor.readings)
            new_reading_data = sensor.get_reading(avg_times=1, units='none', verbose=verbose_logging_enabled)
            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()

            if new_reading_data is not None:
                if verbose_logging_enabled:
                    print(f"[{end_time.isoformat()}] server.py: <<< sensor.get_reading() successful in {duration:.2f} seconds.")
                
                # --- SOLO 文件写入逻辑 ---
                if hasattr(sensor.config, 'solo_data_file_path') and sensor.config.solo_data_file_path:
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
                # get_reading 返回 None，表示本次读取无效
                # CloudSensor.get_reading() 内部已更新状态并可能记录错误
                if verbose_logging_enabled:
                    print(f"[{end_time.isoformat()}] server.py: <<< sensor.get_reading() returned None (no valid data obtained this cycle). Duration: {duration:.2f}s. Sensor Status: {sensor.connection_status.value}, Last Error: {sensor.last_error_message}")

        except Exception as e_get_reading: 
            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()
            print(f"[red][{end_time.isoformat()}] server.py: !!! Unexpected error during sensor.get_reading() call after {duration:.2f} seconds: {e_get_reading}")
            import traceback
            traceback.print_exc()
            # 这种意外错误可能需要将传感器状态标记为 ERROR
            if sensor: # 确保 sensor 对象存在
                 sensor._connection_status = ConnectionStatus.ERROR # 直接访问内部状态（或者添加一个方法）
                 sensor.last_error_message = f"Unexpected error in get_reading task: {e_get_reading}"

# 新增：/state API 端点
@app.get('/state', response_model=SensorStateResponse, summary="获取传感器和服务的当前状态")
def get_sensor_state():
    global sensor
    current_time = datetime.now(timezone.utc)

    if sensor is None:
        return SensorStateResponse(
            service_status="NOT_INITIALIZED", 
            last_error_message="Sensor object is None. Service might be starting or failed to initialize.",
            current_server_time_utc=current_time
        )

    # 确保 sensor.config 存在
    capture_delay = None
    serial_p = None
    if hasattr(sensor, 'config') and sensor.config is not None:
        capture_delay = getattr(sensor.config, 'capture_delay', None)
        serial_p = getattr(sensor.config, 'serial_port', None)


    return SensorStateResponse(
        service_status=sensor.connection_status.value,
        sensor_name=sensor.name,
        serial_port=serial_p,
        firmware_version=sensor.firmware,
        serial_number=sensor.serial_number,
        last_successful_reading_at_utc=sensor.last_successful_read_timestamp,
        last_error_message=sensor.last_error_message,
        last_connection_attempt_at_utc=sensor.last_connection_attempt_timestamp,
        current_server_time_utc=current_time,
        capture_delay_seconds=capture_delay,
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

