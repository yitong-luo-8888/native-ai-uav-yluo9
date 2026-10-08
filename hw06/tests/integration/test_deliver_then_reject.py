"""deliver end to end, then a second deliver the validator must reject (R6, R7)."""
import pytest

from planner import mqtt_bus


@pytest.mark.integration
def test_deliver_then_second_deliver_rejected(real_stack):
    """R6/R7: the first deliver succeeds and removes the kit; a second deliver for a
    different person is rejected and the operator is re-asked with the reasons."""
    s = real_stack
    s.wait_mid_leg()

    # -- first person: deliver succeeds ---------------------------------------
    first = s.inject_near_uav(east_m=25.0, confidence=0.9)
    req1 = s.wait_request(first["event_id"], timeout=5.0)
    assert req1 is not None
    assert "deliver" in [c["type"] for c in req1["candidates"]]
    s.decide(req1, "deliver", item="medical_kit", dwell_s=3.0)
    res1 = s.wait_result(req1["request_id"])
    assert res1 is not None and res1["approved"] is True, res1
    states = s.wait_for_states(mqtt_bus.BEHAVIOR_STATUS, "state", ["PENDING", "RUNNING", "COMPLETED"],
                               timeout=240, where=lambda m: m.get("action_id") == res1["action_id"])
    assert states[-1] == "COMPLETED", states
    assert "medical_kit" not in s.planner.world.uav("1").payloads
    assert s.recorder.first(mqtt_bus.BEHAVIOR_STATUS,
                            lambda m: m["detail"] == "payload released: medical_kit") is not None

    # -- second person (60 m away): deliver rejected, re-asked ------------------
    second = s.inject_near_uav(east_m=-35.0, north_m=50.0, confidence=0.9)
    req2 = s.wait_request(second["event_id"], timeout=5.0)
    assert req2 is not None, "no decision_request for the second person"
    s.decide(req2, "deliver", item="medical_kit")
    res2 = s.wait_result(req2["request_id"])
    assert res2 is not None and res2["approved"] is False, res2
    assert any("medical_kit" in r or "payload" in r for r in res2["reasons"]), res2["reasons"]

    req3 = s.wait_request(second["event_id"], timeout=5.0, exclude={req2["request_id"]})
    assert req3 is not None, "operator was not re-asked after the rejection"
    assert req3["event"] == req2["event"]
    assert req3["request_id"] != req2["request_id"]
    assert req3["previous_rejection"] == res2["reasons"]
    s.dismiss(req3)
