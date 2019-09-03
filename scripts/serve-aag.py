import os
from flask import Flask
from flask import request
from flask import send_file
from flask import Response
from sqlalchemy import create_engine

import pandas as pd

app = Flask(__name__)

DB_FILE = os.getenv('DB_NAME', 'weather.db')
DB_ENGINE = create_engine(f'sqlite:///{DB_FILE}', echo=False)


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

    # Start from the end so make negative.
    num_records = int(num_records) * -1

    table = pd.read_sql_table('weather', DB_ENGINE).sort_values(by='date')
    record = table.iloc[num_records:].to_json(orient='records', date_format='iso')

    return Response(record, mimetype='application/json')


@app.route('/download-db')
def download_db():
    """Download the sqlite3 database """
    return send_file(DB_FILE, as_attachment=True)
