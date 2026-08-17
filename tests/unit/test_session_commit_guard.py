from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pre_commits.session_commit_guard.hook as hook
from pre_commits.session_commit_guard.hook import check_files, scan_file


def test_grep_fast_path_reports_candidates(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "route.py"
    path.write_text("async def route(session):\n    await session.commit()\n")
    monkeypatch.setattr(hook.shutil, "which", lambda _: "/usr/bin/grep")
    monkeypatch.setattr(
        hook.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=f"{path}\n",
            stderr="",
        ),
    )

    violations = check_files([path])

    assert len(violations) == 1
    assert violations[0].line == 2
    assert violations[0].function == "route"


def test_grep_unavailable_falls_back_to_ast(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "route.py"
    path.write_text(
        "# session.commit()\n"
        "message = 'db_session.commit()'\n"
        "async def route(session):\n"
        "    await db_session.commit()\n"
    )
    monkeypatch.setattr(hook.shutil, "which", lambda _: None)

    violations = check_files([path])

    assert len(violations) == 1
    assert violations[0].function == "route"


def test_grep_failure_falls_back_to_ast(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "route.py"
    path.write_text("async def route(session):\n    await session.commit()\n")
    monkeypatch.setattr(hook.shutil, "which", lambda _: "/usr/bin/grep")
    monkeypatch.setattr(
        hook.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=2, stdout="", stderr="failed"
        ),
    )

    violations = check_files([path])

    assert len(violations) == 1
    assert violations[0].function == "route"


def test_function_exception_forces_ast_path(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "routes.py"
    path.write_text(
        "def allowed_route(session):\n"
        "    session.commit()\n"
        "\n"
        "def forbidden_route(db_session):\n"
        "    db_session.commit()\n"
    )
    monkeypatch.setattr(
        hook.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("grep must not run for AST-scoped exceptions")
        ),
    )

    violations = check_files([path], allowed_functions=(f"{path}:allowed_route",))

    assert len(violations) == 1
    assert violations[0].function == "forbidden_route"


def test_aliases_are_caught_but_comments_and_strings_are_not(tmp_path: Path) -> None:
    path = tmp_path / "routes.py"
    path.write_text(
        "# session.commit()\n"
        "message = 'db_session.commit()'\n"
        "async def route(session):\n"
        "    await db_session.commit()\n"
    )

    violations = scan_file(path)

    assert len(violations) == 1
    assert violations[0].line == 4
    assert violations[0].function == "route"


def test_function_exception_is_scoped_to_one_function(tmp_path: Path) -> None:
    path = tmp_path / "routes.py"
    path.write_text(
        "def allowed_route(session):\n"
        "    session.commit()\n"
        "\n"
        "def forbidden_route(db_session):\n"
        "    db_session.commit()\n"
    )

    violations = check_files([path], allowed_functions=(f"{path}:allowed_route",))

    assert len(violations) == 1
    assert violations[0].function == "forbidden_route"


def test_file_exception_skips_every_commit_in_file(tmp_path: Path) -> None:
    path = tmp_path / "dependencies.py"
    path.write_text("session.commit()\ndb.commit()\n")

    assert check_files([path], excluded_files=(str(path),)) == []


def test_non_python_files_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "example.txt"
    path.write_text("session.commit()\n")

    assert check_files([path]) == []
