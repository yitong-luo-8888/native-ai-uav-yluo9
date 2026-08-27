from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class Drone:
    name: str
    lat: float
    lon: float
    alt: float
    phys_h_m: float = 0.3
    heading_rad: float = 0.0
    att_q: Optional[Tuple[float, float, float, float]] = None

    status: str = ""           # e.g., "STANDBY", "ACTIVE"
    mode: str = ""             # e.g., "LOITER", "OFFBOARD", "LAND"
    onboard_pilot: str = ""    # e.g., "ReceiveMission", "Takeoff"
    air_lease_state: str = ""  # e.g., "IDLE"
    heartbeat_status: str = "" # e.g., "CONTINUE"
    state_type: str = ""       # e.g., "Waypoint"
    voltage: float = 0.0
    battery_level: float = 0.0    # 0.0–1.0
    battery_current: Optional[float] = None  # amps
    speed: Optional[float] = None            # m/s
    armed: Optional[bool] = None
    geofence: Optional[bool] = None

    # Render (smoothed) geodetic pose
    r_lat: Optional[float] = None
    r_lon: Optional[float] = None
    r_alt: Optional[float] = None

    # Render (smoothed) heading
    r_heading_rad: Optional[float] = None

    # Smoothed camera-relative angles and range
    s_az: Optional[float] = None
    s_elev: Optional[float] = None
    s_rng: Optional[float] = None

    # Signed forward depth (meters); <0 means behind camera
    s_depth: Optional[float] = None

    # Timestamp of last target update
    t_updated: float = 0.0
