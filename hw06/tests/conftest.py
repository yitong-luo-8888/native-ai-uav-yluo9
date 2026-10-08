"""Fakes and fixtures for unit tests: no MQTT broker, no SITL, no YOLO, no docker.

FakeBus        synchronous in-memory Bus; records every publish; can auto-reply
               to a topic (an operator answering the popup).
FakeUavClient  records commands; telemetry is whatever the test sets; can
               "teleport" to each goto target so executor steps complete.
FakeClock      frozen time that only moves when sleep()/wait() move it; wait()
               on an unset event returns immediately after advancing timeout_s.
"""
from __future__ import annotations

import itertools
import threading
from collections import deque
from typing import Callable

import pytest

from planner.clock import Clock
from planner.config import MissionConfig, load_config
from planner.decision_source import DecisionSource, HumanDecisionSource
from planner.main import Planner
from planner.person_registry import PersonRegistry
from planner.world_model import WorldModel, offset_latlon


def _matches(pattern: str, topic: str) -> bool:
    p, t = pattern.split("/"), topic.split("/")
    for i, part in enumerate(p):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(p) == len(t)


class FakeBus:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []
        self._subs: list[tuple[str, Callable]] = []
        self._responders: dict[str, Callable[[dict], None]] = {}

    def subscribe(self, topic: str, handler, qos: int = 0) -> None:
        self._subs.append((topic, handler))

    def publish(self, topic: str, payload: dict, qos: int = 0) -> None:
        self.published.append((topic, payload))
        for pattern, handler in list(self._subs):
            if _matches(pattern, topic):
                handler(topic, payload)
        if topic in self._responders:
            self._responders[topic](payload)

    def deliver(self, topic: str, payload: dict) -> None:
        """A message arriving from someone else (detector, popup)."""
        self.publish(topic, payload)

    def respond(self, topic: str, fn: Callable[[dict], None]) -> None:
        self._responders[topic] = fn

    def messages(self, topic: str) -> list[dict]:
        return [p for t, p in self.published if t == topic]


class FakeClock(Clock):
    def __init__(self, start: float = 1_000_000.0):
        self.t = start

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds

    def wait(self, event: threading.Event, timeout_s: float) -> bool:
        if event.is_set():
            return True
        self.t += timeout_s
        return event.is_set()


class FakeUavClient:
    def __init__(self, uav: str = "1", lat: float = 41.6990, lon: float = -86.2370, alt_rel: float = 20.0,
                 battery_level: float | None = 0.9, armed: bool = True, teleport: bool = True):
        self.uav = uav
        self.commands: list[dict] = []
        self.teleport = teleport
        self._t = {"vehicle_id": uav, "lat": lat, "lon": lon, "alt_rel": alt_rel, "heading": 0.0,
                   "battery_level": battery_level, "armed": armed, "mode": "GUIDED", "activity": "flying"}

    def send(self, command: dict) -> None:
        self.commands.append(command)
        if self.teleport and command["type"] == "goto":
            self._t.update(lat=command["lat"], lon=command["lon"], alt_rel=command["alt"])
        if self.teleport and command["type"] == "takeoff":
            self._t.update(armed=True, alt_rel=command["alt"])

    def telemetry(self) -> dict | None:
        return dict(self._t)

    def home(self) -> dict | None:
        return None

    def set(self, **kw) -> None:
        self._t.update(kw)

    def command_types(self) -> list[str]:
        return [c["type"] for c in self.commands]


def inline_runner(fn):
    """Run the decision loop synchronously inside handle_event()."""
    fn()


_event_ids = itertools.count(1)


def make_event(lat: float = 41.69925, lon: float = -86.23700, confidence: float = 0.82,
               event_id: str | None = None, source_uav: str = "1") -> dict:
    """A mission/events payload shaped exactly like lesson6/inject_event.py's."""
    return {"event_id": event_id or f"ev{next(_event_ids)}", "type": "person", "lat": lat, "lon": lon,
            "confidence": confidence, "source_uav": source_uav, "source_drone": None,
            "timestamp": 1_000_000.0, "image_b64": None}


def near(event: dict, east_m: float, north_m: float = 0.0, **overrides) -> dict:
    lat, lon = offset_latlon(event["lat"], event["lon"], east_m, north_m)
    return make_event(lat=lat, lon=lon, **overrides)


class Operator:
    """Answers mission/decision_request on a FakeBus from a script.
    Each entry is a callable(request) -> reply dict, or None (= say nothing,
    so the request times out)."""

    def __init__(self, bus: FakeBus):
        self.bus = bus
        self.script: deque = deque()
        self.requests: list[dict] = []
        bus.respond("mission/decision_request", self._on_request)

    def then(self, reply) -> "Operator":
        self.script.append(reply)
        return self

    def _on_request(self, request: dict) -> None:
        self.requests.append(request)
        if not self.script:
            return
        reply = self.script.popleft()
        if reply is not None:
            self.bus.deliver("mission/decision", reply(request))


def choose(response_type: str, uav: str = "1", **params):
    """Operator reply: pick `response_type` from the request's menu with its
    default parameters (overridden by **params)."""
    def reply(request: dict) -> dict:
        cand = next((c for c in request["candidates"] if c["type"] == response_type), None)
        parameters = dict(cand["parameters"]) if cand else {}
        parameters.update(params)
        return {"request_id": request["request_id"],
                "action": {"type": response_type, "uav": uav,
                           "target": {"lat": request["event"]["lat"], "lon": request["event"]["lon"]},
                           "parameters": parameters}}
    return reply


def dismiss(request: dict) -> dict:
    return {"request_id": request["request_id"], "dismiss": True}


@pytest.fixture
def config() -> MissionConfig:
    """The real lab/lesson6/mission_config.json."""
    return load_config()


@pytest.fixture
def world(config) -> WorldModel:
    w = WorldModel(config, PersonRegistry(config.planner.merge_radius_m))
    w.update_telemetry("1", {"lat": 41.6990, "lon": -86.2370, "alt_rel": 20.0, "battery_level": 0.9, "armed": True})
    return w


class Harness:
    def __init__(self, config: MissionConfig, decision_source: DecisionSource | None = None,
                 battery: float | None = 0.9):
        self.bus = FakeBus()
        self.clock = FakeClock()
        self.uav = FakeUavClient(battery_level=battery)
        self.operator = Operator(self.bus)
        source = decision_source or HumanDecisionSource(self.bus, self.clock)
        self.planner = Planner(config, self.bus, {"1": self.uav}, self.clock, source, runner=inline_runner)
        self.planner.refresh_telemetry()

    def event(self, event: dict):
        self.bus.deliver("mission/events", event)
        return self.planner.persons.nearest(event["lat"], event["lon"])

    def requests(self) -> list[dict]:
        return self.bus.messages("mission/decision_request")

    def results(self) -> list[dict]:
        return self.bus.messages("mission/action_result")

    def statuses(self, action_id: str | None = None) -> list[str]:
        return [s["state"] for s in self.bus.messages("mission/behavior_status")
                if action_id is None or s["action_id"] == action_id]

    def run(self, ticks: int = 50, step_s: float = 1.0) -> None:
        for _ in range(ticks):
            self.planner.tick()
            self.clock.sleep(step_s)

    def run_until(self, predicate: Callable[[], bool], max_ticks: int = 500, step_s: float = 1.0) -> bool:
        for _ in range(max_ticks):
            self.planner.tick()
            if predicate():
                return True
            self.clock.sleep(step_s)
        return False


@pytest.fixture
def harness(config):
    """A Planner on fakes with the human (popup) decision source."""
    return Harness(config)
