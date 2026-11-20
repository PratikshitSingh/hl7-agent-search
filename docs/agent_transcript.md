# Agent transcript: ADT timeline for one patient

**Task given to the agent:** "Find all admissions, discharges and transfers for the
patient with MRN 12345 at facility MC."

**Agent:** Claude, calling the `hl7-mcp` server over a real MCP stdio transport via
`scripts/mcp_call.py` (no API key was available in the build sandbox, so the agent was the
Claude session itself; `scripts/agent_demo.py` runs the same loop through the Anthropic API).
The agent saw only the MCP tool list, server instructions and tool results.

Data: `hl7-seed` sent 19 synthetic messages to `hl7-server` over MLLP (shuffled order).

### `hl7_stats`
```json
{}
```
Result:
```json
{
  "total_messages": 19,
  "by_type": [
    {
      "message_type": "ADT",
      "trigger_event": "A01",
      "description": "Admit/visit notification",
      "count": 5
    },
    {
      "message_type": "ADT",
      "trigger_event": "A02",
      "description": "Transfer a patient",
      "count": 4
    },
    {
      "message_type": "ADT",
      "trigger_event": "A03",
      "description": "Discharge/end visit",
      "count": 4
    },
    {
      "message_type": "ADT",
      "trigger_event": "A04",
      "description": "Register a patient",
      "count": 1
    },
    {
      "message_type": "ADT",
      "trigger_event": "A08",
      "description": "Update patient information",
      "count": 1
    },
    {
      "message_type": "ADT",
      "trigger_event": "A11",
      "description": "Cancel admit/visit notification (cancels A01)",
      "count": 1
    },
    {
      "message_type": "ADT",
      "trigger_event": "A13",
      "description": "Cancel discharge/end visit (cancels A03)",
      "count": 1
    },
    {
      "message_type": "ORM",
      "trigger_event": "O01",
      "description": null,
      "count": 1
    },
    {
      "message_type": "ORU",
      "trigger_event": "R01",
      "description": null,
      "count": 1
    }
  ],
  "segments_seen": [
    "EVN",
    "MSH",
    "OBR",
    "OBX",
    "ORC",
    "PID",
    "PV1"
  ]
}
```

### `hl7_search_messages`
```json
{
  "filters": [
    {
      "path": "PID.3.1",
      "op": "eq",
      "value": "12345"
    }
  ],
  "return_fields": [
    "PID.3.4",
    "PID.5"
  ],
  "limit": 50
}
```
Result:
```json
{
  "total": 14,
  "returned": 14,
  "next_offset": null,
  "hits": [
    {
      "message_id": 9,
      "message_type": "ADT",
      "trigger_event": "A01",
      "event_description": "Admit/visit notification",
      "event_time": "2024-03-01T08:15:00",
      "control_id": "MC0001",
      "sending_facility": "MC",
      "fields": {
        "PID.3.4": [
          "MC"
        ],
        "PID.5": [
          "DOE^JANE^A"
        ]
      }
    },
    {
      "message_id": 4,
      "message_type": "ORU",
      "trigger_event": "R01",
      "event_description": null,
      "event_time": "2024-03-02T06:00:00",
      "control_id": "LAB0001",
      "sending_facility": "MC",
      "fields": {
        "PID.3.4": [
          "MC"
        ],
        "PID.5": [
          "DOE^JANE^A"
        ]
      }
    },
    {
      "message_id": 16,
      "message_type": "ADT",
      "trigger_event": "A02",
      "event_description": "Transfer a patient",
      "event_time": "2024-03-02T14:30:00",
      "control_id": "MC0002",
      "sending_facility": "MC",
      "fields": {
        "PID.3.4": [
          "MC"
        ],
        "PID.5": [
          "DOE^JANE^A"
        ]
      }
    },
    {
      "message_id": 2,
      "message_type": "ADT",
      "trigger_event": "A02",
      "event_description": "Transfer a patient",
      "event_time": "2024-03-04T09:00:00",
      "control_id": "MC0003",
      "sending_facility": "MC",
      "fields": {
        "PID.3.4": [
          "MC"
        ],
        "PID.5": [
          "DOE^JANE^A"
        ]
      }
    },
    {
      "message_id": 8,
      "message_type": "ADT",
      "trigger_event": "A03",
      "event_description": "Discharge/end visit",
      "event_time": "2024-03-06T11:00:00",
      "control_id": "MC0004",
      "sending_facility": "MC",
      "fields": {
        "PID.3.4": [
          "MC"
        ],
        "PID.5": [
          "DOE^JANE^A"
        ]
      }
    },
    {
      "message_id": 18,
      "message_type": "ADT",
      "trigger_event": "A08",
      "event_description": "Update patient information",
      "event_time": "2024-03-10T12:00:00",
      "control_id": "MC0005",
      "sending_facility": "MC",
      "fields": {
        "PID.3.4": [
          "MC"
        ],
        "PID.5": [
          "DOE^JANE^A"
        ]
      }
    },
    {
      "message_id": 1,
      "message_type": "ADT",
      "trigger_event": "A01",
      "event_description": "Admit/visit notification",
      "event_time": "2024-04-01T09:00:00",
      "control_id": "OH0001",
      "sending_facility": "OTHERHOSP",
      "fields": {
        "PID.3.4": [
          "OTHERHOSP"
        ],
        "PID.5": [
          "ROE^RICHARD"
        ]
      }
    },
    {
      "message_id": 17,
      "message_type": "ADT",
      "trigger_event": "A03",
      "event_description": "Discharge/end visit",
      "event_time": "2024-04-03T10:00:00",
      "control_id": "OH0002",
      "sending_facility": "OTHERHOSP",
      "fields": {
        "PID.3.4": [
          "OTHERHOSP"
        ],
        "PID.5": [
          "ROE^RICHARD"
        ]
      }
    },
    {
      "message_id": 11,
      "message_type": "ADT",
      "trigger_event": "A01",
      "event_description": "Admit/visit notification",
      "event_time": "2024-06-10T22:40:00",
      "control_id": "MC0006",
      "sending_facility": "MC",
      "fields": {
        "PID.3.4": [
          "MC"
        ],
        "PID.5": [
          "DOE^JANE^A"
        ]
      }
    },
    {
      "message_id": 6,
      "message_type": "ADT",
      "trigger_event": "A11",
      "event_description": "Cancel admit/visit notification (cancels A01)",
      "event_time": "2024-06-10T23:05:00",
      "control_id": "MC0007",
      "sending_facility": "MC",
      "fields": {
        "PID.3.4": [
          "MC"
        ],
        "PID.5": [
          "DOE^JANE^A"
        ]
      }
    },
    {
      "message_id": 5,
      "message_type": "ADT",
      "trigger_event": "A01",
      "event_description": "Admit/visit notification",
      "event_time": "2024-09-20T07:00:00",
      "control_id": "MC0008",
      "sending_facility": "MC",
      "fields": {
        "PID.3.4": [
          "MC"
        ],
        "PID.5": [
          "DOE^JANE^A"
        ]
      }
    },
    {
      "message_id": 13,
      "message_type": "ADT",
      "trigger_event": "A02",
      "event_description": "Transfer a patient",
      "event_time": "2024-09-22T10:00:00",
      "control_id": "MC0009",
      "sending_facility": "MC",
      "fields": {
        "PID.3.4": [
          "MC"
        ],
        "PID.5": [
          "DOE^JANE^A"
        ]
      }
    },
    {
      "message_id": 10,
      "message_type": "ADT",
      "trigger_event": "A03",
      "event_description": "Discharge/end visit",
      "event_time": "2024-09-25T15:00:00",
      "control_id": "MC0010",
      "sending_facility": "MC",
      "fields": {
        "PID.3.4": [
          "MC"
        ],
        "PID.5": [
          "DOE^JANE^A"
        ]
      }
    },
    {
      "message_id": 19,
      "message_type": "ADT",
      "trigger_event": "A13",
      "event_description": "Cancel discharge/end visit (cancels A03)",
      "event_time": "2024-09-25T16:20:00",
      "control_id": "MC0011",
      "sending_facility": "MC",
      "fields": {
        "PID.3.4": [
          "MC"
        ],
        "PID.5": [
          "DOE^JANE^A"
        ]
      }
    }
  ]
}
```

### `hl7_search_messages`
```json
{
  "filters": [
    {
      "path": "PID.3.1",
      "value": "12345"
    },
    {
      "path": "PID.3.4",
      "value": "MC"
    }
  ],
  "scope": "repetition",
  "message_type": "ADT",
  "trigger_events": [
    "A01",
    "A02",
    "A03",
    "A11",
    "A12",
    "A13"
  ],
  "return_fields": [
    "PV1.19",
    "PV1.3",
    "PV1.6",
    "PV1.36"
  ]
}
```
Result:
```json
{
  "total": 10,
  "returned": 10,
  "next_offset": null,
  "hits": [
    {
      "message_id": 9,
      "message_type": "ADT",
      "trigger_event": "A01",
      "event_description": "Admit/visit notification",
      "event_time": "2024-03-01T08:15:00",
      "control_id": "MC0001",
      "sending_facility": "MC",
      "fields": {
        "PV1.19": [
          "V1001"
        ],
        "PV1.3": [
          "4WEST^401^A^MC"
        ]
      }
    },
    {
      "message_id": 16,
      "message_type": "ADT",
      "trigger_event": "A02",
      "event_description": "Transfer a patient",
      "event_time": "2024-03-02T14:30:00",
      "control_id": "MC0002",
      "sending_facility": "MC",
      "fields": {
        "PV1.19": [
          "V1001"
        ],
        "PV1.3": [
          "ICU^12^1^MC"
        ],
        "PV1.6": [
          "4WEST^401^A^MC"
        ]
      }
    },
    {
      "message_id": 2,
      "message_type": "ADT",
      "trigger_event": "A02",
      "event_description": "Transfer a patient",
      "event_time": "2024-03-04T09:00:00",
      "control_id": "MC0003",
      "sending_facility": "MC",
      "fields": {
        "PV1.19": [
          "V1001"
        ],
        "PV1.3": [
          "4WEST^405^B^MC"
        ],
        "PV1.6": [
          "ICU^12^1^MC"
        ]
      }
    },
    {
      "message_id": 8,
      "message_type": "ADT",
      "trigger_event": "A03",
      "event_description": "Discharge/end visit",
      "event_time": "2024-03-06T11:00:00",
      "control_id": "MC0004",
      "sending_facility": "MC",
      "fields": {
        "PV1.19": [
          "V1001"
        ],
        "PV1.3": [
          "4WEST^405^B^MC"
        ],
        "PV1.36": [
          "01"
        ]
      }
    },
    {
      "message_id": 11,
      "message_type": "ADT",
      "trigger_event": "A01",
      "event_description": "Admit/visit notification",
      "event_time": "2024-06-10T22:40:00",
      "control_id": "MC0006",
      "sending_facility": "MC",
      "fields": {
        "PV1.19": [
          "V1002"
        ],
        "PV1.3": [
          "3EAST^310^A^MC"
        ]
      }
    },
    {
      "message_id": 6,
      "message_type": "ADT",
      "trigger_event": "A11",
      "event_description": "Cancel admit/visit notification (cancels A01)",
      "event_time": "2024-06-10T23:05:00",
      "control_id": "MC0007",
      "sending_facility": "MC",
      "fields": {
        "PV1.19": [
          "V1002"
        ],
        "PV1.3": [
          "3EAST^310^A^MC"
        ]
      }
    },
    {
      "message_id": 5,
      "message_type": "ADT",
      "trigger_event": "A01",
      "event_description": "Admit/visit notification",
      "event_time": "2024-09-20T07:00:00",
      "control_id": "MC0008",
      "sending_facility": "MC",
      "fields": {
        "PV1.19": [
          "V1003"
        ],
        "PV1.3": [
          "5NORTH^502^A^MC"
        ]
      }
    },
    {
      "message_id": 13,
      "message_type": "ADT",
      "trigger_event": "A02",
      "event_description": "Transfer a patient",
      "event_time": "2024-09-22T10:00:00",
      "control_id": "MC0009",
      "sending_facility": "MC",
      "fields": {
        "PV1.19": [
          "V1003"
        ],
        "PV1.3": [
          "5NORTH^510^B^MC"
        ],
        "PV1.6": [
          "5NORTH^502^A^MC"
        ]
      }
    },
    {
      "message_id": 10,
      "message_type": "ADT",
      "trigger_event": "A03",
      "event_description": "Discharge/end visit",
      "event_time": "2024-09-25T15:00:00",
      "control_id": "MC0010",
      "sending_facility": "MC",
      "fields": {
        "PV1.19": [
          "V1003"
        ],
        "PV1.3": [
          "5NORTH^510^B^MC"
        ],
        "PV1.36": [
          "01"
        ]
      }
    },
    {
      "message_id": 19,
      "message_type": "ADT",
      "trigger_event": "A13",
      "event_description": "Cancel discharge/end visit (cancels A03)",
      "event_time": "2024-09-25T16:20:00",
      "control_id": "MC0011",
      "sending_facility": "MC",
      "fields": {
        "PV1.19": [
          "V1003"
        ],
        "PV1.3": [
          "5NORTH^510^B^MC"
        ]
      }
    }
  ]
}
```

### `hl7_get_message`
```json
{
  "message_id": 19
}
```
Result:
```json
{
  "message_id": 19,
  "message_type": "ADT",
  "trigger_event": "A13",
  "event_description": "Cancel discharge/end visit (cancels A03)",
  "event_time": "2024-09-25T16:20:00",
  "received_at": "2026-11-20T04:39:08.652581+00:00",
  "raw": "MSH|^~\\&|EPIC|MC|HL7SEARCH|BH|20240925162000||ADT^A13^ADT_A01|MC0011|P|2.5\nEVN|A13|20240925162000||||20240925162000\nPID|1||12345^^^MC^MR||DOE^JANE^A||19800214|F\nPV1|1|I|5NORTH^510^B^MC||||1001^HOUSE^GREGORY^^^DR|||MED|||||||||V1003|||||||||||||||||||||||||20240920070000|",
  "segments": [
    {
      "segment": "MSH",
      "position": 1,
      "fields": [
        {
          "field": "MSH-1",
          "name": "Field Separator",
          "value": "|"
        },
        {
          "field": "MSH-2",
          "name": "Encoding Characters",
          "value": "^~\\&"
        },
        {
          "field": "MSH-3",
          "name": "Sending Application",
          "value": "EPIC"
        },
        {
          "field": "MSH-4",
          "name": "Sending Facility",
          "value": "MC"
        },
        {
          "field": "MSH-5",
          "name": "Receiving Application",
          "value": "HL7SEARCH"
        },
        {
          "field": "MSH-6",
          "name": "Receiving Facility",
          "value": "BH"
        },
        {
          "field": "MSH-7",
          "name": "Date/Time of Message",
          "value": "20240925162000"
        },
        {
          "field": "MSH-9",
          "name": "Message Type (type^trigger^structure)",
          "value": "ADT^A13^ADT_A01"
        },
        {
          "field": "MSH-10",
          "name": "Message Control ID",
          "value": "MC0011"
        },
        {
          "field": "MSH-11",
          "name": "Processing ID",
          "value": "P"
        },
        {
          "field": "MSH-12",
          "name": "Version ID",
          "value": "2.5"
        }
      ]
    },
    {
      "segment": "EVN",
      "position": 2,
      "fields": [
        {
          "field": "EVN-1",
          "name": "Event Type Code (deprecated; use MSH-9.2)",
          "value": "A13"
        },
        {
          "field": "EVN-2",
          "name": "Recorded Date/Time",
          "value": "20240925162000"
        },
        {
          "field": "EVN-6",
          "name": "Event Occurred",
          "value": "20240925162000"
        }
      ]
    },
    {
      "segment": "PID",
      "position": 3,
      "fields": [
        {
          "field": "PID-1",
          "name": "Set ID",
          "value": "1"
        },
        {
          "field": "PID-3",
          "name": "Patient Identifier List (ID^check^scheme^assigning authority^id type)",
          "value": "12345^^^MC^MR"
        },
        {
          "field": "PID-5",
          "name": "Patient Name (family^given^middle^suffix^prefix)",
          "value": "DOE^JANE^A"
        },
        {
          "field": "PID-7",
          "name": "Date/Time of Birth",
          "value": "19800214"
        },
        {
          "field": "PID-8",
          "name": "Administrative Sex",
          "value": "F"
        }
      ]
    },
    {
      "segment": "PV1",
      "position": 4,
      "fields": [
        {
          "field": "PV1-1",
          "name": "Set ID",
          "value": "1"
        },
        {
          "field": "PV1-2",
          "name": "Patient Class (I=inpatient, O=outpatient, E=emergency...)",
          "value": "I"
        },
        {
          "field": "PV1-3",
          "name": "Assigned Patient Location (point of care^room^bed^facility)",
          "value": "5NORTH^510^B^MC"
        },
        {
          "field": "PV1-7",
          "name": "Attending Doctor",
          "value": "1001^HOUSE^GREGORY^^^DR"
        },
        {
          "field": "PV1-10",
          "name": "Hospital Service",
          "value": "MED"
        },
        {
          "field": "PV1-19",
          "name": "Visit Number",
          "value": "V1003"
        },
        {
          "field": "PV1-44",
          "name": "Admit Date/Time",
          "value": "20240920070000"
        }
      ]
    }
  ]
}
```

## Agent's reasoning and final answer

1. `hl7_stats` showed A11 and A13 cancellation messages exist, so cancellations must be applied.
2. Searching `PID.3.1 = 12345` alone returned **two different people** (DOE^JANE at MC,
   ROE^RICHARD at OTHERHOSP). MRNs are only unique per assigning authority.
3. Re-searched with `PID.3.1 = 12345` + `PID.3.4 = MC` in `scope="repetition"`, ADT triggers
   A01/A02/A03 plus cancels A11/A12/A13, returning visit number and locations.
4. Pulled the A13 message to confirm it cancels the V1003 discharge.

**Patient: DOE, JANE A — MRN 12345 (MC)**

| Visit | Time | Event | Location | Notes |
|---|---|---|---|---|
| V1001 | 2024-03-01 08:15 | Admit (A01) | 4WEST 401-A | |
| V1001 | 2024-03-02 14:30 | Transfer (A02) | ICU 12-1 | from 4WEST 401-A |
| V1001 | 2024-03-04 09:00 | Transfer (A02) | 4WEST 405-B | from ICU 12-1 |
| V1001 | 2024-03-06 11:00 | Discharge (A03) | 4WEST 405-B | disposition 01 (home) |
| V1002 | 2024-06-10 22:40 | ~~Admit (A01)~~ | 3EAST 310-A | **cancelled** by A11 at 23:05 |
| V1003 | 2024-09-20 07:00 | Admit (A01) | 5NORTH 502-A | |
| V1003 | 2024-09-22 10:00 | Transfer (A02) | 5NORTH 510-B | from 5NORTH 502-A |
| V1003 | 2024-09-25 15:00 | ~~Discharge (A03)~~ | 5NORTH 510-B | **cancelled** by A13 at 16:20, so the patient is still admitted |

Excluded on purpose: the A08 demographics update (not an admit/discharge/transfer), and
the admissions of the *other* patient with MRN 12345 at OTHERHOSP.

Result checked against the seeded ground truth (`EXPECTED_JANE_ADT_CONTROL_IDS`): exact match.
