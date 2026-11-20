from __future__ import annotations

import pytest

from hl7search.parser import parse
from hl7search.seed import EXPECTED_JANE_ADT_CONTROL_IDS, TASK_EXAMPLE_ORM, demo_messages
from hl7search.store import FieldFilter, SearchResult, Store

ADT_AND_CANCELS = ["A01", "A02", "A03", "A11", "A12", "A13"]


def ids(result: SearchResult) -> list[str | None]:
    return [h["control_id"] for h in result["hits"]]


def test_insert_is_idempotent_on_control_id(store: Store) -> None:
    before = store.stats()["total_messages"]
    again = store.insert(parse(demo_messages()[0]))
    assert again.duplicate
    assert store.stats()["total_messages"] == before == len(demo_messages())


def test_search_any_field_on_task_example(store: Store) -> None:
    r = store.search([FieldFilter("OBX.3.1", "eq", "513230")], return_fields=["OBX.5"])
    assert ids(r) == ["AccessionNumber"]
    assert r["hits"][0]["fields"]["OBX.5"] == ["26"]
    assert ids(store.search([FieldFilter("MSH.3", "eq", "BUNKERHILL")])) == ["AccessionNumber"]


def test_mrn_alone_matches_two_hospitals(store: Store) -> None:
    r = store.search([FieldFilter("PID.3.1", "eq", "12345")], message_type="ADT")
    facilities = {h["sending_facility"] for h in r["hits"]}
    assert facilities == {"MC", "OTHERHOSP"}  # the trap


def test_patient_adt_timeline(store: Store) -> None:
    """The query the agent should arrive at."""
    r = store.search(
        [FieldFilter("PID.3.1", "eq", "12345"), FieldFilter("PID.3.4", "eq", "MC")],
        scope="repetition",
        message_type="ADT",
        trigger_events=ADT_AND_CANCELS,
        return_fields=["PV1.3", "PV1.6", "PV1.19"],
    )
    assert ids(r) == EXPECTED_JANE_ADT_CONTROL_IDS  # also proves event-time ordering
    first = r["hits"][0]
    assert first["trigger_event"] == "A01"
    assert first["event_description"] == "Admit/visit notification"
    assert first["fields"]["PV1.19"] == ["V1001"]
    assert first["fields"]["PV1.3"] == ["4WEST^401^A^MC"]


def test_repetition_scope_requires_same_identifier() -> None:
    s = Store(":memory:")
    # Patient with two identifiers: 111 at MC, 222 at OTHER.
    s.insert(parse("MSH|^~\\&|A|B|||20240101||ADT^A01|1|P|2.5\rPID|1||111^^^MC~222^^^OTHER"))
    both = [FieldFilter("PID.3.1", "eq", "222"), FieldFilter("PID.3.4", "eq", "MC")]
    assert s.search(both)["total"] == 1  # message scope: false positive
    assert s.search(both, scope="repetition")["total"] == 0  # correct


def test_segment_scope_numeric(store: Store) -> None:
    high_glucose = [
        FieldFilter("OBX.3.1", "eq", "2345-7"),
        FieldFilter("OBX.5", "gt", "150", numeric=True),
    ]
    assert ids(store.search(high_glucose, scope="segment")) == ["LAB0001"]
    # Sodium is 139 (> 100) but it is a different OBX than glucose:
    mixed = [
        FieldFilter("OBX.3.1", "eq", "2345-7"),
        FieldFilter("OBX.5", "lt", "150", numeric=True),
    ]
    assert store.search(mixed, scope="segment")["total"] == 0
    assert store.search(mixed, scope="message")["total"] == 1


def test_ops(store: Store) -> None:
    assert store.search([FieldFilter("PID.5.1", "prefix", "DO")])["total"] == 12
    assert store.search([FieldFilter("PV1.3.1", "contains", "NORTH")])["total"] == 4
    r = store.search([FieldFilter("MSH.9.2", "in", ["A11", "A13"])])
    assert ids(r) == ["MC0007", "MC0011"]


def test_time_bounds_and_pagination(store: Store) -> None:
    r = store.search(message_type="ADT", since="20240901", until="2024-09-30T23:59:59")
    assert ids(r) == ["MC0008", "MC0009", "MC0010", "MC0011"]
    page1 = store.search(message_type="ADT", limit=5)
    page2 = store.search(message_type="ADT", limit=5, offset=page1["next_offset"] or 0)
    assert page1["total"] == 17 and page1["next_offset"] == 5
    assert set(ids(page1)).isdisjoint(ids(page2))


def test_validation_errors(store: Store) -> None:
    with pytest.raises(ValueError, match="Invalid HL7 path"):
        store.search([FieldFilter("PID.x", "eq", "1")])
    with pytest.raises(ValueError, match="same segment"):
        store.search([FieldFilter("PID.3", "eq", "1"), FieldFilter("PV1.3", "eq", "1")],
                     scope="segment")  # fmt: skip
    with pytest.raises(ValueError, match="limit"):
        store.search(limit=10_000)


def test_injection_is_inert(store: Store) -> None:
    r = store.search([FieldFilter("PID.3.1", "eq", "1' OR '1'='1")])
    assert r["total"] == 0


def test_get_message_and_describe(store: Store) -> None:
    hit = store.search([FieldFilter("MSH.10", "eq", "AccessionNumber")])["hits"][0]
    full = store.get_message(hit["message_id"])
    assert full["raw"].startswith("MSH|^~\\&|BUNKERHILL")
    obr = next(s for s in full["segments"] if s["segment"] == "OBR")
    assert {"field": "OBR-22", "name": "Results Rpt/Status Chng - Date/Time",
            "value": "20240509144522"} in obr["fields"]  # fmt: skip
    pv1 = store.describe_segment("pv1")
    assert any(f["path"] == "PV1.19" and f["name"] == "Visit Number" for f in pv1["fields"])


def test_sub_one_equals_component_without_subcomponents() -> None:
    s = Store(":memory:")
    s.insert(parse(TASK_EXAMPLE_ORM))
    assert s.search([FieldFilter("PID.3.4.1", "eq", "MC")])["total"] == 1


def test_insert_many_matches_insert(store: Store) -> None:
    bulk = Store(":memory:")
    msgs = [parse(m) for m in demo_messages()]
    assert bulk.insert_many(msgs) == len(msgs)
    assert bulk.insert_many(msgs) == 0  # idempotent
    q = [FieldFilter("PID.3.1", "eq", "12345")]
    assert ids(bulk.search(q)) == ids(store.search(q))
