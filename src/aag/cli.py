import typer
import json
from astropy.utils.misc import JsonCustomEncoder
from aag.weather import CloudSensor

app = typer.Typer()


@app.command(name='capture')
def main():
    sensor = CloudSensor()
    typer.echo(f'Sensor: {sensor}')

    def callback(reading):
        print(json.dumps(reading, cls=JsonCustomEncoder))

    sensor.capture(callback=callback)


if __name__ == "__main__":
    app()
