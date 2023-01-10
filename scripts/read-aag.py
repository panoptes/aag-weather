#!/usr/bin/env python3
import sys
import time

from panoptes.utils.database.file import PanFileDB
from panoptes.utils.serializers import from_yaml

from src.aag.weather import AAGCloudSensor


def main(config=None,
         config_file=None,
         read_delay=60,
         store_result=False,
         storage_name='weather',
         storage_dir='.',
         verbose=False,
         **kwargs):
    if config is None:
        if config_file is None:
            print('Must pass either config or config_file')
            return
        else:
            # Read configuration
            with open(config_file, 'r') as f:
                config = from_yaml(f.read())['weather']['aag_cloud']

    db = PanFileDB(storage_dir=storage_dir)

    aag = AAGCloudSensor(config, **kwargs)

    if aag.aag_device is None:
        print(f'No AAG found, check log for details')
        sys.exit(1)

    while True:
        try:
            data = aag.capture()
            if verbose:
                print(f'{data!r}')
            db.insert_current(storage_name, data, store_permanently=store_result)
            time.sleep(read_delay)
        except KeyboardInterrupt:
            print(f'Cancelled by user, shutting down AAG.')
            break


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="Read an AAG CloudWatcher")
    parser.add_argument('--config-file', required=True,
                        help='Config file that contains the AAG params.')
    parser.add_argument('--store-result', default=False, action='store_true',
                        help='If data entries should be saved to db, default False.')
    parser.add_argument('--storage-name', default='weather',
                        help='Name of collection for storing results.')
    parser.add_argument('--storage-dir', default='.',
                        help='Directory for storing results, default current dir.')
    parser.add_argument('--read-delay', default=60, help='Number of seconds between reads.')
    parser.add_argument('--serial-address', default=None,
                        help='USB serial address to use. If None, value from config will be used.')
    parser.add_argument('--verbose', action='store_true', default=False,
                        help='Output data on the command line.')

    args = parser.parse_args()

    main(**vars(args))
    print('Shutting down AAG reader')
