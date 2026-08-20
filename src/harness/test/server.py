"""MCP server for the test harness.

Exposes tools to spin up/down a test database and a resource that tells the
agent how to run tests.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from . import compose, config, ports

server = FastMCP(
    "harness-test",
    instructions=(
        "Test harness for Menelao. Use start_test_db to spin up a PostgreSQL "
        "test database on a free port, run your tests, then call teardown to "
        "clean up. The test_instructions resource tells you how to run tests."
    ),
)


@server.tool()
async def start_test_db(
    port: Annotated[
        int | None,
        Field(
            description="Preferred port. If omitted or unavailable, the next free port is used."
        ),
    ] = None,
) -> str:
    """Spin up the test database.

    Validates config, finds a free port, backs up config.test.yaml, patches
    the port, starts PostgreSQL via docker compose, runs migrations, and
    returns connection details.
    """
    try:
        config.validate()
    except config.ConfigError as e:
        return str(e)

    try:
        chosen = ports.find_free_port(start=port or 5432)
    except RuntimeError as e:
        return str(e)

    try:
        config.backup()
        config.patch_port(chosen)
    except OSError as e:
        return f"Failed to prepare config: {e}"

    try:
        compose.up(chosen)
    except compose.ComposeError as e:
        config.restore()
        return f"Failed to start containers: {e}"

    try:
        compose.run_migrations()
    except compose.ComposeError as e:
        return f"Database started but migrations failed: {e}\n\nRun 'teardown' to clean up."

    return (
        f"Test database is ready.\n"
        f"  Host: localhost\n"
        f"  Port: {chosen}\n"
        f"  Database: backend_test\n"
        f"  User: app_user\n"
        f"\n"
        f"Read the 'test_instructions' resource for how to run tests."
    )


@server.tool()
async def teardown() -> str:
    """Stop and remove test containers, restore config.test.yaml."""
    messages: list[str] = []

    try:
        compose.down()
        messages.append("Containers stopped and removed.")
    except compose.ComposeError as e:
        messages.append(str(e))

    try:
        config.restore()
        messages.append("config.test.yaml restored from backup.")
    except OSError:
        messages.append("No backup to restore (config was not modified).")

    return "\n".join(messages)


@server.tool()
async def status() -> str:
    """Show the current state of test containers."""
    return compose.status_text()


@server.resource("info://test_instructions")
def test_instructions() -> str:
    """Return instructions for running tests against the harness DB."""
    return (
        "## Running Tests\n\n"
        "The test database is managed by the harness. Once `start_test_db` has "
        "completed successfully, config.test.yaml points to the correct port.\n\n"
        "### Unit tests (no database needed)\n"
        "```bash\n"
        "uv run pytest -m unit\n"
        "```\n\n"
        "### Integration tests (requires the test database)\n"
        "```bash\n"
        "uv run pytest -m integration\n"
        "```\n\n"
        "### All tests\n"
        "```bash\n"
        "uv run pytest\n"
        "```\n\n"
        "When you are done, call the `teardown` tool to stop containers "
        "and restore the original config.test.yaml."
    )


def serve() -> None:
    """Start the MCP server over stdio."""
    server.run()
