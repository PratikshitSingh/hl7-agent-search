"""Human-readable names for common HL7 v2 fields and ADT events.

Agents pick better filters when results say "PV1-3 Assigned Patient Location"
instead of just "PV1.3". This is a curated subset, not the full standard.
"""

from __future__ import annotations

FIELD_NAMES: dict[str, dict[int, str]] = {
    "MSH": {
        1: "Field Separator",
        2: "Encoding Characters",
        3: "Sending Application",
        4: "Sending Facility",
        5: "Receiving Application",
        6: "Receiving Facility",
        7: "Date/Time of Message",
        8: "Security",
        9: "Message Type (type^trigger^structure)",
        10: "Message Control ID",
        11: "Processing ID",
        12: "Version ID",
        13: "Sequence Number",
        15: "Accept Acknowledgment Type",
        16: "Application Acknowledgment Type",
        17: "Country Code",
        18: "Character Set",
    },
    "EVN": {
        1: "Event Type Code (deprecated; use MSH-9.2)",
        2: "Recorded Date/Time",
        3: "Date/Time Planned Event",
        4: "Event Reason Code",
        5: "Operator ID",
        6: "Event Occurred",
        7: "Event Facility",
    },
    "PID": {
        1: "Set ID",
        2: "Patient ID (external, deprecated)",
        3: "Patient Identifier List (ID^check^scheme^assigning authority^id type)",
        4: "Alternate Patient ID",
        5: "Patient Name (family^given^middle^suffix^prefix)",
        6: "Mother's Maiden Name",
        7: "Date/Time of Birth",
        8: "Administrative Sex",
        9: "Patient Alias",
        10: "Race",
        11: "Patient Address",
        13: "Phone Number - Home",
        14: "Phone Number - Business",
        15: "Primary Language",
        16: "Marital Status",
        17: "Religion",
        18: "Patient Account Number",
        19: "SSN Number (deprecated)",
        22: "Ethnic Group",
        29: "Patient Death Date and Time",
        30: "Patient Death Indicator",
    },
    "PV1": {
        1: "Set ID",
        2: "Patient Class (I=inpatient, O=outpatient, E=emergency...)",
        3: "Assigned Patient Location (point of care^room^bed^facility)",
        4: "Admission Type",
        5: "Preadmit Number",
        6: "Prior Patient Location",
        7: "Attending Doctor",
        8: "Referring Doctor",
        9: "Consulting Doctor",
        10: "Hospital Service",
        14: "Admit Source",
        17: "Admitting Doctor",
        18: "Patient Type",
        19: "Visit Number",
        20: "Financial Class",
        36: "Discharge Disposition",
        37: "Discharged to Location",
        39: "Servicing Facility",
        44: "Admit Date/Time",
        45: "Discharge Date/Time",
    },
    "MRG": {
        1: "Prior Patient Identifier List",
        5: "Prior Visit Number",
    },
    "ORC": {
        1: "Order Control",
        2: "Placer Order Number",
        3: "Filler Order Number",
        5: "Order Status",
        9: "Date/Time of Transaction",
        12: "Ordering Provider",
    },
    "OBR": {
        1: "Set ID",
        2: "Placer Order Number",
        3: "Filler Order Number",
        4: "Universal Service Identifier",
        7: "Observation Date/Time",
        16: "Ordering Provider",
        22: "Results Rpt/Status Chng - Date/Time",
        25: "Result Status",
    },
    "OBX": {
        1: "Set ID",
        2: "Value Type",
        3: "Observation Identifier",
        4: "Observation Sub-ID",
        5: "Observation Value",
        6: "Units",
        7: "Reference Range",
        8: "Abnormal Flags",
        11: "Observation Result Status",
        14: "Date/Time of the Observation",
    },
    "MSA": {
        1: "Acknowledgment Code",
        2: "Message Control ID",
        3: "Text Message",
    },
}

ADT_EVENTS: dict[str, str] = {
    "A01": "Admit/visit notification",
    "A02": "Transfer a patient",
    "A03": "Discharge/end visit",
    "A04": "Register a patient",
    "A05": "Pre-admit a patient",
    "A06": "Change an outpatient to an inpatient",
    "A07": "Change an inpatient to an outpatient",
    "A08": "Update patient information",
    "A11": "Cancel admit/visit notification (cancels A01)",
    "A12": "Cancel transfer (cancels A02)",
    "A13": "Cancel discharge/end visit (cancels A03)",
    "A40": "Merge patient - patient identifier list",
}


def field_name(seg: str, field: int) -> str | None:
    return FIELD_NAMES.get(seg, {}).get(field)


def event_description(message_type: str | None, trigger: str | None) -> str | None:
    if message_type == "ADT" and trigger:
        return ADT_EVENTS.get(trigger)
    return None
