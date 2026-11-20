"""How quick is "quickly"? Load N synthetic messages and time representative queries.

python scripts/bench.py --messages 100000
"""

from __future__ import annotations

import argparse
import statistics
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hl7search.parser import parse
from hl7search.seed import bulk_messages, demo_messages
from hl7search.store import FieldFilter, Store


def timed(fn: Callable[[], Any], runs: int = 30) -> tuple[float, float, Any]:
    samples, result = [], None
    for _ in range(runs):
        t0 = time.perf_counter()
        result = fn()
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    return statistics.median(samples), samples[int(len(samples) * 0.95) - 1], result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--messages", type=int, default=100_000)
    a = p.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "bench.db"
        store = Store(db)
        # Live path: one commit per message (what the server does before each ACK).
        sample = [parse(m) for m in demo_messages()]
        t0 = time.perf_counter()
        for m in sample:
            store.insert(m)
        live_ms = (time.perf_counter() - t0) * 1000 / len(sample)
        print(f"live insert (1 commit/msg): {live_ms:.2f} ms/msg -> ~{1000 / live_ms:,.0f} msg/s")

        # Bulk path: batched transactions.
        t0 = time.perf_counter()
        n, batch = len(sample), []
        for raw in bulk_messages(a.messages):
            batch.append(parse(raw))
            if len(batch) == 5000:
                n += store.insert_many(batch)
                batch.clear()
        n += store.insert_many(batch)
        ingest_s = time.perf_counter() - t0
        rows = store._conn.execute("SELECT COUNT(*) FROM fields").fetchone()[0]
        store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        size_mb = db.stat().st_size / 1e6
        rate = n / ingest_s
        print(f"bulk load: {n:,} messages in {ingest_s:.1f}s ({rate:,.0f} msg/s, 5k/txn)")
        print(f"fields rows: {rows:,} ({rows / n:.1f}/message), db size: {size_mb:.1f} MB\n")

        queries: dict[str, Callable[[], Any]] = {
            "patient ADT timeline (MRN+authority, repetition scope)": lambda: store.search(
                [FieldFilter("PID.3.1", "eq", "12345"), FieldFilter("PID.3.4", "eq", "MC")],
                scope="repetition",
                message_type="ADT",
                trigger_events=["A01", "A02", "A03", "A11", "A12", "A13"],
                return_fields=["PV1.3", "PV1.19"],
            ),
            "single field eq (MSH.10)": lambda: store.search(
                [FieldFilter("MSH.10", "eq", "AccessionNumber")]
            ),
            "name prefix (PID.5.1 ^= DO)": lambda: store.search(
                [FieldFilter("PID.5.1", "prefix", "DO")], limit=50
            ),
            "lab value > 290, same OBX (segment scope)": lambda: store.search(
                [
                    FieldFilter("OBX.3.1", "eq", "2345-7"),
                    FieldFilter("OBX.5", "gt", "290", numeric=True),
                ],
                scope="segment",
                limit=50,
            ),
        }
        print(f"{'query':58} {'p50 ms':>8} {'p95 ms':>8} {'total':>8}")
        for name, fn in queries.items():
            p50, p95, res = timed(fn)
            print(f"{name:58} {p50:8.2f} {p95:8.2f} {res['total']:8,}")
        store.close()


if __name__ == "__main__":
    main()
