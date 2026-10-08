"""Executable live-API tools for Gmail (search, read, send)."""

from __future__ import annotations

from typing import Any, List

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _connector():
    from openjarvis.connectors.gmail import GmailConnector

    return GmailConnector()


@ToolRegistry.register("gmail_search_emails")
class GmailSearchEmailsTool(BaseTool):
    tool_id = "gmail_search_emails"

    @property
    def spec(self) -> ToolSpec:
        return _connector().mcp_tools()[0]

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.connectors.gmail import (
            _gmail_api_get_message,
            _gmail_api_list_messages,
        )
        from openjarvis.connectors.google_auth import call_with_refresh

        query = str(params.get("query", "")).strip()
        if not query:
            return ToolResult(
                tool_name=self.tool_id, content="A query is required.", success=False
            )
        max_results = max(1, min(int(params.get("max_results", 20)), 100))

        connector = _connector()
        if not connector.is_connected():
            return ToolResult(
                tool_name=self.tool_id,
                content="Gmail is not connected. Run `jarvis connect gmail` first.",
                success=False,
            )

        list_resp = call_with_refresh(
            _gmail_api_list_messages, connector._credentials_path, query=query
        )
        stubs = list_resp.get("messages", [])[:max_results]

        lines: List[str] = []
        for stub in stubs:
            msg = call_with_refresh(
                _gmail_api_get_message, connector._credentials_path, stub["id"]
            )
            headers = msg.get("payload", {}).get("headers", [])
            subject = next(
                (h["value"] for h in headers if h.get("name") == "Subject"), ""
            )
            sender = next(
                (h["value"] for h in headers if h.get("name") == "From"), ""
            )
            lines.append(
                f"[{stub['id']}] From: {sender} | Subject: {subject} | "
                f"{msg.get('snippet', '')}"
            )

        return ToolResult(
            tool_name=self.tool_id,
            content="\n".join(lines) or f"No emails matched '{query}'.",
            success=True,
            metadata={"count": len(lines)},
        )


@ToolRegistry.register("gmail_list_unread")
class GmailListUnreadTool(BaseTool):
    tool_id = "gmail_list_unread"

    @property
    def spec(self) -> ToolSpec:
        return _connector().mcp_tools()[2]

    def execute(self, **params: Any) -> ToolResult:
        label = str(params.get("label", "INBOX")).strip()
        max_results = params.get("max_results", 20)
        query = "is:unread" + (f" label:{label}" if label else "")
        return GmailSearchEmailsTool().execute(query=query, max_results=max_results)


@ToolRegistry.register("gmail_get_thread")
class GmailGetThreadTool(BaseTool):
    tool_id = "gmail_get_thread"

    @property
    def spec(self) -> ToolSpec:
        return _connector().mcp_tools()[1]

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.connectors.gmail import _gmail_api_get_thread
        from openjarvis.connectors.google_auth import call_with_refresh

        thread_id = str(params.get("thread_id", "")).strip()
        if not thread_id:
            return ToolResult(
                tool_name=self.tool_id,
                content="A thread_id is required.",
                success=False,
            )

        connector = _connector()
        if not connector.is_connected():
            return ToolResult(
                tool_name=self.tool_id,
                content="Gmail is not connected. Run `jarvis connect gmail` first.",
                success=False,
            )

        thread = call_with_refresh(
            _gmail_api_get_thread, connector._credentials_path, thread_id
        )
        lines: List[str] = []
        for msg in thread.get("messages", []):
            headers = msg.get("payload", {}).get("headers", [])
            sender = next(
                (h["value"] for h in headers if h.get("name") == "From"), ""
            )
            lines.append(f"From: {sender}\n{msg.get('snippet', '')}")

        return ToolResult(
            tool_name=self.tool_id,
            content="\n\n".join(lines) or "Thread has no messages.",
            success=True,
            metadata={"count": len(lines)},
        )


@ToolRegistry.register("gmail_send_email")
class GmailSendEmailTool(BaseTool):
    tool_id = "gmail_send_email"

    @property
    def spec(self) -> ToolSpec:
        return _connector().mcp_tools()[3]

    def execute(self, **params: Any) -> ToolResult:
        to = str(params.get("to", "")).strip()
        subject = str(params.get("subject", "")).strip()
        body = str(params.get("body", ""))
        cc = str(params.get("cc", "")).strip()

        if not to or not subject:
            return ToolResult(
                tool_name=self.tool_id,
                content="'to' and 'subject' are required.",
                success=False,
            )

        connector = _connector()
        if not connector.is_connected():
            return ToolResult(
                tool_name=self.tool_id,
                content="Gmail is not connected. Run `jarvis connect gmail` first.",
                success=False,
            )

        try:
            msg_id = connector.send_message(to=to, subject=subject, body=body, cc=cc)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Failed to send email: {exc}",
                success=False,
            )

        return ToolResult(
            tool_name=self.tool_id,
            content=f"Email sent to {to} (id: {msg_id}).",
            success=True,
            metadata={"message_id": msg_id},
        )
