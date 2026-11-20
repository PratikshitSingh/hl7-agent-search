"""Synthetic HL7 data (no real PHI).

The demo set is built to catch the classic mistakes an agent can make:

* MRN 12345 exists at TWO assigning authorities (MC and OTHERHOSP): matching on
  PID-3.1 alone returns someone else's admissions.
* Visit V1002's admit was cancelled (A11) and V1003's discharge was cancelled
  (A13): reporting them as-is gives a wrong timeline.
* An A08 (demographics update) and an A04 (outpatient registration) are ADT
  messages but not admissions, discharges or transfers.
* Messages are sent shuffled: you must order by event time, not arrival.
"""

from __future__ import annotations

import argparse
import asyncio
import random
from collections.abc import Iterator
from datetime import datetime, timedelta

from .client import send_messages

# MSH-9.3 message structure per trigger (HL7 v2.5)
_STRUCTURE = {
    "A01": "ADT_A01", "A02": "ADT_A02", "A03": "ADT_A03", "A04": "ADT_A01",
    "A08": "ADT_A01", "A11": "ADT_A09", "A12": "ADT_A12", "A13": "ADT_A01",
}  # fmt: skip

TASK_EXAMPLE_ORM = (
    r"MSH|^~\&|BUNKERHILL|BH|||20240509144522||ORM^O01|"
    "AccessionNumber|P|2.8\r"
    "PID|1||PatientID^^^MC^MC||PatientName||PatientBirthDate|\r"
    "ORC|XO||||||||\r"
    "OBR|1||AccessionNumber|IMG200^CT CHEST WITHOUT IV CONTRAST"
    "||||||||||||||||||20240509144522\r"
    "OBX|1|NM|513230^Bunkerhill - Coronary Calcium Scoring AI"
    "^Estimated calcium score||26"
)


def seg(name: str, fields: dict[int, str]) -> str:
    """Build a segment from {field_number: value} so we never miscount pipes."""
    n = max(fields) if fields else 0
    return "|".join([name, *(fields.get(i, "") for i in range(1, n + 1))])


def adt(
    trigger: str,
    control_id: str,
    ts: str,
    *,
    mrn: str,
    authority: str,
    name: str,
    dob: str,
    sex: str,
    visit: str,
    location: str,
    patient_class: str = "I",
    prior_location: str = "",
    admit_ts: str = "",
    discharge_ts: str = "",
    discharge_disposition: str = "",
) -> str:
    msh = (
        f"MSH|^~\\&|EPIC|{authority}|HL7SEARCH|BH|{ts}||ADT^{trigger}^{_STRUCTURE[trigger]}"
        f"|{control_id}|P|2.5"
    )
    evn = seg("EVN", {1: trigger, 2: ts, 6: ts})
    pid = seg("PID", {1: "1", 3: f"{mrn}^^^{authority}^MR", 5: name, 7: dob, 8: sex})
    pv1 = seg(
        "PV1",
        {
            1: "1",
            2: patient_class,
            3: location,
            6: prior_location,
            7: "1001^HOUSE^GREGORY^^^DR",
            10: "MED",
            19: visit,
            36: discharge_disposition,
            44: admit_ts,
            45: discharge_ts,
        },
    )
    return "\r".join([msh, evn, pid, pv1])


def demo_messages(shuffle: bool = True) -> list[str]:
    jane = {"mrn": "12345", "authority": "MC", "name": "DOE^JANE^A", "dob": "19800214",
            "sex": "F"}  # fmt: skip
    trap = {"mrn": "12345", "authority": "OTHERHOSP", "name": "ROE^RICHARD", "dob": "19550101",
            "sex": "M"}  # fmt: skip
    john = {"mrn": "67890", "authority": "MC", "name": "SMITH^JOHN", "dob": "19721130",
            "sex": "M"}  # fmt: skip

    msgs = [
        # Jane, visit V1001: admit -> ICU -> back to ward -> discharge
        adt("A01", "MC0001", "20240301081500", **jane, visit="V1001",
            location="4WEST^401^A^MC", admit_ts="20240301081500"),
        adt("A02", "MC0002", "20240302143000", **jane, visit="V1001",
            location="ICU^12^1^MC", prior_location="4WEST^401^A^MC",
            admit_ts="20240301081500"),
        adt("A02", "MC0003", "20240304090000", **jane, visit="V1001",
            location="4WEST^405^B^MC", prior_location="ICU^12^1^MC",
            admit_ts="20240301081500"),
        adt("A03", "MC0004", "20240306110000", **jane, visit="V1001",
            location="4WEST^405^B^MC", admit_ts="20240301081500",
            discharge_ts="20240306110000", discharge_disposition="01"),
        # Jane: demographics update (ADT, but not an admit/discharge/transfer)
        adt("A08", "MC0005", "20240310120000", **jane, visit="V1001",
            location="4WEST^405^B^MC"),
        # Jane, visit V1002: admitted in error, then cancelled
        adt("A01", "MC0006", "20240610224000", **jane, visit="V1002",
            location="3EAST^310^A^MC", admit_ts="20240610224000"),
        adt("A11", "MC0007", "20240610230500", **jane, visit="V1002",
            location="3EAST^310^A^MC", admit_ts="20240610224000"),
        # Jane, visit V1003: admit -> transfer -> discharge -> discharge cancelled
        adt("A01", "MC0008", "20240920070000", **jane, visit="V1003",
            location="5NORTH^502^A^MC", admit_ts="20240920070000"),
        adt("A02", "MC0009", "20240922100000", **jane, visit="V1003",
            location="5NORTH^510^B^MC", prior_location="5NORTH^502^A^MC",
            admit_ts="20240920070000"),
        adt("A03", "MC0010", "20240925150000", **jane, visit="V1003",
            location="5NORTH^510^B^MC", admit_ts="20240920070000",
            discharge_ts="20240925150000", discharge_disposition="01"),
        adt("A13", "MC0011", "20240925162000", **jane, visit="V1003",
            location="5NORTH^510^B^MC", admit_ts="20240920070000"),
        # TRAP: same MRN, different hospital
        adt("A01", "OH0001", "20240401090000", **trap, visit="X55",
            location="MED^1^1^OTHERHOSP", admit_ts="20240401090000"),
        adt("A03", "OH0002", "20240403100000", **trap, visit="X55",
            location="MED^1^1^OTHERHOSP", discharge_ts="20240403100000"),
        # John: a normal stay, plus an outpatient registration
        adt("A01", "MC0101", "20240505080000", **john, visit="V2001",
            location="2SOUTH^201^A^MC", admit_ts="20240505080000"),
        adt("A02", "MC0102", "20240506080000", **john, visit="V2001",
            location="2SOUTH^220^A^MC", prior_location="2SOUTH^201^A^MC"),
        adt("A03", "MC0103", "20240507080000", **john, visit="V2001",
            location="2SOUTH^220^A^MC", discharge_ts="20240507080000"),
        adt("A04", "MC0104", "20240801100000", **john, visit="V2002",
            location="CLINIC^^^MC", patient_class="O"),
        # Non-ADT noise: a lab result for Jane and the task's own example message
        "\r".join([
            "MSH|^~\\&|LAB|MC|HL7SEARCH|BH|20240302060000||ORU^R01^ORU_R01|LAB0001|P|2.5",
            "PID|1||12345^^^MC^MR||DOE^JANE^A||19800214|F",
            "OBR|1|ORD1|FIL1|2345-7^GLUCOSE^LN|||20240302055000",
            "OBX|1|NM|2345-7^GLUCOSE^LN||182|mg/dL|70-99|H|||F",
            "OBX|2|NM|2951-2^SODIUM^LN||139|mmol/L|135-145|N|||F",
        ]),
        TASK_EXAMPLE_ORM,
    ]  # fmt: skip
    if shuffle:
        random.Random(7).shuffle(msgs)  # arrival order != event order
    return msgs


# Ground truth for the agent demo / tests (MRN 12345 at MC, A01/A02/A03 + cancels).
EXPECTED_JANE_ADT_CONTROL_IDS = [
    "MC0001", "MC0002", "MC0003", "MC0004", "MC0006", "MC0007",
    "MC0008", "MC0009", "MC0010", "MC0011",
]  # fmt: skip


def bulk_messages(n: int, seed: int = 1) -> Iterator[str]:
    """~n messages: random patients with admit/transfer/discharge cycles + lab results."""
    rng = random.Random(seed)
    start = datetime(2023, 1, 1)
    i = 0
    while i < n:
        mrn = f"{rng.randint(100000, 999999)}"
        pt = {"mrn": mrn, "authority": rng.choice(["MC", "MC", "MC", "OTHERHOSP"]),
              "name": f"PATIENT^{mrn}", "dob": "19700101", "sex": rng.choice("MF")}  # fmt: skip
        t = start + timedelta(minutes=rng.randint(0, 60 * 24 * 600))
        visit = f"B{i}"
        for trigger in ("A01", "A02", "A03"):
            ts = t.strftime("%Y%m%d%H%M%S")
            loc = f"W{rng.randint(1, 9)}^1^1"
            yield adt(trigger, f"BULK{i}", ts, **pt, visit=visit, location=loc)
            t += timedelta(hours=rng.randint(4, 72))
            i += 1
        ts = t.strftime("%Y%m%d%H%M%S")
        yield "\r".join([
            f"MSH|^~\\&|LAB|MC|HL7SEARCH|BH|{ts}||ORU^R01^ORU_R01|BULK{i}|P|2.5",
            f"PID|1||{mrn}^^^{pt['authority']}^MR||PATIENT^{mrn}",
            f"OBX|1|NM|2345-7^GLUCOSE^LN||{rng.randint(60, 300)}|mg/dL",
        ])  # fmt: skip
        i += 1


def main() -> None:
    p = argparse.ArgumentParser(description="Send synthetic HL7 data to the server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=2575)
    a = p.parse_args()
    msgs = demo_messages()
    acks = asyncio.run(send_messages(a.host, a.port, msgs))
    ok = sum("MSA|AA|" in ack for ack in acks)
    print(f"sent {len(msgs)} messages, {ok} accepted (AA)")


if __name__ == "__main__":
    main()
