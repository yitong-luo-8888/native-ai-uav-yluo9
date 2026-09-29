"""Unit tests for atc.py (ATCController).

PURE (per this skill's worked example for this file): get_position,
distance_between, distance_to_waypoint, should_yield. They read
self.drones, but that dict is populated directly by these tests (via the
`controller` fixture in conftest.py) rather than through a live MQTT
callback, so they're exercised like pure functions over injected state.

STUB: _on_message, interrupt_drone, resume_drone, send_command. They're
exercised through the `controller` fixture, whose self.client is a
FakeMqttClient (records publish()/subscribe() instead of talking to a
broker) -- the dependency is faked, never ATCController's own methods.

LIVE: __init__ (builds a real mqtt.Client, connects, loop_starts) and
_on_connect (subscribes from within a real connection callback). Not
unit-tested here; see generated-tests/integration/test_atc_live.py.
"""
import json
import math

import pytest

import hw05.atc as atc
from conftest import FakeMqttMessage


# ---------------------------------------------------------------------------
# PURE: get_position
# ---------------------------------------------------------------------------

def test_get_position_returns_lat_lon_alt_when_present(controller):
    controller.drones["1"] = {"lat": 1.0, "lon": 2.0, "alt_rel": 10.0}
    assert controller.get_position("1") == (1.0, 2.0, 10.0)


def test_get_position_defaults_alt_rel_to_zero_when_missing(controller):
    controller.drones["1"] = {"lat": 1.0, "lon": 2.0}
    assert controller.get_position("1") == (1.0, 2.0, 0)


def test_get_position_returns_none_for_unknown_drone(controller):
    assert controller.get_position("99") is None


def test_get_position_returns_none_when_lon_missing(controller):
    controller.drones["1"] = {"lat": 1.0}
    assert controller.get_position("1") is None


def test_get_position_returns_none_when_lat_missing(controller):
    controller.drones["1"] = {"lon": 2.0}
    assert controller.get_position("1") is None


# ---------------------------------------------------------------------------
# PURE: distance_between
# ---------------------------------------------------------------------------

def test_distance_between_identical_positions_is_zero(controller):
    controller.drones["1"] = {"lat": 10.0, "lon": 20.0, "alt_rel": 5.0}
    controller.drones["2"] = {"lat": 10.0, "lon": 20.0, "alt_rel": 5.0}
    assert controller.distance_between("1", "2") == 0.0


def test_distance_between_pure_altitude_difference_returns_vertical_distance(controller):
    controller.drones["1"] = {"lat": 10.0, "lon": 20.0, "alt_rel": 5.0}
    controller.drones["2"] = {"lat": 10.0, "lon": 20.0, "alt_rel": 15.0}
    assert controller.distance_between("1", "2") == pytest.approx(10.0)


def test_distance_between_pure_horizontal_offset_matches_known_leg_length(controller):
    lat0 = 10.0
    dlat_deg = math.degrees(100.0 / atc.EARTH_RADIUS_M)  # ~100m due-north offset
    controller.drones["1"] = {"lat": lat0, "lon": 20.0, "alt_rel": 0.0}
    controller.drones["2"] = {"lat": lat0 + dlat_deg, "lon": 20.0, "alt_rel": 0.0}
    assert controller.distance_between("1", "2") == pytest.approx(100.0, abs=0.05)


def test_distance_between_is_symmetric(controller):
    controller.drones["1"] = {"lat": 10.0, "lon": 20.0, "alt_rel": 5.0}
    controller.drones["2"] = {"lat": 10.001, "lon": 20.001, "alt_rel": 8.0}
    assert controller.distance_between("1", "2") == pytest.approx(
        controller.distance_between("2", "1")
    )


def test_distance_between_missing_drone_returns_infinity(controller):
    controller.drones["1"] = {"lat": 10.0, "lon": 20.0, "alt_rel": 5.0}
    assert controller.distance_between("1", "2") == float("inf")


def test_distance_between_both_drones_missing_returns_infinity(controller):
    assert controller.distance_between("1", "2") == float("inf")


# ---------------------------------------------------------------------------
# PURE: distance_to_waypoint
# ---------------------------------------------------------------------------

def test_distance_to_waypoint_zero_when_already_at_waypoint(controller):
    controller.drones["1"] = {"lat": 10.0, "lon": 20.0, "alt_rel": 5.0}
    waypoint = {"lat": 10.0, "lon": 20.0, "alt": 5.0}
    assert controller.distance_to_waypoint("1", waypoint) == 0.0


def test_distance_to_waypoint_known_leg_length(controller):
    lat0 = 10.0
    dlat_deg = math.degrees(50.0 / atc.EARTH_RADIUS_M)  # ~50m due-north offset
    controller.drones["1"] = {"lat": lat0, "lon": 20.0, "alt_rel": 0.0}
    waypoint = {"lat": lat0 + dlat_deg, "lon": 20.0, "alt": 0.0}
    assert controller.distance_to_waypoint("1", waypoint) == pytest.approx(50.0, abs=0.05)


def test_distance_to_waypoint_missing_position_returns_infinity(controller):
    waypoint = {"lat": 10.0, "lon": 20.0, "alt": 5.0}
    assert controller.distance_to_waypoint("1", waypoint) == float("inf")


# ---------------------------------------------------------------------------
# PURE: should_yield
# ---------------------------------------------------------------------------

def test_should_yield_true_when_id_is_higher(controller):
    assert controller.should_yield("2", "1") is True


def test_should_yield_false_when_id_is_lower(controller):
    assert controller.should_yield("1", "2") is False


def test_should_yield_false_when_ids_are_equal(controller):
    # Edge case: a drone never yields to itself.
    assert controller.should_yield("1", "1") is False


# ---------------------------------------------------------------------------
# STUB: _on_message
# ---------------------------------------------------------------------------

def test_on_message_stores_telemetry_payload(controller):
    msg = FakeMqttMessage(json.dumps({"lat": 1.0, "lon": 2.0}).encode(), topic="uav/1/telemetry")
    controller._on_message(client=None, userdata=None, msg=msg)
    assert controller.drones["1"] == {"lat": 1.0, "lon": 2.0}


def test_on_message_stores_home_payload(controller):
    msg = FakeMqttMessage(json.dumps({"lat": 3.0, "lon": 4.0}).encode(), topic="uav/1/home")
    controller._on_message(client=None, userdata=None, msg=msg)
    assert controller.home_positions["1"] == {"lat": 3.0, "lon": 4.0}


def test_on_message_malformed_payload_does_not_mutate_state(controller):
    controller.drones["1"] = {"lat": 0.0, "lon": 0.0}
    msg = FakeMqttMessage(b"{not valid json", topic="uav/1/telemetry")
    controller._on_message(client=None, userdata=None, msg=msg)
    assert controller.drones["1"] == {"lat": 0.0, "lon": 0.0}
    assert controller.home_positions == {}


def test_on_message_ignores_topic_with_too_few_parts(controller):
    msg = FakeMqttMessage(json.dumps({"lat": 1.0, "lon": 2.0}).encode(), topic="uav/1")
    controller._on_message(client=None, userdata=None, msg=msg)
    assert controller.drones == {}
    assert controller.home_positions == {}


def test_on_message_ignores_unknown_topic_type(controller):
    msg = FakeMqttMessage(json.dumps({"lat": 1.0, "lon": 2.0}).encode(), topic="uav/1/status")
    controller._on_message(client=None, userdata=None, msg=msg)
    assert controller.drones == {}
    assert controller.home_positions == {}


# ---------------------------------------------------------------------------
# STUB: send_command
# ---------------------------------------------------------------------------

def test_send_command_publishes_json_encoded_command_to_drone_topic(controller):
    controller.send_command("1", {"type": "interrupt"})
    assert controller.client.published == [
        ("uav/1/command", json.dumps({"type": "interrupt"}))
    ]


# ---------------------------------------------------------------------------
# STUB: interrupt_drone
# ---------------------------------------------------------------------------

def test_interrupt_drone_sends_interrupt_and_updates_state(controller):
    controller.interrupt_drone("1")
    assert controller.client.published == [
        ("uav/1/command", json.dumps({"type": "interrupt"}))
    ]
    assert "1" in controller.interrupted
    assert controller.mission_status["1"] == "waiting"


def test_interrupt_drone_does_not_resend_when_already_interrupted(controller):
    # Negative test: interrupting an already-interrupted drone must not
    # trigger a second command.
    controller.interrupt_drone("1")
    controller.interrupt_drone("1")
    assert len(controller.client.published) == 1


# ---------------------------------------------------------------------------
# STUB: resume_drone
# ---------------------------------------------------------------------------

def test_resume_drone_sends_goto_and_updates_state(controller):
    controller.interrupted.add("1")
    controller.mission_status["1"] = "waiting"
    waypoint = {"lat": 1.0, "lon": 2.0, "alt": 10.0}
    # Precondition: airborne, so resume_drone takes the goto-only path
    # rather than also arming/taking off.
    controller.drones["1"] = {"lat": 1.0, "lon": 2.0, "alt_rel": 15.0, "armed": True}

    controller.resume_drone("1", waypoint)

    assert controller.client.published == [
        ("uav/1/command", json.dumps({"type": "goto", "lat": 1.0, "lon": 2.0, "alt": 10.0}))
    ]
    assert "1" not in controller.interrupted
    assert controller.mission_status["1"] == "flying"


def test_resume_drone_is_safe_when_drone_was_not_interrupted(controller):
    # Edge case: resuming a drone that was never interrupted (empty
    # collection to discard from) must not raise.
    waypoint = {"lat": 1.0, "lon": 2.0, "alt": 10.0}
    controller.resume_drone("1", waypoint)
    assert "1" not in controller.interrupted
    assert controller.mission_status["1"] == "flying"


# ---------------------------------------------------------------------------
# Sequence: interrupt -> resume ordering
# ---------------------------------------------------------------------------

def test_interrupt_then_resume_sends_commands_in_order_and_updates_status(controller):
    waypoint = {"lat": 1.0, "lon": 2.0, "alt": 10.0}

    controller.interrupt_drone("1")
    assert controller.mission_status["1"] == "waiting"
    assert "1" in controller.interrupted

    # Precondition: airborne, so resume_drone takes the goto-only path
    # rather than also arming/taking off.
    controller.drones["1"] = {"lat": 1.0, "lon": 2.0, "alt_rel": 15.0, "armed": True}
    controller.resume_drone("1", waypoint)
    assert controller.mission_status["1"] == "flying"
    assert "1" not in controller.interrupted

    command_types = [json.loads(payload)["type"] for _, payload in controller.client.published]
    assert command_types == ["interrupt", "goto"]


# ---------------------------------------------------------------------------
# Requested fixes: dict-type guard in _on_message, arm/takeoff in resume_drone
# ---------------------------------------------------------------------------

def test_on_message_rejects_non_dict_payload_does_not_mutate_state(controller):
    msg = FakeMqttMessage(json.dumps([1, 2, 3]).encode(), topic="uav/1/telemetry")
    controller._on_message(client=None, userdata=None, msg=msg)
    assert controller.drones == {}
    assert controller.home_positions == {}


def test_resume_drone_arms_and_takes_off_before_goto_when_grounded(controller):
    controller.drones["1"] = {"armed": False, "alt_rel": 0.0}
    waypoint = {"lat": 1.0, "lon": 2.0, "alt": 10.0}

    controller.resume_drone("1", waypoint)

    command_types = [json.loads(payload)["type"] for _, payload in controller.client.published]
    assert command_types == ["arm", "takeoff", "goto"]
    assert json.loads(controller.client.published[1][1]) == {"type": "takeoff", "alt": 10.0}
    assert json.loads(controller.client.published[2][1]) == {
        "type": "goto", "lat": 1.0, "lon": 2.0, "alt": 10.0
    }
