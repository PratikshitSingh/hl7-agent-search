"""MLLP framing (pure, no I/O) with a raw-text fallback.

MLLP wraps each message as ``<VT> message <FS><CR>`` (0x0B ... 0x1C 0x0D) because
TCP is a byte stream with no message boundaries: one ``read()`` may return half a
message or three messages.

Raw mode exists because the task's example is an unframed string; someone may
just ``printf ... | nc host port``. In raw mode a message ends when the next
``MSH`` segment starts, when the stream goes quiet, or at EOF.
"""

from __future__ import annotations

import re
from enum import Enum

START_BLOCK = b"\x0b"
END_BLOCK = b"\x1c"
CARRIAGE_RETURN = b"\x0d"

_RAW_BOUNDARY = re.compile(rb"[\r\n]+(?=MSH)")
# NOT bare bytes.strip(): it treats 0x0B (VT, the MLLP start byte) as whitespace.
_WS = b" \t\r\n"


class FrameTooLarge(Exception):
    """A frame exceeded the configured size limit (protects memory)."""


class Mode(Enum):
    UNKNOWN = "unknown"
    MLLP = "mllp"
    RAW = "raw"


def frame(message: str | bytes, encoding: str = "utf-8") -> bytes:
    body = message.encode(encoding) if isinstance(message, str) else message
    return START_BLOCK + body + END_BLOCK + CARRIAGE_RETURN


class StreamFramer:
    """Feed it bytes as they arrive; it returns complete message payloads."""

    def __init__(self, max_frame_bytes: int = 1_048_576) -> None:
        self.max_frame_bytes = max_frame_bytes
        self.mode = Mode.UNKNOWN
        self._buf = bytearray()
        self._skip_cr = False
        self.discarded_bytes = 0

    @property
    def pending(self) -> bool:
        return bool(self._buf.strip(_WS))

    def feed(self, data: bytes) -> list[bytes]:
        self._buf += data
        if self.mode is Mode.UNKNOWN:
            stripped = self._buf.lstrip(_WS)
            if not stripped:
                return []
            self.mode = Mode.MLLP if stripped[:1] == START_BLOCK else Mode.RAW
        return self._feed_mllp() if self.mode is Mode.MLLP else self._feed_raw()

    def flush(self) -> list[bytes]:
        """Call at EOF / idle timeout. In raw mode the buffered text is one message.
        In MLLP mode an unterminated frame is incomplete and is dropped."""
        if self.mode is Mode.RAW and self._buf.strip(_WS):
            out = [bytes(self._buf.strip(_WS))]
            self._buf.clear()
            return out
        if self._buf.strip(_WS):
            self.discarded_bytes += len(self._buf)
        self._buf.clear()
        return []

    # ------------------------------------------------------------------ internals

    def _feed_mllp(self) -> list[bytes]:
        out: list[bytes] = []
        while True:
            if self._skip_cr and self._buf[:1] == CARRIAGE_RETURN:
                del self._buf[:1]
            if self._buf:
                self._skip_cr = False
            start = self._buf.find(START_BLOCK)
            if start == -1:
                # Bytes outside a frame are noise (often a stray CR/LF). Drop them.
                self.discarded_bytes += len(self._buf.strip(_WS))
                self._buf.clear()
                return out
            if start > 0:
                self.discarded_bytes += len(self._buf[:start].strip(_WS))
                del self._buf[:start]
            end = self._buf.find(END_BLOCK, 1)
            if end == -1:
                if len(self._buf) > self.max_frame_bytes:
                    raise FrameTooLarge(f"frame exceeds {self.max_frame_bytes} bytes")
                return out
            out.append(bytes(self._buf[1:end]))
            del self._buf[: end + 1]
            # Spec says FS is followed by CR; be lenient if the CR is late or missing.
            if self._buf[:1] == CARRIAGE_RETURN:
                del self._buf[:1]
            elif not self._buf:
                self._skip_cr = True

    def _feed_raw(self) -> list[bytes]:
        if len(self._buf) > self.max_frame_bytes:
            raise FrameTooLarge(f"raw message exceeds {self.max_frame_bytes} bytes")
        parts = _RAW_BOUNDARY.split(bytes(self._buf))
        # Everything except the last part is complete (a new MSH started after it).
        complete = [p.strip(_WS) for p in parts[:-1] if p.strip(_WS)]
        self._buf = bytearray(parts[-1])
        return complete
