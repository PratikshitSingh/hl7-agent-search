# hl7-agent-search

A TCP server that ingests **HL7 v2** messages, stores them so **any field** can be
searched quickly, and an **MCP tool** that lets AI agents query them. Demo: an agent
reconstructs a patient's admissions, discharges and transfers (ADT).

```
Sender ──MLLP/TCP──▶ hl7-server ──parse──▶ SQLite (WAL)
            ◀── ACK ───┘   commit-then-ACK      ▲
                                    hl7-mcp (stdio) ──▶ Agent (Claude Code/Desktop, SDK)
```

## Quickstart

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,agent]"

hl7-server --db hl7.db --port 2575 &        # 1. ingest server
hl7-seed --port 2575                        # 2. send 19 synthetic messages over MLLP
hl7-search --db hl7.db -f PID.3.1=12345 -f PID.3.4=MC --scope repetition \
  --type ADT --events A01,A02,A03,A11,A12,A13 -r PV1.3 -r PV1.19   # 3. search from CLI

# The task's example works unframed too (e.g. straight from Bash):
printf "MSH|^~\&|BUNKERHILL|BH|||20240509144522||ORM^O01|AccessionNumber|P|2.8\rPID|1||PatientID^^^MC^MC||PatientName||PatientBirthDate|\rOBX|1|NM|513230^Bunkerhill - Coronary Calcium Scoring AI^Estimated calcium score||26" | nc -N 127.0.0.1 2575
```

**Use it from an agent** (Claude Code / Desktop MCP config). See it working in
[docs/mcp-live-demo.md](docs/mcp-live-demo.md): Claude in the Claude app, no API key:

```json
{"mcpServers": {"hl7": {"command": "/abs/path/.venv/bin/hl7-mcp",
                        "env": {"HL7_DB": "/abs/path/hl7.db"}}}}
```

or run the scripted agent loop: `ANTHROPIC_API_KEY=... python scripts/agent_demo.py --db hl7.db`.
For a quick look without an LLM: `python scripts/mcp_call.py --db hl7.db --list`.

**Checks:** `pytest` (76 tests) · `mypy` (strict) · `ruff check .` · `python scripts/bench.py`

## Layout

| File | Role |
|---|---|
| `src/hl7search/mllp.py` | MLLP framing (pure, no I/O) + raw-text fallback |
| `src/hl7search/parser.py` | Lenient HL7 v2 parser, field paths, timestamps |
| `src/hl7search/store.py` | SQLite schema, idempotent insert, filter planner |
| `src/hl7search/server.py` | asyncio TCP server, ACK generation, limits, shutdown |
| `src/hl7search/tool.py` / `mcp_server.py` | Agent-facing API + MCP server |
| `src/hl7search/fields.py` | Human-readable field names and ADT event meanings |
| `src/hl7search/seed.py` / `client.py` / `cli.py` | Synthetic data, MLLP sender, CLI search |
| `scripts/` | `agent_demo.py`, `mcp_call.py`, `bench.py` |
| `docs/` | `mcp-live-demo.md` (Claude app + MCP, with screenshot), `agent_transcript.md`, `benchmark.txt` |

## Design decisions (and their trade-offs)

### 1. Transport: MLLP with hand-written asyncio framing, plus a raw fallback
HL7 v2 over TCP uses **MLLP**: `0x0B` + message + `0x1C 0x0D`. TCP has no message
boundaries, so one `read()` can hold half a message or three. `StreamFramer` buffers and
splits correctly (tested byte-by-byte).

- **Why not python-hl7's `hl7.mllp`?** It is marked experimental, and its last stated
  support is Python 3.7–3.10. The framing is ~100 lines, and owning it gives full control
  of ACKs and limits. *Con:* more code to maintain.
- **Raw fallback:** the task's example is an unframed string, so the server also accepts
  plain text (as from `nc`). A message ends at the next `MSH`, after a short quiet period,
  or at EOF. *Con:* no framing means no perfect message boundaries. MLLP is preferred.
- **Commit, then ACK.** `AA` is sent only after the DB transaction commits. Missing ACK →
  sender retries → insert is **idempotent** on (MSH-3, MSH-4, MSH-10). `AE` = couldn't
  store, `AR` = not readable as HL7.
- Production basics: max frame size, idle timeout, connection cap, SIGTERM drain, logging
  of control IDs only (**never message bodies: they're PHI**).

### 2. Parsing: own lenient parser, python-hl7 as a test oracle
- Separators are read from MSH-1/2 (senders may change them).
- **MSH off-by-one:** MSH-1 *is* the `|`, so a naive split puts MSH-9 at index 8. Fixed and tested.
- Escape sequences (`\F\ \S\ \T\ \R\ \E\ \Xhh\`) are decoded *after* splitting.
- **Lenient on purpose:** the example has `PatientBirthDate` in a date field. We store
  whatever arrives; the raw text is the source of truth and the index can be rebuilt.
- Accepts `\r`, `\n`, `\r\n`, and even a *literal* `\r` (two characters), which is what
  Bash's `echo "...\r..."` actually sends. Side note on the task's Python example: the `r`
  prefix applies only to the first string of an implicit concatenation, so `\&` stays
  literal while the later `\r`s become real carriage returns.
- *Con:* we maintain a parser, mitigated by cross-checking every test message against python-hl7.

### 3. Storage: SQLite, raw message + an EAV field index (the core decision)
`messages` keeps each message verbatim. `fields` has one row per non-empty field,
component and subcomponent: `(msg_id, seg, seg_idx, field, rep, comp, sub, value)`,
indexed on `(seg, field, comp, sub, value)`.

- ✅ Any field is searchable with an index, schema-free (Z-segments work), zero infra, WAL
  lets the tool read while the server writes.
- ❌ Write amplification (~54 rows / ~4.6 KB per message), values are strings, single writer.
- Rejected: regex over raw text (O(n) per query), a JSON column (can't index arbitrary
  paths), Postgres JSONB/Elasticsearch (right at scale, overkill for this scope).

**Query planner.** Multi-filter queries seek the *most selective* filter on the value
index, then check the others per message through a `(msg_id, seg, field, comp, sub)`
probe index. SQLite's own planner can't tell that MRN `12345` is rare while authority `MC`
is on most messages, so we take a capped (≤1000 rows) count per filter first. This took
the patient-timeline query from **233 ms at 20k messages to 10 ms at 100k**.

### 4. Tool: structured filters, not SQL
`hl7_search_messages(filters=[{path, op, value}], scope, message_type, trigger_events,
since, until, return_fields, limit, offset)` plus `hl7_get_message`,
`hl7_describe_segment` and `hl7_stats`.

- Paths use HL7 notation (`PID.3.1`, `PID-3.1`). Ops: `eq in prefix contains gt gte lt lte`, `numeric` flag.
- **`scope`** fixes a classic false positive. `message`: filters may match anywhere.
  `segment`: same segment instance (this OBX's code AND this OBX's value).
  `repetition`: same identifier, e.g. PID-3.1 and PID-3.4 from the *same* PID-3
  repetition, not "MRN from one ID, authority from another".
- Results come back as compact JSON with HL7 names and ADT event descriptions; sorted by
  **event** time (EVN-6 > EVN-2 > MSH-7), not arrival time.
- Validation errors are sent back to the agent as readable `ToolError`s. MCP SDK 2.x hides
  ordinary exception text, which would leave the agent unable to correct its call.
- ✅ Safe (no injection; tested), self-correcting, token-cheap. ❌ Less expressive than SQL.

## The agent demo

`docs/agent_transcript.md` has the full session. The seed data contains deliberate traps:

1. **MRN 12345 exists at two hospitals** (MC and OTHERHOSP): matching PID-3.1 alone
   returns another patient's stays.
2. **Cancellations:** V1002's admit was cancelled (A11); V1003's discharge was
   cancelled (A13), so the patient is still in house.
3. An **A08** update and an **A04** registration are ADT messages but not admits, discharges or transfers.
4. Messages are sent **shuffled**: order must come from event time.

The agent called `hl7_stats` and saw that cancellations exist. A naive MRN search surfaced
two different patients, so it re-queried with MRN + authority in `repetition` scope, then
opened the A13 to confirm. Its timeline matches the ground truth exactly; the same check
runs in `tests/test_store.py` and `tests/test_mcp.py`.

## Benchmark (100k messages, cloud sandbox, `docs/benchmark.txt`)

| | |
|---|---|
| Live ingest (1 commit per message) | ~0.3 ms/msg (~3.5k msg/s) |
| Bulk load (5k/txn) | ~2.8k msg/s |
| Patient ADT timeline (MRN + authority + 6 triggers) | p50 **10 ms** |
| Exact match on a field (MSH-10) | p50 0.04 ms |
| Name prefix | p50 0.07 ms |
| Lab value > 290 within the same OBX (1,028 hits) | p50 147 ms ← string values cast at query time |

## Known limitations

- Timestamps drop the UTC offset (assumes one sender time zone).
- Character set: UTF-8 with Latin-1 fallback; MSH-18 is not honoured yet.
- Numeric comparisons cast strings at query time (slow on wide matches).
- `PATH.n.n.1` on a component without subcomponents matches the component (HL7
  convention); a rare edge case can over-match with `eq "a&b"` / `contains`.
- No TLS or auth yet. Do not expose beyond localhost with real PHI.

## How the tool could be improved

1. **Intent-level tools.** `get_patient_encounters(mrn, authority)` returns visits with
   cancellations already applied and A40 merges followed. Agents do better with one
   intent tool than assembling five low-level queries, and it removes the traps above.
2. **Typed columns at ingest:** parse timestamps and numbers into typed columns (`value_num`,
   `value_ts`) to make range queries index-backed (fixes the 147 ms case).
3. **Normalize to FHIR** (Patient, Encounter, Observation) alongside the raw HL7. That's the
   model most agents and downstream systems understand.
4. **Patient identity:** an identifier cross-reference (an MPI, master patient index) that
   applies A40 merges, so "this patient" means all of their IDs.
5. **Scale:** Postgres (partitioned by time) or OpenSearch, a queue (Kafka/NATS) between
   ACK and indexing, a dead-letter store for unparseable messages, batched commits with
   group-ACK for throughput.
6. **Compliance:** TLS for MLLP, authn/z on the tool, per-query audit log (who/what agent
   saw which patient), field-level redaction, minimum-necessary return fields, retention.
7. **Semantic search** over OBX/NTE free text (embeddings) for questions like "chest CT findings".
8. **Validation profiles** (e.g. hl7apy) as an *offline* data-quality report, never blocking ingest.

## Sources

- HL7 v2 message structure, MLLP and ADT trigger events: HL7 International v2 standard (v2.5/v2.8 chapters 2 and 3).
- [python-hl7 MLLP docs](https://python-hl7.readthedocs.io/en/stable/mllp.html) and [changelog](https://python-hl7.readthedocs.io/en/stable/changelog.html).
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (v2, `MCPServer`).

All patient data in this repository is synthetic.
