"""Structured content library: ideas, scripts, published posts and lessons.

Stored as plain JSON at ``~/.openjarvis/content/library.json`` so the user can
read or edit it by hand. Local only; nothing is sent anywhere.

Entry fields: id, kind, title, platform, status, text, tags, metrics, notes,
created, updated.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

LIBRARY_FILE = DEFAULT_CONFIG_DIR / "content" / "library.json"

KINDS = ("idea", "script", "published", "lesson", "reference")
STATUSES = ("idea", "approved", "recorded", "edited", "scheduled", "published", "discarded")
_LOCK = threading.Lock()
_MAX_TEXT = 8000


def _load() -> List[Dict[str, Any]]:
    try:
        data = json.loads(Path(LIBRARY_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(entries: List[Dict[str, Any]]) -> None:
    path = Path(LIBRARY_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)  # atomic: a crash never leaves a half-written file
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _next_id(entries: List[Dict[str, Any]]) -> str:
    nums = [int(e["id"][1:]) for e in entries if str(e.get("id", "")).startswith("c")
            and str(e["id"])[1:].isdigit()]
    return f"c{(max(nums) + 1) if nums else 1:03d}"


def _line(e: Dict[str, Any]) -> str:
    m = e.get("metrics") or {}
    mtxt = (" | " + ", ".join(f"{k} {v}" for k, v in m.items())) if m else ""
    tags = (" #" + " #".join(e["tags"])) if e.get("tags") else ""
    return (f"[{e['id']}] {e.get('kind')}/{e.get('status')} "
            f"{e.get('platform') or '-'} | {e.get('title')}{mtxt}{tags}")


def _clip(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


@ToolRegistry.register("content_memory")
class ContentMemoryTool(BaseTool):
    tool_id = "content_memory"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="content_memory",
            description=(
                "The user's content library: save and recall ideas, scripts, published "
                "posts (with metrics) and lessons learned. Use it BEFORE proposing "
                "ideas (avoid repeats and build on what worked) and to save "
                "something once the user approves it. Actions: add, list, get, "
                "update, search, remove. Local file, nothing leaves the PC."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "list", "get", "update", "search", "remove"],
                    },
                    "id": {"type": "string", "description": "Entry id like c003 (get/update/remove)."},
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "title": {"type": "string"},
                    "platform": {"type": "string", "description": "instagram, tiktok, x, youtube..."},
                    "status": {"type": "string", "enum": list(STATUSES)},
                    "text": {"type": "string", "description": "Script, idea detail or lesson."},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "metrics": {"type": "object", "description": "e.g. reach, views, shares, saved."},
                    "notes": {"type": "string"},
                    "query": {"type": "string", "description": "Keyword for search."},
                    "limit": {"type": "integer", "description": "Max entries for list/search (default 15)."},
                },
                "required": ["action"],
            },
            category="memory",
        )

    def _ok(self, content: str, **meta: Any) -> ToolResult:
        return ToolResult(tool_name=self.tool_id, content=content, success=True, metadata=meta)

    def _err(self, content: str) -> ToolResult:
        return ToolResult(tool_name=self.tool_id, content=content, success=False)

    def execute(self, **params: Any) -> ToolResult:
        action = str(params.get("action", "")).strip().lower()
        with _LOCK:
            entries = _load()
            if action == "add":
                return self._add(entries, params)
            if action in ("list", "search"):
                return self._list(entries, params, search=action == "search")
            if action == "get":
                e = self._find(entries, params)
                return self._ok(json.dumps(e, ensure_ascii=False, indent=2)) if e else self._err("Entry not found.")
            if action == "update":
                return self._update(entries, params)
            if action == "remove":
                e = self._find(entries, params)
                if not e:
                    return self._err("Entry not found.")
                entries.remove(e)
                _save(entries)
                return self._ok(f"Removed {e['id']}: {e.get('title')}")
        return self._err("Unknown action. Use add, list, get, update, search or remove.")

    @staticmethod
    def _find(entries: List[Dict[str, Any]], params: Dict[str, Any]):
        wanted = str(params.get("id", "")).strip().lower()
        return next((e for e in entries if str(e.get("id", "")).lower() == wanted), None)

    def _add(self, entries: List[Dict[str, Any]], p: Dict[str, Any]) -> ToolResult:
        title = _clip(p.get("title"), 200)
        if not title:
            return self._err("A title is required.")
        kind = str(p.get("kind") or "idea").lower()
        status = str(p.get("status") or ("published" if kind == "published" else "idea")).lower()
        if kind not in KINDS or status not in STATUSES:
            return self._err(f"kind must be one of {KINDS}; status one of {STATUSES}.")
        dup = next((e for e in entries if e.get("title", "").lower() == title.lower()
                    and e.get("kind") == kind), None)
        if dup:
            return self._err(f"Already saved as {dup['id']}. Use update instead.")
        entry = {
            "id": _next_id(entries), "kind": kind, "title": title,
            "platform": _clip(p.get("platform"), 40).lower(), "status": status,
            "text": _clip(p.get("text"), _MAX_TEXT),
            "tags": [_clip(t, 30).lstrip("#") for t in (p.get("tags") or [])][:10],
            "metrics": p.get("metrics") if isinstance(p.get("metrics"), dict) else {},
            "notes": _clip(p.get("notes"), 2000),
            "created": _now(), "updated": _now(),
        }
        entries.append(entry)
        _save(entries)
        return self._ok(f"Saved {entry['id']}: {title}", id=entry["id"])

    def _update(self, entries: List[Dict[str, Any]], p: Dict[str, Any]) -> ToolResult:
        e = self._find(entries, p)
        if not e:
            return self._err("Entry not found.")
        for field, limit in (("title", 200), ("platform", 40), ("text", _MAX_TEXT), ("notes", 2000)):
            if p.get(field) is not None:
                e[field] = _clip(p[field], limit)
        if p.get("kind"):
            if str(p["kind"]).lower() not in KINDS:
                return self._err(f"kind must be one of {KINDS}.")
            e["kind"] = str(p["kind"]).lower()
        if p.get("status"):
            if str(p["status"]).lower() not in STATUSES:
                return self._err(f"status must be one of {STATUSES}.")
            e["status"] = str(p["status"]).lower()
        if isinstance(p.get("tags"), list):
            e["tags"] = [_clip(t, 30).lstrip("#") for t in p["tags"]][:10]
        if isinstance(p.get("metrics"), dict):
            e["metrics"] = {**(e.get("metrics") or {}), **p["metrics"]}
        e["updated"] = _now()
        _save(entries)
        return self._ok(f"Updated {e['id']}: {e.get('title')}")

    def _list(self, entries: List[Dict[str, Any]], p: Dict[str, Any], *, search: bool) -> ToolResult:
        res = entries
        for field in ("kind", "status", "platform"):
            if p.get(field):
                res = [e for e in res if str(e.get(field, "")).lower() == str(p[field]).lower()]
        if search:
            q = str(p.get("query", "")).strip().lower()
            if not q:
                return self._err("A query is required for search.")
            res = [e for e in res if q in json.dumps(e, ensure_ascii=False).lower()]
        limit = max(1, min(int(p.get("limit", 15) or 15), 50))
        res = sorted(res, key=lambda e: e.get("updated", ""), reverse=True)[:limit]
        return self._ok("\n".join(_line(e) for e in res) or "Nothing saved yet.", count=len(res))
