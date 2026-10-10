"""Read-only Instagram tools (account overview, recent posts, post insights).

Uses the Instagram API with Instagram Login (graph.instagram.com) for a
professional (Creator/Business) account. Credentials come from the
environment (``.env``):

    INSTAGRAM_ACCESS_TOKEN   long-lived user access token (about 60 days)
    INSTAGRAM_USER_ID        optional; defaults to ``me``

These tools never post, comment, delete or message anything.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_API = "https://graph.instagram.com"

# Reels/video and image/carousel expose different metrics; unsupported ones make
# the whole request fail, so we try the richest set first and fall back.
_MEDIA_METRIC_SETS = (
    "reach,views,likes,comments,shares,saved,total_interactions",
    "reach,likes,comments,shares,saved,total_interactions",
    "reach,likes,comments,saved",
    "reach",
)


class _InstagramError(Exception):
    pass


def _credentials() -> tuple[str, str]:
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    if not token:
        raise _InstagramError(
            "Instagram is not connected: INSTAGRAM_ACCESS_TOKEN is missing in .env."
        )
    return token, os.environ.get("INSTAGRAM_USER_ID", "").strip() or "me"


def _get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    token, _ = _credentials()
    resp = httpx.get(
        f"{_API}/{path.lstrip('/')}",
        params={**params, "access_token": token},
        timeout=30.0,
    )
    if resp.status_code >= 400:
        try:
            msg = resp.json().get("error", {}).get("message", resp.text)
        except Exception:
            msg = resp.text
        raise _InstagramError(f"Instagram API error {resp.status_code}: {msg}")
    return resp.json()


def _fail(tool_id: str, exc: Exception) -> ToolResult:
    return ToolResult(tool_name=tool_id, content=str(exc), success=False)


@ToolRegistry.register("instagram_account_overview")
class InstagramAccountOverviewTool(BaseTool):
    tool_id = "instagram_account_overview"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="instagram_account_overview",
            description=(
                "Get the user's Instagram account overview: username, followers, "
                "following and number of posts. Read-only."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            category="social",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            _, uid = _credentials()
            data = _get(
                uid,
                {"fields": "username,name,followers_count,follows_count,media_count,biography"},
            )
        except Exception as exc:
            return _fail(self.tool_id, exc)
        lines = [f"{k}: {v}" for k, v in data.items() if k != "id"]
        return ToolResult(
            tool_name=self.tool_id, content="\n".join(lines), success=True, metadata=data
        )


@ToolRegistry.register("instagram_recent_posts")
class InstagramRecentPostsTool(BaseTool):
    tool_id = "instagram_recent_posts"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="instagram_recent_posts",
            description=(
                "List the user's most recent Instagram posts and Reels with caption, "
                "date, likes and comments, and the media id (needed for "
                "instagram_post_insights). Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "How many posts to return (1-25, default 10).",
                    }
                },
                "required": [],
            },
            category="social",
        )

    def execute(self, **params: Any) -> ToolResult:
        limit = max(1, min(int(params.get("limit", 10) or 10), 25))
        try:
            _, uid = _credentials()
            data = _get(
                f"{uid}/media",
                {
                    "fields": (
                        "id,caption,media_type,media_product_type,permalink,"
                        "timestamp,like_count,comments_count"
                    ),
                    "limit": limit,
                },
            )
        except Exception as exc:
            return _fail(self.tool_id, exc)
        lines: List[str] = []
        for m in data.get("data", []):
            caption = (m.get("caption") or "").replace("\n", " ")[:90]
            lines.append(
                f"[{m['id']}] {m.get('timestamp', '')[:10]} "
                f"{m.get('media_product_type', m.get('media_type', ''))} | "
                f"likes {m.get('like_count', '?')} | comments "
                f"{m.get('comments_count', '?')} | {caption}"
            )
        return ToolResult(
            tool_name=self.tool_id,
            content="\n".join(lines) or "No posts found.",
            success=True,
            metadata={"count": len(lines)},
        )


@ToolRegistry.register("instagram_post_insights")
class InstagramPostInsightsTool(BaseTool):
    tool_id = "instagram_post_insights"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="instagram_post_insights",
            description=(
                "Get performance metrics (reach, views, likes, comments, shares, "
                "saves, interactions) for one Instagram post or Reel by media id. "
                "Read-only. Which metrics exist depends on the media type."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "media_id": {
                        "type": "string",
                        "description": "Media id from instagram_recent_posts.",
                    }
                },
                "required": ["media_id"],
            },
            category="social",
        )

    def execute(self, **params: Any) -> ToolResult:
        media_id = str(params.get("media_id", "")).strip()
        if not media_id.isdigit():
            return ToolResult(
                tool_name=self.tool_id,
                content="A numeric media_id is required (see instagram_recent_posts).",
                success=False,
            )
        last_err: Optional[Exception] = None
        for metrics in _MEDIA_METRIC_SETS:
            try:
                data = _get(f"{media_id}/insights", {"metric": metrics})
            except Exception as exc:
                last_err = exc
                continue
            values = {
                item["name"]: (item.get("values") or [{}])[0].get("value")
                for item in data.get("data", [])
            }
            return ToolResult(
                tool_name=self.tool_id,
                content="\n".join(f"{k}: {v}" for k, v in values.items())
                or "No insights returned.",
                success=True,
                metadata=values,
            )
        return _fail(self.tool_id, last_err or _InstagramError("No insights available."))
