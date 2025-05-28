from enum import StrEnum


class WeatherCommand(StrEnum):
    """ Command List (from Rs232_Comms_v100.pdf) """
    GET_INTERNAL_NAME = 'A'
    GET_FIRMWARE = 'B'
    GET_VALUES = 'C'
    GET_INTERNAL_ERRORS = 'D'
    GET_RAIN_FREQUENCY = 'E'
    GET_SWITCH_STATUS = 'F'
    SET_SWITCH_OPEN = 'G'
    SET_SWITCH_CLOSED = 'H'
    GET_SERIAL_NUMBER = 'K'
    GET_ELECTRICAL_CONSTANTS = 'M'
    SET_PWM = 'P'
    GET_PWM = 'Q'
    GET_SKY_TEMP = 'S'
    GET_SENSOR_TEMP = 'T'
    CAN_GET_WINDSPEED = 'v'
    GET_WINDSPEED = 'V'
    RESET_RS232 = 'z'

    GET_RH_SENSOR_TEMP      = 't'   # RH 传感器温度，更加准确
    GET_HUMIDITY            = 'h'   # 相对湿度 %
    GET_HUMIDITY_HIGH       = 'hh'  # 高分辨率湿度原始值
    GET_PRESSURE            = 'p'   # 大气压原始值 (Pa×16)
    GET_PRESSURE_TEMP       = 'q'   # 气压传感器温度 (°C×100)



class WeatherResponseCodes(StrEnum):
    """ Response Codes (from Rs232_Comms_v100.pdf) """
    GET_SKY_TEMP = '1 '
    GET_SENSOR_TEMP = '2 '
    GET_VALUES_AMBIENT = '3 '
    GET_VALUES_LDR_VOLTAGE = '4 '
    GET_VALUES_SENSOR_TEMP = '5 '
    GET_VALUES_ZENER_VOLTAGE = '6 '
    GET_VALUES_LIGHT_SENSOR = '8 '   #Rs323_Comms_v1.3.pdf
    CAN_GET_WINDSPEED = 'v '
    GET_WINDSPEED = 'w '
    GET_INTERNAL_ERROR_1 = 'E1'
    GET_INTERNAL_ERROR_2 = 'E2'
    GET_INTERNAL_ERROR_3 = 'E3'
    GET_INTERNAL_ERROR_4 = 'E4'
    GET_INTERNAL_NAME = 'N '
    GET_FIRMWARE = 'V '
    GET_SERIAL_NUMBER = 'K'
    GET_PWM = 'Q '
    SET_PWM = 'P'
    GET_RAIN_FREQUENCY = 'R '
    SWITCH_OPEN = 'X '
    SWITCH_CLOSED = 'Y '

    GET_HUMIDITY     = 'hh '
    GET_HUMIDITY_HIGH= 'hh'
    GET_PRESSURE     = 'p '
    GET_PRESSURE_TEMP= 'q '
    GET_RH_SENSOR_TEMP = 'th'

    HANDSHAKE = '\x11 '
