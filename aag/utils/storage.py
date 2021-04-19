def setup_db():
    # Setup the DB file
    self.db_conn = sqlite3.connect(db_file)
    self.db_cursor = self.db_conn.cursor()
    self._db_table = db_table

def store_result(data):
    """Insert data into database.

    Args:
        data (dict): Data read `self.capture`.
    """

    # Fix 'errors' columns
    data['errors'] = ' '.join([f'{k}={v}' for k, v in data['errors'].items()])

    # Build place-holders for columns
    column_names = ','.join(list(data.keys()))
    column_values = list(data.values())
    column_holders = ','.join(['?' for _ in column_values])

    # Build sql for insert
    insert_sql = f'INSERT INTO {self._db_table} ({column_names}) VALUES ({column_holders})'

    # Perform insert
    try:
        self.db_cursor.execute(insert_sql, column_values)
        self.db_conn.commit()
    except Exception as e:
        logger.warning(f'Error on insert: {e!r}')
        logger.warning(f'Attempted SQL: {insert_sql}')


def check_db_table():
    """Check if db table exists and if not create it.

    Args:
        db_table (str): Name of db_table.
    """
    table_check_sql = f"""
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name='{self._db_table}';
    """
    self.db_cursor.execute(table_check_sql)
    if self.db_cursor.fetchone() is None:
        # Create table
        self.db_cursor.execute('''
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
