"""dashboard.py -- live mission dashboard for the HW6 planner (PyQt5).

    python -m planner.gui.dashboard [--host localhost] [--port 1883]

A separate process from both the planner and the popup. It observes
mission/# and uav/+/telemetry and rebuilds its own picture of the mission
(MissionMirror) from that traffic alone -- it never imports or queries the
running planner, and it never flies the UAV. The only things it publishes
are things an operator or detector could publish anyway:

  Inject Event       mission/events      (same payload as lesson6/inject_event.py)
  Simulate Timeout   mission/decision    {"request_id": ..., "action": null}
  Cancel response    mission/cancel      (same payload as the popup's Cancel)

Route progress and the resume waypoint come from the planner's
behavior_status `detail` text ("heading to waypoint N of M", "resume at
waypoint N of M"), since the popup contract has no structured field for them
and we don't invent payload keys.

Threading: paho calls back on its own thread; every message is re-emitted as
a Qt signal so the mirror and widgets are only touched on the GUI thread.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QAction, QApplication, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLineEdit, QMainWindow,
    QSplitter, QVBoxLayout, QWidget,
)

from .. import mqtt_bus
from ..config import MissionConfig, color_for, load_config
from ..mqtt_bus import MqttBus
from ..person_registry import PersonRegistry
from ..world_model import offset_latlon
from .widgets import Legend, LogPane, MapView, StatePanel

WAYPOINT_RE = re.compile(r"heading to waypoint (\d+) of (\d+)")
RESUME_RE = re.compile(r"resume at waypoint (\d+) of (\d+)")
RELEASED_RE = re.compile(r"payload released: (\S+)")
TERMINAL = ("COMPLETED", "FAILED", "CANCELLED")

DIRECTIONS = {
    mqtt_bus.EVENTS: "detector→planner",
    mqtt_bus.DECISION_REQUEST: "planner→operator",
    mqtt_bus.ACTION_RESULT: "planner→operator",
    mqtt_bus.BEHAVIOR_STATUS: "planner→operator",
    mqtt_bus.DECISION: "operator→planner",
    mqtt_bus.CANCEL: "operator→planner",
    mqtt_bus.ABORT: "operator→planner",
}


@dataclass
class UavView:
    uav: str
    color: str
    payloads: list[str]
    lat: float | None = None
    lon: float | None = None
    alt_rel: float | None = None
    heading: float | None = None
    battery_level: float | None = None
    current_behavior: str | None = None
    route_index: int | None = None        # 0-based waypoint it's heading to
    resume_index: int | None = None       # 0-based waypoint it will resume to
    response: dict | None = None          # action_id, type, state, detail, target, parameters
    trail: deque = field(default_factory=lambda: deque(maxlen=400))


@dataclass
class PersonView:
    status: str = "unknown"
    action_id: str | None = None
    request_id: str | None = None
    deadline: float | None = None
    candidates: list[dict] = field(default_factory=list)
    last_result: dict | None = None


class MissionMirror:
    """The dashboard's model of the mission, built only from MQTT traffic.
    Pure Python (no Qt) so it can be unit tested."""

    def __init__(self, config: MissionConfig):
        self.config = config
        self.routes = {uav: config.route_for(uav) for uav in config.owned_uavs}
        self.uavs = {uav: UavView(uav, color_for(uav), list(config.payloads.get(uav, [])))
                     for uav in config.owned_uavs}
        self.registry = PersonRegistry(config.planner.merge_radius_m)
        self.views: dict[str, PersonView] = {}
        self._by_event: dict[str, str] = {}      # event_id -> person_id
        self._by_request: dict[str, str] = {}    # request_id -> person_id
        self._by_action: dict[str, str] = {}     # action_id -> person_id
        self._decisions: dict[str, dict] = {}    # request_id -> chosen action

    # -- input ----------------------------------------------------------------
    def on_message(self, topic: str, p: dict, now: float | None = None) -> str | None:
        """Update the mirror; return a one-line log summary (None = don't log)."""
        now = now or time.time()
        if topic.startswith("uav/") and topic.endswith("/telemetry"):
            self._telemetry(topic.split("/")[1], p)
            return None
        handler = {
            mqtt_bus.EVENTS: self._event, mqtt_bus.DECISION_REQUEST: self._request,
            mqtt_bus.DECISION: self._decision, mqtt_bus.ACTION_RESULT: self._result,
            mqtt_bus.BEHAVIOR_STATUS: self._status, mqtt_bus.CANCEL: self._cancel,
            mqtt_bus.ABORT: lambda p, now: f"UAV {p.get('uav')} abort (RTL)",
        }.get(topic)
        return handler(p, now) if handler else None

    def _telemetry(self, uav: str, t: dict) -> None:
        u = self.uavs.get(uav)
        if u is None:
            return
        for key in ("lat", "lon", "alt_rel", "heading", "battery_level"):
            if t.get(key) is not None:
                setattr(u, key, t[key])
        if u.lat is not None and (not u.trail or u.trail[-1] != (u.lat, u.lon)):
            u.trail.append((u.lat, u.lon))

    def _person_for_event(self, event: dict) -> str:
        pid = self._by_event.get(event.get("event_id"))
        if pid is None:
            pid = self.registry.observe(event).person_id
            self._by_event[event["event_id"]] = pid
            self.views.setdefault(pid, PersonView())
        return pid

    def _event(self, e: dict, now: float) -> str:
        if "lat" in e and "lon" in e and "event_id" in e:
            self._person_for_event(e)
        return (f"{e.get('event_id')} {e.get('type')} at {float(e.get('lat', 0)):.6f}, {float(e.get('lon', 0)):.6f} "
                f"conf {float(e.get('confidence') or 0):.2f} from UAV {e.get('source_uav')}")

    def _request(self, r: dict, now: float) -> str:
        pid = self._person_for_event(r["event"])
        view = self.views[pid]
        view.status = "rejected" if r.get("previous_rejection") else "pending"
        view.request_id = r["request_id"]
        view.deadline = now + float(r.get("timeout_s") or 180)
        view.candidates = r.get("candidates") or []
        self._by_request[r["request_id"]] = pid
        for w in (r.get("world_state") or {}).get("uavs", []):
            u = self.uavs.get(str(w.get("uav")))
            if u is not None:
                u.payloads = list(w.get("payloads") or [])
                u.current_behavior = w.get("current_behavior")
        menu = ", ".join(c["type"] for c in view.candidates)
        again = f"  re-ask after: {' '.join(r['previous_rejection'])}" if r.get("previous_rejection") else ""
        return f"{r['request_id']} for {pid} (event {r['event'].get('event_id')}): [{menu}]{again}"

    def _decision(self, d: dict, now: float) -> str:
        pid = self._by_request.get(d.get("request_id"))
        view = self.views.get(pid) if pid else None
        if d.get("dismiss"):
            if view:
                view.status, view.deadline = "dismissed", None
            return f"{d.get('request_id')}: No action (dismiss)"
        action = d.get("action")
        if isinstance(action, dict):
            self._decisions[d["request_id"]] = action
            if view:
                view.deadline = None
            return f"{d.get('request_id')}: {action.get('type')} on UAV {action.get('uav')} {action.get('parameters')}"
        if view:
            view.status, view.deadline = "unknown", None
        return f"{d.get('request_id')}: no answer (simulated timeout)"

    def _result(self, r: dict, now: float) -> str:
        pid = self._by_request.get(r.get("request_id"))
        view = self.views.get(pid) if pid else None
        if view:
            view.last_result = r
        if r.get("approved"):
            if view:
                view.status, view.action_id = "approved", r.get("action_id")
                self._by_action[r["action_id"]] = pid
            action = self._decisions.get(r.get("request_id"), {})
            u = self.uavs.get(str(r.get("uav")))
            if u is not None:
                u.response = {"action_id": r.get("action_id"), "type": r.get("type"), "state": "PENDING",
                              "detail": "", "target": action.get("target"), "parameters": action.get("parameters")}
            return f"{r.get('request_id')}: APPROVED {r.get('type')} on UAV {r.get('uav')} as {r.get('action_id')}"
        if view:
            view.status = "rejected"
        return f"{r.get('request_id')}: REJECTED {r.get('type')} on UAV {r.get('uav')}: {' '.join(r.get('reasons') or [])}"

    def _status(self, s: dict, now: float) -> str:
        u = self.uavs.get(str(s.get("uav")))
        detail, state, action_id = s.get("detail") or "", s.get("state"), s.get("action_id")
        if u is not None:
            m = WAYPOINT_RE.search(detail)
            if m:
                u.route_index = int(m.group(1)) - 1
            m = RESUME_RE.search(detail)
            if m and state not in TERMINAL:
                u.resume_index = int(m.group(1)) - 1
            m = RELEASED_RE.search(detail)
            if m and m.group(1) in u.payloads:
                u.payloads.remove(m.group(1))
            if state in ("PENDING", "RUNNING"):
                u.current_behavior = s.get("behavior")
            if action_id:
                if u.response is None or u.response.get("action_id") != action_id:
                    u.response = {"action_id": action_id, "type": s.get("behavior"), "target": None, "parameters": None}
                u.response.update(state=state, detail=detail)
                if state in TERMINAL:
                    u.resume_index = None
        pid = self._by_action.get(action_id) if action_id else None
        if pid and state == "COMPLETED":
            self.views[pid].status = "completed"
        return f"UAV {s.get('uav')} {s.get('behavior')} {state} [{action_id or '-'}]: {detail}"

    def _cancel(self, c: dict, now: float) -> str:
        return f"UAV {c.get('uav')} cancel action {c.get('action_id')}"

    # -- views for the widgets -------------------------------------------------------
    def _display_status(self, view: PersonView, now: float) -> str:
        if view.status in ("pending", "rejected") and view.deadline and now > view.deadline:
            return "unknown"     # timed out: undecided, may be asked again
        return view.status

    def person_rows(self, now: float | None = None) -> list[dict]:
        now = now or time.time()
        rows = []
        for p in self.registry.all():
            view = self.views.setdefault(p.person_id, PersonView())
            rows.append({"id": p.person_id, "lat": p.lat, "lon": p.lon, "confidence": p.confidence,
                         "source": f"UAV {p.source_uav}" + (f" ({p.source_drone})" if p.source_drone else ""),
                         "status": self._display_status(view, now), "action_id": view.action_id})
        return rows

    def person_detail(self, person_id: str) -> dict | None:
        p = self.registry.get(person_id)
        if p is None:
            return None
        view = self.views.setdefault(person_id, PersonView())
        return {"id": p.person_id, "status": self._display_status(view, time.time()), "confidence": p.confidence,
                "sightings": p.sightings, "event_ids": p.event_ids, "candidates": view.candidates,
                "last_result": view.last_result}

    def open_request(self, person_id: str | None = None) -> str | None:
        """Request id still awaiting an answer: the given person's, else the newest."""
        now = time.time()
        candidates = [(pid, v) for pid, v in self.views.items()
                      if v.request_id and v.deadline and now <= v.deadline and v.status in ("pending", "rejected")]
        for pid, v in candidates:
            if pid == person_id:
                return v.request_id
        return max(candidates, key=lambda pv: pv[1].deadline)[1].request_id if candidates else None

    def active_response(self) -> tuple[str, str] | None:
        for uav, u in self.uavs.items():
            if u.response and u.response.get("state") in ("PENDING", "RUNNING"):
                return uav, u.response["action_id"]
        return None


class Bridge(QObject):
    """MQTT (paho thread) -> Qt signal (GUI thread)."""

    message = pyqtSignal(str, object)

    def __init__(self, bus: MqttBus):
        super().__init__()
        self.bus = bus
        bus.subscribe("mission/#", self._relay, qos=1)
        bus.subscribe("uav/+/telemetry", self._relay)

    def _relay(self, topic: str, payload: dict) -> None:
        self.message.emit(topic, payload)


class InjectDialog(QDialog):
    def __init__(self, lat: float, lon: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Inject person event")
        form = QFormLayout(self)
        self.lat, self.lon = QDoubleSpinBox(), QDoubleSpinBox()
        for box, value, lo, hi in ((self.lat, lat, -90, 90), (self.lon, lon, -180, 180)):
            box.setDecimals(7)
            box.setRange(lo, hi)
            box.setSingleStep(0.0001)
            box.setValue(value)
        self.conf = QDoubleSpinBox()
        self.conf.setRange(0, 1)
        self.conf.setSingleStep(0.05)
        self.conf.setValue(0.82)
        self.uav = QLineEdit("1")
        for name, w in (("Latitude", self.lat), ("Longitude", self.lon), ("Confidence", self.conf),
                        ("Seen by UAV", self.uav)):
            form.addRow(name, w)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def event_payload(self) -> dict:
        # exactly lesson6/inject_event.py's message
        return {"event_id": uuid.uuid4().hex[:8], "type": "person", "lat": self.lat.value(), "lon": self.lon.value(),
                "confidence": self.conf.value(), "source_uav": self.uav.text().strip() or "1",
                "source_drone": None, "timestamp": time.time(), "image_b64": None}


class Dashboard(QMainWindow):
    def __init__(self, bus: MqttBus, config: MissionConfig):
        super().__init__()
        self.bus = bus
        self.mirror = MissionMirror(config)
        self.setWindowTitle("HW6 mission dashboard")
        self.resize(1400, 900)
        self.paused = False
        self._picked: tuple[float, float] | None = None

        self.map = MapView(self.mirror)
        self.map.location_picked.connect(self._on_picked)
        self.panel = StatePanel(self.mirror)
        self.log = LogPane()

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.map, 1)
        lv.addWidget(Legend())
        top = QSplitter(Qt.Horizontal)
        top.addWidget(left)
        top.addWidget(self.panel)
        top.setStretchFactor(0, 3)
        top.setStretchFactor(1, 2)
        main = QSplitter(Qt.Vertical)
        main.addWidget(top)
        main.addWidget(self.log)
        main.setStretchFactor(0, 4)
        main.setStretchFactor(1, 1)
        self.setCentralWidget(main)

        tb = self.addToolBar("Mission")
        tb.addAction(QAction("Inject Event", self, triggered=self.inject_event))
        tb.addAction(QAction("Simulate Timeout", self, triggered=self.simulate_timeout))
        tb.addAction(QAction("Cancel current response", self, triggered=self.cancel_response))
        tb.addSeparator()
        self.pause_action = QAction("Pause", self, checkable=True, toggled=self._on_pause)
        self.follow_action = QAction("Follow UAV", self, checkable=True, toggled=self._on_follow)
        tb.addAction(self.pause_action)
        tb.addAction(self.follow_action)
        tb.addSeparator()
        tb.addAction(QAction("Fit route", self, triggered=self._fit))
        self.statusBar().showMessage(f"MQTT {bus.host}:{bus.port} — double-click the map to inject an event there")

        self.bridge = Bridge(bus)
        self.bridge.message.connect(self._on_message)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(200)

    # -- incoming ----------------------------------------------------------------
    def _on_message(self, topic: str, payload: dict) -> None:
        summary = self.mirror.on_message(topic, payload)
        if summary is not None:
            self.log.add(DIRECTIONS.get(topic, "?"), topic, summary)

    def refresh(self) -> None:
        if self.paused:
            return
        self.map.refresh()
        self.panel.refresh()
        self._maybe_snap()

    # -- evidence capture (--snap-running) ------------------------------------------
    snap_dir: str | None = None
    snap_delay_s: float = 4.0
    _running_since: dict | None = None

    def _maybe_snap(self) -> None:
        """Save one PNG per response, snap_delay_s after it starts RUNNING
        (so the UAV has left the route and the resume marker is showing)."""
        if not self.snap_dir:
            return
        self._running_since = self._running_since or {}
        for u in self.mirror.uavs.values():
            r = u.response
            if not r or r.get("state") != "RUNNING" or r.get("snapped"):
                continue
            since = self._running_since.setdefault(r["action_id"], time.time())
            if time.time() - since >= self.snap_delay_s:
                path = os.path.join(self.snap_dir, f"{r['type']}-{r['action_id']}-RUNNING.png")
                self.grab().save(path)
                r["snapped"] = True
                self.statusBar().showMessage(f"saved {path}", 5000)

    # -- toolbar ------------------------------------------------------------------
    def _default_location(self) -> tuple[float, float]:
        if self._picked:
            return self._picked
        u = next(iter(self.mirror.uavs.values()), None)
        if u is not None and u.lat is not None:
            return offset_latlon(u.lat, u.lon, 30.0, 0.0)
        return self.map.origin

    def _on_picked(self, lat: float, lon: float) -> None:
        self._picked = (lat, lon)
        self.inject_event()

    def inject_event(self) -> None:
        lat, lon = self._default_location()
        dialog = InjectDialog(lat, lon, self)
        if dialog.exec_() == QDialog.Accepted:
            self.bus.publish(mqtt_bus.EVENTS, dialog.event_payload(), qos=1)
        self._picked = None

    def simulate_timeout(self) -> None:
        request_id = self.mirror.open_request(self.panel.selected)
        if request_id is None:
            self.statusBar().showMessage("No open decision request to time out", 5000)
            return
        self.bus.publish(mqtt_bus.DECISION, {"request_id": request_id, "action": None})
        self.statusBar().showMessage(f"Sent 'no answer' for request {request_id}", 5000)

    def cancel_response(self) -> None:
        active = self.mirror.active_response()
        if active is None:
            self.statusBar().showMessage("No response is running", 5000)
            return
        uav, action_id = active
        self.bus.publish(mqtt_bus.CANCEL, {"uav": uav, "action_id": action_id})

    def _on_pause(self, paused: bool) -> None:
        self.paused = paused

    def _on_follow(self, follow: bool) -> None:
        self.map.follow = follow

    def _fit(self) -> None:
        self.map._user_zoomed = False
        self.map.fit_route()


def main() -> None:
    parser = argparse.ArgumentParser(description="HW6 live mission dashboard")
    parser.add_argument("--host", default=os.environ.get("MQTT_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    parser.add_argument("--config", default=None)
    parser.add_argument("--screenshot", default=None, help="save a PNG of the window after --after seconds, then exit")
    parser.add_argument("--after", type=float, default=5.0)
    parser.add_argument("--snap-running", default=None, metavar="DIR",
                        help="save a PNG of every response a few seconds after it goes RUNNING")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    bus = MqttBus(args.host, args.port)
    window = Dashboard(bus, load_config(args.config))
    if args.snap_running:
        os.makedirs(args.snap_running, exist_ok=True)
        window.snap_dir = args.snap_running
    if not bus.connect():
        window.statusBar().showMessage(f"Could not reach MQTT broker at {args.host}:{args.port} — showing route only")
    window.show()
    if args.screenshot:
        def snap():
            window.refresh()
            window.grab().save(args.screenshot)
            app.quit()
        QTimer.singleShot(int(args.after * 1000), snap)
    code = app.exec_()
    bus.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
