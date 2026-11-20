"""Minimal MLLP sender: send messages, wait for each ACK."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Iterable
from pathlib import Path

from .mllp import StreamFramer, frame


async def send_messages(
    host: str, port: int, messages: Iterable[str], timeout_s: float = 10.0
) -> list[str]:
    """Send each message over one connection and return the ACKs in order."""
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout_s)
    framer = StreamFramer()
    acks: list[str] = []
    try:
        for msg in messages:
            writer.write(frame(msg))
            await writer.drain()
            pending: list[bytes] = []
            while not pending:
                data = await asyncio.wait_for(reader.read(65536), timeout_s)
                if not data:
                    raise ConnectionError("server closed the connection before ACKing")
                pending = framer.feed(data)
            acks.extend(p.decode("utf-8", "replace") for p in pending)
    finally:
        writer.close()
        await writer.wait_closed()
    return acks


def split_file(text: str) -> list[str]:
    """Messages in a file are separated by blank lines; segments by newlines."""
    chunks = [c.strip() for c in text.replace("\r\n", "\n").split("\n\n")]
    return [c.replace("\n", "\r") for c in chunks if c]


def main() -> None:
    p = argparse.ArgumentParser(description="Send HL7 messages over MLLP")
    p.add_argument("file", nargs="?", help="file of messages separated by blank lines (- = stdin)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=2575)
    a = p.parse_args()
    text = sys.stdin.read() if a.file in (None, "-") else Path(a.file).read_text()
    acks = asyncio.run(send_messages(a.host, a.port, split_file(text)))
    for ack in acks:
        print(ack.replace("\r", "\n"))


if __name__ == "__main__":
    main()
