"""HW7 R7: AI clue proposals on mission/clues go through the same validator and executor."""
import uuid

from planner.validator import Validator


def assessment(action, lat=41.69915, lon=-86.23745, radius=None, centre=True, aid=None):
    converge = action == "converge_search"
    return {"mission_id": "lost-boy-north-gate", "assessment_id": aid or uuid.uuid4().hex[:8],
            "candidate": {"candidate_id": "e01", "lat": lat, "lon": lon, "cv_label": "unknown",
                          "cv_confidence": 1.0, "source_uav": "1"},
            "descriptions": [{"object_type": "navy baseball cap"}],
            "relevance": {"relevance": "high" if converge else "medium"},
            "decision": {"action": action, "search_radius_m": radius},
            "search_center": {"lat": lat, "lon": lon} if converge and centre else None, "calls": []}


def results(h):
    return h.bus.messages("mission/action_result")


def fly(h, ticks=20):
    """Start the planner (takeoff, route) and let the executor run the response."""
    h.planner.start()
    for _ in range(ticks):
        h.planner.tick()
        h.clock.sleep(1.0)


def test_converge_becomes_circle_around_search_center_with_clamped_radius(harness, config):
    h = harness
    h.bus.deliver("mission/clues", assessment("converge_search", radius=80.0))
    [r] = results(h)
    assert r["approved"] and r["type"] == "circle_stream" and r["decided_by"] == "ai"
    assert any("clamped" in n for n in r["notes"])
    fly(h)
    circle = next(c for c in h.uav.commands if c["type"] == "circle")
    assert (circle["lat"], circle["lon"]) == (41.69915, -86.23745)
    assert circle["radius"] == config.planner.max_circle_radius_m


def test_inspect_closer_becomes_hover_over_the_clue(harness, config):
    h = harness
    h.bus.deliver("mission/clues", assessment("inspect_closer"))
    [r] = results(h)
    assert r["approved"] and r["type"] == "hover_stream" and r["proposal"] == "inspect_closer"
    fly(h)
    gotos = [(c["lat"], c["lon"]) for c in h.uav.commands if c["type"] == "goto"]
    assert (41.69915, -86.23745) in gotos      # standoff 0: directly over the clue


def test_ignore_and_log_only_fly_nothing(harness, config):
    h = harness
    for action in ("ignore", "log_only"):
        h.bus.deliver("mission/clues", assessment(action))
    assert results(h) == []
    assert h.planner.world.uav("1").active_action_id is None


def test_proposal_rejected_when_uav_busy_and_duplicates_ignored(harness, config):
    h = harness
    first = assessment("converge_search", radius=30.0, aid="a1")
    h.bus.deliver("mission/clues", first)
    h.bus.deliver("mission/clues", first)                                  # QoS 1 redelivery
    h.bus.deliver("mission/clues", assessment("inspect_closer", aid="a2"))
    approved, rejected = results(h)
    assert approved["approved"] and approved["assessment_id"] == "a1"
    assert not rejected["approved"] and any("already executing" in r for r in rejected["reasons"])


def test_converge_without_centre_is_rejected(harness, config):
    h = harness
    h.bus.deliver("mission/clues", assessment("converge_search", radius=50.0, centre=False))
    [r] = results(h)
    assert not r["approved"] and any("target location" in x for x in r["reasons"])


def test_validator_clamps_small_circle_radius_up(world, config):
    action = {"type": "circle_stream", "uav": "1", "target": {"lat": 41.6992, "lon": -86.2370},
              "parameters": {"radius_m": 2.0, "speed_mps": 3.0, "duration_s": 60.0}}
    verdict = Validator(world).validate(action, confidence=1.0)
    assert verdict.approved
    assert verdict.action["parameters"]["radius_m"] == config.planner.min_circle_radius_m
    assert verdict.notes


def test_same_spot_repeat_rejected_but_escalation_allowed(harness, config):
    h = harness
    h.bus.deliver("mission/clues", assessment("inspect_closer", aid="h1"))
    fly(h, ticks=120)                                                       # hover completes
    assert h.planner.world.uav("1").active_action_id is None
    h.bus.deliver("mission/clues", assessment("inspect_closer", aid="h2"))  # detector re-reported the clue
    h.bus.deliver("mission/clues", assessment("converge_search", radius=30.0, aid="c1"))
    first, repeat, escalation = results(h)
    assert first["approved"]
    assert not repeat["approved"] and any("already approved" in r for r in repeat["reasons"])
    assert escalation["approved"] and escalation["type"] == "circle_stream"
