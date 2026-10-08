"""main.py -- the Planner (event -> decision -> validation -> execution) and its wiring.

    mission/events -> Planner.handle_event
        PersonRegistry.observe            merge into a known person (R3)
        PersonRegistry.claim_for_decision ask only if UNDECIDED (R3)
        -> decision loop (worker thread):
            build_candidates              menu + R2 policy (R4)
            DecisionSource.decide         popup / AI / test stub (R5)
            Validator.validate            every action, whoever chose it (R6)
            mission/action_result         every verdict
            rejected -> re-ask: same event, new request_id, previous_rejection
            approved -> Executor.submit   fly it, then resume the route (R7)
    mission/cancel -> Executor.cancel

Every collaborator is injected (bus, UAV clients, clock, decision source,
runner), so tests build a Planner with fakes and drive it synchronously.

    python -m planner.main [--config PATH] [--host localhost] [--port 1883]
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
import uuid
from typing import Callable

from . import mqtt_bus
from .candidates import build_candidates
from .clock import Clock, SystemClock
from .config import MissionConfig, load_config
from .decision_source import DISMISS, DecisionRequest, DecisionSource, HumanDecisionSource
from .executor import Executor
from .mqtt_bus import Bus, MqttBus, MqttUavClient, UavClient
from .person_registry import Person, PersonRegistry
from .validator import Validator
from .world_model import WorldModel

log = logging.getLogger("planner")

Runner = Callable[[Callable[[], None]], None]


def thread_runner(fn: Callable[[], None]) -> None:
    """Default Runner: each decision waits on its own thread, so several
    persons can have popups open at once and telemetry keeps flowing."""
    threading.Thread(target=fn, daemon=True, name="decision").start()


def new_id() -> str:
    return uuid.uuid4().hex[:8]


class Planner:
    def __init__(self, config: MissionConfig, bus: Bus, uav_clients: dict[str, UavClient], clock: Clock,
                 decision_source: DecisionSource, runner: Runner = thread_runner):
        self.config = config
        self.bus = bus
        self.clock = clock
        self.decision_source = decision_source
        self.runner = runner
        self.persons = PersonRegistry(config.planner.merge_radius_m)
        self.world = WorldModel(config, self.persons)
        self.validator = Validator(self.world)
        self.uav_clients = uav_clients
        self.executors = {
            uav: Executor(uav, self.world, uav_clients[uav], bus, clock, on_state=self.persons.set_response_state)
            for uav in config.owned_uavs if uav in uav_clients
        }
        self._approve_lock = threading.Lock()   # validate + submit is one step
        bus.subscribe(mqtt_bus.EVENTS, lambda _t, p: self.handle_event(p), qos=1)
        bus.subscribe(mqtt_bus.CANCEL, lambda _t, p: self.handle_cancel(p))
        bus.subscribe(mqtt_bus.ABORT, lambda _t, p: self.handle_abort(p))

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        for ex in self.executors.values():
            ex.start()

    def tick(self) -> None:
        self.refresh_telemetry()
        for ex in self.executors.values():
            ex.tick()

    def run(self, stop: threading.Event, period_s: float = 0.2) -> None:
        while not stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("Planner tick failed")
            self.clock.sleep(period_s)

    def refresh_telemetry(self) -> None:
        for uav, client in self.uav_clients.items():
            t = client.telemetry()
            if t is not None:
                self.world.update_telemetry(uav, t)

    # -- inputs ----------------------------------------------------------------
    def handle_event(self, event: dict) -> Person | None:
        if event.get("type") != "person" or "event_id" not in event:
            log.info("Ignoring non-person event %r", event.get("type"))
            return None
        try:
            float(event["lat"]), float(event["lon"])
        except (KeyError, TypeError, ValueError):
            log.warning("Ignoring event %s without a usable location", event.get("event_id"))
            return None
        duplicate = self.persons.by_event(event["event_id"])
        if duplicate is not None:
            log.debug("Duplicate delivery of event %s ignored", event["event_id"])
            return duplicate
        person = self.persons.observe(event)
        if self.persons.claim_for_decision(person):
            log.info("Event %s -> %s (conf %.2f): asking for a decision", event["event_id"],
                     person.person_id, person.confidence)
            self.runner(lambda: self._decide(person, event))
        else:
            log.info("Event %s merged into %s (%s): no new decision", event["event_id"],
                     person.person_id, person.status.value)
        return person

    def handle_cancel(self, payload: dict) -> None:
        ex = self.executors.get(str(payload.get("uav")))
        if ex is None or not ex.cancel(payload.get("action_id")):
            log.info("Nothing to cancel for %s", payload)

    def handle_abort(self, payload: dict) -> None:
        log.warning("Abort/RTL for UAV %s requested: out of scope for HW6, ignored", payload.get("uav"))

    # -- the decision loop -------------------------------------------------------
    def _decide(self, person: Person, event: dict) -> None:
        previous: list[str] = []
        while True:
            self.refresh_telemetry()
            request = DecisionRequest(
                request_id=new_id(), event=event, world_state=self.world.world_state(),
                candidates=[c.to_dict() for c in build_candidates(person.confidence, self.world)],
                timeout_s=self.config.planner.decision_timeout_s, previous_rejection=previous)
            try:
                decision = self.decision_source.decide(request)
            except Exception:
                log.exception("Decision source failed for %s; leaving %s undecided",
                              request.request_id, person.person_id)
                self.persons.mark_timed_out(person)
                return
            if decision is None:
                self.persons.mark_timed_out(person)
                return
            if decision is DISMISS:
                self.persons.mark_dismissed(person)
                return
            if self._validate_and_execute(person, request, decision):
                return
            previous = list(person.last_rejection)   # re-ask with the reasons

    def _validate_and_execute(self, person: Person, request: DecisionRequest, decision: dict) -> bool:
        self.refresh_telemetry()
        with self._approve_lock:
            verdict = self.validator.validate(decision, person.confidence)
            action = verdict.action or decision
            action_id = new_id() if verdict.approved else None
            self.bus.publish(mqtt_bus.ACTION_RESULT, {
                "request_id": request.request_id, "approved": verdict.approved, "action_id": action_id,
                "type": action.get("type"), "uav": action.get("uav"), "reasons": verdict.reasons})
            if not verdict.approved:
                log.info("Rejected %s for %s: %s", action.get("type"), person.person_id, " ".join(verdict.reasons))
                self.persons.mark_rejected(person, verdict.reasons)
                return False
            self.persons.mark_responded(person, action_id, action["type"])
            self.executors[action["uav"]].submit(action_id, action)
            log.info("Approved %s on UAV %s for %s as %s", action["type"], action["uav"],
                     person.person_id, action_id)
            return True


def build_planner(bus: Bus, config: MissionConfig | None = None, clock: Clock | None = None,
                  decision_source: DecisionSource | None = None, runner: Runner = thread_runner) -> Planner:
    """The production wiring: MQTT UAV clients and the human (popup)
    decision source. Swap decision_source for an AIDecisionSource next week."""
    config = config or load_config()
    clock = clock or SystemClock()
    uav_clients = {uav: MqttUavClient(bus, uav) for uav in config.owned_uavs}
    decision_source = decision_source or HumanDecisionSource(bus, clock)
    return Planner(config, bus, uav_clients, clock, decision_source, runner)


def main() -> None:
    parser = argparse.ArgumentParser(description="HW6 Human-on-the-Loop mission response planner")
    parser.add_argument("--config", default=None, help="mission_config.json (default: lab/lesson6/)")
    parser.add_argument("--host", default=os.environ.get("MQTT_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    parser.add_argument("--no-fly", action="store_true", help="don't take off / fly the route (decisions only)")
    parser.add_argument("--persistent-session", action="store_true",
                        help="keep a broker session so QoS-1 events survive a planner restart")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")

    config = load_config(args.config)
    bus = MqttBus(args.host, args.port, client_id="hotl-planner" if args.persistent_session else None,
                  persistent_session=args.persistent_session)
    planner = build_planner(bus, config)
    if not bus.connect():
        raise SystemExit(f"Could not reach the MQTT broker at {args.host}:{args.port} -- is `docker compose up` running in lab/?")
    log.info("Planner up: UAVs %s, deliver threshold %.2f, decision timeout %.0fs",
             ", ".join(config.owned_uavs), config.planner.deliver_min_confidence,
             config.planner.decision_timeout_s)
    if not args.no_fly:
        planner.start()

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        planner.run(stop)
    finally:
        bus.close()


if __name__ == "__main__":
    main()
