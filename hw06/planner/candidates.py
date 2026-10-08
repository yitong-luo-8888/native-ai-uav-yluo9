"""candidates.py -- the response menu for one person (R2, R4).

Policy only: which responses to offer, to which UAVs, with which default
parameters. Whether a chosen response can actually be flown is the
validator's job, not this module's -- the menu may offer something the
validator later rejects (e.g. deliver after the kit is gone), and that is the
point: the operator chooses, the software checks.

R2 low-confidence policy: below PlannerSettings.deliver_min_confidence
(0.35) a detection is treated as unverified, and only the verify-only
responses (hover_stream, circle_stream) are offered. design.md has the
justification (detector cutoff 0.25, class-frame hit at 0.26, false
positive at 0.31).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .config import MissionConfig
from .world_model import WorldModel

LABELS = {
    "hover_stream": "Hover && stream",   # && renders as a literal & on a Qt button
    "circle_stream": "Circle && stream",
    "deliver": "Deliver item",
}


@dataclass
class Candidate:
    type: str
    label: str
    description: str
    eligible_uavs: list[str]
    default_uav: str | None
    parameters: dict
    options: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def is_low_confidence(confidence: float, config: MissionConfig) -> bool:
    return confidence < config.planner.deliver_min_confidence


def default_parameters(response_type: str, config: MissionConfig) -> dict:
    d = config.defaults
    if response_type == "hover_stream":
        return {"standoff_m": d.hover_standoff_m, "duration_s": d.stream_duration_s}
    if response_type == "circle_stream":
        return {"radius_m": d.circle_radius_m, "speed_mps": d.circle_speed_mps,
                "duration_s": d.stream_duration_s}
    if response_type == "deliver":
        items = config.deliverable_items()
        return {"item": items[0] if items else "", "delivery_alt_m": d.delivery_alt_m,
                "dwell_s": d.delivery_dwell_s}
    raise ValueError(f"unknown response type {response_type!r}")


def _pick_default(eligible: list[str], world: WorldModel) -> str | None:
    """Prefer an idle UAV, then the one with the most battery."""
    def key(uav: str):
        s = world.uav(uav)
        return (s.active_action_id is not None, -(s.battery_level or 0.0))
    return min(eligible, key=key) if eligible else None


def build_candidates(confidence: float, world: WorldModel) -> list[Candidate]:
    config = world.config
    owned = world.uav_ids()
    cost = config.battery.cost
    low = is_low_confidence(confidence, config)
    threshold = config.planner.deliver_min_confidence
    verify_note = (f" Confidence {confidence:.2f} is below {threshold:.2f}: verify before committing "
                   f"a payload (delivery not offered)." if low else "")

    menu = [
        Candidate("hover_stream", LABELS["hover_stream"],
                  f"Fly to standoff_m from the person and hold there for duration_s, streaming video. "
                  f"Battery cost {cost.get('hover_stream', 0):.0%}.{verify_note}",
                  owned, _pick_default(owned, world), default_parameters("hover_stream", config)),
        Candidate("circle_stream", LABELS["circle_stream"],
                  f"Orbit the person at radius_m for duration_s (entering due north of them), "
                  f"streaming video. Battery cost {cost.get('circle_stream', 0):.0%}.{verify_note}",
                  owned, _pick_default(owned, world), default_parameters("circle_stream", config)),
    ]
    if not low:
        items = config.deliverable_items()
        carriers = [u for u in owned if any(i in world.uav(u).payloads for i in items)]
        # If nobody carries anything any more the option still appears (on
        # every owned UAV) so the operator can see -- via the validator's
        # rejection -- why it can't be done, rather than it silently vanishing.
        eligible = carriers or owned
        note = "" if carriers else " No UAV currently carries a deliverable item."
        menu.append(Candidate(
            "deliver", LABELS["deliver"],
            f"Fly to the person, descend to delivery_alt_m, wait dwell_s, release the item, "
            f"climb back out. Battery cost {cost.get('deliver', 0):.0%}.{note}",
            eligible, _pick_default(eligible, world), default_parameters("deliver", config),
            options={"item": items}))
    return menu
