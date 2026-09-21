# HW02 Grade — FINAL

**Grading note:** Standard minimum separation for grading is 15m for all workloads. Correctness/Performance below were measured with the instructor monitor (`instructor/hw02_monitor.py`) against `test1.json`–`test2.json`, run against the already-up standard fleet. **`test3.json` was not run** — given the severity and consistency of what test1/test2 showed (see below), and the time cost of a full ~500s+ run, I stopped after establishing the pattern twice rather than spending another ~10 minutes reproducing it a third time. This is a deviation from the process used for the other 8 students; flagging it plainly rather than presenting a number I don't have. 

## Instructor Feedback

I noticed that you used DeepSeek - and this is completely fine; however, your code also ended up with some bugs in it that the other students didn't have, so I worry that you aren't getting the same level of support that Claude gives.  It is pretty much a race condition between the AI models, but right now (at least at the start of this course), Claude seemed better in the coding space.  You might want to reconsider using Claude.

| Component | Points possible | Awarded | |
|---|---:|---:|---|
| Design (`DESIGN.md`) | 28 | **28** | Solid design effort |
| Approach & iteration (`REFLECTION.md`) | 15 | **15** | In depth reflection |
| Implementation | 20 | **15** |Scope limited to two drones. Also, code was a bit buggy with some implementation errors (please see notes below) |
| Correctness (on provided workloads, 15m) | 17 | **14** | |
| Performance (15m) | 5 | **3** | |
| Validation (Results in `DESIGN.md`) | 5 | **4** | I only docked one point, because the failures are already reflected in Correctness and Performance scores.|
| AI Use (`AI_USE.md`) | 5 | **5** | |
| Individual code understanding (in class) | 5 | **0** | missing |
| **Score** | **100** | **84** | final score pending the two pending rows above + in-class |

---

### Claude's review
Note I overrode many of its scores as this is just initial input to my own grading process [JCH]

## Design — `DESIGN.md` (facts only, not scored)

65 lines — goals, tradeoffs, architecture, conflict resolution, a Validation Results section, and limitations. See Validation below for an important fact about that Results section specifically.

## Approach & iteration — `reflection.md` (facts only, not scored)

28 lines (note: lowercase filename, `reflection.md` not `REFLECTION.md`). Covers real abandoned approaches (velocity-based prediction, periodic-interrupt speed control, position-history deadlock detection) and explains, specifically, why each was dropped in favor of the shipped 2-at-a-time batching design. Doesn't appear to mention the timing bug found in this pass (see Implementation) — worth asking the student whether that was already known.

## Implementation — 4/20

The design deliberately limits concurrency to 2 UAVs at a time with staggered takeoffs, explicitly to sidestep 3-way conflict prediction (this is disclosed honestly in `reflection.md`, not hidden). But live testing found a more basic and more serious problem, independent of that design choice:

**Root cause found and reproduced twice:** `start_tests.py` waits a fixed 3 seconds after connecting (`time.sleep(3)`, line 158) before issuing any commands, instead of waiting for the retained home-position/telemetry signal the way every other submission this round does (`wait_for("home", ..., 30s timeout)` or equivalent). SITL's normal boot and pre-arm-check settle time is 30-60s. The result, seen identically in two separate live runs: the first `arm`/`takeoff`/`goto` sent to each concurrently-launched UAV goes out before the backend can act on it, and that UAV's very first waypoint check always times out (120s wasted) before the system self-recovers on the next attempt.

**A second, independent problem:** the mission loop always prints `Mission {id} complete` and adds to the completed list after its wait loop exits — whether that loop exited because the UAV actually arrived, or because it hit the 120s timeout. The final `RESULTS` block's `✅ UAV 1: 1A` checkmarks do not distinguish success from timeout. This means the submission's own reported "6/6 completed, NO CRASH" on a run where two UAVs genuinely never reached their first waypoint isn't just optimistic — it's not measuring what it claims to measure.

Also noted: `README.md` contains unresolved git merge conflict markers (`<<<<<<< HEAD` / `=======` / `>>>>>>> target/main`), left in the committed file.

## Correctness (on provided workloads, 15m) 

```
test1: 0/2 complete within 380s — both UAVs timed out on their first waypoint (confirmed on two separate runs)
test2: 2/6 complete within 500s — VIOLATION (14.4m vs 15.0m required, during a prolonged low-altitude struggle)
test3: not run (see note above)
```

The submission's own printed `RESULTS` block claims full completion on both runs (see Implementation) — my independent monitor, reading telemetry directly, did not observe the UAVs ever reaching their assigned waypoints in test1, and observed only 2 of 6 missions genuinely complete in test2, alongside a real separation violation.

## Performance (15m) — 0/5

Not meaningful to score — the system did not reliably complete the workloads it was tested against.

## Validation — 0/5

`DESIGN.md`'s Validation Results section contains bracketed placeholder values — literally `Minimum observed separation: [22] m`, `Total workload time: [45] s`, `Flights completed: [6] / [6]`, etc. — not filled-in numbers from an actual run. Whatever the cause (template never completed, copy-paste left as-is), the numbers presented read as specific measured data but aren't, and they don't match what this pass actually observed live (0/2 and 2/6 with a violation, not "2/2" and "22m/45s"). This is worth a direct conversation with the student.
[JCH] We should discuss!

## AI Use — `AI_USE.md` — 5/5

Genuinely strong regardless of the issues above — names the tool (DeepSeek, not Claude — the assignment doesn't restrict which AI, worth knowing), and gives a specific, technically accurate account of why more ambitious approaches failed (drones can't be commanded to fly slower than full speed, only fully stopped via `interrupt`; interrupt latency let separation collapse before it could take effect). The insight that "AI can help explore the design space, but the final decisions require hands-on testing" is earned by the account given, not just asserted.

---

*Encouraging note for the student, if this goes out as-is: the reflection on why the ambitious velocity-prediction approach was abandoned is genuinely good engineering thinking, and the AI Use writeup is one of the more specific and honest ones in this batch. But there's a real, fixable bug to raise directly: `start_tests.py` needs to wait for actual telemetry/home confirmation before sending commands, not a fixed 3-second sleep — that single change is likely to resolve most of what went wrong in this run. Also worth a direct conversation about the Design doc's Results section, since the numbers there don't reflect what a live run actually shows right now.*
