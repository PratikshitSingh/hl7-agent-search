"""Agent-facing search API. Plain functions, so the same code backs the MCP server,
the CLI and the Anthropic-SDK demo.

Design choice: structured filters instead of letting the LLM write SQL. It's safe
(no injection), validated (bad paths fail with a useful message the agent can
correct), and returns compact JSON instead of raw pipe-delimited text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Required, TypedDict

from .store import FieldFilter, Op, Scope, SearchResult, Store

GUIDE = """\
HL7 v2 message store. Every non-empty field, component and subcomponent is indexed.

PATHS use HL7 notation: SEG.FIELD[.COMPONENT[.SUBCOMPONENT]], 1-based, e.g.
  PID.3.1  patient identifier (MRN)       PID.3.4  assigning authority of that ID
  PID.5.1  family name                    PV1.3    assigned location (unit^room^bed^facility)
  PV1.6    prior location (transfers)     PV1.19   visit number
  MSH.9.1  message type (ADT, ORU, ORM)   MSH.9.2  trigger event (A01, R01...)
  EVN.6    event occurred time            OBX.3.1  observation code   OBX.5 value
A path without a component (PID.3) matches the whole field repetition text.

ADT TRIGGER EVENTS (MSH-9.2):
  A01 admit   A02 transfer   A03 discharge
  A11 cancels A01, A12 cancels A02, A13 cancels A03  (match on PV1.19 visit number)
  A04 register (outpatient), A05 pre-admit, A08 demographics update, A40 merge

GOTCHAS:
  * An MRN (PID.3.1) is only unique within its assigning authority (PID.3.4). Filter on
    both, with scope="repetition" so they must come from the same identifier.
  * Results are sorted by event time (EVN-6 > EVN-2 > MSH-7), not arrival time.
  * Check cancellations before reporting an admission/transfer/discharge as final.
"""


class FilterSpec(TypedDict, total=False):
    path: Required[str]
    op: Op
    value: str | list[str]
    numeric: bool


def to_filters(specs: list[FilterSpec] | None) -> list[FieldFilter]:
    out: list[FieldFilter] = []
    for s in specs or []:
        if "path" not in s:
            raise ValueError(f"filter is missing 'path': {s!r}")
        out.append(
            FieldFilter(
                path=s["path"],
                op=s.get("op", "eq"),
                value=s.get("value", ""),
                numeric=bool(s.get("numeric", False)),
            )
        )
    return out


class HL7Tools:
    def __init__(self, db_path: str | Path) -> None:
        if not Path(db_path).exists():
            raise FileNotFoundError(f"database {db_path} not found; start the server first")
        self.store = Store(db_path, readonly=True)

    def search_messages(
        self,
        filters: list[FilterSpec] | None = None,
        scope: Scope = "message",
        message_type: str | None = None,
        trigger_events: list[str] | None = None,
        since: str | None = None,
        until: str | None = None,
        return_fields: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> SearchResult:
        return self.store.search(
            to_filters(filters),
            scope=scope,
            message_type=message_type,
            trigger_events=trigger_events,
            since=since,
            until=until,
            return_fields=return_fields or [],
            limit=limit,
            offset=offset,
        )

    def get_message(self, message_id: int) -> dict[str, Any]:
        return self.store.get_message(message_id)

    def describe_segment(self, segment: str) -> dict[str, Any]:
        return self.store.describe_segment(segment)

    def stats(self) -> dict[str, Any]:
        return self.store.stats()
