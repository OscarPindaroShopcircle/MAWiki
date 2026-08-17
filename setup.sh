# precommit
VENV_PATH=".venv"
if [ -z "$VIRTUAL_ENV" ]; then
    source "$VENV_PATH/bin/activate"
fi


uv sync --dev
uv run pre-commit install
