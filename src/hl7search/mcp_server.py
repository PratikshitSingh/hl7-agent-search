"""MCP server exposing the HL7 search tools to any MCP client (Claude Code,
Claude Desktop, other agent frameworks). Runs over stdio.

    HL7_DB=hl7.db hl7-mcp
"""

from __future__ import annotations

import functools
import os
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from .store import Scope, SearchResult
from .tool import GUIDE, FilterSpec, HL7Tools

_READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True)


def _agent_visible_errors[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """MCP SDK 2.x hides ordinary exception text from the client. Validation errors
    ("Invalid HL7 path 'X'...") are exactly what an agent needs to fix its next call,
    so re-raise them as ToolError, whose message IS sent back."""

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


def build_server(db_path: str) -> MCPServer:
    tools = HL7Tools(db_path)
    mcp: MCPServer = MCPServer("hl7-search", instructions=GUIDE)

    @mcp.tool(annotations=_READ_ONLY)
    @_agent_visible_errors
    def hl7_stats() -> dict[str, Any]:
        """Overview of the store: message counts by type/trigger event and the segment
        types present. Call this first to see what data exists."""
        return tools.stats()

    @mcp.tool(annotations=_READ_ONLY)
    @_agent_visible_errors
    def hl7_search_messages(
        filters: list[FilterSpec] | None = None,
        scope: Scope = "message",
        message_type: str | None = None,
        trigger_events: list[str] | None = None,
        since: str | None = None,
        until: str | None = None,
        return_fields: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> SearchResult:
        """Search stored HL7 v2 messages by ANY field. All filters must match (AND).

        filters: [{"path": "PID.3.1", "op": "eq", "value": "12345"}, ...]
          op: eq | in (value is a list) | prefix | contains | gt | gte | lt | lte
          numeric: true to compare gt/lt as numbers (e.g. OBX.5 lab values)
        scope: "message" (filters may match anywhere in the message), "segment" (same
          segment instance, e.g. one OBX's code AND value), or "repetition" (same field
          repetition, e.g. PID.3.1 + PID.3.4 of the same identifier).
        message_type / trigger_events: shortcuts for MSH-9.1 / MSH-9.2, e.g. "ADT",
          ["A01","A02","A03"].
        since / until: event time bounds, HL7 (20240301) or ISO-8601.
        return_fields: paths to include per hit, e.g. ["PV1.3", "PV1.19", "PID.5"].
        Results are sorted by event time; page with offset/next_offset.
        """
        return tools.search_messages(
            filters, scope, message_type, trigger_events, since, until,
            return_fields, limit, offset,
        )  # fmt: skip

    @mcp.tool(annotations=_READ_ONLY)
    @_agent_visible_errors
    def hl7_get_message(message_id: int) -> dict[str, Any]:
        """Full message by id: raw text plus every non-empty field with its HL7 name."""
        return tools.get_message(message_id)

    @mcp.tool(annotations=_READ_ONLY)
    @_agent_visible_errors
    def hl7_describe_segment(segment: str) -> dict[str, Any]:
        """Which fields of a segment (e.g. "PV1", or custom Z-segments) hold data,
        with names and an example value. Use it to discover paths to filter on."""
        return tools.describe_segment(segment)

    return mcp


def main() -> None:
    build_server(os.getenv("HL7_DB", "hl7.db")).run("stdio")


if __name__ == "__main__":
    main()
