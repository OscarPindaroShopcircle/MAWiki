from datetime import UTC, datetime

from . import compose, config, ports, state


class EnvironmentError(RuntimeError):
    """Raised when an environment cannot be created or managed."""


def up(
    mode: state.EnvironmentMode,
    *,
    database_port: int = 0,
    backend_port: int = 0,
    openwebui_port: int = 0,
) -> state.EnvironmentState:
    root = state.worktree_root()
    existing = state.read(root)
    if existing is not None:
        if existing.mode != mode:
            raise EnvironmentError(
                f"A {existing.mode.value} environment is already active for this worktree."
            )
        return existing
    try:
        allocated = ports.allocate(mode, database_port, backend_port, openwebui_port)
        active_config = config.prepare(root, allocated.database)
    except (config.ConfigError, RuntimeError) as error:
        raise EnvironmentError(str(error)) from error
    environment_state = state.EnvironmentState(
        worktree=root,
        mode=mode,
        status="starting",
        created_at=datetime.now(UTC),
        compose_project=state.project_name(root),
        ports=allocated,
        config=active_config,
    )
    state.write(environment_state, root)
    try:
        compose.up(environment_state)
    except compose.ComposeError as error:
        try:
            compose.down(environment_state)
        except compose.ComposeError:
            pass
        config.restore(environment_state)
        state.clear(root)
        raise EnvironmentError(str(error)) from error
    environment_state.status = "ready"
    state.write(environment_state, root)
    return environment_state


def teardown() -> None:
    root = state.worktree_root()
    environment_state = state.read(root)
    if environment_state is None:
        return
    try:
        compose.down(environment_state)
    except compose.ComposeError as error:
        raise EnvironmentError(str(error)) from error
    config.restore(environment_state)
    state.clear(root)


def status() -> tuple[state.EnvironmentState | None, str]:
    root = state.worktree_root()
    environment_state = state.read(root)
    if environment_state is None:
        return None, "No active environment for this worktree."
    try:
        return environment_state, compose.status_text(environment_state)
    except compose.ComposeError as error:
        raise EnvironmentError(str(error)) from error
