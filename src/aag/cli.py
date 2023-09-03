import subprocess
from pathlib import Path

import typer
from astropy.table import Table
from rich import print

from aag.weather import CloudSensor

app = typer.Typer()
readings_table = Table()

format_lookup = {
    '.csv': 'ascii.csv',
    '.ecsv': 'ascii.ecsv',
    '.json': 'pandas.json',
}


@app.command(name='capture')
def capture(
        output: Path = typer.Option('weather.ecsv',
                                    help='Output filename with format determined by extension, '
                                         'defaults to an astropy ECSV file.'),
        verbose: bool = typer.Option(False, help='Show the weather readings.'),
):
    """Captures readings continuously."""
    sensor = CloudSensor()
    print(f'Sensor: {sensor}')

    def callback(reading):
        global readings_table

        if len(readings_table) == 0:
            readings_table = Table([reading])
        else:
            readings_table.add_row(reading)

        if verbose:
            print(reading)

        if output is not None:
            readings_table.write(output, overwrite=True, format=format_lookup.get(output.suffix))

    try:
        # Blocking.
        sensor.capture(callback=callback)
    except KeyboardInterrupt:
        print('Stopping capture.')
    finally:
        if output is not None:
            print(f'\nData saved to [green]{output}[/green]')


@app.command(name='serve')
def serve(
        port: int = typer.Option(8080, help='Port to serve on.'),
        host: str = typer.Option('localhost', help='Host to serve on.'),
):
    """Start the FastAPI server."""
    subprocess.run(['uvicorn', 'aag.server:app', f'--host={host}', f'--port={port}'])


if __name__ == "__main__":
    app()
