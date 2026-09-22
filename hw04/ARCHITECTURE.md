# Architecture

## Overall shape

SITL is the simulated drone, emulating the key hardware and sensors — GPS,
arm checks, magnetometer, battery. It's the source of truth for what the
drone is doing, and where injected disturbances show up as abnormal
parameter values. The `drone_backend` sits between SITL and the broker,
using `mavlink_lib` to speak MAVLink to SITL in both directions and
`monitor_signals` to translate telemetry into MQTT messages. It's the
middleware that decouples the drone from the things observing and
controlling it.

The mosquitto broker is the hub, exposed on port 1883 and publishing
messages out to the host so client programs can run outside the
container. This is what makes the architecture publish/subscribe and
lets multiple observers run independently without stepping on each
other. The client programs on the host are the subscribers and injectors:
`monitor_plot.py` plots telemetry live, `gps/detector.py` and
`compass-mag/detector.py` emit verdicts, `test_monitor_flight.py` drives
the flight, and `mischief_maker.py` injects `SIM_*` faults. Data flows
SITL ⇄ drone_backend ⇄ mosquitto → client programs, with commands
flowing back the same way. Keeping this straight was itself part of the
challenge, because debugging meant figuring out which layer a problem was
in.

Each client also publishes a retained `monitor_config` message declaring
which categories it wants the backend to include in `monitored_data`.
Because this topic is shared, all three clients publish the same list
(`gps` and `compass`) so they don't overwrite each other's request.

## Where the window lives

The rolling window lives inside each detector process, in memory, as a
`collections.deque` of `(timestamp, value)` tuples. One deque per
detector — no shared state. This matters because the detectors are
completely independent: a crash in the GPS detector has no effect on the
compass detector, which continues running. The cost is that each detector
receives the full `monitored_data` stream and filters it down to the
field it cares about, but at this telemetry rate that's negligible.

## Who updates and clears it

The MQTT callback updates the window on each incoming `monitored_data`
message: append the new sample to the right, then trim from the left
while the oldest sample is older than `now - WINDOW_S`. There is no
explicit clear step — the window is purely time-based, so clearing is
just trimming, and old samples age out on their own. The trade-off: a
longer window gives each verdict more evidence but adds lag when a fault
resolves; a shorter window is snappier but trips on noise. GPS uses 4s
because the signal is deterministic; compass uses 5s because the fault is
statistical and needs more samples to see the range.

## What happens when a fault resolves

Nothing special — the faulted samples age out naturally over `WINDOW_S`
seconds. Once the aggregate falls back below the threshold, the next
report prints "no problem." No flag to unset. The side effect is that the
detector keeps reporting "problem present" for up to `WINDOW_S` seconds
after the fault physically ends, because the old samples are still in the
window. That's a property of the design, not a bug — it's the price of
using a window at all.

## How a third category would slot in

Copy `gps/detector.py` to `<category>/detector.py` and change three
things: `CATEGORIES`, which field to read from the payload, and the
aggregate and threshold. The MQTT wiring, deque management, `MIN_SAMPLES`
gate, verdict vocabulary, and evidence format all stay the same. If many
categories were expected, the natural next step is a shared base class
with a `compute_verdict(samples)` method each detector overrides —
copy-paste is fine for two or three, but at ten the base class pays for
itself.