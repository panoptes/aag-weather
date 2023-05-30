import subprocess
from pathlib import Path

import typer
from astropy.table import Table
from rich import print

from aag.weather import CloudSensor

app = typer.Typer()
readings_table = Table()


@app.command(name='capture')
def capture(
        output: Path = typer.Option('weather.csv', help='Output filename, defaults to an astropy ECSV file.'),
        verbose: bool = typer.Option(False, help='Verbose output.'),
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
            readings_table.write(output, overwrite=True, format='ascii.ecsv', delimiter=',')

    # Blocking
    sensor.capture(callback=callback)

    if output is not None:
        print(f'Data saved to {output}')


@app.command(name='serve')
def serve(
        port: int = typer.Option(8080, help='Port to serve on.'),
        host: str = typer.Option('localhost', help='Host to serve on.'),
):
    """Start the FastAPI server."""
    subprocess.run(['uvicorn', 'aag.server:app', f'--host={host}', f'--port={port}'])


if __name__ == "__main__":
    app()
