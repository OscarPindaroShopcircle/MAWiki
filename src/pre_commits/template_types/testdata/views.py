"""Fixture routes covering every branch of the resolution chain.

These functions are never called — only parsed and introspected — but the module
must import cleanly, so the bodies are trivial. Each route is named after the
resolution rule it exercises.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates

from .models import Branch, Leaf, Page, TabAlpha, TabBeta

router = APIRouter()
other_router = APIRouter()


def _get_templates() -> Jinja2Templates:
    """Stand-in for the app's dependency; never actually called."""
    raise NotImplementedError


_TABS = {
    "alpha": "tab_alpha.html",
    "beta": "tab_beta.html",
}


def _annotated_helper() -> Branch:
    raise NotImplementedError


def _unannotated_returning_ctor():
    """No return annotation — the return statement names the model."""
    return Branch(leaf=Leaf(name="x", created_at=None, colour="RED"))


def _unannotated_generic():
    """The Gap B case: a generic model built without a type argument.

    The argument has to come from the constructor keyword, via the comprehension
    element, or everything below ``.data`` goes unchecked.
    """
    rows = []
    return Page(data=[_leaf_of(r) for r in rows], page=1)


def _leaf_of(row: object) -> Leaf:
    raise NotImplementedError


def _dispatcher(tab: str):
    """Returns a different model per branch, keyed by the same literal as _TABS."""
    if tab == "alpha":
        return TabAlpha(alpha="a")
    if tab == "beta":
        return TabBeta(beta="b")
    raise NotImplementedError


@router.get("/annotated")
async def annotated_route(
    request: Request, templates: Jinja2Templates = Depends(_get_templates)
):
    view = _annotated_helper()
    return templates.TemplateResponse(
        request=request, name="branch.html", context={"view": view}
    )


@router.get("/unannotated")
async def unannotated_route(
    request: Request, templates: Jinja2Templates = Depends(_get_templates)
):
    view = _unannotated_returning_ctor()
    return templates.TemplateResponse(
        request=request, name="branch_via_return.html", context={"view": view}
    )


@router.get("/generic")
async def generic_route(
    request: Request, templates: Jinja2Templates = Depends(_get_templates)
):
    view = _unannotated_generic()
    return templates.TemplateResponse(
        request=request, name="page.html", context={"view": view}
    )


@router.get("/direct-ctor/{item_id}")
async def direct_ctor_route(
    item_id: uuid.UUID,
    request: Request,
    templates: Jinja2Templates = Depends(_get_templates),
):
    return templates.TemplateResponse(
        request=request,
        name="scalars.html",
        context={
            "leaf": Leaf(name="n", created_at=None, colour="RED"),
            "item_id": item_id,
            "label": f"/items/{item_id}",
        },
    )


@router.get("/validated")
async def validated_route(
    request: Request, templates: Jinja2Templates = Depends(_get_templates)
):
    row = object()
    return templates.TemplateResponse(
        request=request,
        name="leaf.html",
        context={"leaf": Leaf.model_validate(row)},
    )


@router.get("/tabs/{tab}")
async def tab_route(
    tab: str, request: Request, templates: Jinja2Templates = Depends(_get_templates)
):
    view = _dispatcher(tab)
    return templates.TemplateResponse(
        request=request, name=_TABS[tab], context={"view": view}
    )


@router.get("/unresolvable")
async def unresolvable_route(
    request: Request, templates: Jinja2Templates = Depends(_get_templates)
):
    row = object()
    return templates.TemplateResponse(
        request=request, name="unresolved.html", context={"value": row.attribute}
    )


async def not_a_route(
    request: Request, templates: Jinja2Templates = Depends(_get_templates)
):
    """Undecorated: must be ignored by discovery."""
    return templates.TemplateResponse(
        request=request, name="never_rendered.html", context={"view": None}
    )


@other_router.get("/second-router")
async def second_router_route(
    request: Request, templates: Jinja2Templates = Depends(_get_templates)
):
    """A second APIRouter in the same module must also be discovered."""
    view = _annotated_helper()
    return templates.TemplateResponse(
        request=request, name="second.html", context={"view": view}
    )


@router.get("/no-templates-param")
async def no_templates_param(request: Request):
    """No Jinja2Templates parameter: nothing to discover here."""
    return {"ok": True}
