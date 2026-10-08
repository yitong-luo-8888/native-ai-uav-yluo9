"""world_model.py -- what the planner believes about the world (R1).

UAV state (position, battery, payload, current behavior, route progress) and
the found persons (held by a PersonRegistry). Nothing else: no map, no
obstacles, no other traffic.

Telemetry is the source of truth for position/battery/armed; payloads start
from mission_config.json and change only when the planner itself releases an
item (there is no release command -- see executor.py).

Also home to the small flat-earth geometry helpers everything else uses;
over a few hundred metres the error is centimetres.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .config import MissionConfig, Waypoint, color_for

if TYPE_CHECKING:
    from .person_registry import PersonRegistry

EARTH_RADIUS_M = 6378137.0


# -- geometry -------------------------------------------------------------
def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Horizontal distance, same formula as lab/cv/geolocate.py's distance_m."""
    dx = math.radians(lon2 - lon1) * EARTH_RADIUS_M * math.cos(math.radians((lat1 + lat2) / 2))
    dy = math.radians(lat2 - lat1) * EARTH_RADIUS_M
    return math.hypot(dx, dy)


def offset_latlon(lat: float, lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    """Small ENU offset -> lat/lon (same idea as lab/scripts/test_circle.py)."""
    dlat = math.degrees(north_m / EARTH_RADIUS_M)
    dlon = math.degrees(east_m / (EARTH_RADIUS_M * math.cos(math.radians(lat))))
    return lat + dlat, lon + dlon


def enu_m(origin_lat: float, origin_lon: float, lat: float, lon: float) -> tuple[float, float]:
    """lat/lon -> (east, north) metres from origin."""
    east = math.radians(lon - origin_lon) * EARTH_RADIUS_M * math.cos(math.radians(origin_lat))
    north = math.radians(lat - origin_lat) * EARTH_RADIUS_M
    return east, north


# -- state ----------------------------------------------------------------
@dataclass
class RouteProgress:
    waypoints: list[Waypoint]
    current_waypoint_index: int = 0   # the waypoint the UAV is heading to
    laps: int = 0

    @property
    def current(self) -> Waypoint | None:
        if 0 <= self.current_waypoint_index < len(self.waypoints):
            return self.waypoints[self.current_waypoint_index]
        return None


@dataclass
class UavState:
    uav: str
    color: str
    payloads: list[str]
    route: RouteProgress
    lat: float | None = None
    lon: float | None = None
    alt_rel: float | None = None
    heading: float | None = None
    battery_level: float | None = None
    armed: bool = False
    mode: str | None = None
    activity: str | None = None
    telemetry_time: float | None = None
    current_behavior: str | None = None      # what the planner has it doing
    active_action_id: str | None = None      # response in progress, if any

    @property
    def has_position(self) -> bool:
        return self.lat is not None and self.lon is not None

    def popup_view(self) -> dict:
        """Exactly the keys hotl_popup.py's DecisionDialog reads per UAV."""
        return {"uav": self.uav, "color": self.color, "battery_level": self.battery_level,
                "payloads": list(self.payloads), "current_behavior": self.current_behavior}


class WorldModel:
    """Thread-safe: telemetry arrives on paho's thread, the executor ticks
    on the planner thread, decisions run on worker threads."""

    def __init__(self, config: MissionConfig, persons: PersonRegistry):
        self.config = config
        self.persons = persons
        self._lock = threading.RLock()
        self._uavs: dict[str, UavState] = {
            uav: UavState(uav=uav, color=color_for(uav), payloads=list(config.payloads.get(uav, [])),
                          route=RouteProgress(config.route_for(uav)))
            for uav in config.owned_uavs
        }

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def uav(self, uav: str) -> UavState:
        return self._uavs[uav]

    def uav_ids(self) -> list[str]:
        return list(self._uavs)

    def has_uav(self, uav: str) -> bool:
        return uav in self._uavs

    # -- updates -----------------------------------------------------------
    def update_telemetry(self, uav: str, t: dict) -> None:
        state = self._uavs.get(uav)
        if state is None:
            return
        with self._lock:
            for key in ("lat", "lon", "alt_rel", "heading", "battery_level", "mode", "activity"):
                if key in t:
                    setattr(state, key, t[key])
            state.armed = bool(t.get("armed", state.armed))
            state.telemetry_time = t.get("timestamp", state.telemetry_time)

    def set_behavior(self, uav: str, behavior: str | None, action_id: str | None = None) -> None:
        with self._lock:
            state = self._uavs[uav]
            state.current_behavior = behavior
            state.active_action_id = action_id

    def set_route_index(self, uav: str, index: int) -> None:
        with self._lock:
            self._uavs[uav].route.current_waypoint_index = index

    def remove_payload(self, uav: str, item: str) -> bool:
        with self._lock:
            payloads = self._uavs[uav].payloads
            if item in payloads:
                payloads.remove(item)
                return True
            return False

    # -- views -------------------------------------------------------------
    def world_state(self) -> dict:
        """The decision_request "world_state" block the popup renders."""
        with self._lock:
            return {"uavs": [s.popup_view() for s in self._uavs.values()]}
