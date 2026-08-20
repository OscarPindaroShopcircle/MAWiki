"""MCP server for the test harness.

Exposes tools to spin up/down a test database and a resource that tells the
agent how to run tests.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from . import environment, state

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

    Validates .env.test and config.test.yaml, allocates a worktree-scoped
    port, starts PostgreSQL through Docker Compose, and returns connection
    details.
    """
    try:
        environment_state = environment.up(
            state.EnvironmentMode.LOCAL,
            database_port=port or 0,
        )
    except environment.EnvironmentError as error:
        return str(error)

    return (
        f"Test database is ready.\n"
        f"  Host: localhost\n"
        f"  Port: {environment_state.ports.database}\n"
        f"  Database: backend_test\n"
        f"  User: app_user\n"
        f"\n"
        f"Read the 'test_instructions' resource for how to run tests."
    )


@server.tool()
async def teardown() -> str:
    """Stop and remove test containers, restore config.test.yaml."""
    try:
        environment.teardown()
    except environment.EnvironmentError as error:
        return str(error)
    return "Containers stopped and config restored."


@server.tool()
async def status() -> str:
    """Show the current state of this worktree's environment."""
    try:
        _, output = environment.status()
        return output
    except environment.EnvironmentError as error:
        return str(error)


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
