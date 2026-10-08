"""config.py -- load lab/lesson6/mission_config.json into typed settings.

Everything the planner tunes by is read from here: payloads, battery reserve
and per-response costs, response defaults, search routes. The few values
mission_config.json doesn't carry (R2 confidence threshold, R3 merge radius,
decision timeout) live in PlannerSettings, and can be overridden by an
optional "planner" block in the same JSON file.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "lab" / "lesson6" / "mission_config.json"

# new-gui names drones by color: VEHICLE_ID n is DRONE_COLORS[n-1]. Same
# list as cv/person_event_detector.py's UPDATE_DRONE_COLORS (which mirrors
# backend/drone_backend.py); the popup shows it as "UAV 1 (Fuchsia)".
DRONE_COLORS = ["Fuchsia", "Navy", "Purple", "Aqua", "Lime", "Orange", "Yellow"]

RESPONSE_TYPES = ("hover_stream", "circle_stream", "deliver")


def color_for(uav: str) -> str:
    try:
        return DRONE_COLORS[int(uav) - 1]
    except (ValueError, IndexError):
        return "unknown"


@dataclass(frozen=True)
class Waypoint:
    lat: float
    lon: float
    alt: float


@dataclass(frozen=True)
class BatteryConfig:
    reserve: float
    cost: dict[str, float]


@dataclass(frozen=True)
class ResponseDefaults:
    transit_alt_m: float
    delivery_alt_m: float
    delivery_dwell_s: float
    circle_radius_m: float
    circle_speed_mps: float
    stream_duration_s: float
    hover_standoff_m: float


@dataclass(frozen=True)
class PlannerSettings:
    """Planner policy values that mission_config.json doesn't define."""

    # R2: below this, only verify-only responses are offered (see design.md).
    deliver_min_confidence: float = 0.35
    # R3: events this close to a known person are the same person. Matches
    # the detector's DEDUP_RADIUS_M.
    merge_radius_m: float = 10.0
    # R5: advertised to the popup as timeout_s and enforced by the planner.
    decision_timeout_s: float = 180.0
    # Executor tuning.
    arrival_tolerance_m: float = 2.5
    altitude_tolerance_m: float = 1.0
    command_resend_s: float = 8.0
    loop_route: bool = True


@dataclass(frozen=True)
class MissionConfig:
    owned_uavs: list[str]
    payloads: dict[str, list[str]]
    battery: BatteryConfig
    defaults: ResponseDefaults
    routes: dict[str, list[Waypoint]]
    planner: PlannerSettings = field(default_factory=PlannerSettings)
    source_path: str | None = None

    def route_for(self, uav: str) -> list[Waypoint]:
        return list(self.routes.get(uav, []))

    def deliverable_items(self) -> list[str]:
        """Every item any UAV starts with, in first-seen order."""
        items: list[str] = []
        for carried in self.payloads.values():
            for item in carried:
                if item not in items:
                    items.append(item)
        return items


def _strip_comments(block: dict) -> dict:
    return {k: v for k, v in block.items() if not k.startswith("_")}


def parse_config(raw: dict, source_path: str | None = None) -> MissionConfig:
    battery = raw["battery"]
    known = PlannerSettings.__dataclass_fields__
    planner_overrides = {k: v for k, v in _strip_comments(raw.get("planner", {})).items() if k in known}
    routes = {
        uav: [Waypoint(float(lat), float(lon), float(alt)) for lat, lon, alt in mission["waypoints"]]
        for uav, mission in raw.get("missions", {}).items()
    }
    return MissionConfig(
        owned_uavs=[str(u) for u in raw["owned_uavs"]],
        payloads={str(u): list(items) for u, items in raw.get("payloads", {}).items()},
        battery=BatteryConfig(reserve=float(battery["reserve"]),
                              cost={k: float(v) for k, v in _strip_comments(battery["cost"]).items()}),
        defaults=ResponseDefaults(**{k: float(v) for k, v in _strip_comments(raw["defaults"]).items()
                                     if k in ResponseDefaults.__dataclass_fields__}),
        routes=routes,
        planner=PlannerSettings(**planner_overrides),
        source_path=source_path,
    )


def load_config(path: str | os.PathLike | None = None) -> MissionConfig:
    """Load the mission config. Lookup order: explicit path, $HOTL_MISSION_CONFIG,
    then lab/lesson6/mission_config.json in this repo."""
    path = Path(path or os.environ.get("HOTL_MISSION_CONFIG") or DEFAULT_CONFIG_PATH)
    with open(path, encoding="utf-8") as f:
        return parse_config(json.load(f), str(path))
