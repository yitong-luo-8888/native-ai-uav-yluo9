"""DecisionSource: the human popup round-trip, and swapping in an AI (R5)."""
import pytest

from planner.decision_source import (
    DISMISS, TIMEOUT, AIDecisionSource, DecisionRequest, DecisionSource, HumanDecisionSource,
)
from planner.person_registry import DecisionStatus
from tests.conftest import FakeBus, FakeClock, Harness, Operator, choose, dismiss, make_event


def request(timeout_s=180.0, request_id="r1"):
    event = make_event()
    return DecisionRequest(request_id=request_id, event=event, world_state={"uavs": []},
                           candidates=[{"type": "hover_stream", "parameters": {"standoff_m": 10.0, "duration_s": 60.0}}],
                           timeout_s=timeout_s)


def test_human_decision_source_returns_action():
    """R5: the action the operator sends on mission/decision is what decide() returns."""
    bus, clock = FakeBus(), FakeClock()
    Operator(bus).then(choose("hover_stream", standoff_m=7.0))
    result = HumanDecisionSource(bus, clock).decide(request())
    sent = bus.messages("mission/decision")[0]["action"]
    assert result == sent
    assert result["type"] == "hover_stream" and result["parameters"]["standoff_m"] == 7.0
    # and the request went out keyed exactly as the popup reads it
    req = bus.messages("mission/decision_request")[0]
    assert set(req) == {"request_id", "event", "world_state", "candidates", "timeout_s"}


def test_human_decision_source_dismiss():
    """R5: "No action" returns the DISMISS sentinel, not an action."""
    bus, clock = FakeBus(), FakeClock()
    Operator(bus).then(dismiss)
    assert HumanDecisionSource(bus, clock).decide(request()) is DISMISS


def test_human_decision_source_timeout():
    """R5: no answer returns the timeout sentinel after the advertised timeout_s, without hanging."""
    bus, clock = FakeBus(), FakeClock()
    Operator(bus)                        # never answers
    source = HumanDecisionSource(bus, clock)
    start = clock.now()
    result = source.decide(request(timeout_s=42.0))
    assert result is TIMEOUT is None
    assert clock.now() - start == pytest.approx(42.0)
    assert bus.messages("mission/decision_request")[0]["timeout_s"] == 42.0


def test_late_decision_is_ignored():
    """R5: a decision arriving after its request timed out is dropped, not applied."""
    bus, clock = FakeBus(), FakeClock()
    source = HumanDecisionSource(bus, clock)
    assert source.decide(request(request_id="old")) is TIMEOUT
    bus.deliver("mission/decision", {"request_id": "old", "dismiss": True})   # no error, no effect


class StubAIDecisionSource(DecisionSource):
    """What next week's AI looks like from the planner's side: same input, same return shape."""

    def __init__(self, choice):
        self.choice = choice
        self.seen: list[DecisionRequest] = []

    def decide(self, req: DecisionRequest):
        self.seen.append(req)
        return self.choice(req.to_payload())["action"]


def run_approve_hover(h: Harness) -> None:
    """The decision-loop scenario both sources must pass unchanged."""
    person = h.event(make_event(confidence=0.82))
    results = h.results()
    assert len(results) == 1 and results[0]["approved"] is True and results[0]["type"] == "hover_stream"
    assert person.status is DecisionStatus.RESPONDED and person.action_id == results[0]["action_id"]
    assert h.planner.executors["1"].active_action_id == results[0]["action_id"]


def test_decision_source_is_swappable(config):
    """R5: a stub AI with the same return shape substitutes with no planner changes."""
    human = Harness(config)
    human.operator.then(choose("hover_stream"))
    run_approve_hover(human)

    ai = StubAIDecisionSource(choose("hover_stream"))
    stubbed = Harness(config, decision_source=ai)
    run_approve_hover(stubbed)
    assert ai.seen[0].event["confidence"] == 0.82 and ai.seen[0].timeout_s == config.planner.decision_timeout_s


def test_ai_placeholder_failure_leaves_person_undecided(config):
    """R5: the NotImplementedError stub must not crash the planner; the person stays askable."""
    h = Harness(config, decision_source=AIDecisionSource())
    person = h.event(make_event())
    assert person.status is DecisionStatus.UNDECIDED
    assert h.results() == []
