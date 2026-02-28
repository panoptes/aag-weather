from pathlib import Path

import typer
import uvicorn
from astropy.table import Table
from rich import print

from aag.weather import CloudSensor

app = typer.Typer()

format_lookup = {
    ".csv": "ascii.csv",
    ".ecsv": "ascii.ecsv",
    ".json": "pandas.json",
}


@app.command(name="capture")
def capture(
    output: Path | None = typer.Option(
        "weather.ecsv",
        help="Output filename with format determined by extension, "
        "defaults to an astropy ECSV file.",
    ),
    verbose: bool = typer.Option(False, help="Show the weather readings."),
):
    """Captures readings continuously."""
    sensor = CloudSensor()
    print(f"Sensor: {sensor}")

    readings_table: Table | None = None

    def callback(reading):
        nonlocal readings_table

        if readings_table is None:
            readings_table = Table([reading])
        else:
            readings_table.add_row(reading)

        if verbose:
            print(reading)

        readings_table.write(output, overwrite=True, format=format_lookup.get(output.suffix))

    try:
        # Blocking.
        sensor.capture(callback=callback)
    except KeyboardInterrupt:
        print("Stopping capture.")
    finally:
        print(f"\nData saved to [green]{output}[/green]")


@app.command(name="serve")
def serve(
    port: int = typer.Option(8080, help="Port to serve on."),
    host: str = typer.Option("localhost", help="Host to serve on."),
):
    """Start the FastAPI server."""
    uvicorn.run("aag.server:app", host=host, port=port)


if __name__ == "__main__":
    app()
