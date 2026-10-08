"""person_registry.py -- found persons and the one-decision-per-person rule (R1, R3).

Every mission/events message is evidence about a person, not a new person:
an event within merge_radius_m of someone already known merges into them
(the detector re-announces a person every 30 s with a fresh event_id, and a
drone circling a victim keeps seeing them). Each Person carries its decision
status, and that status alone decides whether the operator is asked:

    UNDECIDED --claim--> PENDING --approve--> RESPONDED   (decided: never re-asked)
        ^                   |----dismiss--> DISMISSED   (decided: never re-asked)
        '----timeout--------'

A rejected choice keeps the person PENDING while the planner re-asks.
"""
from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field
from enum import Enum

from .world_model import distance_m


class DecisionStatus(str, Enum):
    UNDECIDED = "UNDECIDED"   # never asked, or asked and timed out -- may be asked
    PENDING = "PENDING"       # a decision_request is outstanding
    RESPONDED = "RESPONDED"   # operator chose a response and it was approved
    DISMISSED = "DISMISSED"   # operator chose "No action"

    @property
    def decided(self) -> bool:
        return self in (DecisionStatus.RESPONDED, DecisionStatus.DISMISSED)


@dataclass
class Person:
    person_id: str
    lat: float
    lon: float
    confidence: float
    source_uav: str | None
    source_drone: str | None
    first_seen: float
    last_seen: float
    event_ids: list[str] = field(default_factory=list)
    latest_event: dict = field(default_factory=dict)
    sightings: int = 1
    status: DecisionStatus = DecisionStatus.UNDECIDED
    times_asked: int = 0
    times_timed_out: int = 0
    action_id: str | None = None
    response_type: str | None = None
    response_state: str | None = None        # last behavior_status state of its response
    last_rejection: list[str] = field(default_factory=list)


class PersonRegistry:
    def __init__(self, merge_radius_m: float = 10.0):
        self.merge_radius_m = merge_radius_m
        self._persons: dict[str, Person] = {}
        self._ids = itertools.count(1)
        self._lock = threading.RLock()

    # -- evidence ----------------------------------------------------------
    def observe(self, event: dict) -> Person:
        """Merge one mission/events payload into the registry; returns the
        (new or existing) person it is evidence of."""
        lat, lon = float(event["lat"]), float(event["lon"])
        confidence = float(event.get("confidence") or 0.0)
        timestamp = float(event.get("timestamp") or 0.0)
        with self._lock:
            person = self.nearest(lat, lon)
            if person is None:
                person = Person(
                    person_id=f"P{next(self._ids)}", lat=lat, lon=lon, confidence=confidence,
                    source_uav=event.get("source_uav"), source_drone=event.get("source_drone"),
                    first_seen=timestamp, last_seen=timestamp,
                    event_ids=[event["event_id"]], latest_event=dict(event))
                self._persons[person.person_id] = person
                return person
            person.sightings += 1
            # running mean: repeated sightings refine the location estimate
            person.lat += (lat - person.lat) / person.sightings
            person.lon += (lon - person.lon) / person.sightings
            person.confidence = max(person.confidence, confidence)
            person.last_seen = max(person.last_seen, timestamp)
            if event["event_id"] not in person.event_ids:
                person.event_ids.append(event["event_id"])
            person.latest_event = dict(event)
            return person

    def by_event(self, event_id: str) -> Person | None:
        """The person an event_id was already merged into. QoS-1 delivery is
        at-least-once, so the same event can arrive twice; it must not
        count as a second sighting."""
        with self._lock:
            for person in self._persons.values():
                if event_id in person.event_ids:
                    return person
            return None

    def nearest(self, lat: float, lon: float) -> Person | None:
        """Closest known person within merge_radius_m, else None."""
        with self._lock:
            best, best_d = None, self.merge_radius_m
            for person in self._persons.values():
                d = distance_m(person.lat, person.lon, lat, lon)
                if d <= best_d:
                    best, best_d = person, d
            return best

    # -- the R3 rule -------------------------------------------------------
    def should_request_decision(self, person: Person) -> bool:
        with self._lock:
            return person.status is DecisionStatus.UNDECIDED

    def claim_for_decision(self, person: Person) -> bool:
        """Atomically: if the person may be asked, mark them PENDING and
        return True. Two events for one person arriving together can't both
        open a popup."""
        with self._lock:
            if not self.should_request_decision(person):
                return False
            person.status = DecisionStatus.PENDING
            person.times_asked += 1
            person.last_rejection = []
            return True

    def mark_rejected(self, person: Person, reasons: list[str]) -> None:
        with self._lock:
            person.last_rejection = list(reasons)   # stays PENDING: we re-ask

    def mark_responded(self, person: Person, action_id: str, response_type: str) -> None:
        with self._lock:
            person.status = DecisionStatus.RESPONDED
            person.action_id = action_id
            person.response_type = response_type
            person.response_state = "PENDING"
            person.last_rejection = []

    def mark_dismissed(self, person: Person) -> None:
        with self._lock:
            person.status = DecisionStatus.DISMISSED

    def mark_timed_out(self, person: Person) -> None:
        with self._lock:
            person.status = DecisionStatus.UNDECIDED
            person.times_timed_out += 1

    def set_response_state(self, action_id: str, state: str) -> None:
        with self._lock:
            for person in self._persons.values():
                if person.action_id == action_id:
                    person.response_state = state

    # -- queries -----------------------------------------------------------
    def get(self, person_id: str) -> Person | None:
        with self._lock:
            return self._persons.get(person_id)

    def all(self) -> list[Person]:
        with self._lock:
            return list(self._persons.values())

    def __len__(self) -> int:
        with self._lock:
            return len(self._persons)
