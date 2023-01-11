from pathlib import Path

import typer
from astropy.table import Table
from aag.weather import CloudSensor

app = typer.Typer()
readings_table = Table()


@app.command(name='capture')
def main(
        output_filename: Path = typer.Option(None, help='Output filename'),
        verbose: bool = typer.Option(False, help='Verbose output'),
):
    sensor = CloudSensor()
    typer.echo(f'Sensor: {sensor}')

    def callback(reading):
        global readings_table

        if len(readings_table) == 0:
            readings_table = Table([reading])
        else:
            readings_table.add_row(reading)

        if verbose:
            typer.echo(reading)

    # Blocking
    sensor.capture(callback=callback)

    if output_filename is not None:
        global readings_table
        readings_table.write(output_filename)
        typer.echo(f'Data saved to {output_filename}')


if __name__ == "__main__":
    app()
