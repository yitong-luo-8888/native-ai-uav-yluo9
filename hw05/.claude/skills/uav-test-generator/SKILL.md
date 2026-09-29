cat > .claude/skills/uav-test-generator/SKILL.md << 'EOF'
---
name: uav-test-generator
description: Generate unit and integration tests for Python code in a UAV/MQTT/SITL codebase. Use when the user asks to test, generate tests, write a test suite, or validate a module that talks to drones, MQTT, or MAVLink. Classifies each function as pure, stub-testable, or live-fleet-required, then writes real pytest files for both unit and integration cases.
---

# UAV Test Generator

## What this skill does

Given a target Python file (or module) in a UAV codebase, this skill:

1. Reads the code and identifies every public function, method, and class.
2. Classifies each one into exactly one of three buckets:
   - **PURE** — no I/O, no state outside arguments, deterministic. Unit-test directly.
   - **STUB-TESTABLE** — touches MQTT/SITL/time but only through a small interface that can be replaced with a stub or fake. Unit-test with a fake.
   - **LIVE-FLEET** — requires a real MQTT broker, real SITL, real telemetry, or a full event loop. Integration-test only.
3. Writes actual pytest files:
   - `generated-tests/unit/test_<module>.py` for PURE and STUB-TESTABLE functions.
   - `generated-tests/integration/test_<module>_live.py` for LIVE-FLEET functions.
4. Runs the unit tests immediately (they must pass or fail for a real reason — not for import errors).
5. Reports what it generated, what it could not test, and why.

## When to invoke

Invoke when the user says any of:
- "generate tests for <file>"
- "write a test suite for <module>"
- "test this code"
- "what would break in this file?"
- "find bugs in <file> via tests"

Do NOT invoke for:
- Non-Python files.
- Files that are pure configuration or data.
- Generating tests for a single function the user names explicitly — that is a one-off; this skill is for whole-file or whole-module coverage.

## Procedure

### Step 1 — Read and inventory

Read the target file. Produce an inventory table with columns:

| Name | Kind | Reason | Test plan |
|---|---|---|---|

`Kind` is one of `PURE`, `STUB`, `LIVE`.

Classification rules (apply in order):

1. If the function calls `mqtt.Client.publish`, `client.connect`, `client.loop_start`, `requests.*`, `socket.*`, `subprocess.*`, `open(...)` for write, or `docker`, mark **LIVE** — unless the call is trivially wrappable (see rule 3).
2. If the function reads `self.<attr>` where `<attr>` is populated only by an MQTT callback or a live telemetry stream, mark **STUB** — it can be tested by injecting the state directly.
3. If the function calls `time.sleep(...)`, `threading.Thread(...)`, or any waiting loop, mark **STUB** — it can be tested by monkeypatching `time.sleep` and using a fake driver.
4. If the function performs math on arguments or on injected state, with no external calls, mark **PURE**.
5. If the function is `main()` or a top-level entry point, mark **LIVE**.

When in doubt between PURE and STUB, prefer STUB — a stub test still runs fast and is more honest about dependencies.

### Step 2 — Determine the stub interface

For every STUB function, identify the minimum surface it depends on. Common shapes in this codebase:

- **MQTT wrapper**: an object with `.publish(topic, payload)` and `.subscribe(topic)`. Replace with a `RecordingClient` that stores `(topic, payload)` tuples in a list.
- **ATC-facing interface**: an object with `send_command`, `distance_between`, `interrupt_drone`, `resume_drone`, `should_yield`. Replace with a `FakeATC` whose `distance_between` returns a scripted sequence.
- **Time**: replace `time.sleep` with a no-op via `monkeypatch.setattr(time, "sleep", lambda _: None)`. Never let a unit test actually wait.
- **Telemetry dict**: a plain dict with `lat`, `lon`, `alt_rel`, `heading`, `groundspeed`, `armed`, `mode`. Populate `self.drones[drone_id]` directly.

Emit the stub classes in `generated-tests/unit/conftest.py` so they are reusable across test files.

### Step 3 — Write unit tests

For each PURE function, write tests that:
- Cover the normal case with hand-computed expected values.
- Cover boundaries: zero distance, negative altitude difference, identical positions.
- Cover the input-validation case if the function assumes anything about its arguments.

For each STUB function, write tests that:
- Inject the stub or fake state, call the function, and assert on the *observable* effect (recorded commands, mutated state, return value).
- Assert on the *sequence* where ordering matters (e.g., `arm` before `takeoff`, `interrupt` before `resume`).
- Include at least one negative test: a case that should *not* trigger the action (e.g., distance above threshold -> no interrupt).
- Include at least one edge case the author likely did not test: malformed payload, missing field, equal IDs, empty collection.

Do not write tests that merely call a function and assert it does not raise, unless the function is a parser and the test feeds it malformed input.

### Step 4 — Write integration tests

For each LIVE function, write tests that:
- Assume the fleet is running (`docker compose up -d`) and the MQTT broker is at `localhost:1883`.
- Are marked with `@pytest.mark.integration` so they can be skipped when the fleet is not up.
- Subscribe to `uav/+/telemetry` and assert on real telemetry, not on printed output.
- Have a hard timeout (use `pytest-timeout` or an explicit deadline) so a hung test does not hang CI.
- Clean up: land all drones and disconnect at the end, even on failure.

Integration tests must assert on **telemetry-observable** facts:
- Minimum separation observed over the run.
- Whether each drone reached its waypoints.
- Whether the drone's `alt_rel` dropped below a floor during a yield.
- Whether the run completed inside the deadline.

Do not write integration tests that assert on printed strings. The grading monitor in this course reads telemetry only.

### Step 5 — Run and report

Run `pytest generated-tests/unit/ -v`. Unit tests must be import-clean and must not require the fleet.

Then run `pytest generated-tests/integration/ -v -m integration` if the fleet is up. If it is not, report that integration tests were generated but not run, and say so explicitly.

Produce a summary:


### Step 6 — Do not do this

- Do NOT emit test functions with empty bodies, `pass`, `TODO`, or `assert True`.
- Do NOT emit tests that mock the function under test. Mock its dependencies, never the thing being tested.
- Do NOT emit tests that assert on log output or `print` statements.
- Do NOT emit a test that passes only because it swallows an exception.
- Do NOT mark a function LIVE and then skip writing a test for it. If it is LIVE, write the integration test — even if it can only be run manually.
- Do NOT hardcode the target module's file name, class name, or function names into the generated tests' imports in a way that would break if the file is moved. Import by module path relative to the repo root.

## Output format


Each unit test file begins with a comment block:


## Worked example expectations

When run against `lab/scripts/test_flight.py`, this skill should:
- Classify the telemetry-wait helpers as STUB (they can be driven with a fake telemetry source).
- Classify the MQTT publish calls as STUB (wrap in a recording client).
- Classify `main()` as LIVE.
- Emit at least one test that asserts the arm -> takeoff -> goto ordering, and one that asserts the arrival check uses the 2 m tolerance.

When run against `lab/lesson4/battery/battery_detector.py`, this skill should:
- Classify the threshold logic as PURE.
- Emit tests covering above-threshold, below-threshold, and exactly-at-threshold.

When run against `hw05/atc.py` (the controller), this skill should:
- Classify `distance_between`, `distance_to_waypoint`, `should_yield`, `get_position` as PURE.
- Classify `_on_message`, `interrupt_drone`, `resume_drone`, `send_command` as STUB.
- Classify `__init__` / `_on_connect` as LIVE.
- Emit a test that feeds `_on_message` a malformed payload and asserts no state mutation.

When run against `hw05/start_tests.py` (the runner), this skill should:
- Classify `_run_mission` as STUB (fake ATC, monkeypatched sleep).
- Emit a test that scripts `distance_between` through a conflict and asserts the interrupt-then-resume sequence.
- Classify `main()` as LIVE.
EOF