"""Unit tests for lab/scripts/test_flight.py.

PURE functions (offset_to_lla, horizontal_distance_m) are exercised directly.
STUB functions (on_message, wait_for, execute_command) are exercised by
injecting a fake MQTT message, a RecordingClient in place of the real
paho client, and/or a FakeClock in place of the real wall clock -- see
conftest.py. LIVE functions (on_connect, main) are not covered here; they
require a real broker/fleet and are covered by
generated-tests/integration/test_test_flight_live.py instead.
"""
import json
import math

import pytest

import lab.scripts.test_flight as test_flight


# ---------------------------------------------------------------------------
# PURE: offset_to_lla
# ---------------------------------------------------------------------------

def test_offset_to_lla_zero_offset_returns_origin():
    lat, lon = test_flight.offset_to_lla(37.0, -122.0, 0.0, 0.0)
    assert lat == pytest.approx(37.0)
    assert lon == pytest.approx(-122.0)


def test_offset_to_lla_north_offset_changes_latitude_only():
    origin_lat, origin_lon = 37.0, -122.0
    lat, lon = test_flight.offset_to_lla(origin_lat, origin_lon, 0.0, 100.0)
    expected_dlat = math.degrees(100.0 / test_flight.EARTH_RADIUS_M)
    assert lat == pytest.approx(origin_lat + expected_dlat)
    assert lon == pytest.approx(origin_lon)


def test_offset_to_lla_east_offset_changes_longitude_only():
    origin_lat, origin_lon = 37.0, -122.0
    lat, lon = test_flight.offset_to_lla(origin_lat, origin_lon, 100.0, 0.0)
    lat0_rad = math.radians(origin_lat)
    expected_dlon = math.degrees(100.0 / (test_flight.EARTH_RADIUS_M * math.cos(lat0_rad)))
    assert lat == pytest.approx(origin_lat)
    assert lon == pytest.approx(origin_lon + expected_dlon)


def test_offset_to_lla_round_trips_through_horizontal_distance():
    origin_lat, origin_lon = 47.6, -122.3
    lat, lon = test_flight.offset_to_lla(origin_lat, origin_lon, 15.0, 15.0)
    dist = test_flight.horizontal_distance_m(origin_lat, origin_lon, lat, lon)
    assert dist == pytest.approx(math.hypot(15.0, 15.0), abs=0.05)


# ---------------------------------------------------------------------------
# PURE: horizontal_distance_m
# ---------------------------------------------------------------------------

def test_horizontal_distance_m_identical_positions_is_zero():
    assert test_flight.horizontal_distance_m(37.0, -122.0, 37.0, -122.0) == 0.0


def test_horizontal_distance_m_known_north_south_leg():
    origin_lat, origin_lon = 0.0, 0.0
    lat, lon = test_flight.offset_to_lla(origin_lat, origin_lon, 0.0, 111.0)
    dist = test_flight.horizontal_distance_m(origin_lat, origin_lon, lat, lon)
    assert dist == pytest.approx(111.0, abs=0.01)


def test_horizontal_distance_m_is_symmetric():
    a = (37.0, -122.0)
    b = (37.001, -122.001)
    assert test_flight.horizontal_distance_m(*a, *b) == pytest.approx(
        test_flight.horizontal_distance_m(*b, *a)
    )


def test_horizontal_distance_m_within_arrival_tolerance_for_small_offset():
    origin_lat, origin_lon = 47.6, -122.3
    lat, lon = test_flight.offset_to_lla(origin_lat, origin_lon, 1.0, 1.0)
    dist = test_flight.horizontal_distance_m(origin_lat, origin_lon, lat, lon)
    assert dist < test_flight.ARRIVAL_TOLERANCE_M


# ---------------------------------------------------------------------------
# STUB: on_message
# ---------------------------------------------------------------------------

class _FakeMsg:
    def __init__(self, topic, payload_bytes):
        self.topic = topic
        self.payload = payload_bytes


def test_on_message_stores_home_payload():
    msg = _FakeMsg(test_flight.HOME_TOPIC, json.dumps({"lat": 1.0, "lon": 2.0}).encode())
    test_flight.on_message(client=None, userdata=None, msg=msg)
    assert test_flight._latest["home"] == {"lat": 1.0, "lon": 2.0}


def test_on_message_stores_telemetry_payload():
    payload = {"armed": True, "alt_rel": 5.0}
    msg = _FakeMsg(test_flight.TELEMETRY_TOPIC, json.dumps(payload).encode())
    test_flight.on_message(client=None, userdata=None, msg=msg)
    assert test_flight._latest["telemetry"] == payload


def test_on_message_ignores_unrelated_topic():
    msg = _FakeMsg("uav/1/unrelated", json.dumps({"foo": "bar"}).encode())
    test_flight.on_message(client=None, userdata=None, msg=msg)
    assert test_flight._latest == {}


def test_on_message_malformed_payload_does_not_mutate_state():
    test_flight._latest["telemetry"] = {"armed": True}
    msg = _FakeMsg(test_flight.TELEMETRY_TOPIC, b"{not valid json")
    test_flight.on_message(client=None, userdata=None, msg=msg)
    assert test_flight._latest["telemetry"] == {"armed": True}
    assert "home" not in test_flight._latest


def test_on_message_accepts_telemetry_missing_expected_fields():
    msg = _FakeMsg(test_flight.TELEMETRY_TOPIC, json.dumps({}).encode())
    test_flight.on_message(client=None, userdata=None, msg=msg)
    assert test_flight._latest["telemetry"] == {}


# ---------------------------------------------------------------------------
# STUB: wait_for
# ---------------------------------------------------------------------------

def test_wait_for_returns_immediately_when_value_already_present(fake_clock):
    test_flight._latest["home"] = {"lat": 1.0, "lon": 2.0}
    result = test_flight.wait_for("home", lambda h: True, 30, "home")
    assert result == {"lat": 1.0, "lon": 2.0}
    assert fake_clock.sleep_calls == 0


def test_wait_for_polls_until_predicate_becomes_true(fake_clock):
    fake_clock.after_sleep(
        2, lambda: test_flight._latest.__setitem__("home", {"lat": 9.0, "lon": 9.0})
    )
    result = test_flight.wait_for("home", lambda h: True, 30, "home")
    assert result == {"lat": 9.0, "lon": 9.0}
    assert fake_clock.sleep_calls == 2


def test_wait_for_ignores_value_until_predicate_matches(fake_clock):
    test_flight._latest["home"] = {"lat": 0.0, "lon": 0.0, "ready": False}
    fake_clock.after_sleep(
        1, lambda: test_flight._latest.__setitem__("home", {"lat": 0.0, "lon": 0.0, "ready": True})
    )
    result = test_flight.wait_for("home", lambda h: h.get("ready"), 30, "home ready")
    assert result["ready"] is True


def test_wait_for_timeout_exits_with_status_1(fake_clock):
    with pytest.raises(SystemExit) as exc_info:
        test_flight.wait_for("home", lambda h: True, 5, "home never arrives")
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# STUB: execute_command
# ---------------------------------------------------------------------------

def test_execute_command_publishes_before_checking_predicate(fake_clock, recording_client):
    test_flight._latest["telemetry"] = {"armed": True}
    command = {"type": "takeoff", "alt": 20.0}
    result = test_flight.execute_command(
        "telemetry", lambda t: t.get("armed"), 30, "armed",
        command=command, client=recording_client,
    )
    assert result == {"armed": True}
    assert recording_client.published == [(test_flight.COMMAND_TOPIC, json.dumps(command))]


def test_execute_command_resends_only_after_resend_interval_elapses(fake_clock, recording_client):
    command = {"type": "takeoff", "alt": 20.0}

    def set_armed():
        test_flight._latest["telemetry"] = {"armed": True}

    # Each poll sleeps 0.5s; RESEND_INTERVAL_S is 8s, so the resend is due
    # right after the 16th sleep (0.5 * 16 == 8.0). Arm exactly then, so the
    # command is republished once before the predicate is satisfied.
    fake_clock.after_sleep(16, set_armed)

    test_flight.execute_command(
        "telemetry", lambda t: t.get("armed"), 60, "armed",
        command=command, client=recording_client,
    )

    assert len(recording_client.published) == 2
    assert all(
        payload == (test_flight.COMMAND_TOPIC, json.dumps(command))
        for payload in recording_client.published
    )


def test_execute_command_does_not_resend_before_interval_elapses(fake_clock, recording_client):
    command = {"type": "takeoff", "alt": 20.0}

    def set_armed():
        test_flight._latest["telemetry"] = {"armed": True}

    # Only 5 polls (2.5s) elapse -- well under the 8s resend interval.
    fake_clock.after_sleep(5, set_armed)

    test_flight.execute_command(
        "telemetry", lambda t: t.get("armed"), 60, "armed",
        command=command, client=recording_client,
    )

    assert len(recording_client.published) == 1


def test_execute_command_timeout_exits_with_status_1(fake_clock, recording_client):
    with pytest.raises(SystemExit) as exc_info:
        test_flight.execute_command(
            "telemetry", lambda t: t.get("armed"), 5, "armed",
            command={"type": "takeoff"}, client=recording_client,
        )
    assert exc_info.value.code == 1
    # The command must still have been sent at least once before giving up.
    assert len(recording_client.published) >= 1


def test_execute_command_goto_predicate_accepts_within_2m_tolerance(fake_clock, recording_client):
    target_lat, target_lon = 47.6, -122.3
    near_lat, near_lon = test_flight.offset_to_lla(target_lat, target_lon, 1.5, 0.0)
    test_flight._latest["telemetry"] = {"lat": near_lat, "lon": near_lon}

    def goto_predicate(t):
        return (
            t.get("lat") is not None
            and test_flight.horizontal_distance_m(t["lat"], t["lon"], target_lat, target_lon)
            < test_flight.ARRIVAL_TOLERANCE_M
        )

    result = test_flight.execute_command(
        "telemetry", goto_predicate, 30, "arrival",
        command={"type": "goto", "lat": target_lat, "lon": target_lon},
        client=recording_client,
    )
    assert result["lat"] == near_lat


def test_execute_command_goto_predicate_rejects_outside_2m_tolerance(fake_clock, recording_client):
    target_lat, target_lon = 47.6, -122.3
    far_lat, far_lon = test_flight.offset_to_lla(target_lat, target_lon, 3.0, 0.0)
    test_flight._latest["telemetry"] = {"lat": far_lat, "lon": far_lon}

    def goto_predicate(t):
        return (
            t.get("lat") is not None
            and test_flight.horizontal_distance_m(t["lat"], t["lon"], target_lat, target_lon)
            < test_flight.ARRIVAL_TOLERANCE_M
        )

    with pytest.raises(SystemExit) as exc_info:
        test_flight.execute_command(
            "telemetry", goto_predicate, 5, "arrival",
            command={"type": "goto", "lat": target_lat, "lon": target_lon},
            client=recording_client,
        )
    assert exc_info.value.code == 1


def test_mission_sequence_sends_takeoff_before_goto_waypoints_in_order(fake_clock, recording_client):
    """Reproduces main()'s command sequence (armed+takeoff, then each square
    waypoint's goto, in order) by driving the same STUB functions main() uses,
    without invoking main() itself (main() is LIVE -- it owns a real
    mqtt.Client and a real broker connection)."""
    origin_lat, origin_lon = 47.6, -122.3
    waypoints = [
        test_flight.offset_to_lla(origin_lat, origin_lon, 0, test_flight.LEG_M),
        test_flight.offset_to_lla(origin_lat, origin_lon, test_flight.LEG_M, test_flight.LEG_M),
        test_flight.offset_to_lla(origin_lat, origin_lon, test_flight.LEG_M, 0),
        (origin_lat, origin_lon),
    ]

    test_flight._latest["telemetry"] = {
        "armed": True,
        "alt_rel": test_flight.TAKEOFF_ALT_M,
        "lat": origin_lat,
        "lon": origin_lon,
    }

    test_flight.execute_command(
        "telemetry",
        lambda t: t.get("armed") and (t.get("alt_rel") or 0) > test_flight.TAKEOFF_ALT_M * 0.9,
        60, "takeoff",
        command={"type": "takeoff", "alt": test_flight.TAKEOFF_ALT_M},
        client=recording_client,
    )

    for lat, lon in waypoints:
        test_flight._latest["telemetry"]["lat"] = lat
        test_flight._latest["telemetry"]["lon"] = lon
        test_flight.execute_command(
            "telemetry",
            lambda t, lat=lat, lon=lon: (
                t.get("lat") is not None
                and test_flight.horizontal_distance_m(t["lat"], t["lon"], lat, lon)
                < test_flight.ARRIVAL_TOLERANCE_M
            ),
            30, "arrival",
            command={"type": "goto", "lat": lat, "lon": lon, "alt": test_flight.TAKEOFF_ALT_M},
            client=recording_client,
        )

    command_types = [json.loads(payload)["type"] for _, payload in recording_client.published]
    assert command_types == ["takeoff", "goto", "goto", "goto", "goto"]
