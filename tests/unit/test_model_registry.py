"""Tests for the ``pre_commits.model_registry`` hook.

Two layers:

* **Real-repo sync** — the on-disk ``db/registry.py`` must match what the hook
  generates from the actual model files. This is the CI guard: if someone adds
  a model and forgets to run pre-commit, this test fails.
* **Fixture scenarios** — a temp tree exercises add / rename / ignore-non-Base
  so every branch of the discovery + generation logic is pinned.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pre_commits.model_registry.hook import (
    ModelClass,
    discover_models,
    generate_registry,
    run_check,
)

REPO_ROOT = Path(__file__).parents[2]
REAL_BACKEND = REPO_ROOT / "src" / "backend"
REAL_REGISTRY = REPO_ROOT / "src" / "backend" / "db" / "registry.py"


# ---------------------------------------------------------------------------
# Real-repo sync guard
# ---------------------------------------------------------------------------


def test_real_registry_is_in_sync() -> None:
    """The committed registry.py must match what the hook generates."""
    in_sync, _ = run_check(REAL_BACKEND, REAL_REGISTRY, check=True)
    assert in_sync, (
        "db/registry.py is out of sync with model classes. "
        "Run `uv run python -m pre_commits.model_registry` to fix."
    )


def test_real_registry_registers_all_tables() -> None:
    """Importing the registry must populate Base.metadata with every table."""
    models = discover_models(REAL_BACKEND)
    names = {m.name for m in models}
    assert names == {
        "FileModel",
        "InvitationModel",
        "TaskModel",
        "UserAuthProviderModel",
        "UserPasswordModel",
        "UserModel",
    }


# ---------------------------------------------------------------------------
# Fixture scenarios
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_backend(tmp_path: Path) -> Path:
    """A minimal backend tree with a db/ package and one feature."""
    backend = tmp_path / "backend"
    db_dir = backend / "db"
    db_dir.mkdir(parents=True)
    (db_dir / "__init__.py").write_text("")
    (db_dir / "db.py").write_text(
        "from sqlalchemy.orm import DeclarativeBase\n"
        "class Base(DeclarativeBase):\n"
        "    pass\n"
    )
    (db_dir / "registry.py").write_text(
        '"""Registry."""\n\nfrom ..users.models import UserModel  # noqa: F401\n\n'
        '__all__ = [\n    "UserModel",\n]\n'
    )

    users_dir = backend / "users"
    users_dir.mkdir()
    (users_dir / "__init__.py").write_text("")
    (users_dir / "models.py").write_text(
        "from ..db.db import Base\nclass UserModel(Base):\n    pass\n"
    )
    return backend


def test_add_model_updates_registry(fake_backend: Path) -> None:
    """Adding a model class to an existing feature updates the registry."""
    # Add a second model to users/models.py
    users_models = fake_backend / "users" / "models.py"
    users_models.write_text(
        "from ..db.db import Base\n"
        "class UserModel(Base):\n"
        "    pass\n"
        "class UserProfileModel(Base):\n"
        "    pass\n"
    )
    registry = fake_backend / "db" / "registry.py"
    in_sync, generated = run_check(fake_backend, registry, check=True)
    assert not in_sync
    assert "UserProfileModel" in generated
    assert "from ..users.models import (  # noqa: F401" in generated


def test_rename_model_updates_registry(fake_backend: Path) -> None:
    """Renaming a model class is reflected in the generated registry."""
    users_models = fake_backend / "users" / "models.py"
    users_models.write_text(
        "from ..db.db import Base\nclass AccountModel(Base):\n    pass\n"
    )
    registry = fake_backend / "db" / "registry.py"
    in_sync, generated = run_check(fake_backend, registry, check=True)
    assert not in_sync
    assert "AccountModel" in generated
    assert "UserModel" not in generated


def test_non_base_class_is_ignored(fake_backend: Path) -> None:
    """A class that doesn't inherit from Base must not appear in the registry."""
    users_models = fake_backend / "users" / "models.py"
    users_models.write_text(
        "from ..db.db import Base\n"
        "from sqlalchemy.orm import MappedColumn\n"
        "class UserModel(Base):\n"
        "    pass\n"
        "class TimestampMixin:\n"
        "    pass\n"
        "class BaseMixin:\n"
        "    pass\n"
    )
    models = discover_models(fake_backend)
    names = {m.name for m in models}
    assert names == {"UserModel"}


def test_new_feature_model_is_discovered(fake_backend: Path) -> None:
    """A models.py in a new feature folder is picked up."""
    tasks_dir = fake_backend / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "__init__.py").write_text("")
    (tasks_dir / "models.py").write_text(
        "from ..db.db import Base\nclass TaskModel(Base):\n    pass\n"
    )
    registry = fake_backend / "db" / "registry.py"
    in_sync, generated = run_check(fake_backend, registry, check=True)
    assert not in_sync
    assert "from ..tasks.models import TaskModel" in generated
    assert "TaskModel" in generated


def test_db_package_is_excluded(fake_backend: Path) -> None:
    """The db/ package itself must never be scanned for models."""
    # Put a model-looking class in db/db.py — it must be ignored.
    (fake_backend / "db" / "db.py").write_text(
        "from sqlalchemy.orm import DeclarativeBase\n"
        "class Base(DeclarativeBase):\n"
        "    pass\n"
        "class SneakyModel(Base):\n"
        "    pass\n"
    )
    models = discover_models(fake_backend)
    names = {m.name for m in models}
    assert "SneakyModel" not in names


def test_models_package_is_scanned(fake_backend: Path) -> None:
    """A ``models/`` package (directory) is scanned, not just ``models.py``."""
    # Replace users/models.py with users/models/ package
    (fake_backend / "users" / "models.py").unlink()
    models_pkg = fake_backend / "users" / "models"
    models_pkg.mkdir()
    (models_pkg / "__init__.py").write_text("")
    (models_pkg / "user.py").write_text(
        "from ...db.db import Base\nclass UserModel(Base):\n    pass\n"
    )
    models = discover_models(fake_backend)
    names = {m.name for m in models}
    assert "UserModel" in names


def test_generate_registry_format() -> None:
    """The generated text has the expected structure."""
    models = [
        ModelClass(name="ZModel", module_dotted="..z.feature"),
        ModelClass(name="AModel", module_dotted="..a.feature"),
        ModelClass(name="B2", module_dotted="..a.feature"),
        ModelClass(name="B1", module_dotted="..a.feature"),
    ]
    text = generate_registry(models, '"""Header."""')
    # Modules sorted alphabetically
    assert text.index("..a.feature") < text.index("..z.feature")
    # Classes within a module sorted
    assert text.index("AModel") < text.index("B1") < text.index("B2")
    # Single-class module is single-line
    assert "from ..z.feature import ZModel  # noqa: F401" in text
    # Multi-class module uses parens
    assert "from ..a.feature import (  # noqa: F401" in text
    # __all__ is sorted
    assert (
        text.index('"AModel"')
        < text.index('"B1"')
        < text.index('"B2"')
        < text.index('"ZModel"')
    )
