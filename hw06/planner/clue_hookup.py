"""clue_hookup.py -- HW7 R7: AI clue proposals (mission/clues) -> planner actions.

The HW7 pipeline (hw07/clues, run by lab/lesson7/detector.py) publishes one
ClueAssessment per object on mission/clues. Each one is a PROPOSAL. This
module turns it into one of the planner's own actions, marked as decided by
the AI, and sends it through the same Validator and Executor as an operator's
choice:

    inspect_closer   -> hover_stream over the clue (standoff 0)
    converge_search  -> circle_stream around search_center, radius_m =
                        search_radius_m (the validator clamps it)
    ignore, log_only -> no flight; logged

Every verdict goes out on mission/action_result, as for the operator, with
decided_by "ai" and the assessment_id it came from. The model never chooses
coordinates: the hover target is the candidate's position and the circle
centre is search_center, which the pipeline's code set from the candidate.

Same-spot rule: the detector re-reports a clue while a UAV hovers right over
it, so a proposal for a response TYPE already approved within SAME_SPOT_M of
the same spot is rejected with that reason (reported like any verdict). An
escalation is still allowed: a converge after the hover at the same spot.
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import TYPE_CHECKING

from . import mqtt_bus
from .candidates import default_parameters
from .world_model import distance_m

if TYPE_CHECKING:
    from .main import Planner

log = logging.getLogger("planner.clues")

CLUES = "mission/clues"
NO_FLIGHT = ("ignore", "log_only")
SAME_SPOT_M = 5.0   # the detector's own de-duplication radius


def new_id() -> str:
    return uuid.uuid4().hex[:8]


class ClueHookup:
    def __init__(self, planner: "Planner"):
        self.planner = planner
        self._seen: set[str] = set()
        self._approved: list[tuple[float, float, str, str]] = []   # (lat, lon, type, action_id)
        self._lock = threading.Lock()
        self.log: list[dict] = []        # every proposal and what became of it (tests, debugging)
        planner.bus.subscribe(CLUES, lambda _t, p: self.handle(p), qos=1)

    def handle(self, assessment: dict) -> dict | None:
        """Returns the action_result payload published, or None (duplicate, no flight, unusable)."""
        aid = str(assessment.get("assessment_id") or "")
        with self._lock:
            if aid and aid in self._seen:
                log.debug("Duplicate delivery of assessment %s ignored", aid)
                return None
            self._seen.add(aid)
        decision = assessment.get("decision") or {}
        proposal = decision.get("action")
        candidate = assessment.get("candidate") or {}
        what = self._describe(assessment)
        if proposal in NO_FLIGHT:
            log.info("AI clue %s: %s -> %s; no flight (%s)", aid, what,
                     proposal, (assessment.get("relevance") or {}).get("relevance"))
            self.log.append({"assessment_id": aid, "proposal": proposal, "outcome": "logged"})
            return None
        action = self._to_action(proposal, decision, candidate, assessment)
        if action is None:
            log.warning("AI clue %s: unusable proposal %r (%s); nothing flies", aid, proposal, what)
            self.log.append({"assessment_id": aid, "proposal": proposal, "outcome": "unusable"})
            return None
        result = self._validate_and_execute(aid, action)
        self.log.append({"assessment_id": aid, "proposal": proposal, "outcome": result})
        return result

    # -- proposal -> planner action ------------------------------------------
    def _to_action(self, proposal: str | None, decision: dict, candidate: dict, assessment: dict) -> dict | None:
        config = self.planner.config
        if proposal == "inspect_closer":
            target = {"lat": candidate.get("lat"), "lon": candidate.get("lon")}
            params = default_parameters("hover_stream", config)
            params["standoff_m"] = 0.0               # directly over the clue
            rtype = "hover_stream"
        elif proposal == "converge_search":
            centre = assessment.get("search_center") or {}
            target = {"lat": centre.get("lat"), "lon": centre.get("lon")}
            params = default_parameters("circle_stream", config)
            params["radius_m"] = decision.get("search_radius_m")   # the validator checks and clamps it
            rtype = "circle_stream"
        else:
            return None
        return {"type": rtype, "uav": self._pick_uav(candidate), "target": target, "parameters": params,
                "decided_by": "ai", "assessment_id": assessment.get("assessment_id"),
                "proposal": proposal, "object": self._describe(assessment),
                "relevance": (assessment.get("relevance") or {}).get("relevance")}

    def _pick_uav(self, candidate: dict) -> str:
        """The UAV that saw it, if this planner flies it and it's idle; else the
        idle UAV with the most battery; else (all busy) the first one -- the
        validator then rejects it with the reason."""
        world = self.planner.world
        source = str(candidate.get("source_uav") or "")
        if world.has_uav(source) and world.uav(source).active_action_id is None:
            return source
        owned = world.uav_ids()
        return min(owned, key=lambda u: (world.uav(u).active_action_id is not None,
                                         -(world.uav(u).battery_level or 0.0)))

    @staticmethod
    def _describe(assessment: dict) -> str:
        descriptions = assessment.get("descriptions") or [{}]
        return str(descriptions[-1].get("object_type", "?"))

    # -- the same validator and executor as the operator's choices ------------
    def _validate_and_execute(self, aid: str, action: dict) -> dict:
        p = self.planner
        p.refresh_telemetry()
        with p._approve_lock:
            # confidence only gates deliver, which the AI can never propose
            verdict = p.validator.validate(action, confidence=1.0)
            reasons = verdict.reasons + self._same_spot(action)
            approved = not reasons
            normalised = verdict.action or action
            action_id = new_id() if approved else None
            result = {"request_id": f"clue-{aid}", "approved": approved, "action_id": action_id,
                      "type": normalised.get("type"), "uav": normalised.get("uav"), "reasons": reasons,
                      "notes": verdict.notes, "decided_by": "ai", "assessment_id": aid,
                      "proposal": action["proposal"], "object": action["object"]}
            p.bus.publish(mqtt_bus.ACTION_RESULT, result)
            if not approved:
                log.info("Rejected AI %s (%s) for clue %s: %s", normalised.get("type"), action["proposal"], aid,
                         " ".join(reasons))
                return result
            target = normalised["target"]
            self._approved.append((target["lat"], target["lon"], normalised["type"], action_id))
            normalised.update({k: action[k] for k in ("decided_by", "assessment_id", "proposal")})
            p.executors[normalised["uav"]].submit(action_id, normalised)
            log.info("Approved AI %s on UAV %s for clue %s (%s) as %s%s", normalised["type"], normalised["uav"],
                     aid, action["object"], action_id, f" -- {' '.join(verdict.notes)}" if verdict.notes else "")
            return result

    def _same_spot(self, action: dict) -> list[str]:
        lat, lon = action["target"].get("lat"), action["target"].get("lon")
        if lat is None or lon is None:
            return []
        for a_lat, a_lon, a_type, a_id in self._approved:
            if a_type == action["type"] and distance_m(lat, lon, a_lat, a_lon) <= SAME_SPOT_M:
                return [f"A {a_type} within {SAME_SPOT_M:g} m of this spot was already approved "
                        f"(action {a_id}); not flying it again."]
        return []
