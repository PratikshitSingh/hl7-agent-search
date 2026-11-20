"""Command-line search, handy for humans and for quick checks during a demo.

    hl7-search --db hl7.db -f PID.3.1=12345 -f PID.3.4=MC --scope repetition \
        --type ADT --events A01,A02,A03,A11,A12,A13 -r PV1.3 -r PV1.19
"""

from __future__ import annotations

import argparse
import json

from .store import FieldFilter, Store


def _parse_filter(text: str) -> FieldFilter:
    for token, op in (("^=", "prefix"), ("~=", "contains"), (">=", "gte"), ("<=", "lte"),
                      ("=", "eq"), (">", "gt"), ("<", "lt")):  # fmt: skip
        if token in text:
            path, value = text.split(token, 1)
            return FieldFilter(path=path.strip(), op=op, value=value)  # type: ignore[arg-type]
    raise argparse.ArgumentTypeError(f"bad filter {text!r}; use PATH=VALUE, PATH^=PREFIX, ...")


def main() -> None:
    p = argparse.ArgumentParser(description="Search stored HL7 messages")
    p.add_argument("--db", default="hl7.db")
    p.add_argument("-f", "--filter", action="append", type=_parse_filter, default=[])
    p.add_argument("--scope", choices=["message", "segment", "repetition"], default="message")
    p.add_argument("--type", dest="message_type")
    p.add_argument("--events", help="comma-separated trigger events, e.g. A01,A02")
    p.add_argument("-r", "--return-field", action="append", default=[])
    p.add_argument("--limit", type=int, default=50)
    a = p.parse_args()
    store = Store(a.db, readonly=True)
    result = store.search(
        a.filter,
        scope=a.scope,
        message_type=a.message_type,
        trigger_events=a.events.split(",") if a.events else None,
        return_fields=a.return_field,
        limit=a.limit,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
