"""hover_stream end to end against SITL, then resume the search route (R5, R6, R7)."""
import time

import pytest

from planner import mqtt_bus


@pytest.mark.integration
def test_hover_stream_completes_and_resumes(real_stack):
    """R5/R6/R7: event -> decision_request (<2 s) -> approve hover_stream -> PENDING, RUNNING,
    COMPLETED -> the route resumes at the SAME waypoint it was heading to before."""
    s = real_stack
    s.wait_mid_leg()

    sent_at = time.time()
    event = s.inject_near_uav(east_m=25.0, confidence=0.9)
    request = s.wait_request(event["event_id"], timeout=2.0)
    assert request is not None, "no decision_request within 2 s of the event"
    asked_at = next(t for t, topic, p in s.recorder.log
                    if topic == mqtt_bus.DECISION_REQUEST and p["request_id"] == request["request_id"])
    assert asked_at - sent_at < 2.0

    index_before = s.route_index
    s.decide(request, "hover_stream", standoff_m=10.0, duration_s=10.0)
    result = s.wait_result(request["request_id"])
    assert result is not None and result["approved"] is True, result
    action_id = result["action_id"]

    states = s.wait_for_states(mqtt_bus.BEHAVIOR_STATUS, "state", ["PENDING", "RUNNING", "COMPLETED"],
                               timeout=180, where=lambda m: m.get("action_id") == action_id)
    assert states == ["PENDING", "RUNNING", "COMPLETED"], states

    executor = s.planner.executors["1"]
    assert executor.last_resume_index == index_before
    assert s.route_index == index_before
    resumed = s.recorder.messages(mqtt_bus.BEHAVIOR_STATUS,
                                  lambda m: m["action_id"] is None and m["behavior"] == "search_route")
    assert f"waypoint {index_before + 1} of" in resumed[-1]["detail"]
