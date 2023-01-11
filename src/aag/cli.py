from pathlib import Path

import typer
import json
from astropy.utils.misc import JsonCustomEncoder
from aag.weather import CloudSensor

app = typer.Typer()


@app.command(name='capture')
def main(
        output_filename: Path = typer.Argument(..., help='Output filename'),
        verbose: bool = typer.Option(False, help='Verbose output'),
):
    sensor = CloudSensor()
    typer.echo(f'Sensor: {sensor}')

    def callback(reading):
        reading = json.dumps(reading, cls=JsonCustomEncoder)

        if output_filename is not None:
            with output_filename.open('a') as f:
                f.write(reading + '\n')

        if verbose:
            typer.echo(reading)

    sensor.capture(callback=callback)


if __name__ == "__main__":
    app()
