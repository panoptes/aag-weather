import os
import sqlite3
from loguru import logger

DB_FILE = os.getenv('DB_FILE', 'weather.db')


def setup_db(db_file=DB_FILE):
    # Setup the DB file
    return sqlite3.connect(db_file)


def store_result(data, db_table, db_conn):
    """Insert data into database.

    Args:
        data (dict): Data read `self.capture`.
    """
    db_cursor = db_conn.cursor()

    # Fix 'errors' columns
    data['errors'] = ' '.join([f'{k}={v}' for k, v in data['errors'].items()])

    # Build place-holders for columns
    column_names = ','.join(list(data.keys()))
    column_values = list(data.values())
    column_holders = ','.join(['?' for _ in column_values])

    # Build sql for insert
    insert_sql = f'INSERT INTO {db_table} ({column_names}) VALUES ({column_holders})'

    # Perform insert
    try:
        db_cursor.execute(insert_sql, column_values)
        db_conn.commit()
    except Exception as e:
        logger.warning(f'Error on insert: {e!r}')
        logger.warning(f'Attempted SQL: {insert_sql}')


def check_db_table(db_table, db_conn):
    """Check if db table exists and if not create it.

    Args:
        db_table (str): Name of db_table.
    """
    db_cursor = db_conn.cursor()

    table_check_sql = f"""
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name='{db_table}';
    """
    db_cursor.execute(table_check_sql)
    if db_cursor.fetchone() is None:
        # Create table
        db_cursor.execute('''
            CREATE TABLE weather (
                    date DATETIME,
                    weather_sensor_name TEXT,
                    weather_sensor_firmware_version FLOAT,
                    weather_sensor_serial_number BIGINT,
                    "sky_temp_C" FLOAT,
                    "ambient_temp_C" FLOAT,
                    "internal_voltage_V" FLOAT,
                    "ldr_resistance_Ohm" FLOAT,
                    "rain_sensor_temp_C" FLOAT,
                    rain_frequency FLOAT,
                    pwm_value FLOAT,
                    errors TEXT,
                    "wind_speed_KPH" FLOAT,
                    safe BOOLEAN,
                    sky_condition TEXT,
                    wind_condition TEXT,
                    gust_condition TEXT,
                    rain_condition TEXT,
                    CHECK (safe IN (0, 1))
            );
        ''')
