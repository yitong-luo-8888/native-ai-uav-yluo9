"""Validator: every action is checked before anything flies (R6)."""
import pytest

from planner.validator import Validator


def action(rtype="hover_stream", uav="1", **params):
    defaults = {"hover_stream": {"standoff_m": 10.0, "duration_s": 60.0},
                "circle_stream": {"radius_m": 15.0, "speed_mps": 3.0, "duration_s": 60.0},
                "deliver": {"item": "medical_kit", "delivery_alt_m": 5.0, "dwell_s": 5.0}}[rtype]
    return {"type": rtype, "uav": uav, "target": {"lat": 41.6992, "lon": -86.2370},
            "parameters": {**defaults, **params}}


def test_valid_hover_approved(world):
    """R6: a feasible hover_stream is approved with no reasons."""
    verdict = Validator(world).validate(action("hover_stream"), confidence=0.82)
    assert verdict.approved is True
    assert verdict.reasons == []


def test_deliver_without_kit_rejected(world):
    """R6: deliver needs the item on board."""
    world.remove_payload("1", "medical_kit")
    verdict = Validator(world).validate(action("deliver"), confidence=0.82)
    assert verdict.approved is False
    assert any("medical_kit" in r or "payload" in r for r in verdict.reasons)


def test_battery_reserve_rejected(world, config):
    """R6: rejected when the response cost would dip below the battery reserve."""
    cost = config.battery.cost["deliver"]
    world.update_telemetry("1", {"battery_level": config.battery.reserve + cost - 0.01})
    verdict = Validator(world).validate(action("deliver"), confidence=0.82)
    assert verdict.approved is False
    assert any("battery" in r.lower() for r in verdict.reasons)


@pytest.mark.parametrize("rtype", ["hover_stream", "circle_stream", "deliver"])
def test_battery_boundary_approved(world, config, rtype):
    """R6: battery exactly equal to reserve + cost is approved (inclusive boundary)."""
    world.update_telemetry("1", {"battery_level": config.battery.reserve + config.battery.cost[rtype]})
    verdict = Validator(world).validate(action(rtype), confidence=0.82)
    assert verdict.approved is True, verdict.reasons


def test_rejection_reasons_are_nonempty_strings(world):
    """R6: every rejection reason is a non-empty string (the popup shows them verbatim)."""
    world.remove_payload("1", "medical_kit")
    world.update_telemetry("1", {"battery_level": 0.1})
    bad = action("deliver", delivery_alt_m="low")
    verdict = Validator(world).validate(bad, confidence=0.2)
    assert verdict.approved is False
    assert len(verdict.reasons) >= 3
    assert all(isinstance(r, str) and r.strip() for r in verdict.reasons)


def test_unknown_battery_rejected(world):
    """R6: no battery reading yet means the reserve can't be confirmed."""
    world.update_telemetry("1", {"battery_level": None})
    verdict = Validator(world).validate(action("hover_stream"), confidence=0.82)
    assert verdict.approved is False and any("battery" in r for r in verdict.reasons)


def test_low_confidence_deliver_rejected_even_if_chosen(world):
    """R2/R6: deliver chosen on a 0.31 detection (e.g. by an AI) is rejected by the validator too."""
    verdict = Validator(world).validate(action("deliver"), confidence=0.31)
    assert verdict.approved is False
    assert any("confidence" in r for r in verdict.reasons)


def test_popup_string_parameters_are_coerced(world):
    """R6: line-edit values arrive as strings; numeric ones are coerced, garbage is rejected."""
    ok = Validator(world).validate(action("hover_stream", standoff_m="12.5"), confidence=0.82)
    assert ok.approved and ok.action["parameters"]["standoff_m"] == 12.5
    bad = Validator(world).validate(action("circle_stream", radius_m="0"), confidence=0.82)
    assert not bad.approved and any("radius_m" in r for r in bad.reasons)
