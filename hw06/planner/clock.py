"""clock.py -- time as an injected dependency.

Everything time-dependent (decision timeouts, hover/dwell durations, command
resends) asks a Clock instead of calling time.time()/sleep() directly, so
unit tests drive it with tests/conftest.py's FakeClock and never really wait.
"""
from __future__ import annotations

import threading
import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...

    def wait(self, event: threading.Event, timeout_s: float) -> bool:
        """Block until `event` is set or timeout_s elapses; True if set."""
        ...


class SystemClock:
    def now(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def wait(self, event: threading.Event, timeout_s: float) -> bool:
        return event.wait(timeout_s)
