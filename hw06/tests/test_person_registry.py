"""PersonRegistry: merging evidence into persons and the one-decision rule."""
from planner.person_registry import DecisionStatus, PersonRegistry
from tests.conftest import make_event, near


def test_merge_within_10m():
    """R3: two events ~5 m apart are the same person; both event ids attached."""
    reg = PersonRegistry(merge_radius_m=10.0)
    first = make_event(event_id="a")
    p1 = reg.observe(first)
    p2 = reg.observe(near(first, 5.0, event_id="b"))
    assert len(reg) == 1
    assert p1 is p2
    assert p1.event_ids == ["a", "b"]


def test_split_beyond_10m():
    """R3: two events ~150 m apart are two different people."""
    reg = PersonRegistry(merge_radius_m=10.0)
    first = make_event()
    reg.observe(first)
    reg.observe(near(first, 150.0))
    assert len(reg) == 2


def test_confidence_updated_on_merge():
    """R1/R3: a higher-confidence re-sighting raises the stored confidence to the max."""
    reg = PersonRegistry()
    first = make_event(confidence=0.40)
    person = reg.observe(first)
    reg.observe(near(first, 3.0, confidence=0.75))
    reg.observe(near(first, 2.0, confidence=0.50))
    assert person.confidence == 0.75


def test_decided_person_no_repopup():
    """R3: after RESPONDED, a new sighting does not need a decision."""
    reg = PersonRegistry()
    first = make_event()
    person = reg.observe(first)
    assert reg.claim_for_decision(person)
    reg.mark_responded(person, "act1", "hover_stream")
    again = reg.observe(near(first, 4.0))
    assert again is person and person.status is DecisionStatus.RESPONDED
    assert reg.should_request_decision(again) is False


def test_dismissed_person_no_repopup():
    """R3: after DISMISSED ("No action"), a new sighting does not need a decision."""
    reg = PersonRegistry()
    first = make_event()
    person = reg.observe(first)
    reg.claim_for_decision(person)
    reg.mark_dismissed(person)
    again = reg.observe(near(first, 4.0))
    assert reg.should_request_decision(again) is False


def test_timedout_person_can_repopup():
    """R3: after a timeout the person is UNDECIDED and may be asked about again."""
    reg = PersonRegistry()
    first = make_event()
    person = reg.observe(first)
    reg.claim_for_decision(person)
    reg.mark_timed_out(person)
    again = reg.observe(near(first, 4.0))
    assert again.status is DecisionStatus.UNDECIDED
    assert reg.should_request_decision(again) is True
