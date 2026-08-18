"""Install/uninstall the harness MCP server into coding agents' configs."""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_HOME = Path.home()
_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class McpTarget:
    """MCP config location for one editor/agent."""

    id: str
    display_name: str
    path: Path
    key: str  # JSON key for the servers object, e.g. "mcpServers" or "servers"
    binary: str | None = None
    config_dir: Path | None = None


def _vscode_mcp_path() -> Path:
    if sys.platform == "darwin":
        return _HOME / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    elif sys.platform == "win32":
        return (
            Path(os.environ.get("APPDATA", str(_HOME))) / "Code" / "User" / "mcp.json"
        )
    else:
        base = os.environ.get("XDG_CONFIG_HOME", str(_HOME / ".config"))
        return Path(base) / "Code" / "User" / "mcp.json"


TARGETS: list[McpTarget] = [
    McpTarget(
        id="windsurf",
        display_name="Windsurf",
        path=_HOME / ".codeium" / "windsurf" / "mcp_config.json",
        key="mcpServers",
        binary="windsurf",
        config_dir=_HOME / ".codeium" / "windsurf",
    ),
    McpTarget(
        id="claude",
        display_name="Claude Code",
        path=_HOME / ".claude.json",
        key="mcpServers",
        binary="claude",
        config_dir=_HOME / ".claude",
    ),
    McpTarget(
        id="cursor",
        display_name="Cursor",
        path=_HOME / ".cursor" / "mcp.json",
        key="mcpServers",
        binary="cursor",
        config_dir=_HOME / ".cursor",
    ),
    McpTarget(
        id="vscode",
        display_name="VS Code",
        path=_vscode_mcp_path(),
        key="servers",
        binary="code",
    ),
    McpTarget(
        id="copilot",
        display_name="GitHub Copilot",
        path=_HOME / ".copilot" / "mcp-config.json",
        key="mcpServers",
        config_dir=_HOME / ".config" / "github-copilot",
    ),
    McpTarget(
        id="devin",
        display_name="Devin",
        path=_HOME / ".config" / "devin" / "mcp_config.json",
        key="mcpServers",
        binary="devin",
        config_dir=_HOME / ".config" / "devin",
    ),
]

SERVER_NAME = "menelao-test-harness"

SERVER_ENTRY: dict[str, object] = {
    "command": "uv",
    "args": [
        "run",
        "--directory",
        str(_REPO_ROOT),
        "menelao",
        "harness",
        "test",
        "serve",
    ],
}


def is_detected(target: McpTarget) -> bool:
    """Return True if the agent/editor appears to be installed."""
    if target.binary and shutil.which(target.binary):
        return True
    return bool(target.config_dir and target.config_dir.exists())


def _read_json(path: Path) -> dict[str, object]:
    """Read a JSON file, returning {} if it doesn't exist or is empty."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return {}


def _write_json(path: Path, data: dict[str, object]) -> None:
    """Write JSON to a file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def install(target: McpTarget) -> str:
    """Add the harness MCP server to a target's config. Returns a status string."""
    data = _read_json(target.path)
    servers = data.setdefault(target.key, {})

    if not isinstance(servers, dict):
        return (
            f"{target.display_name}: {target.key} is not a JSON object — add manually."
        )

    if SERVER_NAME in servers:
        existing = servers[SERVER_NAME]
        if existing == SERVER_ENTRY:
            return f"{target.display_name}: unchanged"
        servers[SERVER_NAME] = SERVER_ENTRY
        _write_json(target.path, data)
        return f"{target.display_name}: updated"

    servers[SERVER_NAME] = SERVER_ENTRY
    _write_json(target.path, data)
    return f"{target.display_name}: installed"


def uninstall(target: McpTarget) -> str:
    """Remove the harness MCP server from a target's config. Returns a status string."""
    if not target.path.exists():
        return f"{target.display_name}: not found"
    data = _read_json(target.path)
    servers = data.get(target.key)
    if not isinstance(servers, dict) or SERVER_NAME not in servers:
        return f"{target.display_name}: not configured"
    del servers[SERVER_NAME]
    if servers:
        data[target.key] = servers
        _write_json(target.path, data)
    elif data:
        del data[target.key]
        _write_json(target.path, data)
    else:
        target.path.unlink()
    return f"{target.display_name}: removed"


def resolve_targets(target_ids: list[str] | None) -> list[McpTarget]:
    """Resolve target IDs to McpTarget objects. 'all' means every target."""
    if not target_ids:
        return []
    if "all" in target_ids:
        return list(TARGETS)
    return [t for t in TARGETS if t.id in target_ids]


def run_install(target_ids: list[str] | None = None, yes: bool = False) -> None:
    """Interactive or unattended install."""
    if target_ids:
        targets = resolve_targets(target_ids)
        if not targets:
            print("No matching agents found.")
            return
        _apply_all(targets, install, "Installing")
    else:
        _interactive(install, "configure", True)


def run_uninstall(target_ids: list[str] | None = None, yes: bool = False) -> None:
    """Interactive or unattended uninstall."""
    if target_ids:
        targets = resolve_targets(target_ids)
        if not targets:
            print("No matching agents found.")
            return
        _apply_all(targets, uninstall, "Removing")
    else:
        _interactive(uninstall, "remove configuration from", False)


def _apply_all(
    targets: list[McpTarget],
    action: Callable[[McpTarget], str],
    verb: str,
) -> None:
    """Apply an action to all targets and print results."""
    print(f"\n  {verb} harness MCP server...\n")
    for t in targets:
        print(f"  {action(t)}")
    print("\n  Done. Restart your agents to pick up the changes.\n")


def _interactive(
    action: Callable[[McpTarget], str],
    verb: str,
    default_checked: bool,
) -> None:
    """Prompt the user to select agents interactively."""
    print(f"\n  Select agents to {verb}:\n")
    detected = sorted(TARGETS, key=lambda t: not is_detected(t))
    for i, t in enumerate(detected):
        marker = "(detected)" if is_detected(t) else ""
        check = "[x]" if default_checked and is_detected(t) else "[ ]"
        print(f"  {i + 1}. {check} {t.display_name} {marker}".strip())

    print("\n  Enter numbers, 'd' for detected, 'a' for all, empty to cancel:")
    try:
        raw = input("  > ").strip()
    except EOFError, KeyboardInterrupt:
        print("\n  Cancelled.")
        return

    if not raw:
        print("  Cancelled.")
        return

    if raw.lower() == "a":
        chosen = detected
    elif raw.lower() == "d":
        chosen = [t for t in detected if is_detected(t)]
    else:
        try:
            indices = [int(x) - 1 for x in raw.split()]
            chosen = [detected[i] for i in indices if 0 <= i < len(detected)]
        except ValueError:
            print("  Invalid input.")
            return

    if not chosen:
        print("  Nothing selected.")
        return

    print(f"\n  {verb} harness MCP server for:")
    for t in chosen:
        print(f"    → {t.display_name} ({t.path})")

    try:
        confirm = input("\n  Proceed? [Y/n] ").strip().lower()
    except EOFError, KeyboardInterrupt:
        print("\n  Cancelled.")
        return

    if confirm and confirm != "y":
        print("  Cancelled.")
        return

    _apply_all(chosen, action, verb.title())
