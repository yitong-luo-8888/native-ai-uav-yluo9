"""pipeline.py -- ClueAnalyzer: runs Stages 2-4 on one Candidate.

The given tools (evaluate.py, detector.py) construct it and call analyze():

    analyzer = ClueAnalyzer(backend, mission, closer_look=fn, on_event=print_fn)
    assessment = analyzer.analyze(candidate)        # -> contract.ClueAssessment

Flow (design.md, Section 2):

    describe ── needs_closer_look? ──► closer look (at most once) ─► describe again
       ▼
    relevance ─► decide ── inspect_closer and no look yet? ──► closer look ─► describe,
       ▼                                                       relevance, decide again
    _constrain (code guard) ─► search_center from the candidate ─► ClueAssessment

closer_look(candidate) -> Candidate | None gives a zoomed view of the same
object (offline: a higher-resolution render; in flight: None, so an
inspect_closer is published for the planner to fly instead).

LLMError from the backend is NOT caught: with no valid answer there is no
honest assessment to publish (evaluate.py records the failure; detector.py
logs it and publishes nothing).
"""
import _kit  # noqa: F401
from contract import ClueAssessment, LatLon
from stages import assess_relevance, decide_action, describe

DEFAULT_RADIUS_M = 80.0
MIN_RADIUS_M, MAX_RADIUS_M = 20.0, 200.0
RELEVANT = ("high", "medium")


class ClueAnalyzer:
    def __init__(self, backend, mission, closer_look=None, on_event=None):
        self.backend = backend
        self.mission = mission
        self.closer_look = closer_look
        self.on_event = on_event or (lambda message: None)

    def analyze(self, candidate):
        """Describe -> (closer look?) -> relevance -> decide -> ClueAssessment."""
        calls, descriptions = [], []
        looked_closer = candidate.zoomed      # a view that is already zoomed never gets another

        def run(stage_fn, *args):
            result, call = stage_fn(self.backend, *args)
            calls.append(call)
            return result

        def look_closer(reason):
            """The one closer look. Returns the zoomed Candidate, or None if unavailable."""
            nonlocal looked_closer
            if looked_closer or self.closer_look is None:
                return None
            looked_closer = True
            zoomed = self.closer_look(candidate)
            if zoomed is None:
                return None
            self.on_event(f"CLOSER LOOK ({reason}): zoomed view of {candidate.candidate_id}")
            descriptions.append(run(describe, zoomed))
            return zoomed

        descriptions.append(run(describe, candidate))
        if descriptions[-1].needs_closer_look:
            look_closer("describe could not tell")

        relevance = run(assess_relevance, self.mission, candidate, descriptions[-1])
        decision = run(decide_action, self.mission, candidate, descriptions[-1], relevance, looked_closer)
        if decision.action == "inspect_closer" and look_closer("decide asked for it") is not None:
            relevance = run(assess_relevance, self.mission, candidate, descriptions[-1])
            decision = run(decide_action, self.mission, candidate, descriptions[-1], relevance, True)

        decision_dict = self._constrain(decision.model_dump(), relevance.relevance, looked_closer)
        search_center = None
        if decision_dict["action"] == "converge_search":
            search_center = LatLon(lat=candidate.lat, lon=candidate.lon)   # from code, never the model
            self.on_event(f"SEARCH CENTRE set by code to the candidate's position "
                          f"({candidate.lat:.6f}, {candidate.lon:.6f}), radius {decision_dict['search_radius_m']:g} m")

        return ClueAssessment(
            mission_id=self.mission.mission_id,
            candidate=candidate.without_images(),
            descriptions=[d.model_dump() for d in descriptions],
            relevance=relevance.model_dump(),
            decision=decision_dict,
            search_center=search_center,
            calls=calls,
        )

    def _constrain(self, decision, relevance, looked_closer):
        """The code guard: the model proposes, these rules are not negotiable.
        Every override is narrated and recorded in decision["guard"]."""
        proposed = decision["action"]
        notes = []
        if proposed == "converge_search" and relevance not in RELEVANT:
            decision["action"] = "log_only"
            notes.append(f"converge_search needs relevance high/medium, got {relevance}: downgraded to log_only")
        if proposed == "inspect_closer" and looked_closer and self.closer_look is not None:
            decision["action"] = "log_only"
            notes.append("inspect_closer after the one closer look: downgraded to log_only")
        if decision["action"] == "converge_search":
            radius = decision.get("search_radius_m")
            if not radius:
                decision["search_radius_m"] = DEFAULT_RADIUS_M
                notes.append(f"no search radius given: using {DEFAULT_RADIUS_M:g} m")
            elif not MIN_RADIUS_M <= radius <= MAX_RADIUS_M:
                decision["search_radius_m"] = min(max(radius, MIN_RADIUS_M), MAX_RADIUS_M)
                notes.append(f"search radius {radius:g} m clamped to {decision['search_radius_m']:g} m")
        else:
            decision["search_radius_m"] = None
            decision["priority"] = None
        decision["guard"] = notes
        for note in notes:
            self.on_event(f"CODE GUARD: {note}")
        return decision
