"""drone_store.py — in-memory drone list, MQTT ingestion, and staleness pruning.

Owns the DroneResponse MQTT pipeline end-to-end: connecting, decoding
telemetry into Drone objects, pruning drones that go stale, and fanning
the current drone list out to every interested consumer once per poll().
Deliberately has no knowledge of Qt widgets or rendering -- MapOverlay and
its children are the only things that turn this data into pixels.

Must be a QObject (not a plain class) because DroneMqttClient calls back
on a background paho-mqtt thread; touching drone state from that thread
directly would race with the Qt main thread's paint/tick cycle.
drone_pose_signal is how a background thread hands data to the main
thread safely: emit() is threadsafe from any thread, and Qt auto-queues
delivery of the connected slot onto the thread that owns this QObject
(the main thread, since DroneStore is constructed there).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from drone import Drone
from drone_mqtt_client import DroneMqttClient
from map_config import MapConfig

# A drone with no telemetry for this long is dropped from the map (e.g. its
# backend container went away) rather than sitting frozen at its last known
# position forever. Checked at _STALE_CHECK_INTERVAL_S, not every poll() --
# staleness only matters at ~1s granularity, no need to do it at tick_rate_ms.
_STALE_TIMEOUT_S = 5.0
_STALE_CHECK_INTERVAL_S = 1.0


class DroneStore(QObject):
    """Owns the live drone list and its MQTT ingestion pipeline.

    Consumers register via add_consumer(); poll() (call once per app tick)
    prunes stale drones then hands the current List[Drone] to each
    registered callback in registration order. Register a consumer right
    next to where it's constructed, the same tick it starts needing drone
    data -- that's what keeps a consumer from silently falling out of the
    fan-out, the failure mode this list-based design exists to prevent.
    """

    drone_pose_signal = pyqtSignal(str, dict, dict, float, dict)

    def __init__(
        self,
        cfg: MapConfig,
        on_pose_update: Optional[Callable[[str, float], None]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._cfg = cfg
        # Optional hook fired with (uavid, alt) after every successful pose
        # update -- lets MapOverlay feed AltitudeCollector without DroneStore
        # importing vertical_view.py (a display concern this class has no
        # business knowing about).
        self._on_pose_update = on_pose_update

        self._drones: List[Drone] = []
        self._drone_index: Dict[str, int] = {}
        self._last_stale_check: float = time.monotonic()

        self._consumers: List[Callable[[List[Drone]], None]] = []

        self._mqtt_client: Optional[DroneMqttClient] = None

        self.drone_pose_signal.connect(self._on_drone_pose_signal)

    # -------------------- Consumer registration --------------------

    def add_consumer(self, callback: Callable[[List[Drone]], None]) -> None:
        self._consumers.append(callback)

    # -------------------- Tick --------------------

    def poll(self) -> None:
        """Call once per app tick (driven by MapOverlay's shared QTimer)."""
        self._prune_stale_drones()
        for notify in self._consumers:
            notify(self._drones)

    def _prune_stale_drones(self) -> None:
        """Drop any drone with no telemetry for _STALE_TIMEOUT_S, so a
        backend that goes away (e.g. docker compose down) doesn't leave a
        frozen marker on the map forever. Rate-limited to
        _STALE_CHECK_INTERVAL_S -- staleness doesn't need tick_rate_ms
        granularity."""
        now = time.monotonic()
        if now - self._last_stale_check < _STALE_CHECK_INTERVAL_S:
            return
        self._last_stale_check = now

        fresh = [d for d in self._drones if now - d.t_updated <= _STALE_TIMEOUT_S]
        if len(fresh) == len(self._drones):
            return
        self._drones = fresh
        self._drone_index = {d.name: i for i, d in enumerate(self._drones)}

    # -------------------- Drone pose --------------------

    def update_drone_pose(
        self,
        uavid: str,
        location: Dict[str, Any],
        drone_attitude: Optional[Dict[str, Any]],
        drone_heading: Optional[float],
        state_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        lat = float(location.get("latitude", 0.0))
        lon = float(location.get("longitude", 0.0))
        alt = float(location.get("altitude", 0.0))

        if self._on_pose_update is not None:
            self._on_pose_update(uavid, alt)

        if uavid in self._drone_index:
            d = self._drones[self._drone_index[uavid]]
            d.lat, d.lon, d.alt = lat, lon, alt
            if d.r_lat is None:
                d.r_lat, d.r_lon, d.r_alt = lat, lon, alt

            if state_info:
                d.status           = str(state_info.get("status", d.status or ""))
                d.mode             = str(state_info.get("mode", d.mode or ""))
                d.onboard_pilot    = str(state_info.get("onboard_pilot", d.onboard_pilot or ""))
                d.air_lease_state  = str(state_info.get("air_lease_state", d.air_lease_state or ""))
                d.heartbeat_status = str(state_info.get("heartbeat_status", d.heartbeat_status or ""))
                d.state_type       = str(state_info.get("state_type", d.state_type or ""))
                for attr, key in (
                    ("voltage",         "voltage"),
                    ("battery_level",   "battery_level"),
                    ("battery_current", "battery_current"),
                    ("speed",           "speed"),
                ):
                    v = state_info.get(key)
                    if v is not None:
                        try:
                            setattr(d, attr, float(v))
                        except (ValueError, TypeError):
                            pass
                armed = state_info.get("armed")
                if armed is not None:
                    d.armed = bool(armed)
                geofence = state_info.get("geofence")
                if geofence is not None:
                    d.geofence = bool(geofence)

            if drone_heading is not None:
                try:
                    d.heading_rad = float(drone_heading)
                    if d.r_heading_rad is None:
                        d.r_heading_rad = d.heading_rad
                except (ValueError, TypeError):
                    pass

            if drone_attitude:
                try:
                    d.att_q = (
                        float(drone_attitude.get("x", 0.0)),
                        float(drone_attitude.get("y", 0.0)),
                        float(drone_attitude.get("z", 0.0)),
                        float(drone_attitude.get("w", 1.0)),
                    )
                except (ValueError, TypeError):
                    d.att_q = None

            d.t_updated = time.monotonic()

        else:
            d = Drone(
                name=uavid,
                lat=lat, lon=lon, alt=alt,
                phys_h_m=self._cfg.default_phys_h_m,
                heading_rad=float(drone_heading) if drone_heading is not None else 0.0,
                att_q=(
                    float(drone_attitude.get("x", 0.0)) if drone_attitude else 0.0,
                    float(drone_attitude.get("y", 0.0)) if drone_attitude else 0.0,
                    float(drone_attitude.get("z", 0.0)) if drone_attitude else 0.0,
                    float(drone_attitude.get("w", 1.0)) if drone_attitude else 1.0,
                ) if drone_attitude else None,
            )

            if state_info:
                d.status           = str(state_info.get("status", ""))
                d.mode             = str(state_info.get("mode", ""))
                d.onboard_pilot    = str(state_info.get("onboard_pilot", ""))
                d.air_lease_state  = str(state_info.get("air_lease_state", ""))
                d.heartbeat_status = str(state_info.get("heartbeat_status", ""))
                d.state_type       = str(state_info.get("state_type", ""))
                for attr, key in (
                    ("voltage",         "voltage"),
                    ("battery_level",   "battery_level"),
                    ("battery_current", "battery_current"),
                    ("speed",           "speed"),
                ):
                    v = state_info.get(key)
                    if v is not None:
                        try:
                            setattr(d, attr, float(v))
                        except (ValueError, TypeError):
                            pass
                armed = state_info.get("armed")
                if armed is not None:
                    d.armed = bool(armed)
                geofence = state_info.get("geofence")
                if geofence is not None:
                    d.geofence = bool(geofence)

            d.r_lat, d.r_lon, d.r_alt = lat, lon, alt
            d.r_heading_rad = d.heading_rad
            d.t_updated = time.monotonic()

            self._drone_index[uavid] = len(self._drones)
            self._drones.append(d)

    # -------------------- Qt signal slots --------------------

    def _on_drone_pose_signal(
        self,
        uavid: str,
        location: dict,
        drone_attitude: dict,
        drone_heading: float,
        state_info: dict,
    ) -> None:
        self.update_drone_pose(uavid, location, drone_attitude, drone_heading, state_info)

    def _handle_mqtt_state(
        self,
        uavid: str,
        location: Dict[str, Any],
        drone_attitude: Dict[str, Any],
        drone_heading: float,
        state_info: Dict[str, Any],
    ) -> None:
        """Called by DroneMqttClient in its background thread — forward via signal."""
        self.drone_pose_signal.emit(uavid, location, drone_attitude, drone_heading, state_info)

    # -------------------- MQTT lifecycle --------------------

    def start_mqtt(self) -> None:
        cfg = self._cfg
        self._mqtt_client = DroneMqttClient(
            broker=cfg.broker,
            port=cfg.port,
            topic=cfg.topic,
            on_state=self._handle_mqtt_state,
        )
        self._mqtt_client.start()

    def stop_mqtt(self) -> None:
        if self._mqtt_client is not None:
            self._mqtt_client.stop()

    def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> None:
        if self._mqtt_client is not None:
            self._mqtt_client.publish(topic, payload, qos=qos, retain=retain)
