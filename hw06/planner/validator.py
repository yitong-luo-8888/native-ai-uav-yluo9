"""validator.py -- the stage every chosen action passes before anything flies (R6).

It doesn't matter who chose the action (operator, AI, a test): the same
checks run, and the verdict is what gets reported on mission/action_result.
Reasons are complete sentences because the popup shows them verbatim
(joined with spaces) and re-sends them as previous_rejection.

Checks, in order:
  * known response type, owned UAV, numeric target and parameters
  * deliver: the item is on board that UAV; detection confidence is at or
    above the R2 threshold (an AI could pick deliver from a menu it wasn't
    offered, so the policy is enforced here too, not only in the menu)
  * battery: battery_level >= reserve + response cost (inclusive boundary)
  * the UAV isn't already executing another response
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import RESPONSE_TYPES
from .world_model import WorldModel

# Float noise must not turn "exactly reserve + cost" into a rejection.
BATTERY_EPSILON = 1e-9

# (name, must be > 0?) per response type; everything is coerced to float
# because the popup returns spin boxes as floats and line edits as strings.
NUMERIC_PARAMETERS: dict[str, list[tuple[str, bool]]] = {
    "hover_stream": [("standoff_m", False), ("duration_s", True)],
    "circle_stream": [("radius_m", True), ("speed_mps", True), ("duration_s", True)],
    "deliver": [("delivery_alt_m", True), ("dwell_s", False)],
}


@dataclass
class Verdict:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    action: dict | None = None   # normalised copy of the action (typed parameters)


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class Validator:
    def __init__(self, world: WorldModel):
        self.world = world
        self.config = world.config

    def validate(self, action: dict, confidence: float) -> Verdict:
        reasons: list[str] = []
        rtype = action.get("type")
        uav = str(action.get("uav") or "")
        target = action.get("target") or {}
        raw_params = dict(action.get("parameters") or {})

        if rtype not in RESPONSE_TYPES:
            return Verdict(False, [f"Unknown response type {rtype!r}; expected one of {', '.join(RESPONSE_TYPES)}."])
        if not self.world.has_uav(uav):
            owned = ", ".join(self.world.uav_ids()) or "none"
            return Verdict(False, [f"UAV {uav or '(none)'} is not a UAV this planner flies (owned: {owned})."])

        lat, lon = as_float(target.get("lat")), as_float(target.get("lon"))
        if lat is None or lon is None:
            reasons.append("The target location is missing or not numeric.")

        params: dict[str, Any] = dict(raw_params)
        for name, positive in NUMERIC_PARAMETERS[rtype]:
            value = as_float(raw_params.get(name))
            if value is None:
                reasons.append(f"Parameter {name} is missing or not a number.")
            elif value < 0 or (positive and value == 0):
                reasons.append(f"Parameter {name} must be {'greater than' if positive else 'at least'} 0 (got {value:g}).")
            else:
                params[name] = value

        with self.world.lock:
            state = self.world.uav(uav)
            payloads = list(state.payloads)
            battery = state.battery_level
            busy_with = (state.current_behavior, state.active_action_id) if state.active_action_id else None

        if rtype == "deliver":
            item = str(raw_params.get("item") or "").strip()
            params["item"] = item
            if not item:
                reasons.append("No item chosen to deliver.")
            elif item not in payloads:
                carried = ", ".join(payloads) if payloads else "none"
                reasons.append(f"UAV {uav} is not carrying {item} (payload on board: {carried}).")
            threshold = self.config.planner.deliver_min_confidence
            if confidence < threshold:
                reasons.append(f"Detection confidence {confidence:.2f} is below {threshold:.2f}; "
                               f"verify with hover_stream or circle_stream before delivering.")

        reserve = self.config.battery.reserve
        cost = self.config.battery.cost.get(rtype, 0.0)
        if battery is None:
            reasons.append(f"UAV {uav} battery level is unknown, so the {reserve:.0%} reserve "
                           f"plus {cost:.0%} {rtype} cost cannot be confirmed.")
        elif battery + BATTERY_EPSILON < reserve + cost:
            reasons.append(f"UAV {uav} battery {battery:.0%} is below the {reserve:.0%} reserve "
                           f"plus {cost:.0%} {rtype} cost ({reserve + cost:.0%} needed).")

        if busy_with is not None:
            reasons.append(f"UAV {uav} is already executing {busy_with[0]} (action {busy_with[1]}); "
                           f"cancel it first or choose another UAV.")

        normalised = {"type": rtype, "uav": uav, "target": {"lat": lat, "lon": lon}, "parameters": params}
        return Verdict(not reasons, reasons, normalised)
