"""Call the HL7 MCP server over a real stdio transport (same as Claude Desktop/Code).

    python scripts/mcp_call.py --list
    python scripts/mcp_call.py hl7_stats '{}'
    python scripts/mcp_call.py hl7_search_messages '{"filters": [...]}'

Every call is appended to --log (markdown) so an agent session can be replayed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
from pathlib import Path

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.types import TextContent


async def call(db: str, tool: str | None, args: dict[str, object], log: Path | None) -> None:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "hl7search.mcp_server"],
        env={**os.environ, "HL7_DB": db},
    )
    async with Client(server) as client:
        if tool is None:
            for t in (await client.list_tools()).tools:
                print(f"## {t.name}\n{t.description}\n")
            print(f"## server instructions\n{client.instructions}")
            return
        res = await client.call_tool(tool, args)
        text = "\n".join(c.text for c in res.content if isinstance(c, TextContent))
        with contextlib.suppress(json.JSONDecodeError):  # pretty-print JSON results
            text = json.dumps(json.loads(text), indent=2)
        print(("ERROR: " if res.is_error else "") + text)
        if log:
            with log.open("a") as fh:
                fh.write(f"\n### `{tool}`\n```json\n{json.dumps(args, indent=2)}\n```\n")
                fh.write(f"Result{' (error)' if res.is_error else ''}:\n```json\n{text}\n```\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("tool", nargs="?")
    p.add_argument("args", nargs="?", default="{}")
    p.add_argument("--list", action="store_true")
    p.add_argument("--db", default=os.getenv("HL7_DB", "hl7.db"))
    p.add_argument("--log", type=Path)
    a = p.parse_args()
    asyncio.run(call(a.db, None if a.list else a.tool, json.loads(a.args), a.log))


if __name__ == "__main__":
    main()
