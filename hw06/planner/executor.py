"""executor.py -- flies the search route and approved responses, then resumes (R7).

One Executor per UAV. It is a tick-driven state machine (tick() is called a
few times a second by the planner loop), never a blocking script, so:
  * cancel takes effect on the next tick, mid-step;
  * unit tests can drive it with a FakeUavClient and FakeClock.

All flight goes through uav/<id>/command (takeoff / goto / circle /
interrupt, as listed in lab/ARCHITECTURE.md). Commands that wait on arrival
are re-sent every command_resend_s, the same self-healing pattern as
lab/scripts/test_flight.py, because commands travel over UDP to SITL.

Route resume: when a response is accepted, the index of the waypoint the UAV
was *heading to* is stored before it leaves the route; afterwards (COMPLETED,
FAILED or CANCELLED) the UAV is sent back to that same waypoint.

Responses are sequences of steps:
  hover_stream   goto(standoff point, transit alt) -> hold(duration_s)
  circle_stream  goto(radius_m due NORTH of target) -> circle(degrees for duration_s)
                 (the backend's circle always starts at bearing 0 --
                  ARCHITECTURE.md, scripts/test_circle.py)
  deliver        goto(target, transit alt) -> goto(target, delivery_alt_m)
                 -> hold(dwell_s) -> release -> goto(target, transit alt)

There is no release primitive in ARCHITECTURE.md, so release is simulated in
the planner: the item is removed from the world-model payload list and a
behavior_status "payload released: <item>" is published.
"""
from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from . import mqtt_bus
from .clock import Clock
from .config import MissionConfig
from .mqtt_bus import Bus, UavClient
from .world_model import WorldModel, distance_m, enu_m, offset_latlon

log = logging.getLogger("planner.executor")

SEARCH_BEHAVIOR = "search_route"


class Mode(str, Enum):
    IDLE = "IDLE"
    TAKING_OFF = "TAKING_OFF"
    SEARCHING = "SEARCHING"
    RESPONDING = "RESPONDING"
    ROUTE_DONE = "ROUTE_DONE"


# -- steps ------------------------------------------------------------------
class Step:
    label = "step"
    timeout_s: float | None = None

    def start(self, ex: "Executor", t: dict) -> None: ...

    def poll(self, ex: "Executor", t: dict) -> bool:
        return True


@dataclass
class GotoStep(Step):
    lat: float
    lon: float
    alt: float
    label: str = "goto"
    timeout_s: float | None = None
    _next_send: float = 0.0

    def start(self, ex, t):
        if self.timeout_s is None and t.get("lat") is not None:
            # generous: ~1.5 m/s plus a minute for climbs/descents and resends
            self.timeout_s = distance_m(t["lat"], t["lon"], self.lat, self.lon) / 1.5 + 60.0
        self._next_send = 0.0

    def poll(self, ex, t):
        now = ex.clock.now()
        if now >= self._next_send:
            ex.uav_client.send({"type": "goto", "lat": self.lat, "lon": self.lon, "alt": self.alt})
            self._next_send = now + ex.settings.command_resend_s
        if t.get("lat") is None or t.get("alt_rel") is None:
            return False
        close = distance_m(t["lat"], t["lon"], self.lat, self.lon) <= ex.settings.arrival_tolerance_m
        level = abs(t["alt_rel"] - self.alt) <= ex.settings.altitude_tolerance_m
        return close and level


@dataclass
class HoldStep(Step):
    seconds: float
    label: str = "hold"
    _until: float = 0.0

    def start(self, ex, t):
        self._until = ex.clock.now() + self.seconds

    def poll(self, ex, t):
        return ex.clock.now() >= self._until


@dataclass
class CircleStep(Step):
    lat: float
    lon: float
    alt: float
    radius_m: float
    speed_mps: float
    duration_s: float
    label: str = "circle"
    timeout_s: float | None = None
    _started: float = 0.0
    _seen_circling: bool = False
    _sends: int = 0

    @property
    def degrees(self) -> float:
        # angular rate = speed / radius (rad/s), as in scripts/test_circle.py
        return math.degrees(self.speed_mps * self.duration_s / self.radius_m)

    def _send(self, ex):
        ex.uav_client.send({"type": "circle", "lat": self.lat, "lon": self.lon, "alt": self.alt,
                            "radius": self.radius_m, "degrees": self.degrees, "speed": self.speed_mps})
        self._sends += 1

    def start(self, ex, t):
        self.timeout_s = self.duration_s + 60.0
        self._started = ex.clock.now()
        self._send(ex)

    def poll(self, ex, t):
        elapsed = ex.clock.now() - self._started
        if t.get("activity") == "circling":
            self._seen_circling = True
        elif self._seen_circling:
            return True              # the backend finished the sweep by itself
        elif elapsed > 3.0 * self._sends and self._sends < 3:
            self._send(ex)           # never saw it start: the command may have been dropped
        return elapsed >= self.duration_s + 2.0


@dataclass
class CallStep(Step):
    fn: Callable[[], None]
    label: str = "call"

    def start(self, ex, t):
        self.fn()


@dataclass
class TakeoffStep(Step):
    alt: float
    label: str = "takeoff"
    timeout_s: float | None = None
    _next_send: float = 0.0

    def poll(self, ex, t):
        now = ex.clock.now()
        if now >= self._next_send:
            ex.uav_client.send({"type": "takeoff", "alt": self.alt})
            self._next_send = now + ex.settings.command_resend_s
        return bool(t.get("armed")) and (t.get("alt_rel") or 0.0) >= 0.9 * self.alt


# -- the executor -----------------------------------------------------------
@dataclass
class ActiveResponse:
    action_id: str
    action: dict
    resume_index: int
    steps: list[Step] = field(default_factory=list)
    step_index: int = -1
    step_started: float = 0.0
    started: bool = False


class Executor:
    def __init__(self, uav: str, world: WorldModel, uav_client: UavClient, bus: Bus, clock: Clock,
                 on_state: Callable[[str, str], None] | None = None):
        self.uav = uav
        self.world = world
        self.config: MissionConfig = world.config
        self.settings = self.config.planner
        self.uav_client = uav_client
        self.bus = bus
        self.clock = clock
        self.on_state = on_state            # (action_id, state) -> None
        self.mode = Mode.IDLE
        self.last_resume_index: int | None = None
        self._response: ActiveResponse | None = None
        self._cancel_requested: str | None = None
        self._route_step: Step | None = None
        self._takeoff: TakeoffStep | None = None
        self._lock = threading.RLock()

    # -- public API (any thread) -------------------------------------------
    @property
    def route(self):
        return self.world.uav(self.uav).route

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._response is not None

    @property
    def active_action_id(self) -> str | None:
        with self._lock:
            return self._response.action_id if self._response else None

    def start(self) -> None:
        """Begin the mission: take off if needed, then fly the search route."""
        with self._lock:
            if self.mode is Mode.IDLE:
                self.mode = Mode.TAKING_OFF
                self.world.set_behavior(self.uav, "taking_off")

    def submit(self, action_id: str, action: dict) -> None:
        """Accept a validated action. Reports PENDING now; flying starts on
        the next tick. Captures the resume waypoint before leaving the route."""
        with self._lock:
            if self._response is not None:
                raise RuntimeError(f"UAV {self.uav} is already executing {self._response.action_id}")
            resume = self.route.current_waypoint_index
            self._response = ActiveResponse(action_id, action, resume)
            self.last_resume_index = resume
            self.world.set_behavior(self.uav, action["type"], action_id)
            self._status(action_id, action["type"], "PENDING",
                         f"{action['type']} approved; will resume at {self._wp_text(resume)}")

    def cancel(self, action_id: str | None = None) -> bool:
        """Stop the current response (if action_id matches, or is None) and
        resume the route. Returns False if there was nothing to cancel."""
        with self._lock:
            if self._response is None:
                return False
            if action_id is not None and action_id != self._response.action_id:
                log.info("Ignoring cancel for %s: current response is %s", action_id, self._response.action_id)
                return False
            self._cancel_requested = self._response.action_id
            return True

    # -- the loop -----------------------------------------------------------
    def tick(self) -> None:
        with self._lock:
            t = self.uav_client.telemetry()
            if self._cancel_requested:
                self._finish("CANCELLED", "cancelled by operator; resuming search")
            if t is None or self.mode is Mode.IDLE:
                return
            if self.mode is Mode.TAKING_OFF:
                self._tick_takeoff(t)
                return
            if self._response is not None:
                self._tick_response(t)
            elif self.mode is Mode.SEARCHING:
                self._tick_route(t)

    def _tick_takeoff(self, t: dict) -> None:
        alt = self.route.waypoints[0].alt if self.route.waypoints else self.config.defaults.transit_alt_m
        if self._takeoff is None:
            if t.get("armed") and (t.get("alt_rel") or 0.0) >= 0.9 * alt:
                self._enter_search()      # already airborne (e.g. planner restarted)
                return
            self._takeoff = TakeoffStep(alt)
            log.info("UAV %s taking off to %.0f m", self.uav, alt)
        if self._takeoff.poll(self, t):
            self._takeoff = None
            self._enter_search()

    def _enter_search(self) -> None:
        self.mode = Mode.SEARCHING
        if self._response is None:
            self._route_step = None
            self.world.set_behavior(self.uav, SEARCH_BEHAVIOR)
            self._route_status()

    def _tick_route(self, t: dict) -> None:
        route = self.route
        wp = route.current
        if wp is None:
            return
        if self._route_step is None:
            self._route_step = GotoStep(wp.lat, wp.lon, wp.alt, label="route")
            self._route_step.start(self, t)
        if self._route_step.poll(self, t):
            nxt = route.current_waypoint_index + 1
            if nxt >= len(route.waypoints):
                if not self.settings.loop_route:
                    self.mode = Mode.ROUTE_DONE
                    self.world.set_behavior(self.uav, "route_complete")
                    self._status(None, SEARCH_BEHAVIOR, "COMPLETED", "search route complete; holding")
                    return
                nxt = 0
                route.laps += 1
            self.world.set_route_index(self.uav, nxt)
            self._route_step = None
            self._route_status()

    def _tick_response(self, t: dict) -> None:
        r = self._response
        if not r.started:
            if t.get("lat") is None:
                return
            r.steps = self._plan(r.action, t)
            r.started = True
            self.mode = Mode.RESPONDING
            self._route_step = None
            stream = r.action["type"] in ("hover_stream", "circle_stream")
            self._status(r.action_id, r.action["type"], "RUNNING",
                         f"{r.action['type']}: leaving route at {self._wp_text(r.resume_index)}",
                         stream_required=stream)
            self._advance(r, t)
            return
        step = r.steps[r.step_index]
        if step.timeout_s is not None and self.clock.now() - r.step_started > step.timeout_s:
            self.uav_client.send({"type": "interrupt"})
            self._finish("FAILED", f"step '{step.label}' did not finish within {step.timeout_s:.0f}s; resuming search")
            return
        if step.poll(self, t):
            self._advance(r, t)

    def _advance(self, r: ActiveResponse, t: dict) -> None:
        r.step_index += 1
        if r.step_index >= len(r.steps):
            self._finish("COMPLETED", f"{r.action['type']} complete; resuming at {self._wp_text(r.resume_index)}")
            return
        step = r.steps[r.step_index]
        r.step_started = self.clock.now()
        step.start(self, t)
        if step.label not in ("release",):    # release reports itself
            self._status(r.action_id, r.action["type"], "RUNNING", step.label,
                         stream_required=r.action["type"] in ("hover_stream", "circle_stream"))
        if isinstance(step, CallStep):        # instantaneous: don't wait a tick
            self._advance(r, t)

    def _finish(self, state: str, detail: str) -> None:
        r = self._response
        self._cancel_requested = None
        if r is None:
            return
        if state == "CANCELLED":
            self.uav_client.send({"type": "interrupt"})
        self._status(r.action_id, r.action["type"], state, detail)
        self._response = None
        # resume: same waypoint the UAV was heading to before it left
        self.world.set_route_index(self.uav, r.resume_index)
        self._route_step = None
        if self.mode is Mode.RESPONDING:
            self.mode = Mode.SEARCHING
        if self.mode is Mode.SEARCHING:
            self.world.set_behavior(self.uav, SEARCH_BEHAVIOR)
            self._route_status()
        else:
            self.world.set_behavior(self.uav, "taking_off" if self.mode is Mode.TAKING_OFF else None)

    # -- planning one response ---------------------------------------------
    def _plan(self, action: dict, t: dict) -> list[Step]:
        d = self.config.defaults
        p = action["parameters"]
        lat, lon = action["target"]["lat"], action["target"]["lon"]
        transit = d.transit_alt_m
        rtype = action["type"]
        if rtype == "hover_stream":
            hlat, hlon = self._standoff_point(lat, lon, float(p["standoff_m"]), t)
            return [GotoStep(hlat, hlon, transit, label=f"flying to {p['standoff_m']:g} m standoff"),
                    HoldStep(float(p["duration_s"]), label=f"hovering and streaming for {p['duration_s']:g} s")]
        if rtype == "circle_stream":
            radius = float(p["radius_m"])
            slat, slon = offset_latlon(lat, lon, 0.0, radius)     # due north of the target
            return [GotoStep(slat, slon, transit, label=f"flying to circle start ({radius:g} m north of target)"),
                    CircleStep(lat, lon, transit, radius, float(p["speed_mps"]), float(p["duration_s"]),
                               label=f"circling at {radius:g} m for {p['duration_s']:g} s")]
        if rtype == "deliver":
            item = p["item"]
            low = float(p["delivery_alt_m"])
            return [GotoStep(lat, lon, transit, label="flying to delivery point"),
                    GotoStep(lat, lon, low, label=f"descending to {low:g} m"),
                    HoldStep(float(p["dwell_s"]), label=f"dwelling {p['dwell_s']:g} s"),
                    CallStep(lambda: self._release(action, item), label="release"),
                    GotoStep(lat, lon, transit, label=f"climbing out to {transit:g} m")]
        raise ValueError(f"unknown response type {rtype!r}")

    @staticmethod
    def _standoff_point(lat: float, lon: float, standoff_m: float, t: dict) -> tuple[float, float]:
        """standoff_m from the target, on the side the UAV is approaching from."""
        if standoff_m <= 0:
            return lat, lon
        east, north = enu_m(lat, lon, t["lat"], t["lon"])
        norm = math.hypot(east, north)
        if norm < 0.5:
            east, north, norm = 0.0, 1.0, 1.0
        return offset_latlon(lat, lon, east / norm * standoff_m, north / norm * standoff_m)

    def _release(self, action: dict, item: str) -> None:
        # Simulated: there is no release command in ARCHITECTURE.md.
        removed = self.world.remove_payload(self.uav, item)
        log.info("UAV %s released %s (removed=%s)", self.uav, item, removed)
        self._status(self._response.action_id, action["type"], "RUNNING", f"payload released: {item}")

    # -- reporting ------------------------------------------------------------
    def _wp_text(self, index: int) -> str:
        return f"waypoint {index + 1} of {len(self.route.waypoints)}"

    def _route_status(self) -> None:
        self._status(None, SEARCH_BEHAVIOR, "RUNNING",
                     f"searching: heading to {self._wp_text(self.route.current_waypoint_index)}")

    def _status(self, action_id: str | None, behavior: str, state: str, detail: str,
                stream_required: bool = False) -> None:
        """mission/behavior_status, keyed as hotl_popup.py reads it."""
        payload = {"uav": self.uav, "action_id": action_id, "behavior": behavior, "state": state,
                   "detail": detail}
        if stream_required:
            payload["stream_required"] = True
        self.bus.publish(mqtt_bus.BEHAVIOR_STATUS, payload)
        if action_id is not None and self.on_state is not None:
            self.on_state(action_id, state)
