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


class WeatherResponseCodes(StrEnum):
    """ Response Codes (from Rs232_Comms_v100.pdf) """
    GET_SKY_TEMP = '1 '
    GET_SENSOR_TEMP = '2 '
    GET_VALUES_AMBIENT = '3 '
    GET_VALUES_LDR_VOLTAGE = '4 '
    GET_VALUES_SENSOR_TEMP = '5 '
    GET_VALUES_ZENER_VOLTAGE = '6 '
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
    HANDSHAKE = '\x11 '
