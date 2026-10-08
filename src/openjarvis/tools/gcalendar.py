"""Executable live-API tools for Google Calendar (read + create events)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, List

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _connector():
    from openjarvis.connectors.gcalendar import GCalendarConnector

    return GCalendarConnector()


def _rfc3339(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@ToolRegistry.register("calendar_get_events_today")
class CalendarGetEventsTodayTool(BaseTool):
    tool_id = "calendar_get_events_today"

    @property
    def spec(self) -> ToolSpec:
        return _connector().mcp_tools()[0]

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.connectors.gcalendar import _format_event, _gcal_api_events_list
        from openjarvis.connectors.google_auth import call_with_refresh

        calendar_id = str(params.get("calendar_id", "primary")).strip() or "primary"
        connector = _connector()
        if not connector.is_connected():
            return ToolResult(
                tool_name=self.tool_id,
                content="Google Calendar is not connected. Run `jarvis connect gcalendar` first.",
                success=False,
            )

        now = datetime.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        resp = call_with_refresh(
            _gcal_api_events_list,
            connector._credentials_path,
            calendar_id,
            time_min=_rfc3339(start_of_day),
            time_max=_rfc3339(end_of_day),
        )
        events = resp.get("items", [])
        lines = [_format_event(e) for e in events]

        return ToolResult(
            tool_name=self.tool_id,
            content="\n\n".join(lines) or "No events scheduled today.",
            success=True,
            metadata={"count": len(events)},
        )


@ToolRegistry.register("calendar_search_events")
class CalendarSearchEventsTool(BaseTool):
    tool_id = "calendar_search_events"

    @property
    def spec(self) -> ToolSpec:
        return _connector().mcp_tools()[1]

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.connectors.gcalendar import _format_event, _gcal_api_events_list
        from openjarvis.connectors.google_auth import call_with_refresh

        query = str(params.get("query", "")).strip()
        if not query:
            return ToolResult(
                tool_name=self.tool_id, content="A query is required.", success=False
            )
        max_results = max(1, min(int(params.get("max_results", 20)), 100))
        calendar_id = str(params.get("calendar_id", "primary")).strip() or "primary"

        connector = _connector()
        if not connector.is_connected():
            return ToolResult(
                tool_name=self.tool_id,
                content="Google Calendar is not connected. Run `jarvis connect gcalendar` first.",
                success=False,
            )

        resp = call_with_refresh(
            _gcal_api_events_list, connector._credentials_path, calendar_id, query=query
        )
        events: List[Any] = resp.get("items", [])[:max_results]
        lines = [_format_event(e) for e in events]

        return ToolResult(
            tool_name=self.tool_id,
            content="\n\n".join(lines) or f"No events matched '{query}'.",
            success=True,
            metadata={"count": len(events)},
        )


@ToolRegistry.register("calendar_next_meeting")
class CalendarNextMeetingTool(BaseTool):
    tool_id = "calendar_next_meeting"

    @property
    def spec(self) -> ToolSpec:
        return _connector().mcp_tools()[2]

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.connectors.gcalendar import _format_event, _gcal_api_events_list
        from openjarvis.connectors.google_auth import call_with_refresh

        calendar_id = str(params.get("calendar_id", "primary")).strip() or "primary"
        connector = _connector()
        if not connector.is_connected():
            return ToolResult(
                tool_name=self.tool_id,
                content="Google Calendar is not connected. Run `jarvis connect gcalendar` first.",
                success=False,
            )

        resp = call_with_refresh(
            _gcal_api_events_list,
            connector._credentials_path,
            calendar_id,
            time_min=_rfc3339(datetime.now()),
        )
        events = resp.get("items", [])
        if not events:
            return ToolResult(
                tool_name=self.tool_id, content="No upcoming meetings.", success=True
            )

        return ToolResult(
            tool_name=self.tool_id,
            content=_format_event(events[0]),
            success=True,
        )


@ToolRegistry.register("calendar_create_event")
class CalendarCreateEventTool(BaseTool):
    tool_id = "calendar_create_event"

    @property
    def spec(self) -> ToolSpec:
        return _connector().mcp_tools()[3]

    def execute(self, **params: Any) -> ToolResult:
        summary = str(params.get("summary", "")).strip()
        start = str(params.get("start", "")).strip()
        end = str(params.get("end", "")).strip()
        if not summary or not start or not end:
            return ToolResult(
                tool_name=self.tool_id,
                content="'summary', 'start', and 'end' are required.",
                success=False,
            )

        connector = _connector()
        if not connector.is_connected():
            return ToolResult(
                tool_name=self.tool_id,
                content="Google Calendar is not connected. Run `jarvis connect gcalendar` first.",
                success=False,
            )

        try:
            event = connector.create_event(
                summary=summary,
                start=start,
                end=end,
                attendees=params.get("attendees") or [],
                description=str(params.get("description", "")),
                calendar_id=str(params.get("calendar_id", "primary")) or "primary",
                add_meet=bool(params.get("add_meet", True)),
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Failed to create event: {exc}",
                success=False,
            )

        meet_link = event.get("hangoutLink", "")
        content = f"Created '{summary}'. Link: {event.get('htmlLink', '')}"
        if meet_link:
            content += f"\nGoogle Meet: {meet_link}"

        return ToolResult(
            tool_name=self.tool_id,
            content=content,
            success=True,
            metadata={"event_id": event.get("id", ""), "meet_link": meet_link},
        )
