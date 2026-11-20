"""The MCP layer: tools are listed with schemas and return the right data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.client import Client
from mcp.types import TextContent

from hl7search.mcp_server import build_server
from hl7search.seed import EXPECTED_JANE_ADT_CONTROL_IDS
from hl7search.store import Store


def payload(result: Any) -> Any:
    if getattr(result, "structured_content", None):
        return result.structured_content
    return json.loads(result.content[0].text)


async def test_tools_listed_and_callable(store: Store, db_path: Path) -> None:
    async with Client(build_server(str(db_path))) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert names == {
            "hl7_stats", "hl7_search_messages", "hl7_get_message", "hl7_describe_segment",
        }  # fmt: skip
        r = payload(
            await client.call_tool(
                "hl7_search_messages",
                {
                    "filters": [
                        {"path": "PID.3.1", "value": "12345"},
                        {"path": "PID.3.4", "value": "MC"},
                    ],
                    "scope": "repetition",
                    "message_type": "ADT",
                    "trigger_events": ["A01", "A02", "A03", "A11", "A12", "A13"],
                },
            )
        )
        assert [h["control_id"] for h in r["hits"]] == EXPECTED_JANE_ADT_CONTROL_IDS


async def test_bad_path_returns_error_the_agent_can_read(store: Store, db_path: Path) -> None:
    async with Client(build_server(str(db_path))) as client:
        res = await client.call_tool(
            "hl7_search_messages", {"filters": [{"path": "PATIENT_ID", "value": "1"}]}
        )
        assert res.is_error
        first = res.content[0]
        assert isinstance(first, TextContent)
        assert "Invalid HL7 path" in first.text
