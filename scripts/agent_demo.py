"""Agent demo: Claude uses the HL7 MCP tools to build a patient's ADT timeline.

The agent sees only the MCP tool list + server instructions. Nothing about the
query is hard-coded; every tool call is printed so you can follow its reasoning.

    export ANTHROPIC_API_KEY=...
    python scripts/agent_demo.py --db hl7.db
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from anthropic import AsyncAnthropic
from mcp.client import Client

from hl7search.mcp_server import build_server

DEFAULT_QUESTION = (
    "Find all admissions, discharges and transfers for the patient with MRN 12345 at "
    "facility MC. Give a chronological timeline grouped by visit, with locations, and "
    "flag anything that was cancelled."
)


async def run(db: str, question: str, model: str, max_turns: int = 12) -> str:
    anthropic = AsyncAnthropic()
    async with Client(build_server(db)) as mcp:
        tools: list[Any] = [
            {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
            for t in (await mcp.list_tools()).tools
        ]
        system = (mcp.instructions or "") + "\nAnswer only from tool results."
        messages: list[Any] = [{"role": "user", "content": question}]
        for turn in range(max_turns):
            resp = await anthropic.messages.create(
                model=model, max_tokens=4096, system=system, tools=tools, messages=messages
            )
            messages.append({"role": "assistant", "content": resp.content})
            calls = [b for b in resp.content if b.type == "tool_use"]
            if not calls:
                return "".join(b.text for b in resp.content if b.type == "text")
            results = []
            for call in calls:
                print(f"\n[turn {turn + 1}] tool call: {call.name}")
                print(json.dumps(call.input, indent=2))
                res = await mcp.call_tool(call.name, dict(call.input))
                text = "\n".join(c.text for c in res.content if c.type == "text")
                print(f"  -> {'ERROR ' if res.is_error else ''}{len(text)} chars")
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": text,
                        "is_error": bool(res.is_error),
                    }
                )
            messages.append({"role": "user", "content": results})
    raise RuntimeError("agent did not finish within max_turns")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=os.getenv("HL7_DB", "hl7.db"))
    p.add_argument("--model", default=os.getenv("HL7_AGENT_MODEL", "claude-sonnet-5-5"))
    p.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    a = p.parse_args()
    print("\n=== ANSWER ===\n" + asyncio.run(run(a.db, a.question, a.model)))


if __name__ == "__main__":
    main()
