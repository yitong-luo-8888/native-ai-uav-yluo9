"""Stretch: Cancel from the popup mid-response resumes the route (R7)."""
import pytest

from planner import mqtt_bus


@pytest.mark.integration
@pytest.mark.stretch
def test_cancel_mid_response_resumes_route(real_stack):
    """R7: cancelling a running hover_stream reports CANCELLED and resumes at the same waypoint."""
    s = real_stack
    s.wait_mid_leg()
    event = s.inject_near_uav(east_m=25.0, confidence=0.9)
    request = s.wait_request(event["event_id"], timeout=5.0)
    assert request is not None
    index_before = s.route_index
    s.decide(request, "hover_stream", duration_s=300.0)
    result = s.wait_result(request["request_id"])
    assert result and result["approved"]
    action_id = result["action_id"]
    s.wait_for_states(mqtt_bus.BEHAVIOR_STATUS, "state", ["PENDING", "RUNNING"], timeout=30,
                      where=lambda m: m.get("action_id") == action_id)

    s.bus.publish(mqtt_bus.CANCEL, {"uav": "1", "action_id": action_id})   # what the popup sends
    states = s.wait_for_states(mqtt_bus.BEHAVIOR_STATUS, "state", ["PENDING", "RUNNING", "CANCELLED"],
                               timeout=15, where=lambda m: m.get("action_id") == action_id)
    assert states[-1] == "CANCELLED", states
    assert s.planner.executors["1"].last_resume_index == index_before
    assert s.route_index == index_before
