"""MCP server for Menelao environments and test execution."""

from __future__ import annotations

import asyncio

from fastmcp import FastMCP
from pydantic import Field

from . import environment, runner, state
from .browser import ScreenshotResult, capture_screenshots as _capture_screenshots

server = FastMCP(
    "harness-test",
    instructions=(
        "Create isolated local or Docker environments with env_up, then run "
        "the matching pytest suite. Test tools only execute uv run pytest."
    ),
)


def _environment_result(
    environment_state: state.EnvironmentState,
) -> state.EnvironmentState:
    return environment_state


@server.tool()
async def env_up(
    mode: state.EnvironmentMode = state.EnvironmentMode.LOCAL,
    database_port: int | None = Field(default=None, ge=1, le=65535),
    backend_port: int | None = Field(default=None, ge=1, le=65535),
    openwebui_port: int | None = Field(default=None, ge=1, le=65535),
) -> state.EnvironmentState | str:
    """Create an isolated local database or Docker test environment."""
    try:
        return _environment_result(
            environment.up(
                mode,
                database_port=database_port or 0,
                backend_port=backend_port or 0,
                openwebui_port=openwebui_port or 0,
            )
        )
    except environment.EnvironmentError as error:
        return str(error)


@server.tool()
async def env_teardown() -> str:
    """Stop this worktree's active environment and restore config.test.yaml."""
    try:
        environment.teardown()
    except environment.EnvironmentError as error:
        return str(error)
    return "Environment stopped and config restored."


@server.tool()
async def env_status() -> state.EnvironmentState | str:
    """Return this worktree's active environment state."""
    try:
        environment_state, output = environment.status()
    except environment.EnvironmentError as error:
        return str(error)
    return environment_state or output


async def _run_tests(
    suite: runner.TestSuite,
    selectors: list[str] | None,
    options: runner.PytestOptions | None,
) -> runner.TestResult | str:
    if suite != runner.TestSuite.UNIT:
        environment_state, _ = environment.status()
        if environment_state is None:
            return "No active environment for this worktree."
        if (
            suite == runner.TestSuite.E2E
            and environment_state.mode != state.EnvironmentMode.DOCKER
        ):
            return "E2E tests require an active Docker environment."
    try:
        return runner.run(suite, selectors, options)
    except ValueError as error:
        return str(error)


@server.tool()
async def test_unit(
    selectors: list[str] | None = None,
    options: runner.PytestOptions | None = None,
) -> runner.TestResult | str:
    """Run unit tests with uv run pytest tests/unit."""
    return await _run_tests(runner.TestSuite.UNIT, selectors, options)


@server.tool()
async def test_integration(
    selectors: list[str] | None = None,
    options: runner.PytestOptions | None = None,
) -> runner.TestResult | str:
    """Run integration tests against the active test database."""
    return await _run_tests(runner.TestSuite.INTEGRATION, selectors, options)


@server.tool()
async def test_e2e(
    selectors: list[str] | None = None,
    options: runner.PytestOptions | None = None,
) -> runner.TestResult | str:
    """Run E2E tests against the active Docker test environment."""
    return await _run_tests(runner.TestSuite.E2E, selectors, options)


@server.tool()
async def capture_page_screenshots(
    path: str,
    email: str,
    name: str | None = None,
) -> ScreenshotResult | str:
    """Capture authenticated desktop and phone screenshots for one path."""
    try:
        return await asyncio.to_thread(
            _capture_screenshots, path, email=email, name=name
        )
    except (OSError, RuntimeError, ValueError) as error:
        return str(error)


@server.resource("info://test_instructions")
def test_instructions() -> str:
    """Describe the fixed pytest commands exposed by this server."""
    return (
        "Use env_up before integration tests or E2E tests. "
        "test_unit runs uv run pytest tests/unit; test_integration and test_e2e "
        "run uv run pytest with their respective markers."
    )


def serve() -> None:
    """Start the MCP server over stdio."""
    server.run()
