# PANOPTES AAG weather reader

[![codecov](https://codecov.io/github/panoptes/aag-weather/branch/main/graph/badge.svg?token=wwoAn40DVB)](https://codecov.io/github/panoptes/aag-weather)

> Weather service for the Lunatico AAG CloudWatcher.

This is a simple weather service for the Lunatico AAG CloudWatcher. It is
intended to be used with the [aag-cloudwatcher](https://www.lunatico.es/ourproducts/aag-cloud-watcher.html).

There are two main components to this project:

1. The `aag-weather` command line tool.
2. [FastAPI](https://fastapi.tiangolo.com/lo/) web service.

The `aag-weather` command line tool is used to read the weather data from the
CloudWatcher and store it in a file. 

The web service is used to serve the weather data to a web browser as json, which can be read by various tools. If
using [POCS](https://github.com/panoptes/POCS) you can use the `pocs sensor monitor`
command to read the weather data continuously.

# Installation

Install with `pip`:

```bash
pip install panoptes-aag
```

Or from a local repository:

```bash
git clone https://github.com/panoptes/aag-weather
cd aag-weather
pip install -e .
```

# Usage

You can use either the `aag-weather` command line tool or the web service to
read the weather data.

## Web service

### Starting

The web service can be run with the `aag-weather` command line tool:

```bash
aag-weather serve
```

The `host` and `port` can be specified with the `--host` and `--port` options.

### Reading

#### POCS

If you are using [POCS](https://github.com/panoptes/POCS) you can use the remote sensor utilities:

```bash
pocs sensor monitor weather --endpoint http://localhost:8080
```

> :information_source: If you installed POCS via the install script then this is all managed for you.


#### Command line

The web service will serve the weather data as json. The data can be accessed
by going to the `/weather` endpoint. For example, if the web service is
running on `localhost` on port `8080` then the weather data can be accessed at
`http://localhost:8080/weather`.

The [httpie](https://httpie.io/) is installed with this package and can be
used to read the weather data from the command line:

```bash
http :8080/weather
```

## Command line

### Starting

The `aag-weather` command line tool can be used to read the weather data from
the CloudWatcher and store it in a csv file. The `aag-weather` command line tool
can be run with:

```bash
aag-weather capture
```

See `aag-weather capture --help` for more options.

### Reading

When the `aag-weather` command line tool is running it will write the weather
data to a file. The default file is `weather.csv` in the current directory. You
can change the format by specifying a different output file when capturing, for
example:

```bash
aag-weather capture --output-file weather.json
```

# Configuration

The `aag-weather` command line tool and web service
are [pydantic settings](https://pydantic-docs.helpmanual.io/usage/settings/) and can be configured with
environment variables or a `config.env` file in the directory from which the command is run.

The environment variables are prepended with `AAG_`. The main configuration options are:

| Environment variable | Default        | Description                                                      |
|----------------------|----------------|------------------------------------------------------------------|
| `AAG_SERIAL_PORT`    | `/dev/ttyUSB0` | The serial port to use to connect to the CloudWatcher.           |
| `AAG_SAFETY_DELAY`   | `15`           | Minutes after an unsafe reading before the system is safe again. |
| `AAG_CAPTURE_DELAY`  | `30`           | Seconds between readings.                                        |
| `AAG_NUM_READINGS`   | `10`           | Number of readings to use for averaging.                         |
| `AAG_IGNORE_UNSAFE`  | `None`         | None, otherwise can be a list, e.g. 'rain','cloud','gust','wind' |

Additionally, you can set the `thresholds` options as well as options to control the `heater`. These options
are "nested" and so use a double underscore (e.g. `__`) to separate the levels.

| Environment variable           | Default | Description                                                 |
|--------------------------------|---------|-------------------------------------------------------------|
| `AAG_THRESHOLDS__CLOUDY`       | `-25`   | Difference between sky and ambient temperatures in Celsius. |
| `AAG_THRESHOLDS__VERY_CLOUDY`  | `-15`   | Difference between sky and ambient temperatures in Celsius. |
| `AAG_THRESHOLDS__WINDY`        | `50`    | Wind speed in km/h.                                         |
| `AAG_THRESHOLDS__VERY_WINDY`   | `75`    | Wind speed in km/h.                                         |
| `AAG_THRESHOLDS__GUSTY`        | `100`   | Wind gust speed in km/h.                                    |
| `AAG_THRESHOLDS__VERY_GUSTY`   | `125`   | Wind gust speed in km/h.                                    |
| `AAG_THRESHOLDS__WET`          | `2200`  | Wetness in Ohms.                                            |
| `AAG_THRESHOLDS__RAINY`        | `1800`  | Rain in Ohms.                                               |
| `AAG_HEATER__MIN_POWER`        | `0`     | Minimum power to use for the heater.                        |
| `AAG_HEATER__LOW_TEMP`         | `0`     | Temperature in Celsius.                                     |
| `AAG_HEATER__LOW_DELTA`        | `6`     | Difference between sky and ambient temperatures in Celsius. |
| `AAG_HEATER__HIGH_TEMP`        | `20`    | Temperature in Celsius.                                     |
| `AAG_HEATER__HIGH_DELTA`       | `4`     | Difference between sky and ambient temperatures in Celsius. |
| `AAG_HEATER__IMPULSE_TEMP`     | `10`    | Temperature in Celsius.                                     |
| `AAG_HEATER__IMPULSE_DURATION` | `60`    | Duration in seconds.                                        |
| `AAG_HEATER__IMPULSE_CYCLE`    | `600`   | Cycle in seconds.                                           |

# Misc

This project has been set up using PyScaffold 4.4.1. For details and usage
information on PyScaffold see https://pyscaffold.org/.

[![Project generated with PyScaffold](https://img.shields.io/badge/-PyScaffold-005CA0?logo=pyscaffold)](https://pyscaffold.org/)
