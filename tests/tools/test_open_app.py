"""open_app only launches allowlisted programs, with validated arguments."""

from __future__ import annotations

import json
import sys

import pytest

from openjarvis.tools import open_app
from openjarvis.tools.open_app import OpenAppTool

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="open_app is Windows-only")


@pytest.fixture
def tool(tmp_path, monkeypatch):
    exe = tmp_path / "browser.exe"
    exe.write_text("")
    apps = {
        "chrome": {"path": str(exe), "aliases": ["navegador"], "accepts_url": True},
        "notes": {"path": str(exe), "args": ["--flag"]},
        "gone": {"path": str(tmp_path / "missing.exe")},
        "steamgame": {"uri": "steam://rungameid/1"},
        "evil": {"uri": "file:///C:/Windows/System32/calc.exe"},
    }
    apps_file = tmp_path / "apps.json"
    apps_file.write_text(json.dumps(apps), encoding="utf-8")
    monkeypatch.setattr(open_app, "APPS_FILE", apps_file)

    launched: list[dict] = []
    monkeypatch.setattr(
        open_app.subprocess,
        "Popen",
        lambda argv, **kw: launched.append({"argv": argv, **kw}),
    )
    started: list[str] = []
    monkeypatch.setattr(open_app.os, "startfile", started.append, raising=False)

    t = OpenAppTool()
    t.launched, t.started, t.exe = launched, started, str(exe)
    return t


def test_unlisted_app_is_refused_and_nothing_runs(tool):
    r = tool.execute(app="powershell")
    assert not r.success and "not on the approved list" in r.content
    assert tool.launched == [] and tool.started == []


def test_listed_app_launches_without_a_shell(tool):
    r = tool.execute(app="notes")
    assert r.success
    call = tool.launched[0]
    assert call["argv"] == [tool.exe, "--flag"]
    assert call["shell"] is False


def test_alias_resolves_case_insensitively(tool):
    assert tool.execute(app="  NAVEGADOR ").success
    assert tool.launched[0]["argv"][0] == tool.exe


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Windows/System32/calc.exe",
        "javascript:alert(1)",
        "ftp://example.com/x",
        "https://example.com/a b",
        'https://example.com/"&calc',
        "https://example.com/a|b",
        "https://example.com/`x`",
        "https://",
        "https://example.com/" + "a" * 2100,
    ],
)
def test_unsafe_urls_are_rejected(tool, url):
    r = tool.execute(app="chrome", url=url)
    assert not r.success
    assert tool.launched == []


def test_plain_https_url_is_passed_as_a_single_argument(tool):
    r = tool.execute(app="chrome", url="https://example.com/path?q=1")
    assert r.success
    assert tool.launched[0]["argv"] == [tool.exe, "https://example.com/path?q=1"]


def test_url_refused_for_apps_that_do_not_accept_one(tool):
    r = tool.execute(app="notes", url="https://example.com")
    assert not r.success and "does not accept a URL" in r.content
    assert tool.launched == []


def test_missing_executable_is_reported(tool):
    r = tool.execute(app="gone")
    assert not r.success and "does not exist" in r.content


def test_launcher_uri_must_use_an_allowed_scheme(tool):
    assert tool.execute(app="steamgame").success
    assert tool.started == ["steam://rungameid/1"]
    bad = tool.execute(app="evil")
    assert not bad.success
    assert tool.started == ["steam://rungameid/1"]


def test_launcher_entries_ignore_a_model_supplied_url(tool):
    r = tool.execute(app="steamgame", url="https://example.com")
    assert not r.success


def test_no_apps_file_means_nothing_can_be_opened(tool, tmp_path, monkeypatch):
    monkeypatch.setattr(open_app, "APPS_FILE", tmp_path / "nope.json")
    r = tool.execute(app="chrome")
    assert not r.success and "none" in r.content.lower()
