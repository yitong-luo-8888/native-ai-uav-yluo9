"""decision_source.py -- who chooses the response (R5). The seam for next week.

The planner hands a DecisionSource one DecisionRequest -- the event, the
world_state, the candidate menu, any previous_rejection and timeout_s -- and
gets back exactly one of:

    dict      the chosen action {type, uav, target{lat, lon}, parameters}
    DISMISS   "No action": the person is decided, never ask again
    None      no answer within timeout_s: the person stays undecided

HumanDecisionSource does that through the popup (mission/decision_request
out, mission/decision back). AIDecisionSource is next week's stand-in. The
planner never knows which one it has; the validator checks whatever comes
back either way.
"""
from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from . import mqtt_bus
from .clock import Clock
from .mqtt_bus import Bus

log = logging.getLogger("planner.decision")


class _Dismiss:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "DISMISS"


DISMISS = _Dismiss()
"""Sentinel: the operator chose "No action"."""

TIMEOUT = None
"""Sentinel: no decision within timeout_s."""

Decision = dict | _Dismiss | None


@dataclass
class DecisionRequest:
    request_id: str
    event: dict
    world_state: dict
    candidates: list[dict]
    timeout_s: float
    previous_rejection: list[str] = field(default_factory=list)

    def to_payload(self) -> dict:
        """mission/decision_request, keyed exactly as hotl_popup.py reads it."""
        payload = {"request_id": self.request_id, "event": self.event, "world_state": self.world_state,
                   "candidates": self.candidates, "timeout_s": self.timeout_s}
        if self.previous_rejection:
            payload["previous_rejection"] = list(self.previous_rejection)
        return payload


class DecisionSource(ABC):
    @abstractmethod
    def decide(self, request: DecisionRequest) -> Decision:
        """Block for at most request.timeout_s and return an action dict,
        DISMISS, or None (timeout)."""


class HumanDecisionSource(DecisionSource):
    """The operator, via the popup. Publishes the request and waits for the
    matching mission/decision. A decision for a request that already timed
    out (or was never ours) is ignored."""

    def __init__(self, bus: Bus, clock: Clock):
        self.bus = bus
        self.clock = clock
        self._pending: dict[str, dict] = {}   # request_id -> {"event": Event, "reply": dict|None}
        self._lock = threading.Lock()
        bus.subscribe(mqtt_bus.DECISION, self._on_decision)

    def decide(self, request: DecisionRequest) -> Decision:
        slot = {"event": threading.Event(), "reply": None}
        with self._lock:
            self._pending[request.request_id] = slot
        try:
            self.bus.publish(mqtt_bus.DECISION_REQUEST, request.to_payload(), qos=1)
            answered = self.clock.wait(slot["event"], request.timeout_s)
        finally:
            with self._lock:
                self._pending.pop(request.request_id, None)
        if not answered:
            log.info("Request %s timed out after %.0fs", request.request_id, request.timeout_s)
            return TIMEOUT
        return self._interpret(slot["reply"])

    @staticmethod
    def _interpret(reply: dict) -> Decision:
        if reply.get("dismiss"):
            return DISMISS
        action = reply.get("action")
        if isinstance(action, dict):
            return action
        # {"request_id": ..., "action": null}: an explicit "no answer" -- the
        # dashboard's Simulate Timeout button sends this (design.md).
        return TIMEOUT

    def _on_decision(self, topic: str, payload: dict) -> None:
        with self._lock:
            slot = self._pending.get(payload.get("request_id"))
        if slot is None:
            log.info("Ignoring decision for unknown/expired request %s", payload.get("request_id"))
            return
        slot["reply"] = payload
        slot["event"].set()


class AIDecisionSource(DecisionSource):
    """Next week: an AI chooses from the same menu with the same inputs.
    Swap it in for HumanDecisionSource in main.build_planner(); nothing else
    changes, and its choices still go through the Validator."""

    def __init__(self, model: str | None = None):
        self.model = model

    def decide(self, request: DecisionRequest) -> Decision:
        raise NotImplementedError("AIDecisionSource is next week's work (HW7)")
