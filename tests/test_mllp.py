from __future__ import annotations

import pytest

from hl7search.mllp import FrameTooLarge, Mode, StreamFramer, frame

MSG_A = b"MSH|^~\\&|A|B|||20240101||ADT^A01|1|P|2.5\rPID|1||1"
MSG_B = b"MSH|^~\\&|A|B|||20240101||ADT^A02|2|P|2.5\rPID|1||2"


def test_one_message_split_across_many_reads() -> None:
    f = StreamFramer()
    data = frame(MSG_A)
    out: list[bytes] = []
    for i in range(len(data)):  # worst case: one byte per read
        out += f.feed(data[i : i + 1])
    assert out == [MSG_A]
    assert f.mode is Mode.MLLP


def test_several_messages_in_one_read() -> None:
    f = StreamFramer()
    assert f.feed(frame(MSG_A) + frame(MSG_B) + frame(MSG_A)) == [MSG_A, MSG_B, MSG_A]


def test_frame_end_split_between_fs_and_cr() -> None:
    f = StreamFramer()
    data = frame(MSG_A)
    assert f.feed(data[:-1]) == [MSG_A]  # FS arrived, CR not yet
    assert f.feed(b"\r" + frame(MSG_B)) == [MSG_B]
    assert f.discarded_bytes == 0


def test_noise_between_frames_is_dropped() -> None:
    f = StreamFramer()
    assert f.feed(frame(MSG_A) + b"\r\ngarbage" + frame(MSG_B)) == [MSG_A, MSG_B]
    assert f.discarded_bytes == len(b"garbage")


def test_incomplete_frame_is_not_emitted() -> None:
    f = StreamFramer()
    assert f.feed(b"\x0b" + MSG_A) == []
    assert f.flush() == []  # EOF mid-frame: drop, don't store half a message


def test_frame_too_large() -> None:
    f = StreamFramer(max_frame_bytes=100)
    with pytest.raises(FrameTooLarge):
        f.feed(b"\x0b" + b"x" * 200)


def test_raw_mode_splits_on_msh_and_flushes_at_eof() -> None:
    f = StreamFramer()
    out = f.feed(MSG_A + b"\n" + MSG_B[:20])
    assert f.mode is Mode.RAW
    assert out == [MSG_A]
    assert f.feed(MSG_B[20:] + b"\n") == []
    assert f.flush() == [MSG_B]
