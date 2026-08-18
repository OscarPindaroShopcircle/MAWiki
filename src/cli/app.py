import typer

from .commands.modules import register as register_module_commands
from harness.cli import app as harness_app

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Menelao command-line tools."""


register_module_commands(app)
app.add_typer(harness_app, name="harness")
