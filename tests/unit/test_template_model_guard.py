from __future__ import annotations

from pathlib import Path

from pre_commits.template_model_guard.hook import run_check


def _write_backend(tmp_path: Path, views: str) -> Path:
    backend = tmp_path / "src" / "backend"
    (backend / "widgets").mkdir(parents=True)
    (backend / "db").mkdir()
    (backend / "widgets" / "models.py").write_text(
        "from sqlalchemy.orm import Mapped\n"
        "from ..db.db import Base\n\n"
        "class FileModel(Base):\n"
        "    pass\n\n"
        "class WidgetModel(Base):\n"
        "    files: Mapped[list[FileModel]]\n"
    )
    (backend / "widgets" / "service.py").write_text(
        "from .models import WidgetModel\n\n"
        "async def get_widgets() -> tuple[list[WidgetModel], int]:\n"
        "    raise NotImplementedError\n\n"
        "async def get_widget() -> WidgetModel:\n"
        "    raise NotImplementedError\n"
    )
    (backend / "widgets" / "views.py").write_text(views)
    return backend


def test_flags_models_returned_by_service_and_tuple_unpacking(tmp_path: Path) -> None:
    backend = _write_backend(
        tmp_path,
        "from .service import get_widgets\n\n"
        "async def page(catalog):\n"
        "    widgets, _ = await get_widgets()\n"
        "    return catalog.render('pages.WidgetList', widgets=widgets)\n",
    )

    violations = run_check(backend)

    assert [(item.prop, item.models) for item in violations] == [
        ("widgets", ("WidgetModel",)),
    ]


def test_flags_model_typed_route_parameters(tmp_path: Path) -> None:
    backend = _write_backend(
        tmp_path,
        "async def page(catalog, widget: WidgetModel):\n"
        "    return catalog.render('pages.Widget', widget=widget)\n",
    )

    violations = run_check(backend)

    assert [(item.prop, item.models) for item in violations] == [
        ("widget", ("WidgetModel",)),
    ]


def test_flags_models_reached_through_relationships(tmp_path: Path) -> None:
    backend = _write_backend(
        tmp_path,
        "from .service import get_widget\n\n"
        "async def page(catalog):\n"
        "    widget = await get_widget()\n"
        "    return catalog.render('pages.FilesTable', files=widget.files)\n",
    )

    violations = run_check(backend)

    assert [(item.prop, item.models) for item in violations] == [
        ("files", ("FileModel",)),
    ]


def test_allows_pydantic_conversion_and_unknown_values(tmp_path: Path) -> None:
    backend = _write_backend(
        tmp_path,
        "from .service import get_widget\n\n"
        "class WidgetView:\n"
        "    @classmethod\n"
        "    def model_validate(cls, value):\n"
        "        return cls()\n\n"
        "async def page(catalog, dynamic):\n"
        "    widget = await get_widget()\n"
        "    view = WidgetView.model_validate(widget)\n"
        "    return catalog.render('pages.Widget', widget=view, dynamic=dynamic)\n",
    )

    assert run_check(backend) == []
