"""Integration fixtures: the real broker + SITL from lab/ (docker compose up -d).

real_stack connects to MQTT_HOST:MQTT_PORT (default localhost:1883), waits up
to 10 s for uav/1/telemetry and pytest.skip()s if none arrives -- so these
tests skip, not fail, when the stack is down. Otherwise it builds the
production planner (real MqttBus, real MqttUavClient, HumanDecisionSource)
and runs it on a background thread. The test plays the operator by
answering mission/decision_request on the same broker.

Synchronisation is always wait_until()/wait_for_states() polling, never a
fixed sleep.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Callable

import pytest

from planner import mqtt_bus
from planner.config import load_config
from planner.executor import Mode
from planner.main import build_planner
from planner.mqtt_bus import MqttBus
from planner.world_model import distance_m, offset_latlon

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
UAV = os.environ.get("VEHICLE_ID", "1")
TELEMETRY_WAIT_S = 10.0


def wait_until(predicate: Callable[[], object], timeout: float, interval: float = 0.2):
    """Poll predicate until it returns something truthy (returned) or timeout (None)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


class Recorder:
    """Every mission/* message seen on the broker, in arrival order."""

    def __init__(self, bus: MqttBus):
        self._lock = threading.Lock()
        self.log: list[tuple[float, str, dict]] = []
        bus.subscribe("mission/#", self._on, qos=1)

    def _on(self, topic: str, payload: dict) -> None:
        with self._lock:
            self.log.append((time.time(), topic, payload))

    def messages(self, topic: str, where: Callable[[dict], bool] | None = None) -> list[dict]:
        with self._lock:
            return [p for _, t, p in self.log if t == topic and (where is None or where(p))]

    def first(self, topic: str, where: Callable[[dict], bool] | None = None) -> dict | None:
        found = self.messages(topic, where)
        return found[0] if found else None


class Stack:
    def __init__(self, bus: MqttBus, planner, recorder: Recorder):
        self.bus = bus
        self.planner = planner
        self.recorder = recorder

    # -- helpers the tests use -------------------------------------------------
    def wait_for_states(self, topic: str, key: str, states: list[str], timeout: float,
                        where: Callable[[dict], bool] | None = None) -> list[str]:
        """Wait until every value in `states` has been seen (or a terminal state
        ends the sequence early) and return the observed ordered list of
        `key` values, consecutive duplicates collapsed."""
        def observed() -> list[str]:
            out: list[str] = []
            for msg in self.recorder.messages(topic, where):
                if not out or out[-1] != msg.get(key):
                    out.append(msg.get(key))
            return out

        terminal = {"COMPLETED", "FAILED", "CANCELLED"} - set(states)
        wait_until(lambda: set(states) <= set(observed()) or terminal & set(observed()), timeout)
        return observed()

    def wait_searching(self, timeout: float = 150.0) -> None:
        ex = self.planner.executors[UAV]
        ok = wait_until(lambda: ex.mode is Mode.SEARCHING and not ex.busy, timeout)
        assert ok, f"UAV {UAV} never reached the search route (mode {ex.mode}); check pre-arm/SITL logs"

    def wait_mid_leg(self, min_remaining_m: float = 15.0, timeout: float = 120.0) -> None:
        """Wait until the UAV is searching and at least min_remaining_m from the
        waypoint it's heading to, so it can't reach that waypoint (and advance
        the route index) during the sub-second decision exchange. Without this,
        "index before" vs "index the planner captured" is a race in the test."""
        self.wait_searching()
        ex, world = self.planner.executors[UAV], self.planner.world

        def ready() -> bool:
            s, wp = world.uav(UAV), world.uav(UAV).route.current
            return (ex.mode is Mode.SEARCHING and not ex.busy and wp is not None and s.lat is not None
                    and distance_m(s.lat, s.lon, wp.lat, wp.lon) >= min_remaining_m)

        assert wait_until(ready, timeout), "UAV never got mid-leg on the search route"

    @property
    def route_index(self) -> int:
        return self.planner.world.uav(UAV).route.current_waypoint_index

    def uav_position(self) -> tuple[float, float]:
        s = self.planner.world.uav(UAV)
        return s.lat, s.lon

    def inject(self, lat: float, lon: float, confidence: float = 0.9) -> dict:
        """Same payload as lesson6/inject_event.py."""
        event = {"event_id": uuid.uuid4().hex[:8], "type": "person", "lat": lat, "lon": lon,
                 "confidence": confidence, "source_uav": UAV, "source_drone": None,
                 "timestamp": time.time(), "image_b64": None}
        self.bus.publish(mqtt_bus.EVENTS, event, qos=1)
        return event

    def inject_near_uav(self, east_m: float, north_m: float = 0.0, confidence: float = 0.9) -> dict:
        lat, lon = offset_latlon(*self.uav_position(), east_m, north_m)
        return self.inject(lat, lon, confidence)

    def wait_request(self, event_id: str, timeout: float, exclude: set[str] = frozenset()) -> dict | None:
        return wait_until(lambda: self.recorder.first(
            mqtt_bus.DECISION_REQUEST,
            lambda r: r["event"]["event_id"] == event_id and r["request_id"] not in exclude), timeout)

    def wait_result(self, request_id: str, timeout: float = 10.0) -> dict | None:
        return wait_until(lambda: self.recorder.first(
            mqtt_bus.ACTION_RESULT, lambda r: r["request_id"] == request_id), timeout)

    def decide(self, request: dict, response_type: str, **params) -> dict:
        """Answer like the popup does: the candidate's defaults, overridden by params."""
        cand = next(c for c in request["candidates"] if c["type"] == response_type)
        parameters = {**cand["parameters"], **params}
        action = {"type": response_type, "uav": UAV,
                  "target": {"lat": request["event"]["lat"], "lon": request["event"]["lon"]},
                  "parameters": parameters}
        self.bus.publish(mqtt_bus.DECISION, {"request_id": request["request_id"], "action": action})
        return action

    def dismiss(self, request: dict) -> None:
        self.bus.publish(mqtt_bus.DECISION, {"request_id": request["request_id"], "dismiss": True})


@pytest.fixture
def real_stack():
    # Two connections, like the real deployment: the planner's own, and the
    # test's (playing detector + popup + observer). Sharing one connection
    # would make the broker deliver overlapping subscriptions twice.
    test_bus = MqttBus(MQTT_HOST, MQTT_PORT)
    telemetry = threading.Event()
    test_bus.subscribe(mqtt_bus.telemetry_topic(UAV), lambda *_: telemetry.set())
    recorder = Recorder(test_bus)
    if not test_bus.connect(timeout_s=TELEMETRY_WAIT_S):
        test_bus.close()
        pytest.skip(f"No MQTT broker at {MQTT_HOST}:{MQTT_PORT} (is `docker compose up -d` running in lab/?)")
    if not telemetry.wait(TELEMETRY_WAIT_S):
        test_bus.close()
        pytest.skip(f"No uav/{UAV}/telemetry within {TELEMETRY_WAIT_S:.0f}s -- SITL is not running")

    planner_bus = MqttBus(MQTT_HOST, MQTT_PORT)
    planner = build_planner(planner_bus, load_config())
    assert planner_bus.connect(), "planner could not connect to the broker"
    assert wait_until(lambda: planner.uav_clients[UAV].telemetry(), TELEMETRY_WAIT_S)
    stop = threading.Event()
    planner.start()
    thread = threading.Thread(target=planner.run, args=(stop,), daemon=True, name="planner")
    thread.start()
    stack = Stack(test_bus, planner, recorder)
    try:
        yield stack
    finally:
        for ex in planner.executors.values():
            ex.cancel()                      # don't leave a response running into the next test
        planner.tick()
        stop.set()
        thread.join(timeout=5)
        planner_bus.close()
        test_bus.close()
