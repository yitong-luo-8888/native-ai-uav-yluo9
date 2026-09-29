# HW05 Report

## Declared scope

Written before any code change.

### 1. Fix the yield primitive in `ATCController.interrupt_drone` / `resume_drone`

The generated suite contains an interrupt→resume ordering test, and it
passes. But it only asserts the *call order*: that `interrupt_drone`
publishes an `interrupt` command and that `resume_drone` later publishes
a `goto`. It does not model what the vehicle actually does in between.

On this fleet, `interrupt` drops the UAV out of GUIDED into LOITER,
which descends to the ground and disarms the vehicle in roughly 7
seconds. When the conflict clears and `resume_drone` fires, the vehicle
is on the ground and disarmed, and the bare `goto` it sends is ignored.

I will:
(a) add a behavior-faking test that models the LOITER-descent: after
    `interrupt_drone`, simulate the drone descending and disarming,
    then call `resume_drone` and assert the emitted command sequence
    includes `arm` and `takeoff` when the drone is grounded;
(b) fix `resume_drone` to check `armed` / `alt_rel` before sending
    `goto`, and to re-arm and re-take-off if the drone is down;
(c) show the new test failing against the current code and passing
    after the fix.

### 2. Harden `_on_message` against valid-JSON-but-not-a-dict payloads

The generated `test_on_message_malformed_payload_does_not_mutate_state`
feeds `b"{not valid json"`, which fails `json.loads` and is caught by
the existing `JSONDecodeError` handler. It passes.

But a payload of `b"[1, 2, 3]"` or `b"42"` is valid JSON and not a
dict. `_on_message` currently stores it verbatim in `self.drones`, and
`get_position` later crashes with `AttributeError` when it calls
`.get("lat")` on a list.

I will:
(a) add a test that feeds `_on_message` a valid-JSON non-dict payload
    and asserts no state mutation;
(b) fix `_on_message` to reject non-dict payloads;
(c) show the new test failing before and passing after.

**Out of scope, documented as debt:**
- The `run_all` batch-scope bug: cross-batch pairs are never compared.
  Batch 1's UAVs are never checked against batch 2's, so pairs like
  (1,3) and (2,3) can conflict undetected.
- The fixed sleeps in `start_tests.py` (`sleep(3)` after arm, `sleep(8)`
  after takeoff) instead of telemetry-driven waits.
- `main()` prints "NO CRASH" and exits 0 regardless of outcome.

## What the tests found

The generated suite for `atc.py` classified 28 functions and produced
28 unit tests, all passing against the original code. Two of them
passed for reasons that turned out to be shallow, which is itself the
most useful finding of the run:

1. **`test_on_message_malformed_payload_does_not_mutate_state` passed
   against buggy code.** It feeds `b"{not valid json"`, which fails
   `json.loads` and is caught by the existing `JSONDecodeError`
   handler. It never exercises the more dangerous case: valid JSON
   that isn't a dict. So the test was green, but the bug — storing
   a list or int in `self.drones` and later crashing `get_position` —
   was still there.

2. **The interrupt→resume ordering test passed against buggy code.**
   It asserts that `interrupt_drone` publishes an `interrupt` and
   that `resume_drone` later publishes a `goto`. It does not model
   what the vehicle does in between. On this fleet, `interrupt`
   descends and disarms the drone in about 7 seconds, so the resume
   `goto` is ignored. The test is green because the code satisfies
   the ordering property; the code is still wrong because the
   ordering property isn't the safety property that matters.

The generated suite also produced a `should_yield` equal-ID test,
which is a characterization test — it asserts the current behavior
(neither drone yields) rather than probing whether the behavior is
correct. Passing, but not a bug hunt.

The suite did not test `run_all`'s batch-scope behavior at all. It
is documented as known debt in this report.

## What I changed

### `hw05/atc.py`

**1. `_on_message` — reject non-dict payloads.**

Added a type check immediately after `json.loads` succeeds:

    if not isinstance(payload, dict):
        return

The check is placed before the topic-type branch, so a non-dict payload
on either the telemetry or the home topic leaves both `self.drones` and
`self.home_positions` untouched.

**2. `interrupt_drone` — state-preserving yield primitive.**

Replaced the `{"type": "interrupt"}` command with a `goto` to the
drone's current lat/lon at `alt_rel + 10 m`, keeping the drone in
GUIDED. Falls back to `interrupt` if the drone has no known position.

**3. `resume_drone` — re-arm and re-takeoff if grounded.**

Before sending the resume `goto`, read the drone's telemetry from
`self.drones.get(drone_id, {})`. If `armed == False` or
`alt_rel < 1.0`, send `arm` then `takeoff` at `waypoint["alt"]` before
the `goto`. If the drone is already airborne, send only the `goto`,
preserving prior behavior.

### `generated-tests/unit/test_atc.py`

Two new tests added:

- `test_on_message_rejects_non_dict_payload_does_not_mutate_state`
- `test_resume_drone_arms_and_takes_off_before_goto_when_grounded`

Two pre-existing tests needed a precondition update, because under the
new logic they read as grounded (default `armed=False`, `alt_rel=0`) and
their goto-only assertions no longer matched the new command sequence.
Both now explicitly set the drone airborne before calling `resume_drone`:

- `test_resume_drone_sends_goto_and_updates_state`
- `test_interrupt_then_resume_sends_commands_in_order_and_updates_status`

Assertions were not changed. The grounded case is covered by the new
test; the airborne case remains covered by these two.

### `SKILL.md`

Two procedural fixes were made during validation, before the ATC run:

1. Integration tests must check broker reachability and `pytest.skip`
   rather than hang. (Prompted by the 13-minute hang on the first
   `test_flight.py` run.)
2. Step 5 must scope the pytest invocation to `generated-tests/unit/`
   only, and explicitly forbid running the integration directory as
   part of generation.

## Before / after evidence

Environment: Python 3.14.4, pytest 9.1.1, interpreter
`/home/yitong/uav-native-ai/.venv/bin/python`, run from `hw05/`.

### Two new tests failing against the pre-fix code

- `test_on_message_rejects_non_dict_payload_does_not_mutate_state`
  FAILED against the original `atc.py`. A payload of `b"[1, 2, 3]"`
  was accepted, stored verbatim in `self.drones`, and the test's
  assertion that the dict was unchanged failed.
- `test_resume_drone_arms_and_takes_off_before_goto_when_grounded`
  FAILED against the original `atc.py`. `resume_drone` emitted only a
  `goto` even when the drone was grounded (`armed=False`,
  `alt_rel=0`), so the assertion that `arm` and `takeoff` preceded the
  `goto` failed.

### Full suite after the fix

    $ python -m pytest generated-tests/unit/ -v
    ...
    generated-tests/unit/test_atc.py::test_on_message_rejects_non_dict_payload_does_not_mutate_state PASSED
    generated-tests/unit/test_atc.py::test_resume_drone_arms_and_takes_off_before_goto_when_grounded PASSED
    ...
    ============================= 69 passed in 0.99==============================

69 tests pass. No regressions: the 39 pre-existing tests from the two
worked examples (24 for `test_flight`, 15 for `battery_detector`)
remain green, and the 26 unchanged `atc.py` tests pass.

### Integration tests

`generated-tests/integration/test_atc_live.py` covers `__init__` and
`_on_connect` against a live broker. It was written but not executed,
per the constraint that the generation run must not connect to MQTT.

## Known debt

Three items are documented but not fixed in this submission:

1. **`run_all` batch-scope bug.** In `MissionRunner.run_all`, UAVs are
   processed in batches of two, and `self.active_drones` is set to the
   current batch. `_run_mission` only checks conflicts against
   `self.active_drones`, so pairs across batches (e.g. UAV 1 and UAV 3)
   are never compared. On `test2.json` this means pairs (1,3) and (2,3)
   can conflict undetected. The fix is to make the conflict check see
   all airborne UAVs; batching should govern launch scheduling only,
   not conflict-detection scope. A test for this would require
   constructing a workload where the cross-batch pair is the one that
   conflicts, which none of the generated tests do.

2. **Fixed sleeps in `start_tests.py`.** `_run_drone` uses
   `sleep(3)` after `arm` and `sleep(8)` after `takeoff` instead of
   waiting on telemetry for the state transition. This passed on a
   warm local SITL but would break on a fresh one where pre-arm checks
   take 30–60 seconds. The robust pattern is in
   `lab/scripts/test_flight.py`: poll telemetry until `armed == True`,
   until `alt_rel >= target`, until `distance < 2 m`. Each wait has a
   timeout but is event-driven.

3. **`main()` exits 0 regardless of outcome.** It prints "NO CRASH"
   and exits 0 even if a waypoint timed out or a separation violation
   occurred. It also never computes a minimum observed separation.
   The grading monitor reads telemetry, so this does not affect
   grading, but any CI keyed off the exit code would misread a failed
   run as a pass.