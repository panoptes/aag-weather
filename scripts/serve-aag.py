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

DB_FILE = os.getenv('DB_FILE', 'weather.db')
DB_TABLE = os.getenv('DB_TABLE', 'weather')
DB_ENGINE = create_engine(f'sqlite:///{DB_FILE}', echo=False)


def get_records(sql_query):
    records = pd.read_sql_query(sql_query, DB_ENGINE,
                                index_col='date',
                                parse_dates=['date'],
                                coerce_float=True)

    return records.sort_index().to_json(orient='records', date_format='iso')


@app.route('/', methods=['GET', 'POST'])
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
    sql_query = f'''
        SELECT *
        FROM {DB_TABLE}
        ORDER BY date DESC
        LIMIT {num_records}
    '''
    records = get_records(sql_query)

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
    sql_query = f'''
        SELECT *
        FROM {DB_TABLE}
        WHERE date >= '{from_date}'
    '''
    records = get_records(sql_query)

    return Response(records, mimetype='application/json')


@app.route('/download-db')
def download_db():
    """Download the sqlite3 database """
    return send_file(DB_FILE, as_attachment=True)
