from __future__ import annotations

import hl7  # independent implementation, used as an oracle
import pytest

from hl7search.parser import HL7ParseError, flatten, hl7_ts_to_iso, parse, parse_path, unescape
from hl7search.seed import TASK_EXAMPLE_ORM, demo_messages

# The same message written the "Bash way": one line, CR between segments.
TASK_EXAMPLE_ONE_LINE = (
    "MSH|^~\\&|BUNKERHILL|BH|||20240509144522||ORM^O01|AccessionNumber|P|2.8\r"
    "PID|1||PatientID^^^MC^MC||PatientName||PatientBirthDate|\r"
    "ORC|XO||||||||\r"
    "OBR|1||AccessionNumber|IMG200^CT CHEST WITHOUT IV CONTRAST||||||||||||||||||"
    "20240509144522\r"
    "OBX|1|NM|513230^Bunkerhill - Coronary Calcium Scoring AI^Estimated calcium score||26"
)


def test_both_task_examples_are_the_same_message() -> None:
    assert TASK_EXAMPLE_ORM == TASK_EXAMPLE_ONE_LINE
    assert parse(TASK_EXAMPLE_ORM).raw == parse(TASK_EXAMPLE_ONE_LINE).raw


def test_msh_field_numbers_match_the_spec() -> None:
    m = parse(TASK_EXAMPLE_ORM)
    assert m.get("MSH.1") == "|"
    assert m.get("MSH.2") == "^~\\&"
    assert m.get("MSH.3") == "BUNKERHILL"
    assert m.get("MSH.9") == "ORM^O01"
    assert (m.message_type, m.trigger_event) == ("ORM", "O01")
    assert m.control_id == "AccessionNumber"
    assert m.get("MSH.12") == "2.8"


def test_example_fields() -> None:
    m = parse(TASK_EXAMPLE_ORM)
    assert m.get("PID.3.1") == "PatientID"
    assert m.get("PID.3.4") == "MC"
    assert m.get("PID.7") == "PatientBirthDate"  # lenient: not a valid date, still stored
    assert m.get("OBR.4.2") == "CT CHEST WITHOUT IV CONTRAST"
    assert m.get("OBR.22") == "20240509144522"
    assert m.get("OBX.3.3") == "Estimated calcium score"
    assert m.get("OBX.5") == "26"


@pytest.mark.parametrize("raw", [TASK_EXAMPLE_ORM, *demo_messages(shuffle=False)])
def test_matches_python_hl7_oracle(raw: str) -> None:
    ours = parse(raw)
    theirs = hl7.parse(raw)
    seen: dict[str, int] = {}
    for seg in ours.segments:
        if seg.name == "MSH":
            continue
        k = seen[seg.name] = seen.get(seg.name, -1) + 1  # nth OBX vs nth OBX
        other = theirs.segments(seg.name)[k]
        for n in range(1, len(seg.fields)):
            assert seg.fields[n] == str(other[n]), f"{seg.name}-{n}"
    for path, oracle in [("MSH.9.1", "MSH.F9.R1.C1"), ("MSH.9.2", "MSH.F9.R1.C2"),
                         ("MSH.10", "MSH.F10"), ("PID.3.1", "PID.F3.R1.C1")]:  # fmt: skip
        assert ours.get(path) == str(theirs[oracle]), path


def test_line_endings_are_normalized() -> None:
    lf = TASK_EXAMPLE_ORM.replace("\r", "\n")
    crlf = TASK_EXAMPLE_ORM.replace("\r", "\r\n")
    assert parse(lf).raw == parse(crlf).raw == parse(TASK_EXAMPLE_ORM).raw


def test_literal_backslash_r_from_bash_echo() -> None:
    # `echo "MSH|...\rPID|..."` in Bash sends a backslash and an 'r', not a CR.
    m = parse(TASK_EXAMPLE_ORM.replace("\r", "\\r"))
    assert [s.name for s in m.segments] == ["MSH", "PID", "ORC", "OBR", "OBX"]
    assert m.get("OBX.5") == "26"
    assert m.warnings


def test_repetitions_and_subcomponents() -> None:
    raw = "MSH|^~\\&|A|B|||20240101||ADT^A01|1|P|2.5\rPID|1||111^^^MC^MR~222^^^OTHER^MR&X"
    rows = [r for r in flatten(parse(raw)) if r.seg == "PID" and r.field == 3]
    by_pos = {(r.rep, r.comp, r.sub): r.value for r in rows}
    assert by_pos[(1, 1, 0)] == "111"
    assert by_pos[(2, 1, 0)] == "222"
    assert by_pos[(2, 4, 0)] == "OTHER"
    assert by_pos[(2, 5, 1)] == "MR" and by_pos[(2, 5, 2)] == "X"


def test_escape_sequences() -> None:
    raw = "MSH|^~\\&|A|B|||20240101||ORU^R01|1|P|2.5\rOBX|1|TX|C||a\\F\\b\\S\\c\\T\\d\\R\\e\\E\\f"
    m = parse(raw)
    assert m.get("OBX.5") == "a|b^c&d~e\\f"
    # escaped separators must NOT split the field
    assert len(m.first("OBX").fields) == 6  # type: ignore[union-attr]
    assert unescape("x\\X41\\y", m.encoding) == "xAy"


def test_custom_separators() -> None:
    raw = "MSH#$~\\&#APP#FAC#####ADT$A01#99#P#2.5\rPID#1##555$$$MC"
    m = parse(raw)
    assert m.message_type == "ADT" and m.trigger_event == "A01"
    assert m.get("PID.3.1") == "555" and m.get("PID.3.4") == "MC"


def test_rejects_non_hl7() -> None:
    with pytest.raises(HL7ParseError):
        parse("hello world")
    with pytest.raises(HL7ParseError):
        parse("PID|1||123")


@pytest.mark.parametrize(
    ("text", "expected"),
    [("PID.3", "PID.3"), ("pid-3.1", "PID.3.1"), ("OBX.5.1.2", "OBX.5.1.2"), ("ZPI.1", "ZPI.1")],
)
def test_parse_path(text: str, expected: str) -> None:
    assert str(parse_path(text)) == expected


@pytest.mark.parametrize("bad", ["PID", "PID.0", "PID.3.0", "P.3", "PID.3.1.2.3", "'; DROP"])
def test_parse_path_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_path(bad)


@pytest.mark.parametrize(
    ("value", "iso"),
    [
        ("20240509144522", "2024-05-09T14:45:22"),
        ("202405091445", "2024-05-09T14:45:00"),
        ("20240509", "2024-05-09T00:00:00"),
        ("20240509144522.123-0500", "2024-05-09T14:45:22"),
        ("2024-05-09T14:45:22", "2024-05-09T14:45:22"),
        ("PatientBirthDate", None),
        ("", None),
        ("20241345", None),
    ],
)
def test_timestamps(value: str, iso: str | None) -> None:
    assert hl7_ts_to_iso(value) == iso
