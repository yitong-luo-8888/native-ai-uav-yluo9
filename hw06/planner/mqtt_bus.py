"""mqtt_bus.py -- the only module that knows about paho-mqtt.

Bus       -- publish/subscribe of JSON dicts. The planner, decision source,
             executor and dashboard all talk through this interface, so unit
             tests swap in tests/conftest.py's FakeBus and never touch MQTT.
UavClient -- one vehicle's uav/<id>/command, uav/<id>/telemetry and
             uav/<id>/home, on top of a Bus. Commands are the ARCHITECTURE.md
             vocabulary only (takeoff/goto/circle/interrupt/...); nothing here
             speaks MAVLink.

Topic names and payload keys follow lab/lesson6/hotl_popup.py and
lab/lesson6/inject_event.py exactly.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from typing import Callable, Protocol

import paho.mqtt.client as mqtt

log = logging.getLogger("planner.bus")

# mission/* -- the popup contract (hotl_popup.py) and detector (inject_event.py)
EVENTS = "mission/events"
DECISION_REQUEST = "mission/decision_request"
DECISION = "mission/decision"
ACTION_RESULT = "mission/action_result"
BEHAVIOR_STATUS = "mission/behavior_status"
CANCEL = "mission/cancel"
ABORT = "mission/abort"


def command_topic(uav: str) -> str:
    return f"uav/{uav}/command"


def telemetry_topic(uav: str) -> str:
    return f"uav/{uav}/telemetry"


def home_topic(uav: str) -> str:
    return f"uav/{uav}/home"


Handler = Callable[[str, dict], None]


class Bus(Protocol):
    def publish(self, topic: str, payload: dict, qos: int = 0) -> None: ...

    def subscribe(self, topic: str, handler: Handler, qos: int = 0) -> None:
        """handler(topic, payload) for every JSON-object message matching
        `topic` (MQTT wildcards allowed). May be called on another thread."""
        ...


class MqttBus:
    """paho-mqtt implementation of Bus. Subscriptions are re-made on every
    (re)connect, so a broker restart doesn't silently stop the planner."""

    def __init__(self, host: str = "localhost", port: int = 1883, client_id: str | None = None,
                 persistent_session: bool = False):
        self.host, self.port = host, port
        client_id = client_id or f"hotl-{uuid.uuid4().hex[:8]}"
        # A persistent session (fixed client_id, clean_session=False) lets the
        # broker hold QoS-1 mission/events while the planner is down -- the
        # detector publishes them at QoS 1 for exactly that reason.
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id,
                                   clean_session=not persistent_session)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._subs: list[tuple[str, int, Handler]] = []
        self._lock = threading.Lock()
        self._connected = threading.Event()

    # -- lifecycle ---------------------------------------------------------
    def connect(self, timeout_s: float = 5.0) -> bool:
        """Connect and start paho's network thread. Returns False (instead
        of raising) when no broker answers within timeout_s."""
        try:
            self._client.connect(self.host, self.port)
        except OSError as exc:
            log.warning("MQTT connect to %s:%s failed: %s", self.host, self.port, exc)
            return False
        self._client.loop_start()
        return self._connected.wait(timeout_s)

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    # -- Bus ---------------------------------------------------------------
    def publish(self, topic: str, payload: dict, qos: int = 0) -> None:
        self._client.publish(topic, json.dumps(payload), qos=qos)

    def subscribe(self, topic: str, handler: Handler, qos: int = 0) -> None:
        with self._lock:
            self._subs.append((topic, qos, handler))
        if self.connected:
            self._client.subscribe(topic, qos=qos)

    # -- paho callbacks (paho's network thread) ----------------------------
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.warning("MQTT connect refused: %s", reason_code)
            return
        with self._lock:
            subs = list(self._subs)
        for topic, qos, _ in subs:
            client.subscribe(topic, qos=qos)
        self._connected.set()

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            log.warning("Ignoring non-JSON message on %s", msg.topic)
            return
        if not isinstance(payload, dict):
            return
        with self._lock:
            handlers = [h for topic, _, h in self._subs if mqtt.topic_matches_sub(topic, msg.topic)]
        for handler in handlers:
            try:
                handler(msg.topic, payload)
            except Exception:  # one bad handler must not kill paho's thread
                log.exception("Handler failed for %s", msg.topic)


class UavClient(Protocol):
    uav: str

    def send(self, command: dict) -> None:
        """Publish one uav/<id>/command, e.g. {"type": "goto", "lat":..., "lon":..., "alt":...}."""
        ...

    def telemetry(self) -> dict | None:
        """Latest uav/<id>/telemetry payload, or None if none has arrived."""
        ...

    def home(self) -> dict | None:
        ...


class MqttUavClient:
    """UavClient over a Bus. Keeps only the newest telemetry message."""

    def __init__(self, bus: Bus, uav: str):
        self.uav = uav
        self._bus = bus
        self._telemetry: dict | None = None
        self._home: dict | None = None
        self._listeners: list[Callable[[dict], None]] = []
        self._lock = threading.Lock()
        bus.subscribe(telemetry_topic(uav), self._on_telemetry)
        bus.subscribe(home_topic(uav), self._on_home)

    def on_telemetry(self, listener: Callable[[dict], None]) -> None:
        self._listeners.append(listener)

    def send(self, command: dict) -> None:
        log.debug("UAV %s <- %s", self.uav, command)
        self._bus.publish(command_topic(self.uav), command)

    def telemetry(self) -> dict | None:
        with self._lock:
            return self._telemetry

    def home(self) -> dict | None:
        with self._lock:
            return self._home

    def _on_telemetry(self, topic: str, payload: dict) -> None:
        with self._lock:
            self._telemetry = payload
        for listener in self._listeners:
            listener(payload)

    def _on_home(self, topic: str, payload: dict) -> None:
        with self._lock:
            self._home = payload
