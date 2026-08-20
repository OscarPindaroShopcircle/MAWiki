import subprocess
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from . import state


class TestSuite(str, Enum):
    UNIT = "unit"
    INTEGRATION = "integration"
    E2E = "e2e"


class PytestOptions(BaseModel):
    keyword: str | None = None
    max_failures: int | None = Field(default=None, ge=1)
    fail_fast: bool = False
    quiet: bool = True
    traceback: Literal["auto", "long", "short", "line", "native", "no"] = "short"


class TestResult(BaseModel):
    suite: TestSuite
    command: list[str]
    return_code: int
    stdout: str
    stderr: str


def run(
    suite: TestSuite,
    selectors: list[str] | None = None,
    options: PytestOptions | None = None,
) -> TestResult:
    root = state.worktree_root()
    options = options or PytestOptions()
    command = ["uv", "run", "pytest"]
    if suite == TestSuite.UNIT:
        command.append("tests/unit")
    else:
        command.extend(["-m", suite.value])
    command.extend(_selectors(root, selectors or []))
    if options.keyword:
        command.extend(["-k", options.keyword])
    if options.max_failures:
        command.append(f"--maxfail={options.max_failures}")
    if options.fail_fast:
        command.append("-x")
    if options.quiet:
        command.append("-q")
    command.append(f"--tb={options.traceback}")
    result = subprocess.run(command, cwd=root, capture_output=True, text=True)
    return TestResult(
        suite=suite,
        command=command,
        return_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def _selectors(root: Path, selectors: list[str]) -> list[str]:
    tests = (root / "tests").resolve()
    valid = []
    for selector in selectors:
        path, _, node_id = selector.partition("::")
        candidate = (root / path).resolve()
        try:
            candidate.relative_to(tests)
        except ValueError as error:
            raise ValueError(
                f"Test selector must be inside tests/: {selector}"
            ) from error
        if not candidate.exists():
            raise ValueError(f"Test selector does not exist: {selector}")
        valid.append(f"{candidate}{'::' + node_id if node_id else ''}")
    return valid
