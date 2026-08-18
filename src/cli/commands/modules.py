import re
import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

console = Console()


class ModuleExistsException(Exception):
    """Raised when the target module already exists."""


class InvalidModuleNameException(ValueError):
    """Raised when a module name is not a valid Python package name."""


class InvalidClassNameException(ValueError):
    """Raised when an explicit class name cannot be normalized."""


TEMPLATES = {
    "__init__.py": "",
    "exception.py": """from fastapi import HTTPException, status\n\n\nclass __CLASS__Exception(HTTPException):\n    \"\"\" \"\"\"\n\n    def __init__(self) -> None:\n        super().__init__(\n            status_code=status.HTTP_400_BAD_REQUEST,\n            detail=\"__CLASS__ error.\",\n        )\n""",
    "models.py": """from sqlalchemy import String\nfrom sqlalchemy.orm import Mapped, mapped_column\n\nfrom ..db.db import Base\n\n\nclass __CLASS__Model(Base):\n    \"\"\" \"\"\"\n\n    __tablename__ = \"__MODULE__\"\n\n    id: Mapped[int] = mapped_column(primary_key=True)\n    name: Mapped[str] = mapped_column(String(255), nullable=False)\n""",
    "schemas.py": """from pydantic import BaseModel\n\n\nclass __CLASS__Schema(BaseModel):\n    \"\"\" \"\"\"\n\n    name: str\n""",
    "service.py": """from sqlalchemy.ext.asyncio import AsyncSession\n\n\nclass __CLASS__Service:\n    \"\"\" \"\"\"\n\n    def __init__(self, db: AsyncSession) -> None:\n        self.db = db\n\n    async def get_sample(self) -> None:\n        return None\n""",
    "views.py": """from fastapi import APIRouter\nfrom fastapi.responses import HTMLResponse\n\n\nrouter = APIRouter(tags=[\"__MODULE__-views\"])\n\n\n@router.get(\"/__MODULE__\", response_class=HTMLResponse)\nasync def __MODULE___page() -> str:\n    \"\"\" \"\"\"\n    return \"<h1>__CLASS__</h1>\"\n""",
    "routes.py": """from fastapi import APIRouter\n\n\nrouter = APIRouter(prefix=\"/__MODULE__\", tags=[\"__MODULE__\"])\n\n\n@router.get(\"/sample\")\nasync def __MODULE___sample() -> dict[str, str]:\n    \"\"\" \"\"\"\n    return {\"status\": \"ok\"}\n""",
}


def _class_name(value: str) -> str:
    words = [
        word
        for part in re.split(r"[^A-Za-z0-9]+", value)
        for word in re.findall(
            r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|[0-9]+",
            part,
        )
    ]
    if not words:
        raise InvalidClassNameException("Class name must contain letters or numbers.")
    class_name = "".join(word.capitalize() for word in words)
    if not class_name[0].isalpha():
        raise InvalidClassNameException("Class name must start with a letter.")
    return class_name


def generate_module(
    module_name: str,
    target_dir: Path,
    force: bool = False,
    class_name: str | None = None,
) -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", module_name):
        raise InvalidModuleNameException(
            "Module name must contain lowercase letters, numbers, and underscores "
            "and start with a letter."
        )
    class_name = _class_name(class_name or module_name)

    module_dir = target_dir / module_name
    if module_dir.exists():
        if not force:
            raise ModuleExistsException(f"Module already exists: {module_dir}")
        if module_dir.is_dir() and not module_dir.is_symlink():
            shutil.rmtree(module_dir)
        else:
            module_dir.unlink()

    module_dir.mkdir(parents=True)
    for filename, template in TEMPLATES.items():
        content = template.replace("__MODULE__", module_name).replace(
            "__CLASS__", class_name
        )
        (module_dir / filename).write_text(content)

    return module_dir


def new_module(
    module_name: Annotated[
        str,
        typer.Argument(help="Lowercase backend module name, e.g. knowledge."),
    ],
    target_dir: Annotated[
        Path,
        typer.Option("--target-dir", "-d", help="Backend package directory."),
    ] = Path("src/backend"),
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Recreate an existing module."),
    ] = False,
    class_name: Annotated[
        str | None,
        typer.Option(
            "--class-name",
            "-c",
            help="Class name, e.g. KnowledgeBase; casing is normalized.",
        ),
    ] = None,
) -> None:
    """Create a backend module scaffold."""
    try:
        module_dir = generate_module(module_name, target_dir, force, class_name)
    except (
        InvalidClassNameException,
        InvalidModuleNameException,
        ModuleExistsException,
    ) as error:
        console.print(f"[red]Error:[/red] {error}")
        raise typer.Exit(code=1) from error

    console.print(f"Created [green]{module_dir}[/green]")
    for filename in (
        "exception.py",
        "models.py",
        "schemas.py",
        "service.py",
        "views.py",
        "routes.py",
    ):
        console.print(f"  {module_dir / filename}")


def register(app: typer.Typer) -> None:
    app.command("new-module")(new_module)
