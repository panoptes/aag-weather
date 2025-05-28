import json # 导入 json 模块
from pathlib import Path # 导入 Path 模块
from typing import Optional, Any # 导入 Any
from datetime import datetime, timezone # 导入 timezone
from fastapi import FastAPI, HTTPException # 导入 HTTPException
from fastapi_utils.tasks import repeat_every

from aag.weather import CloudSensor # 假设 CloudSensor 在 aag.weather 中
# from aag.solo_formatter import format_reading_for_solo # 如果您将辅助函数放在单独文件

app = FastAPI()

sensor: Optional[CloudSensor] = None


@app.on_event('startup')
def init_sensor():
    global sensor
    print("[cyan]Initializing CloudSensor...")
    try:
        sensor = CloudSensor(connect=True) # 确保连接
        if sensor.is_connected:
            print("[green]CloudSensor initialized and connected successfully.")
        else:
            print("[red]CloudSensor initialization failed to connect.")
    except Exception as e:
        print(f"[red]Critical error during CloudSensor initialization: {e}")
        # 在这种情况下，服务可能无法正常工作，后续请求会失败


@app.on_event('startup')
@repeat_every(seconds=30, wait_first=True) # wait_first=True 表示启动时会立即执行一次
def periodic_sensor_reading_task(): # 重命名以更清晰地表示其目的
    global sensor
    if sensor is None or not sensor.is_connected:
        print(f"[{datetime.now(timezone.utc).isoformat()}] server.py: Sensor not available or not connected. Skipping periodic reading.")
        # 可以在这里尝试重新连接，或者等待下一次 init_sensor (如果服务重启)
        # 例如: 
        # if sensor is None: init_sensor() # 尝试重新初始化
        # elif not sensor.is_connected: 
        #     print("[yellow]Attempting to reconnect sensor...")
        #     sensor.connect(raise_exceptions=False)
        return

    start_time = datetime.now(timezone.utc)
    verbose_logging_enabled = getattr(sensor.config, 'verbose_logging', False)
    print(f"[{start_time.isoformat()}] server.py: >>> Calling sensor.get_reading()...")
    try:
        # avg_times=1 与您之前的设定一致
        # get_reading 现在返回不带单位的字典，可以直接用于存储和后续处理
        result = sensor.get_reading(avg_times=1, units='none', verbose=verbose_logging_enabled)
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()
        if verbose_logging_enabled:
            print(f"[{end_time.isoformat()}] server.py: <<< sensor.get_reading() completed in {duration:.2f} seconds.")
        # sensor.get_reading() 内部已经将结果追加到 self.readings
        # 此处的 result 变量可以用于其他即时处理（如果需要）

                # --- 集成：将获取到的 result (即最新的读数) 转换为SOLO格式并写入文件 ---
        # 检查是否配置了 solo_data_file_path 并且 result (天气读数) 是否有效
        if hasattr(sensor.config, 'solo_data_file_path') and sensor.config.solo_data_file_path and result:
            try:
                # 调用 sensor 对象的方法将 result (即 latest_panoptes_reading) 转换为SOLO格式字典
                solo_output_dict = sensor.format_reading_for_solo_dict(result) 
                
                # 确保输出目录存在
                output_path = Path(sensor.config.solo_data_file_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                # 写入临时文件然后重命名，以尽量保证原子性
                temp_file_path = output_path.with_suffix(output_path.suffix + '.tmp')
                with open(temp_file_path, 'w', encoding='utf-8') as f:
                    json.dump(solo_output_dict, f, indent=None, separators=(',', ':')) # 紧凑格式
                
                temp_file_path.replace(output_path) # 原子性替换/重命名
                
                if verbose_logging_enabled:
                    print(f"[{datetime.now(timezone.utc).isoformat()}] server.py: SOLO format data successfully written to {output_path}")

            except Exception as e:
                # 文件写入specific的错误日志
                print(f"[red][{datetime.now(timezone.utc).isoformat()}] server.py: Error writing SOLO data to file {sensor.config.solo_data_file_path}: {e}")
        # --- 文件写入逻辑结束 ---

    except Exception as e:
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()
        print(f"[red][{end_time.isoformat()}] server.py: !!! Error in sensor.get_reading() after {duration:.2f} seconds: {e}")
        # 可以在这里添加更详细的错误日志或通知机制


@app.get('/weather', summary="获取原始格式的最新天气数据列表")
def get_all_weather_readings(): # 函数名可以更明确
    global sensor
    if sensor is None or not sensor.is_connected:
        raise HTTPException(status_code=503, detail="天气传感器未初始化或未连接。")
    
    if not sensor.readings: # 检查是否有读数
        return [] # 或者返回一个表示无数据的适当响应
        
    # sensor.readings 是一个 deque，直接返回它 FastAPI 会处理序列化
    # 它包含的是不带 astropy 单位的字典列表
    return list(sensor.readings) # 返回 deque 的列表副本


@app.get('/weather/latest', summary="获取原始格式的最新一条天气数据")
def get_latest_weather_reading():
    global sensor
    if sensor is None or not sensor.is_connected:
        raise HTTPException(status_code=503, detail="天气传感器未初始化或未连接。")

    latest_reading = sensor.status # 使用 status 属性获取最新读数
    if not latest_reading: # 如果 status 返回空字典
        raise HTTPException(status_code=404, detail="尚无天气数据可用。")
    return latest_reading


@app.get('/weather/solo', summary="获取 SOLO 格式的最新天气数据")
async def serve_weather_solo_format(): # 函数名保持与之前讨论一致
    global sensor
    if sensor is None: # 传感器对象本身未创建
        print("[red]错误 (SOLO): Sensor object is None. Service might not have started correctly.")
        raise HTTPException(status_code=503, detail="天气传感器服务未正确初始化。")
    
    if not sensor.is_connected:
        print("[yellow]警告 (SOLO): Sensor not connected. Attempting to serve last known data if available, or erroring out.")
        # 即使未连接，如果仍有旧数据，也可以选择服务旧数据或报错
        # 这里我们选择报错，因为SOLO格式可能需要实时或近乎实时的开关状态
        raise HTTPException(status_code=503, detail="天气传感器当前未连接。")
    
    # 获取最新的读数（不带单位的字典）
    latest_panoptes_reading = sensor.status 
    
    if not latest_panoptes_reading: # 如果 status 返回空字典 (例如，刚启动还没有读数)
        raise HTTPException(status_code=404, detail="尚无天气数据可用以生成SOLO格式。")
        
    try:
        # 调用 CloudSensor 实例的方法来格式化数据
        solo_output = sensor.format_reading_for_solo_dict(latest_panoptes_reading)
        return solo_output
    except Exception as e:
        print(f"[red]生成 SOLO 格式数据时出错: {e}")
        # 可以考虑打印更详细的堆栈跟踪进行调试
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取 SOLO 天气数据时发生内部错误: {str(e)}")

