"""Asyncio TCP server that receives HL7 v2 messages and ACKs them.

Contract with the sender: **commit to the DB, then ACK**. If the sender never sees
an ACK it retries, and the insert is idempotent on MSH-10, so retries are safe.

ACK codes: AA = accepted, AE = application error (we couldn't store it),
AR = reject (we couldn't even read it as HL7).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import itertools
import logging
import os
import signal
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from .mllp import FrameTooLarge, Mode, StreamFramer, frame
from .parser import HL7ParseError, ParsedMessage, parse
from .store import Store

log = logging.getLogger("hl7search.server")
_ack_ids = itertools.count(1)

type AckCode = Literal["AA", "AE", "AR"]


@dataclass(frozen=True, slots=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 2575
    db_path: str = "hl7.db"
    max_frame_bytes: int = 1_048_576
    idle_timeout_s: float = 60.0
    raw_quiet_s: float = 0.5  # raw mode: a pause this long ends the message
    max_connections: int = 100

    @classmethod
    def from_env(cls) -> ServerConfig:
        d = cls()
        return cls(
            host=os.getenv("HL7_HOST", d.host),
            port=int(os.getenv("HL7_PORT", d.port)),
            db_path=os.getenv("HL7_DB", d.db_path),
            max_frame_bytes=int(os.getenv("HL7_MAX_FRAME_BYTES", d.max_frame_bytes)),
            idle_timeout_s=float(os.getenv("HL7_IDLE_TIMEOUT_S", d.idle_timeout_s)),
        )


def decode(payload: bytes) -> str:
    """HL7 is usually ASCII/Latin-1; try UTF-8 first. (Improvement: honour MSH-18.)"""
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload.decode("latin-1")


def build_ack(msg: ParsedMessage | None, code: AckCode, text: str = "") -> str:
    """Build an ACK with the sender/receiver swapped, using the message's own separators."""
    now = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    ack_id = f"ACK{now}{next(_ack_ids):06d}"
    if msg is None:
        return f"MSH|^~\\&|HL7SEARCH||||{now}||ACK|{ack_id}|P|2.5\rMSA|{code}||{text}\r"
    fs = msg.encoding.field
    msh = msg.first("MSH")
    assert msh is not None
    f = msh.field
    trigger = msg.trigger_event
    msg_type = f"ACK{msg.encoding.component}{trigger}" if trigger else "ACK"
    header = fs.join(
        [
            "MSH",
            msg.encoding.msh2,
            f(5) or "HL7SEARCH",  # we are the receiver -> become the sender
            f(6),
            f(3),
            f(4),
            now,
            "",
            msg_type,
            ack_id,
            f(11) or "P",
            f(12) or "2.5",
        ]
    )
    msa = fs.join(["MSA", code, f(10), *([text.replace(fs, " ")] if text else [])])
    return f"{header}\r{msa}\r"


class HL7Server:
    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.store = Store(config.db_path)
        self._sem = asyncio.Semaphore(config.max_connections)
        self._server: asyncio.Server | None = None
        self.stats = {"accepted": 0, "duplicates": 0, "errors": 0, "rejected": 0}

    async def start(self) -> asyncio.Server:
        self._server = await asyncio.start_server(self._handle, self.config.host, self.config.port)
        addrs = ", ".join(str(s.getsockname()) for s in self._server.sockets)
        log.info("listening on %s (db=%s)", addrs, self.config.db_path)
        return self._server

    @property
    def port(self) -> int:
        assert self._server is not None
        return int(self._server.sockets[0].getsockname()[1])

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self.store.close()

    async def process(self, payload: bytes) -> str:
        """Parse -> store -> ACK. Never raises: every outcome becomes an ACK."""
        try:
            msg = parse(decode(payload))
        except HL7ParseError as exc:
            self.stats["rejected"] += 1
            log.warning("rejected unreadable message: %s", exc)
            return build_ack(None, "AR", str(exc))
        for w in msg.warnings:
            log.warning("control_id=%s: %s", msg.control_id, w)
        try:
            # sqlite3 is blocking; keep the event loop free for other connections.
            result = await asyncio.to_thread(self.store.insert, msg)
        except Exception:
            self.stats["errors"] += 1
            log.exception("failed to store control_id=%s", msg.control_id)
            return build_ack(msg, "AE", "storage error")
        self.stats["duplicates" if result.duplicate else "accepted"] += 1
        # Log identifiers only, never message bodies: they contain PHI.
        log.info(
            "stored id=%s type=%s^%s control_id=%s duplicate=%s",
            result.message_id,
            msg.message_type,
            msg.trigger_event,
            msg.control_id,
            result.duplicate,
        )
        return build_ack(msg, "AA")

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        async with self._sem:
            framer = StreamFramer(self.config.max_frame_bytes)
            try:
                while True:
                    timeout = (
                        self.config.raw_quiet_s
                        if framer.mode is Mode.RAW and framer.pending
                        else self.config.idle_timeout_s
                    )
                    try:
                        data = await asyncio.wait_for(reader.read(65536), timeout)
                    except TimeoutError:
                        if framer.mode is Mode.RAW and framer.pending:
                            await self._reply_all(framer.flush(), framer, writer)
                            continue
                        log.info("idle timeout, closing %s", peer)
                        break
                    if not data:  # EOF (client may have half-closed; we can still reply)
                        await self._reply_all(framer.flush(), framer, writer)
                        break
                    await self._reply_all(framer.feed(data), framer, writer)
            except FrameTooLarge as exc:
                log.warning("closing %s: %s", peer, exc)
            except (ConnectionResetError, BrokenPipeError):
                log.info("connection reset by %s", peer)
            finally:
                if framer.discarded_bytes:
                    log.warning("discarded %d bytes outside MLLP frames", framer.discarded_bytes)
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()

    async def _reply_all(
        self, payloads: list[bytes], framer: StreamFramer, writer: asyncio.StreamWriter
    ) -> None:
        for payload in payloads:
            ack = await self.process(payload)
            # Answer in the same framing the sender used.
            writer.write(frame(ack) if framer.mode is Mode.MLLP else (ack + "\n").encode())
            await writer.drain()


async def serve(config: ServerConfig) -> None:
    server = HL7Server(config)
    await server.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows
            loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    log.info("shutting down; stats=%s", server.stats)
    await server.stop()


def main() -> None:
    env = ServerConfig.from_env()
    p = argparse.ArgumentParser(description="HL7 v2 MLLP ingest server")
    p.add_argument("--host", default=env.host)
    p.add_argument("--port", type=int, default=env.port)
    p.add_argument("--db", default=env.db_path)
    p.add_argument("--log-level", default=os.getenv("HL7_LOG_LEVEL", "INFO"))
    a = p.parse_args()
    logging.basicConfig(level=a.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = ServerConfig(
        host=a.host,
        port=a.port,
        db_path=a.db,
        max_frame_bytes=env.max_frame_bytes,
        idle_timeout_s=env.idle_timeout_s,
    )
    asyncio.run(serve(cfg))


if __name__ == "__main__":
    main()
