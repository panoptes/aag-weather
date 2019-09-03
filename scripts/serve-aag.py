import os
from flask import Flask
from flask import request
from flask import send_file
from flask import Response
from sqlalchemy import create_engine

from datetime import datetime as dt
from dateutil.relativedelta import relativedelta as rd

import pandas as pd

app = Flask(__name__)

DB_FILE = os.getenv('DB_NAME', 'weather.db')
DB_ENGINE = create_engine(f'sqlite:///{DB_FILE}', echo=False)


def get_table():
    return pd.read_sql_table('weather', DB_ENGINE).sort_values(by='date')


def get_records(num_records=1):
    # Start from the end so make negative.
    table = get_table()
    num_records = int(num_records) * -1
    return table.iloc[num_records:].to_json(orient='records', date_format='iso')


def get_latest(from_date):
    # Start from the end so make negative.
    table = get_table().set_index('date')
    return table.loc[from_date.isoformat():].reset_index('date').sort_values(
        by='date').to_json(orient='records', date_format='iso')


@app.route('/latest.json', methods=['GET', 'POST'])
def latest():
    """Get the latest records as JSON.

    Returns:
        TYPE: Description
    """
    num_records = 1
    if 'num_records' in request.values:
        num_records = request.values.get('num_records')
    elif request.json:
        params = request.get_json(force=True)
        num_records = params.get('num_records', 1)

    # Get number of records.
    records = get_records(num_records)

    return Response(records, mimetype='application/json')


@app.route('/today.json', methods=['GET', 'POST'])
def today():
    """Get the previous 24 hours.

    Returns:
        TYPE: Description
    """

    # 24 hours ago.
    from_date = dt.now() + rd(dt.now(), days=-1)

    # Get latest from date.
    records = get_latest(from_date)

    return Response(records, mimetype='application/json')


@app.route('/download-db')
def download_db():
    """Download the sqlite3 database """
    return send_file(DB_FILE, as_attachment=True)
