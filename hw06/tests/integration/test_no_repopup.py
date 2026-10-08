"""Stretch: a re-announced person is not asked about again (R3)."""
import pytest

from planner import mqtt_bus
from tests.integration.conftest import wait_until


@pytest.mark.integration
@pytest.mark.stretch
def test_same_person_reannounced_no_popup(real_stack):
    """R3: after a decision, the detector re-announcing the same person opens no new popup."""
    s = real_stack
    s.wait_searching()
    event = s.inject_near_uav(east_m=30.0, confidence=0.9)
    request = s.wait_request(event["event_id"], timeout=5.0)
    assert request is not None
    s.dismiss(request)
    assert wait_until(lambda: s.planner.persons.nearest(event["lat"], event["lon"]).status.decided, 5.0)

    repeats = [s.inject(event["lat"], event["lon"], 0.95) for _ in range(3)]
    ids = {e["event_id"] for e in repeats}
    # every re-announcement reached the planner and merged into the same person...
    person = s.planner.persons.nearest(event["lat"], event["lon"])
    assert wait_until(lambda: ids <= set(person.event_ids), 5.0)
    # ...and none of them produced a request
    assert s.recorder.messages(mqtt_bus.DECISION_REQUEST, lambda r: r["event"]["event_id"] in ids) == []
