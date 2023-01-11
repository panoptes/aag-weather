AAG-WEATHER
###########

   A small script that is capable of reading the `Lunatico`_ weather station data, including the anemometer.


Usage and installation
**********************

Installation
============

Clone the repository and then run either:

.. code-block:: bash

   python setup.py install

Or

.. code-block:: bash

    pip install -e .

Configuration
*************

The agg-weather service needs a configuration file to help it connect to the device, interpret the results (i.e. safety threshold limits), and to help with plotting.

An example configuration is included in `config.yaml <config.yaml>`_.

At a very minimum the correct ``serial_port`` should be changed to match that of the AAG.

Running
*******

Read AAG
========

The ``scripts/read-aag.py`` file is responsible for reading the serial data from the AAG. It requires
a config file in order to properly read from the AAG, with default values provided by ``config.yaml``.
If you require any values to change (for instance the ``serial_address`` or the threshold values), then
you can copy the config file to another location and specify it on the command line.

.. code-block:: bash

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

.. _LUNATICO: https://www.lunatico.es/ourproducts/aag-cloud-watcher.html.
