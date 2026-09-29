"""Shared fixtures for the generated unit tests in this directory.

Adds the repo root to sys.path (found by walking up to the directory that
contains .git) so target modules can be imported by their stable module
path -- e.g. lab.scripts.test_flight, lab.lesson4.battery.battery_detector,
hw05.atc -- instead of a path hack tied to this file's current location.
"""
import sys
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"could not locate repo root (no .git found above {start})")


_REPO_ROOT = _find_repo_root(Path(__file__).resolve())
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

import lab.scripts.test_flight as test_flight
import lab.lesson4.battery.battery_detector as battery_detector
import hw05.atc as atc


@pytest.fixture(autouse=True)
def reset_latest():
    """test_flight._latest is module-level state shared across tests; isolate it."""
    test_flight._latest.clear()
    yield
    test_flight._latest.clear()


@pytest.fixture(autouse=True)
def reset_battery_state():
    """battery_detector._window / ._verdict are module-level state populated
    by on_message; isolate them between tests."""
    battery_detector._window.clear()
    battery_detector._verdict = None
    yield
    battery_detector._window.clear()
    battery_detector._verdict = None


class FakeMqttMessage:
    """Stands in for paho's MQTTMessage: just the attributes a handler reads."""

    def __init__(self, payload, topic=None):
        self.payload = payload
        self.topic = topic


class RecordingClient:
    """Stands in for paho's mqtt.Client: records every publish() call instead
    of talking to a broker."""

    def __init__(self):
        self.published = []

    def publish(self, topic, payload):
        self.published.append((topic, payload))


class FakeClock:
    """Controllable stand-in for the `time` module used by wait_for and
    execute_command. time() returns the current fake time; sleep(s) advances
    it by s instead of actually blocking, so polling loops run instantly.

    Tests can hook a callback to fire right after the Nth sleep() call, to
    simulate telemetry arriving partway through a poll loop.
    """

    def __init__(self, start=0.0):
        self.now = start
        self.sleep_calls = 0
        self._callbacks = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleep_calls += 1
        self.now += seconds
        for call_number, callback in self._callbacks:
            if self.sleep_calls == call_number:
                callback()

    def after_sleep(self, call_number, callback):
        self._callbacks.append((call_number, callback))


@pytest.fixture
def fake_clock(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(test_flight.time, "time", clock.time)
    monkeypatch.setattr(test_flight.time, "sleep", clock.sleep)
    return clock


@pytest.fixture
def recording_client():
    return RecordingClient()


class FakeMqttClient:
    """Stands in for paho's mqtt.Client specifically for constructing an
    ATCController in tests: ATCController.__init__ is LIVE (it builds a real
    mqtt.Client and connects/loop_starts it), so tests patch atc.mqtt.Client
    with this fake before constructing -- __init__ itself still runs
    unmodified, it just never touches a real socket. Records publish()/
    subscribe() calls like RecordingClient, and captures the callbacks and
    connect() args the constructor wires up.
    """

    def __init__(self, *args, **kwargs):
        self.on_connect = None
        self.on_message = None
        self.published = []
        self.subscribed = []
        self.connected_to = None
        self.loop_started = False

    def connect(self, host, port):
        self.connected_to = (host, port)

    def loop_start(self):
        self.loop_started = True

    def publish(self, topic, payload):
        self.published.append((topic, payload))

    def subscribe(self, topic):
        self.subscribed.append(topic)


@pytest.fixture
def controller(monkeypatch):
    """An ATCController built with a FakeMqttClient standing in for
    paho's mqtt.Client, so construction never opens a real connection."""
    monkeypatch.setattr(atc.mqtt, "Client", FakeMqttClient)
    return atc.ATCController(min_separation_m=5.0)
