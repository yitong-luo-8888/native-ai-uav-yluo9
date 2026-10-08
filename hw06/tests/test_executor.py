"""Executor on fakes: leave the route, fly the response, resume at the same waypoint (R7).

Not in the guide's test list -- added so R7's logic is covered without SITL;
the integration tests check the same things against a real vehicle.
"""
import pytest

from planner.executor import Mode
from planner.world_model import distance_m
from tests.conftest import choose, make_event


@pytest.fixture
def flying(harness):
    """Planner started and a few waypoints into the search route."""
    harness.planner.start()
    harness.run(ticks=7)
    assert harness.planner.executors["1"].mode is Mode.SEARCHING
    return harness


def route_index(h):
    return h.planner.world.uav("1").route.current_waypoint_index


def test_hover_completes_and_resumes_same_waypoint(flying):
    """R7: PENDING -> RUNNING -> COMPLETED, then back to the waypoint it was heading to."""
    before = route_index(flying)
    flying.operator.then(choose("hover_stream", duration_s=20.0))
    flying.event(make_event())
    action_id = flying.results()[0]["action_id"]
    assert flying.run_until(lambda: "COMPLETED" in flying.statuses(action_id))
    states = flying.statuses(action_id)
    assert states[0] == "PENDING" and "RUNNING" in states and states[-1] == "COMPLETED"
    assert route_index(flying) == before == flying.planner.executors["1"].last_resume_index
    assert flying.planner.world.uav("1").current_behavior == "search_route"


def test_deliver_releases_item_in_planner(flying):
    """R7: deliver descends to delivery_alt_m, the planner 'releases' the kit, then climbs out."""
    flying.operator.then(choose("deliver"))
    flying.event(make_event(confidence=0.9))
    action_id = flying.results()[0]["action_id"]
    flying.run(ticks=30)
    alts = [c["alt"] for c in flying.uav.commands if c["type"] == "goto"]
    assert 5.0 in alts                                        # descended to delivery_alt_m
    details = [s["detail"] for s in flying.bus.messages("mission/behavior_status") if s["action_id"] == action_id]
    assert "payload released: medical_kit" in details
    assert flying.planner.world.uav("1").payloads == []
    assert flying.statuses(action_id)[-1] == "COMPLETED"
    assert "release" not in {c["type"] for c in flying.uav.commands}   # no invented command


def test_circle_starts_due_north_of_target(flying):
    """R7: circle_stream first flies to radius_m due north of the target, then circles it."""
    flying.operator.then(choose("circle_stream", duration_s=10.0))
    ev = make_event()
    flying.event(ev)
    flying.run(ticks=3)
    circle = next(c for c in flying.uav.commands if c["type"] == "circle")
    entry = flying.uav.commands[flying.uav.commands.index(circle) - 1]
    assert entry["type"] == "goto"
    assert entry["lat"] > ev["lat"] and entry["lon"] == pytest.approx(ev["lon"])
    assert distance_m(entry["lat"], entry["lon"], ev["lat"], ev["lon"]) == pytest.approx(15.0, abs=0.01)
    assert circle["degrees"] == pytest.approx(10.0 * 3.0 / 15.0 * 57.29578, rel=1e-4)


def test_cancel_stops_response_and_resumes(flying):
    """R7: Cancel from the popup interrupts the response and resumes the route."""
    before = route_index(flying)
    flying.operator.then(choose("hover_stream"))
    flying.event(make_event())
    action_id = flying.results()[0]["action_id"]
    flying.run(ticks=3)
    flying.bus.deliver("mission/cancel", {"uav": "1", "action_id": action_id})
    flying.run(ticks=1)
    assert flying.statuses(action_id)[-1] == "CANCELLED"
    assert "interrupt" in flying.uav.command_types()
    assert route_index(flying) == before
    assert not flying.planner.executors["1"].busy


def test_cancel_for_other_action_is_ignored(flying):
    """R7: a stale cancel (different action_id) doesn't stop the current response."""
    flying.operator.then(choose("hover_stream"))
    flying.event(make_event())
    flying.bus.deliver("mission/cancel", {"uav": "1", "action_id": "not-this-one"})
    flying.run(ticks=2)
    assert flying.planner.executors["1"].busy


def test_busy_uav_rejects_second_response(flying):
    """R6/R7: one response at a time per UAV (multi-UAV response is out of scope)."""
    flying.operator.then(choose("hover_stream")).then(choose("hover_stream"))
    first = make_event()
    flying.event(first)
    flying.event(make_event(lat=first["lat"] + 0.002))       # ~220 m away: a different person
    second = flying.results()[1]
    assert second["approved"] is False and any("already executing" in r for r in second["reasons"])
