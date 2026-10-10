"""Open an application from a user-approved allowlist (Windows).

The model only ever supplies an app *name* (and, for browsers, an http/https
URL). The executable path and fixed arguments come from the allowlist file
``~/.openjarvis/apps.json`` that the user maintains, so Jarvis cannot run
arbitrary programs, paths or shell commands through this tool.

apps.json format::

    {
      "brave": {"path": "C:/.../brave.exe", "aliases": ["navegador"], "accepts_url": true},
      "valorant": {"path": "C:/.../RiotClientServices.exe",
                   "args": ["--launch-product=valorant", "--launch-patchline=live"]}
    }
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

APPS_FILE = DEFAULT_CONFIG_DIR / "apps.json"

# Only these deep-link schemes may be launched through an apps.json "uri" entry.
_LAUNCHER_SCHEMES = ("steam", "com.epicgames.launcher")


def _load_apps() -> Dict[str, Dict[str, Any]]:
    try:
        data = json.loads(Path(APPS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k).lower(): v for k, v in data.items() if isinstance(v, dict)}


def _resolve(apps: Dict[str, Dict[str, Any]], name: str) -> Optional[str]:
    needle = name.strip().lower()
    if needle in apps:
        return needle
    for key, entry in apps.items():
        if needle in [str(a).lower() for a in entry.get("aliases", [])]:
            return key
    return None


@ToolRegistry.register("open_app")
class OpenAppTool(BaseTool):
    tool_id = "open_app"

    @property
    def spec(self) -> ToolSpec:
        names = ", ".join(sorted(_load_apps())) or "(none configured)"
        return ToolSpec(
            name="open_app",
            description=(
                "Open a desktop application on the user's PC. Only apps on their "
                f"approved list can be opened: {names}. For browsers you may "
                "pass an http/https url to open that page."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "app": {"type": "string", "description": "App name from the list."},
                    "url": {
                        "type": "string",
                        "description": "Optional http(s) URL, browsers only.",
                    },
                },
                "required": ["app"],
            },
            category="system",
        )

    def execute(self, **params: Any) -> ToolResult:
        if sys.platform != "win32":
            return ToolResult(
                tool_name=self.tool_id,
                content="open_app is only implemented for Windows.",
                success=False,
            )
        apps = _load_apps()
        name = str(params.get("app", "")).strip()
        key = _resolve(apps, name) if name else None
        if key is None:
            allowed = ", ".join(sorted(apps)) or "none"
            return ToolResult(
                tool_name=self.tool_id,
                content=f"'{name}' is not on the approved list. Allowed apps: {allowed}.",
                success=False,
            )

        entry = apps[key]
        uri = str(entry.get("uri", ""))
        if uri:
            # Game-launcher deep links (Steam / Epic), fixed in apps.json.
            if urlparse(uri).scheme not in _LAUNCHER_SCHEMES or params.get("url"):
                return ToolResult(
                    tool_name=self.tool_id,
                    content=f"'{key}' has an invalid launcher entry.",
                    success=False,
                )
            try:
                os.startfile(uri)  # type: ignore[attr-defined]  # noqa: S606
            except OSError as exc:
                return ToolResult(
                    tool_name=self.tool_id,
                    content=f"Could not start '{key}': {exc}",
                    success=False,
                )
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Started {key}.",
                success=True,
                metadata={"app": key},
            )

        exe = str(entry.get("path", ""))
        if not exe or not os.path.exists(exe):
            return ToolResult(
                tool_name=self.tool_id,
                content=f"The path configured for '{key}' does not exist: {exe or '(empty)'}.",
                success=False,
            )
        args = [str(a) for a in entry.get("args", [])]

        url = str(params.get("url", "") or "").strip()
        if url:
            parsed = urlparse(url)
            if not entry.get("accepts_url"):
                return ToolResult(
                    tool_name=self.tool_id,
                    content=f"'{key}' does not accept a URL.",
                    success=False,
                )
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or len(url) > 2000
                or any(ch.isspace() or ord(ch) < 32 or ch in '"<>^|`' for ch in url)
            ):
                return ToolResult(
                    tool_name=self.tool_id,
                    content="Only plain http(s) URLs without spaces or special characters are allowed.",
                    success=False,
                )
            args.append(url)

        try:
            subprocess.Popen(  # noqa: S603 - fixed argv from the allowlist, no shell
                [exe, *args],
                shell=False,
                close_fds=True,
                creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | NEW_PROCESS_GROUP
            )
        except OSError as exc:
            return ToolResult(
                tool_name=self.tool_id, content=f"Could not start '{key}': {exc}", success=False
            )
        return ToolResult(
            tool_name=self.tool_id,
            content=f"Started {key}.",
            success=True,
            metadata={"app": key},
        )
