import typer
from aag.weather import CloudSensor

app = typer.Typer()


@app.command(name='capture')
def main(name: str):
    sensor = CloudSensor(name)
    typer.echo(f'Sensor: {sensor}')

    sensor.capture(callback=typer.echo)


if __name__ == "__main__":
    app()
