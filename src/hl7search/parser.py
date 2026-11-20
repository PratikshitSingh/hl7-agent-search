"""Lenient HL7 v2 parser.

Design notes
------------
* Separators are read from MSH-1 / MSH-2 rather than hard-coded, because senders
  are allowed to change them.
* MSH is special: MSH-1 *is* the field separator, so a naive ``split("|")`` puts
  MSH-9 at index 8. We insert the separator so field numbers match the spec.
* Ingest is lenient: we never reject a message because a value has the wrong
  type (the task's own example has ``PatientBirthDate`` in a timestamp field).
  The raw text is the source of truth; the parse is a derived index.
* Splitting happens on the raw text *before* un-escaping, so escaped
  separators (``\\F\\``, ``\\S\\``...) never break the structure.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime

SEGMENT_ID = re.compile(r"^[A-Z][A-Z0-9]{2}$")
# A literal backslash-r (two characters) followed by a segment id. This shows up
# when someone pipes the Bash example from the task through `echo` (double
# quotes in Bash do not turn \r into a carriage return).
_LITERAL_CR = re.compile(r"\\r(?=[A-Z][A-Z0-9]{2}[^A-Za-z0-9\s])")


class HL7ParseError(ValueError):
    """Raised when the text cannot be read as an HL7 v2 message at all."""


@dataclass(frozen=True, slots=True)
class Encoding:
    field: str = "|"
    component: str = "^"
    repetition: str = "~"
    escape: str = "\\"
    subcomponent: str = "&"

    @property
    def msh2(self) -> str:
        return f"{self.component}{self.repetition}{self.escape}{self.subcomponent}"


@dataclass(frozen=True, slots=True)
class Segment:
    """One segment. ``fields[0]`` is the segment id, ``fields[n]`` is field *n* (raw text)."""

    name: str
    fields: tuple[str, ...]

    def field(self, n: int) -> str:
        return self.fields[n] if 0 <= n < len(self.fields) else ""


@dataclass(frozen=True, slots=True)
class FieldRow:
    """One searchable leaf. ``comp == 0`` means the whole repetition; ``sub == 0`` the
    whole component."""

    seg: str
    seg_idx: int  # 1-based position of the segment in the message
    field: int
    rep: int
    comp: int
    sub: int
    value: str


@dataclass(frozen=True, slots=True)
class ParsedMessage:
    raw: str  # normalized: segments joined by \r
    encoding: Encoding
    segments: tuple[Segment, ...]
    warnings: tuple[str, ...] = field(default=())

    def first(self, name: str) -> Segment | None:
        return next((s for s in self.segments if s.name == name), None)

    def get(self, path: str) -> str:
        """Convenience accessor: first segment instance, first repetition. Returns the
        un-escaped value or "" when absent. ``path`` like ``MSH.9.1``."""
        p = parse_path(path)
        seg = self.first(p.seg)
        if seg is None:
            return ""
        raw_field = seg.field(p.field)
        if p.seg == "MSH" and p.field in (1, 2):
            return raw_field
        rep = raw_field.split(self.encoding.repetition)[0]
        if p.comp is None:
            return unescape(rep, self.encoding)
        comps = rep.split(self.encoding.component)
        comp = comps[p.comp - 1] if p.comp <= len(comps) else ""
        if p.sub is None:
            return unescape(comp, self.encoding)
        subs = comp.split(self.encoding.subcomponent)
        return unescape(subs[p.sub - 1], self.encoding) if p.sub <= len(subs) else ""

    @property
    def message_type(self) -> str:
        return self.get("MSH.9.1")

    @property
    def trigger_event(self) -> str:
        return self.get("MSH.9.2")

    @property
    def control_id(self) -> str:
        return self.get("MSH.10")


# --------------------------------------------------------------------------- paths


_PATH = re.compile(r"^([A-Z][A-Z0-9]{2})[.\-](\d+)(?:\.(\d+))?(?:\.(\d+))?$")


@dataclass(frozen=True, slots=True)
class FieldPath:
    seg: str
    field: int
    comp: int | None = None
    sub: int | None = None

    def __str__(self) -> str:
        parts = [self.seg, str(self.field)]
        if self.comp is not None:
            parts.append(str(self.comp))
        if self.sub is not None:
            parts.append(str(self.sub))
        return ".".join(parts)


def parse_path(path: str) -> FieldPath:
    """Accepts ``PID.3``, ``PID-3``, ``PID.3.1``, ``PID-3.1.2`` (HL7 notation)."""
    m = _PATH.match(path.strip().upper())
    if not m:
        raise ValueError(
            f"Invalid HL7 path {path!r}; expected SEG.FIELD[.COMPONENT[.SUBCOMPONENT]], "
            "e.g. 'PID.3.1'"
        )
    seg, f, c, s = m.groups()
    fp = FieldPath(seg, int(f), int(c) if c else None, int(s) if s else None)
    if fp.field < 1 or (fp.comp is not None and fp.comp < 1) or (fp.sub is not None and fp.sub < 1):
        raise ValueError(f"HL7 positions are 1-based: {path!r}")
    return fp


# --------------------------------------------------------------------------- parsing


def normalize(text: str) -> tuple[str, list[str]]:
    """Normalize segment terminators to \\r and strip framing noise."""
    warnings: list[str] = []
    text = text.lstrip("\ufeff").strip("\x0b\x1c\r\n \t")
    if "\r" not in text and "\n" not in text and _LITERAL_CR.search(text):
        text = _LITERAL_CR.sub("\r", text)
        warnings.append("segments were separated by a literal '\\r' (two characters)")
    text = text.replace("\r\n", "\r").replace("\n", "\r")
    return text, warnings


def parse(text: str) -> ParsedMessage:
    text, warnings = normalize(text)
    if not text.startswith("MSH") or len(text) < 8:
        raise HL7ParseError("message must start with an MSH segment")

    fs = text[3]
    try:
        enc_end = text.index(fs, 4)
    except ValueError as exc:
        raise HL7ParseError("MSH segment has no field after the encoding characters") from exc
    enc_chars = text[4:enc_end]
    if not 1 <= len(enc_chars) <= 5:  # v2.7+ allows a 5th (truncation) char
        raise HL7ParseError(f"invalid MSH-2 encoding characters {enc_chars!r}")
    defaults = Encoding()
    enc = Encoding(
        field=fs,
        component=enc_chars[0],
        repetition=enc_chars[1] if len(enc_chars) > 1 else defaults.repetition,
        escape=enc_chars[2] if len(enc_chars) > 2 else defaults.escape,
        subcomponent=enc_chars[3] if len(enc_chars) > 3 else defaults.subcomponent,
    )

    segments: list[Segment] = []
    for i, line in enumerate(text.split("\r"), start=1):
        if not line.strip():
            continue
        name = line[:3]
        if not SEGMENT_ID.match(name) or (len(line) > 3 and line[3] != fs):
            warnings.append(f"skipped unreadable segment #{i}: {line[:20]!r}")
            continue
        parts = line.split(fs)
        if name == "MSH":
            # parts = ["MSH", "^~\\&", "SENDING_APP", ...] -> make index == field number
            fields: tuple[str, ...] = ("MSH", fs, *parts[1:])
        else:
            fields = tuple(parts)
        segments.append(Segment(name, fields))

    return ParsedMessage(
        raw="\r".join(s for s in text.split("\r") if s.strip()),
        encoding=enc,
        segments=tuple(segments),
        warnings=tuple(warnings),
    )


def unescape(value: str, enc: Encoding) -> str:
    """Decode HL7 escape sequences (\\F\\ \\S\\ \\T\\ \\R\\ \\E\\ \\Xhh\\ \\.br\\)."""
    esc = enc.escape
    if esc not in value:
        return value
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == esc:
            end = value.find(esc, i + 1)
            if end == -1:
                out.append(value[i:])
                break
            code = value[i + 1 : end]
            simple = {
                "F": enc.field,
                "S": enc.component,
                "T": enc.subcomponent,
                "R": enc.repetition,
                "E": enc.escape,
                ".br": "\n",
            }
            if code in simple:
                out.append(simple[code])
            elif code.startswith("X") and len(code) > 1:
                try:
                    out.append(bytes.fromhex(code[1:]).decode("latin-1"))
                except ValueError:
                    out.append(value[i : end + 1])
            else:  # unknown/formatting escape: keep verbatim
                out.append(value[i : end + 1])
            i = end + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def flatten(msg: ParsedMessage) -> Iterator[FieldRow]:
    """Explode a message into searchable leaves. Empty leaves are skipped (most HL7
    fields are empty, so this keeps the index small)."""
    enc = msg.encoding
    for seg_idx, seg in enumerate(msg.segments, start=1):
        for field_no in range(1, len(seg.fields)):
            raw_field = seg.fields[field_no]
            if raw_field == "":
                continue
            if seg.name == "MSH" and field_no in (1, 2):
                yield FieldRow(seg.name, seg_idx, field_no, 1, 0, 0, raw_field)
                continue
            for rep_no, rep in enumerate(raw_field.split(enc.repetition), start=1):
                if rep == "":
                    continue
                yield FieldRow(seg.name, seg_idx, field_no, rep_no, 0, 0, unescape(rep, enc))
                for comp_no, comp in enumerate(rep.split(enc.component), start=1):
                    if comp == "":
                        continue
                    yield FieldRow(
                        seg.name, seg_idx, field_no, rep_no, comp_no, 0, unescape(comp, enc)
                    )
                    if enc.subcomponent in comp:
                        for sub_no, sub in enumerate(comp.split(enc.subcomponent), start=1):
                            if sub:
                                yield FieldRow(
                                    seg.name,
                                    seg_idx,
                                    field_no,
                                    rep_no,
                                    comp_no,
                                    sub_no,
                                    unescape(sub, enc),
                                )


# --------------------------------------------------------------------------- timestamps

_TS = re.compile(r"^(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?(?:\.\d+)?([+-]\d{4})?$")


def hl7_ts_to_iso(value: str) -> str | None:
    """HL7 DTM (YYYY[MM[DD[HH[MM[SS[.S]]]]]][+/-ZZZZ]) -> sortable ISO-8601 string.

    The UTC offset is dropped (documented limitation: we assume one sender timezone).
    Already-ISO input is accepted too, so callers can pass either form. Returns None
    for unparseable values instead of raising (lenient ingest).
    """
    v = value.strip()
    if not v:
        return None
    if "-" in v[:5] or "T" in v:  # looks like ISO already
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None).isoformat()
        except ValueError:
            return None
    m = _TS.match(v)
    if not m:
        return None
    y, mo, d, h, mi, s, _tz = m.groups()
    try:
        dt = datetime(int(y), int(mo or 1), int(d or 1), int(h or 0), int(mi or 0), int(s or 0))
    except ValueError:
        return None
    return dt.isoformat()


def event_timestamp(msg: ParsedMessage) -> str | None:
    """When did the *event* happen? EVN-6 (occurred) > EVN-2 (recorded) > MSH-7 (message
    built). MSH-7 is a last resort: it's when the message was created, not the event."""
    for path in ("EVN.6.1", "EVN.2.1", "MSH.7.1"):
        iso = hl7_ts_to_iso(msg.get(path))
        if iso:
            return iso
    return None
