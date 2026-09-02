from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.test import browser


def test_screenshot_forwards_email_to_both_viewports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = []
    environment = SimpleNamespace(
        mode=browser.state.EnvironmentMode.DOCKER,
        ports=SimpleNamespace(backend=8000),
    )
    monkeypatch.setattr(browser.state, "read", lambda: environment)
    monkeypatch.setattr(browser.state, "worktree_root", lambda: tmp_path)
    monkeypatch.setattr(browser, "sync_playwright", lambda: nullcontext(object()))
    monkeypatch.setattr(
        browser,
        "_capture",
        lambda *_args, **kwargs: calls.append(kwargs),
    )

    browser.capture_screenshots(
        "/sources",
        email="admin@example.test",
        output_dir=tmp_path / "screenshots",
    )

    assert [call["email"] for call in calls] == [
        "admin@example.test",
        "admin@example.test",
    ]
    assert [call["phone"] for call in calls] == [False, True]
