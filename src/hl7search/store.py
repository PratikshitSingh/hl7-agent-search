"""SQLite storage: raw messages (source of truth) + an indexed field table.

Why an EAV-style ``fields`` table?
    "Search on ANY HL7 field" means we cannot know the columns up front. One row per
    non-empty leaf, indexed on (seg, field, comp, sub, value), turns every lookup
    into an index seek. Cost: write amplification (~1 row per non-empty leaf) and
    string-typed values. The raw message is kept verbatim so the index can always
    be rebuilt with a better parser later.

Concurrency: WAL mode lets the tool read while the server writes. SQLite allows
one writer at a time, so writes go through a lock.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypedDict

from .fields import event_description, field_name
from .parser import FieldPath, ParsedMessage, event_timestamp, flatten, hl7_ts_to_iso, parse_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id               INTEGER PRIMARY KEY,
    sending_app      TEXT NOT NULL DEFAULT '',
    sending_facility TEXT NOT NULL DEFAULT '',
    control_id       TEXT,              -- NULL when MSH-10 is empty (then no dedupe)
    msg_type         TEXT,
    trigger_event    TEXT,
    version          TEXT,
    event_ts         TEXT,              -- ISO-8601, from EVN-6 > EVN-2 > MSH-7
    received_at      TEXT NOT NULL,
    raw              TEXT NOT NULL,     -- verbatim message, the source of truth
    UNIQUE (sending_app, sending_facility, control_id)
);
CREATE TABLE IF NOT EXISTS fields (
    msg_id   INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    seg      TEXT    NOT NULL,
    seg_idx  INTEGER NOT NULL,   -- position of the segment in the message (1-based)
    field    INTEGER NOT NULL,
    rep      INTEGER NOT NULL,
    comp     INTEGER NOT NULL,   -- 0 = whole repetition
    sub      INTEGER NOT NULL,   -- 0 = whole component
    value    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fields_lookup ON fields (seg, field, comp, sub, value);
-- per-message probe index: used to check the remaining filters once the driver matched
CREATE INDEX IF NOT EXISTS ix_fields_probe  ON fields (msg_id, seg, field, comp, sub);
CREATE INDEX IF NOT EXISTS ix_messages_evt  ON messages (msg_type, trigger_event, event_ts);
"""

type Op = Literal["eq", "in", "prefix", "contains", "gt", "gte", "lt", "lte"]
type Scope = Literal["message", "segment", "repetition"]

MAX_LIMIT = 500
_COMPARE = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


@dataclass(frozen=True, slots=True)
class FieldFilter:
    path: str
    op: Op = "eq"
    value: str | list[str] = ""
    numeric: bool = False  # compare gt/lt as numbers instead of strings


@dataclass(frozen=True, slots=True)
class InsertResult:
    message_id: int
    duplicate: bool


class SearchHit(TypedDict):
    message_id: int
    message_type: str | None
    trigger_event: str | None
    event_description: str | None
    event_time: str | None
    control_id: str | None
    sending_facility: str
    fields: dict[str, list[str]]


class SearchResult(TypedDict):
    total: int
    returned: int
    next_offset: int | None
    hits: list[SearchHit]


def connect(db_path: str | Path, *, readonly: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")  # durable across app crashes in WAL mode
    conn.execute("PRAGMA foreign_keys=ON")
    if readonly:
        conn.execute("PRAGMA query_only=ON")
    return conn


class Store:
    def __init__(self, db_path: str | Path, *, readonly: bool = False) -> None:
        self.db_path = str(db_path)
        self._conn = connect(db_path, readonly=readonly)
        self._lock = threading.Lock()
        if not readonly:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ writes

    def insert(self, msg: ParsedMessage, received_at: datetime | None = None) -> InsertResult:
        """Insert a message and its field index in ONE transaction. Idempotent on
        (sending app, sending facility, MSH-10) because senders retry when they
        don't get an ACK. The server ACKs only after this returns (i.e. committed)."""
        received = (received_at or datetime.now(UTC)).isoformat()
        with self._lock, self._conn:
            return self._insert_one(msg, received)

    def insert_many(self, msgs: Sequence[ParsedMessage]) -> int:
        """Bulk load (backfills, benchmarks): one transaction for the whole batch, so
        we pay one commit instead of one per message. Returns how many were new."""
        received = datetime.now(UTC).isoformat()
        with self._lock, self._conn:
            return sum(not self._insert_one(m, received).duplicate for m in msgs)

    def _insert_one(self, msg: ParsedMessage, received: str) -> InsertResult:
        """Caller holds the lock and the transaction."""
        sending_app = msg.get("MSH.3.1")
        sending_facility = msg.get("MSH.4.1")
        control_id = msg.control_id or None
        cur = self._conn.execute(
            """INSERT OR IGNORE INTO messages
               (sending_app, sending_facility, control_id, msg_type, trigger_event,
                version, event_ts, received_at, raw)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sending_app,
                sending_facility,
                control_id,
                msg.message_type or None,
                msg.trigger_event or None,
                msg.get("MSH.12.1") or None,
                event_timestamp(msg),
                received,
                msg.raw,
            ),
        )
        if cur.rowcount == 0:
            row = self._conn.execute(
                """SELECT id FROM messages WHERE sending_app = ? AND sending_facility = ?
                   AND control_id = ?""",
                (sending_app, sending_facility, control_id),
            ).fetchone()
            return InsertResult(int(row["id"]), duplicate=True)
        msg_id = cur.lastrowid
        assert msg_id is not None
        self._conn.executemany(
            "INSERT INTO fields VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (msg_id, r.seg, r.seg_idx, r.field, r.rep, r.comp, r.sub, r.value)
                for r in flatten(msg)
            ),
        )
        return InsertResult(msg_id, duplicate=False)

    # ------------------------------------------------------------------ reads

    def search(
        self,
        filters: Sequence[FieldFilter] = (),
        *,
        scope: Scope = "message",
        message_type: str | None = None,
        trigger_events: Sequence[str] | None = None,
        since: str | None = None,
        until: str | None = None,
        return_fields: Sequence[str] = (),
        limit: int = 50,
        offset: int = 0,
    ) -> SearchResult:
        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        where: list[str] = []
        params: list[Any] = []

        if filters:
            sub_sql, sub_params = _filters_subquery(self._conn, filters, scope)
            where.append(f"m.id IN ({sub_sql})")
            params += sub_params
        if message_type:
            where.append("m.msg_type = ?")
            params.append(message_type.upper())
        if trigger_events:
            where.append(f"m.trigger_event IN ({','.join('?' * len(trigger_events))})")
            params += [t.upper() for t in trigger_events]
        for bound, op in ((since, ">="), (until, "<=")):
            if bound:
                iso = hl7_ts_to_iso(bound)
                if iso is None:
                    raise ValueError(f"cannot parse timestamp {bound!r} (HL7 or ISO-8601)")
                where.append(f"m.event_ts {op} ?")
                params.append(iso)

        where_sql = " AND ".join(where) or "1=1"
        total = int(
            self._conn.execute(
                f"SELECT COUNT(*) FROM messages m WHERE {where_sql}", params
            ).fetchone()[0]
        )
        rows = self._conn.execute(
            f"""SELECT m.id, m.msg_type, m.trigger_event, m.event_ts, m.control_id,
                       m.sending_facility
                FROM messages m WHERE {where_sql}
                ORDER BY m.event_ts IS NULL, m.event_ts, m.id
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()

        ids = [int(r["id"]) for r in rows]
        extra = self._fetch_fields(ids, return_fields)
        hits: list[SearchHit] = [
            {
                "message_id": int(r["id"]),
                "message_type": r["msg_type"],
                "trigger_event": r["trigger_event"],
                "event_description": event_description(r["msg_type"], r["trigger_event"]),
                "event_time": r["event_ts"],
                "control_id": r["control_id"],
                "sending_facility": r["sending_facility"],
                "fields": extra.get(int(r["id"]), {}),
            }
            for r in rows
        ]
        next_offset = offset + len(hits) if offset + len(hits) < total else None
        return {"total": total, "returned": len(hits), "next_offset": next_offset, "hits": hits}

    def _fetch_fields(
        self, ids: list[int], paths: Sequence[str]
    ) -> dict[int, dict[str, list[str]]]:
        out: dict[int, dict[str, list[str]]] = {i: {} for i in ids}
        if not ids:
            return out
        for path in paths:
            fp = parse_path(path)
            leaf_sql, leaf_params = _position_sql("f", fp)
            rows = self._conn.execute(
                f"""SELECT f.msg_id, f.value FROM fields f
                    WHERE f.msg_id IN ({",".join("?" * len(ids))}) AND {leaf_sql}
                    ORDER BY f.msg_id, f.seg_idx, f.rep, f.sub""",
                [*ids, *leaf_params],
            ).fetchall()
            for r in rows:
                values = out[int(r["msg_id"])].setdefault(str(fp), [])
                if r["value"] not in values:
                    values.append(r["value"])
        return out

    def get_message(self, message_id: int) -> dict[str, Any]:
        from .parser import parse  # local import keeps module import graph simple

        row = self._conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        if row is None:
            raise ValueError(f"no message with id {message_id}")
        msg = parse(row["raw"])
        segments = []
        for idx, seg in enumerate(msg.segments, start=1):
            fields = [
                {"field": f"{seg.name}-{n}", "name": field_name(seg.name, n), "value": v}
                for n, v in enumerate(seg.fields)
                if n > 0 and v != ""
            ]
            segments.append({"segment": seg.name, "position": idx, "fields": fields})
        return {
            "message_id": row["id"],
            "message_type": row["msg_type"],
            "trigger_event": row["trigger_event"],
            "event_description": event_description(row["msg_type"], row["trigger_event"]),
            "event_time": row["event_ts"],
            "received_at": row["received_at"],
            "raw": row["raw"].replace("\r", "\n"),
            "segments": segments,
        }

    def describe_segment(self, segment: str) -> dict[str, Any]:
        seg = segment.strip().upper()
        observed = self._conn.execute(
            """SELECT field, COUNT(DISTINCT msg_id) AS n, MIN(value) AS example
               FROM fields WHERE seg = ? AND comp = 0 GROUP BY field ORDER BY field""",
            (seg,),
        ).fetchall()
        return {
            "segment": seg,
            "fields": [
                {
                    "path": f"{seg}.{r['field']}",
                    "name": field_name(seg, int(r["field"])),
                    "messages_with_value": r["n"],
                    "example": r["example"],
                }
                for r in observed
            ],
        }

    def stats(self) -> dict[str, Any]:
        types = self._conn.execute(
            """SELECT msg_type, trigger_event, COUNT(*) AS n FROM messages
               GROUP BY msg_type, trigger_event ORDER BY n DESC"""
        ).fetchall()
        segs = self._conn.execute("SELECT DISTINCT seg FROM fields ORDER BY seg").fetchall()
        return {
            "total_messages": sum(int(r["n"]) for r in types),
            "by_type": [
                {
                    "message_type": r["msg_type"],
                    "trigger_event": r["trigger_event"],
                    "description": event_description(r["msg_type"], r["trigger_event"]),
                    "count": r["n"],
                }
                for r in types
            ],
            "segments_seen": [r["seg"] for r in segs],
        }


# ---------------------------------------------------------------------- SQL builders


def _position_sql(alias: str, fp: FieldPath) -> tuple[str, list[Any]]:
    """SQL matching the *position* of a path (not its value)."""
    sql = [f"{alias}.seg = ?", f"{alias}.field = ?", f"{alias}.comp = ?"]
    params: list[Any] = [fp.seg, fp.field, fp.comp or 0]
    if fp.sub is None:
        sql.append(f"{alias}.sub = 0")
    elif fp.sub == 1:
        # HL7 convention: a component without subcomponents IS its first subcomponent.
        sql.append(f"{alias}.sub IN (0, 1)")
    else:
        sql.append(f"{alias}.sub = ?")
        params.append(fp.sub)
    return " AND ".join(sql), params


def _value_sql(alias: str, flt: FieldFilter) -> tuple[str, list[Any]]:
    col = f"{alias}.value"
    op = flt.op
    if op == "in":
        values = flt.value if isinstance(flt.value, list) else [flt.value]
        if not values:
            raise ValueError("'in' needs at least one value")
        return f"{col} IN ({','.join('?' * len(values))})", list(values)
    if isinstance(flt.value, list):
        raise ValueError(f"op {op!r} takes a single string value, not a list")
    v = flt.value
    match op:
        case "eq":
            return f"{col} = ?", [v]
        case "prefix":  # range form so the index is used
            return f"{col} >= ? AND {col} < ?", [v, v + "\U0010ffff"]
        case "contains":
            return f"instr({col}, ?) > 0", [v]
        case "gt" | "gte" | "lt" | "lte":
            sym = _COMPARE[op]
            if flt.numeric:
                try:
                    num = float(v)
                except ValueError as exc:
                    raise ValueError(f"numeric comparison needs a number, got {v!r}") from exc
                return (
                    f"{col} GLOB '*[0-9]*' AND {col} NOT GLOB '*[^0-9.+-]*' "
                    f"AND CAST({col} AS REAL) {sym} ?",
                    [num],
                )
            return f"{col} {sym} ?", [v]
    raise ValueError(f"unknown op {op!r}")


_SEEKABLE = {"eq", "in", "prefix"}  # ops the value index can seek on
_ESTIMATE_CAP = 1000


def _estimate(conn: sqlite3.Connection, flt: FieldFilter, fp: FieldPath) -> int:
    """Capped match count for one filter: a tiny cost model. SQLite's planner only knows
    average rows per key, so it can't tell that MRN '12345' is rare while authority 'MC'
    is on most messages. Reading at most ~1000 index entries tells us. Range/contains
    filters can't seek on value, so they are ranked last instead of being counted."""
    if flt.op not in _SEEKABLE:
        return _ESTIMATE_CAP + 1
    pos_sql, pos_params = _position_sql("f", fp)
    val_sql, val_params = _value_sql("f", flt)
    row = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT 1 FROM fields f WHERE {pos_sql} AND {val_sql} "
        f"LIMIT {_ESTIMATE_CAP})",
        pos_params + val_params,
    ).fetchone()
    return int(row[0])


def _filters_subquery(
    conn: sqlite3.Connection, filters: Sequence[FieldFilter], scope: Scope
) -> tuple[str, list[Any]]:
    """SQL returning matching msg_ids. Plan: seek the most selective filter on the value
    index (the "driver"), then check every other filter with a correlated EXISTS probe
    on (msg_id, seg, field, comp, sub). Cost ~ driver matches x filters, independent of
    how common the other values are."""
    paths = [parse_path(f.path) for f in filters]
    if scope != "message" and len({p.seg for p in paths}) != 1:
        raise ValueError(f"scope={scope!r} requires all filters to target the same segment")
    if scope == "repetition" and len({p.field for p in paths}) != 1:
        raise ValueError("scope='repetition' requires all filters to target the same field")

    pairs = list(zip(filters, paths, strict=True))
    if len(pairs) > 1:
        pairs.sort(key=lambda pair: _estimate(conn, *pair))
    (f0, p0), rest = pairs[0], pairs[1:]

    pos_sql, params = _position_sql("f0", p0)
    val_sql, val_params = _value_sql("f0", f0)
    params = params + val_params
    where = [pos_sql, val_sql]
    for i, (flt, fp) in enumerate(rest, start=1):
        a = f"f{i}"
        corr = f"{a}.msg_id = f0.msg_id"
        if scope in ("segment", "repetition"):
            corr += f" AND {a}.seg_idx = f0.seg_idx"
        if scope == "repetition":
            corr += f" AND {a}.rep = f0.rep"
        p_sql, p_params = _position_sql(a, fp)
        v_sql, v_params = _value_sql(a, flt)
        where.append(f"EXISTS (SELECT 1 FROM fields {a} WHERE {corr} AND {p_sql} AND {v_sql})")
        params += p_params + v_params
    return f"SELECT f0.msg_id FROM fields f0 WHERE {' AND '.join(where)}", params
