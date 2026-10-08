"""Planner decision loop on fakes: event -> request -> decision -> validation (R3, R5, R6)."""
from planner.person_registry import DecisionStatus
from tests.conftest import choose, dismiss, make_event, near


def test_event_triggers_decision_request(harness):
    """R5: one person event produces exactly one decision_request for that event."""
    ev = make_event(event_id="e1")
    harness.event(ev)
    requests = harness.requests()
    assert len(requests) == 1
    assert requests[0]["event"]["event_id"] == "e1"
    assert requests[0]["world_state"]["uavs"][0]["payloads"] == ["medical_kit"]


def test_dismiss_marks_person_decided(harness):
    """R3: "No action" makes the person DISMISSED; a re-sighting opens no new request."""
    harness.operator.then(dismiss)
    ev = make_event()
    person = harness.event(ev)
    assert person.status is DecisionStatus.DISMISSED
    harness.event(near(ev, 4.0))
    assert len(harness.requests()) == 1


def test_rejection_reask_carries_reasons(harness):
    """R6: a rejected choice is re-asked: new request_id, same event, previous_rejection == reasons."""
    harness.planner.world.remove_payload("1", "medical_kit")
    harness.operator.then(choose("deliver", item="medical_kit")).then(dismiss)
    ev = make_event(event_id="e7", confidence=0.9)
    harness.event(ev)
    first, second = harness.requests()
    result = harness.results()[0]
    assert result["approved"] is False and result["request_id"] == first["request_id"]
    assert second["request_id"] != first["request_id"]
    assert second["event"] == first["event"] and second["event"]["event_id"] == "e7"
    assert second["previous_rejection"] == result["reasons"]
    assert "previous_rejection" not in first


def test_timeout_marks_person_undecided(harness):
    """R3/R5: no answer within timeout_s leaves the person UNDECIDED (not decided), so a
    later sighting asks again."""
    ev = make_event()
    person = harness.event(ev)                 # operator never answers
    assert person.status is DecisionStatus.UNDECIDED
    assert not person.status.decided
    harness.event(near(ev, 3.0))
    assert len(harness.requests()) == 2


def test_low_confidence_restricts_menu(harness):
    """R2: confidence 0.31 -> the candidates in the request exclude deliver."""
    harness.event(make_event(confidence=0.31))
    menu = [c["type"] for c in harness.requests()[0]["candidates"]]
    assert "deliver" not in menu
    assert menu == ["hover_stream", "circle_stream"]


def test_responded_person_reannounced_no_popup(harness):
    """R3: the detector re-announces a person every 30 s; once responded, no new popup."""
    harness.operator.then(choose("hover_stream"))
    ev = make_event()
    harness.event(ev)
    for d in (2.0, 5.0, 8.0):
        harness.event(near(ev, d))
    assert len(harness.requests()) == 1
    assert len(harness.planner.persons) == 1


def test_duplicate_event_delivery_is_idempotent(harness):
    """R3: a QoS-1 redelivery of the same event_id is not a new sighting and opens no new request."""
    ev = make_event(event_id="dup")
    person = harness.event(ev)            # times out: person stays UNDECIDED
    harness.event(dict(ev))               # same event_id again
    assert person.sightings == 1
    assert len(harness.requests()) == 1


def test_action_result_keys_match_popup(harness):
    """R6: action_result carries exactly the keys hotl_popup.py reads."""
    harness.operator.then(choose("hover_stream"))
    harness.event(make_event())
    assert set(harness.results()[0]) == {"request_id", "approved", "action_id", "type", "uav", "reasons"}
