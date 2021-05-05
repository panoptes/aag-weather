#!/usr/bin/env python3

import pandas as pd
from pandas.io.json import json_normalize
from loguru import logger

from aag.plotter import WeatherPlotter


def label_pos(lim, pos=0.85):
    return lim[0] + pos * (lim[1] - lim[0])


def load_json_file(json_file):
    # Read the json, then normalize the unflattened "data" column, returning a
    # normalized dataframe
    df0 = json_normalize(pd.read_json(json_file,
                                      lines=True,
                                      orient='values')['data'].values).set_index('date')
    df0.index = pd.to_datetime(df0.index)

    return df0


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description="Make a plot of the weather for a give date.")
    parser.add_argument('-c', '--config-file', required=True,
                        help='Config file that contains the AAG params.')
    parser.add_argument('--json-file', help='Name of json file to use')
    parser.add_argument("-d", "--date", type=str, dest="date",
                        default=None, help="UT Date to plot")
    parser.add_argument("-o", "--plot-file", type=str, dest="plot_file",
                        default='today.png', help="Filename for generated plot")
    args = parser.parse_args()

    logger.debug(f'Loading data from json {args.json_file}')
    df0 = load_json_file(args.json_file)

    wp = WeatherPlotter(df0, config_file=args.config_file, date_string=args.date)
    wp.make_plot(output_file=args.plot_file)
