aag-weather
===========

A small script that is capable of reading the [Lunatico AAG Cloud Watcher](https://www.lunatico.es/ourproducts/aag-cloud-watcher.html) weather station data, including the anemometer.

## Docker

The docker image exists on the Google Cloud Container Registry.  To download

### Getting the Docker image

```bash
docker pull gcr.io/panoptes-exp/aag-weather
```

### Configure the aag-weather services

The services will read from the


### Running a Docker container

This repository contains a sample [`docker-compose`](https://docs.docker.com/compose/) file that will
start two containers: `aag-weather-server` and `aag-weather-reader`.

The `aag-weather-server` is responsible for communication with the AAG and therefore needs access to the serial device. Results are written to a simple sqlite3 database.

The `aag-weather-reader` starts a small flask web server that returns the most recent results.

Docker compose files can be started with:

```bash
docker-compose --file docker/docker-compose.yaml up
```


## Install

Clone the repository and then run either:


```bash
python setup.py install
```

or

```bash
pip install -r requirements.txt
pip install -e .
```

## Running

### Read AAG

The `scripts/read-aag.py` file is responsible for reading the serial data from the AAG. It requires
a config file in order to properly read from the AAG, with default values provided by `config.yaml`.
If you require any values to change (for instance the `serial_address` or the threshold values), then
you can copy the config file to another location and specify it on the command line.

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
  --verbose             Output data on the command line.
```

### Serve AAG data

> :warning: **NOTE:** There has been no attempt made to make this secure and Flask runs the development
server out of the box. This is suitable for testing and a minimal network implementation but should
never be used on an unsecure network (aren't they all?) and never in a "production" environment.
Use at your own risk.

A minimal flask server is included with the repository that can be used to serve the latest results
over the network.

The flask server provides two endpoints:

* `/latest.json`: This will serve the latest weather records returned as JSON. By default will only
return the most recent record, but `num_records=5` can be used to return more records.
* `/download-db`: Will send the `weather.db` as a file attachment for downloading.

#### Configure Flask Server

The Flask server uses [`python-dotenv`](https://flask.palletsprojects.com/en/1.1.x/cli/#environment-variables-from-dotenv) for configuration. To configure, create a `.env` file
in the main directory and add the **absolute path** to the database file. If a relative path
is given then the `latest.json` endpoint will still work but the database will not be available
for download.

Example `.env` file:

```bash
FLASK_DEBUG=1
DB_FILE=/home/pi/aag-weather/weather.db
```

If you would like to make the server available at your public IP address, add the host to
the `.env` file, e.g.:

> :warning: :dragon: :warning: Use at your own risk.

```
FLASK_RUN_HOST=0.0.0.0
FLASK_RUN_PORT=8989
```

#### Running Flask Server

The Flask server uses the Flask command line interface. To start, run the following from the root of
the repository:

```bash
flask run
```
