# HW05 Reflection

## What I set out to do

The assignment was to build a Claude Code Skill that generates unit and
integration tests for a Python file, validate it on a small known
target, then point it at my HW02 ATC and use what it found to drive a
scoped fix. The skill is the reusable artifact; the ATC fix is the
proof that the skill produces something useful.

I built the skill as a `SKILL.md` procedure with a three-way
classification (PURE / STUB / LIVE), a stub-interface step, a
unit-test-writing step, an integration-test-writing step, a run-and-
report step, and an explicit "do not do this" section that forbids
the common failure modes (empty test bodies, mocking the function
under test, asserting on printed output, skipping LIVE functions).

I validated it on two known targets — `lab/scripts/test_flight.py` and
`lab/lesson4/battery/battery_detector.py` — before pointing it at
`hw05/atc.py` and `hw05/start_tests.py`.

## What the generated tests caught that my HW02 ad-hoc testing didn't

My HW02 testing was a handful of manual runs against the three provided
workloads, watching for crashes and eyeballing whether things looked
safe. It never exercised the parser's malformed-input path, and it
never modelled what the vehicle actually does during a yield. That was
the testing lapse this lesson is aimed at.

The generated suite went further. It produced 28 tests for `atc.py`,
all passing against the original code — and two of them passed for
reasons that turned out to be shallow, which was the most useful
finding of the whole exercise:

**1. `test_on_message_malformed_payload_does_not_mutate_state` passed
against buggy code.** The skill read "malformed" as "unparseable
bytes," so it fed `b"{not valid json"` and checked that the state was
unchanged. That path was already handled by the existing
`JSONDecodeError` catch. The dangerous case — valid JSON that isn't a
dict, like `b"[1, 2, 3]"` — was not tested. That payload is accepted,
stored verbatim in `self.drones`, and later crashes `get_position`
with an `AttributeError` when it calls `.get("lat")` on a list. A real
bug, hidden behind a green test.

**2. The interrupt→resume ordering test passed against buggy code.**
The skill's stub test asserted that `interrupt_drone` publishes an
`interrupt` command and that `resume_drone` later publishes a `goto`.
That ordering property is satisfied. But the safety property that
actually matters — that the drone is still airborne and armed when
`resume_drone` fires — is not. On this fleet, `interrupt` drops the
UAV into LOITER, which descends to ground and disarms in about seven
seconds. When the conflict clears and `resume_drone` sends its `goto`,
the vehicle is on the ground and disarmed, and the command is ignored.
The test is green because the code satisfies the ordering property;
the code is still wrong.

These two findings are the reason the scope in `report.md` names the
yield primitive and the non-dict payload as the two things to fix.
Both were only visible because the generated suite put the *shape* of
the problem in front of me, even though the assertions it wrote were
too shallow to fail.

## What the skill cannot test

Three things are still out of reach:

- **Fleet-level separation.** Whether the separation envelope actually
  holds when three real UAVs converge is a property of the running
  system, not of the controller's decision logic. The integration
  tests in `generated-tests/integration/test_atc_live.py` are written
  but were not executed this week. They would need the fleet up.
- **Timing under load.** The unit tests use a fake clock so they run
  in fractions of a second. That is the right call for a unit suite,
  but it means nothing tests whether the real loop responds fast
  enough during an actual conflict.
- **The `run_all` batch-scope bug.** The conflict check only compares
  UAVs inside the current batch, so pairs across batches — (1,3) and
  (2,3) on a 3-UAV workload — are never compared. Neither the unit
  suite nor the integration suite as generated catches this, because
  none of the tests construct a workload where the cross-batch pair
  is the one that conflicts. I documented it as debt in `report.md`
  rather than fixing it.

The last one is the sharpest limitation. A testing skill that
generates tests per *function* will miss bugs that live in the
*interaction between functions* — and the batch-scope bug is exactly
that.

## What I'd do differently starting the skill over

- **Require at least one behavioral test per STUB function.** The
  interrupt→resume ordering test passed against buggy code precisely
  because it only asserted call order. I'd add a rule that for any
  function that emits a command based on state, the test must model
  the state and assert the command as a *function* of that state.
- **Define "malformed" more carefully.** "Malformed" should include
  valid-JSON-wrong-type, not just unparseable bytes. The skill read
  the word too narrowly and produced a test that was green without
  being informative.
- **Add a test-per-invariant step.** The skill currently generates
  tests per function. I'd add a step that asks: "what are the safety
  invariants of this system, and what test would fail if each one were
  violated?" The interrupt→resume issue is an invariant violation that
  no per-function test would catch.
- **Scope the pytest invocation in the procedure.** The first run of
  the skill hung for 13 minutes because the agent tried to run the
  whole `generated-tests/` tree, which collected the integration
  tests, which attempted to connect to a broker that wasn't running.
  I interrupted, diagnosed, and tightened Step 5 to run only
  `generated-tests/unit/`. That fix should have been in the skill from
  the start.

## Lessons Learned — using Claude this way

**Where it helped.**

- **Breadth.** It generated 28 tests for `atc.py` in one pass, plus
  test files for `test_flight.py` and `battery_detector.py`. That is
  a lot of edge-case coverage — the "not enough data" battery cases,
  the arrival-tolerance boundary at exactly 2 m, the symmetry of
  distance calculation — that I would not have thought to write by
  hand.
- **Honesty about breaking things.** When the yield fix broke two
  pre-existing tests, Claude flagged them and asked how I wanted to
  handle them instead of quietly editing the assertions. It was
  correct to flag them: the tests asserted the airborne path without
  establishing the airborne precondition, and the fix made the
  missing precondition visible. Updating them to explicitly set
  `armed=True, alt_rel>=1.0` was the right move, and it was my call,
  not Claude's.
- **Mechanical work.** The path-insertion in `conftest.py`, the fake
  MQTT client, the pytest marker registration — all the boilerplate
  that has to be exactly right for a suite to run at all — came out
  correct on the first try.

**Where it didn't.**

- **It doesn't know what a bug is.** The malformed-payload test used
  the narrowest reading of "malformed" and passed against code that
  would crash on a payload like `b"[1,2,3]"`. I had to tell it what
  to test. A human reviewer looking at `_on_message` would have seen
  the missing type check immediately; Claude saw the code, wrote a
  test for the branch that already existed, and moved on.
- **It does what the procedure says, including things you didn't
  intend.** The first run hung for 13 minutes because the procedure
  said "run the unit tests" and the agent ran pytest over
  `generated-tests/` as a whole, collecting the integration tests,
  which tried to connect to MQTT. The agent followed the letter of
  the instruction and got stuck on the spirit.
- **A passing test is not the same as a correct test.** Two of the
  generated tests passed against buggy code. That is the single most
  important thing I learned from this exercise: the skill is good at
  producing tests that *run*, and much weaker at producing tests that
  would *fail if the code were wrong*.

**Where I had to pilot it.**

- I had to tell it what "malformed" meant. I had to tell it the yield
  bug was real and the fix had to preserve airborne state. I had to
  tell it to update the two broken tests rather than reverting the
  fix. I had to interrupt the 13-minute hang and tighten the procedure.
  In each case, the design decision was mine and the implementation
  was Claude's.

That is, I think, the right division of labor for this kind of work.
Claude is a very fast junior engineer who will write whatever you
specify, correctly, and will also faithfully implement a bad
specification without noticing. The skill is valuable because it fixes
the specification — it turns "write me some tests" into a repeatable
procedure — but the procedure itself has to be designed by someone who
knows what the tests are for.

## Honest assessment of where this still falls short

The skill is validated on two small targets and works well on
function-level coverage. It is not yet a system-level testing tool.
The ATC bugs that matter most — the batch-scope conflict-detection
hole, the fixed sleeps under a cold SITL — are interaction bugs, and
the skill as written does not look for them. A next iteration would
add a "safety invariants" step to the procedure: enumerate the
properties the system must hold (no two airborne drones within
`min_separation`; all missions complete; no drone lands during a
yield), and for each one write a test that would fail if the property
were violated. That is the direction I would take next.

The code fix itself is small and correct: `_on_message` now rejects
non-dict payloads, `interrupt_drone` sends a `goto` to a hold point
instead of a bare `interrupt`, and `resume_drone` re-arms and
re-takes-off a grounded drone before sending the `goto`. All 69 unit
tests pass. The three known-debt items remain unfixed and documented.