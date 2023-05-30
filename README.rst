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

The settings are handled via the `pydantic` `Settings`_ module. These values can be modified with an
environment variable, or by creating a ``config.env`` file in the root of the project. The environment
variable names should be prepended with ``AAG_``.

The following values are available:



An example of setting the environment variables at the command line is:

.. code-block:: bash

    AAG_SERIAL_PORT=/dev/ttyUSB1 AAG_OUTPUT_FILENAME=/tmp/aag-weather.csv aag-weather capture




Running
*******

Reading values
==============

Installing the module will create the ``aag-weather`` console script, which can be used
for reading values from the AAG.

.. code-block:: bash

    $ aag-weather --help
    Usage: aag-weather [OPTIONS]

    Options:
      --output-filename PATH    Output filename
      --verbose / --no-verbose  Verbose output  [default: no-verbose]
      --help                    Show this message and exit.


If you require any values to change (for instance the ``serial_address`` or the threshold values), then
you can copy the config file to another location and specify it on the command line.


.. _LUNATICO: https://www.lunatico.es/ourproducts/aag-cloud-watcher.html.
.. _SETTINGS: https://docs.pydantic.dev/latest/usage/settings/
