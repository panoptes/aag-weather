# aag-weather

A small script that is capable of reading the [Lunatico AAG Cloud Watcher](https://www.lunatico.es/ourproducts/aag-cloud-watcher.html) weather station data, including the anemometer.


## Install

Clone the repository and then run:

```bash
pip install -r requirements.txt
pip install -e .
```

## Running

```bash
➜ scripts/read-aag.py --help
usage: read-aag.py [-h] --config-file CONFIG_FILE [--store-result]
                   [--db-file DB_FILE] [--db-table DB_TABLE]
                   [--serial-address SERIAL_ADDRESS] [--verbose]

Read an AAG CloudWatcher

optional arguments:
  -h, --help            show this help message and exit
  --config-file CONFIG_FILE
                        Config file that contains the AAG params.
  --store-result        If data entries should be saved to db, default False.
  --db-file DB_FILE     Name of sqlite3 db file to use.
  --db-table DB_TABLE   Name of db table to use.
  --serial-address SERIAL_ADDRESS
                        USB serial address to use. If None, value from config
                        will be used.
  --verbose             Verbose.
```
