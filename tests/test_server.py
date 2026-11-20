"""End-to-end: real TCP sockets against a real server on an ephemeral port."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from hl7search.client import send_messages
from hl7search.mllp import frame
from hl7search.seed import TASK_EXAMPLE_ORM, demo_messages
from hl7search.server import HL7Server, ServerConfig
from hl7search.store import FieldFilter, Store


@pytest.fixture
async def server(db_path: Path) -> AsyncIterator[HL7Server]:
    srv = HL7Server(ServerConfig(port=0, db_path=str(db_path), raw_quiet_s=0.2))
    await srv.start()
    yield srv
    await srv.stop()


def msa(ack: str) -> list[str]:
    line = next(s for s in ack.replace("\n", "\r").split("\r") if s.startswith("MSA"))
    return line.split("|")


async def test_ingest_ack_and_search(server: HL7Server, db_path: Path) -> None:
    msgs = demo_messages()
    acks = await send_messages("127.0.0.1", server.port, msgs)
    assert len(acks) == len(msgs)
    assert all(msa(a)[1] == "AA" for a in acks)
    # ACK echoes the original MSH-10 and swaps sender/receiver
    ack = next(a for a in acks if "AccessionNumber" in a)
    assert msa(ack)[2] == "AccessionNumber"
    assert ack.startswith("MSH|^~\\&|HL7SEARCH||BUNKERHILL|BH|")
    assert "|ACK^O01|" in ack

    s = Store(db_path, readonly=True)  # a separate reader while the server is up (WAL)
    assert s.stats()["total_messages"] == len(msgs)
    assert s.search([FieldFilter("OBX.5", "eq", "26")])["total"] == 1


async def test_resend_is_acked_but_not_duplicated(server: HL7Server, db_path: Path) -> None:
    await send_messages("127.0.0.1", server.port, [TASK_EXAMPLE_ORM])
    acks = await send_messages("127.0.0.1", server.port, [TASK_EXAMPLE_ORM])
    assert msa(acks[0])[1] == "AA"
    assert server.stats["duplicates"] == 1
    assert Store(db_path, readonly=True).stats()["total_messages"] == 1


async def test_garbage_gets_application_reject(server: HL7Server) -> None:
    acks = await send_messages("127.0.0.1", server.port, ["this is not hl7"])
    assert msa(acks[0])[1] == "AR"


async def test_raw_unframed_like_netcat(server: HL7Server, db_path: Path) -> None:
    """`printf '...' | nc host port` with no MLLP framing, connection closed after."""
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    writer.write(TASK_EXAMPLE_ORM.encode() + b"\n")
    writer.write_eof()  # half-close, like nc -N
    reply = (await asyncio.wait_for(reader.read(), 5)).decode()
    writer.close()
    assert msa(reply)[1:3] == ["AA", "AccessionNumber"]
    assert Store(db_path, readonly=True).stats()["total_messages"] == 1


async def test_raw_connection_kept_open_flushes_on_quiet(server: HL7Server) -> None:
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    writer.write(TASK_EXAMPLE_ORM.replace("\r", "\\r").encode() + b"\n")  # bash `echo` style
    reply = (await asyncio.wait_for(reader.readline(), 5)).decode()
    writer.close()
    assert msa(reply)[1] == "AA"


async def test_split_frames_over_the_socket(server: HL7Server) -> None:
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    data = frame(TASK_EXAMPLE_ORM)
    for chunk in (data[:7], data[7:50], data[50:]):
        writer.write(chunk)
        await writer.drain()
        await asyncio.sleep(0.01)
    reply = await asyncio.wait_for(reader.readuntil(b"\x1c\r"), 5)
    writer.close()
    assert b"MSA|AA|AccessionNumber" in reply


async def test_concurrent_senders(server: HL7Server, db_path: Path) -> None:
    msgs = demo_messages()
    halves = [msgs[::2], msgs[1::2]]
    results = await asyncio.gather(*(send_messages("127.0.0.1", server.port, h) for h in halves))
    assert sum(len(r) for r in results) == len(msgs)
    assert Store(db_path, readonly=True).stats()["total_messages"] == len(msgs)
