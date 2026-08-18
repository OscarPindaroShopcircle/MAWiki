import typer

from .commands.modules import register as register_module_commands

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Menelao command-line tools."""


register_module_commands(app)
