# HW05 Grade

Claude reviewed first.  JCH reviewed reflection and reports.  Please see my comment about your reflection and let me know if I'm wrong.  

| Component | Points possible | Awarded | Notes |
|---|---:|---:|---|
| Skill design & quality | 25 | **18** | The skill has a sensible PURE/STUB/LIVE classification and a good "don't" list (no empty bodies, no mocking the function under test). But it generates tests per function. All 28 ATC tests passed on the original code, with ordering and characterization tests rather than bug hunts, and Step 5 forbids running the integration tier, so the live tests have never run. You identify all of this yourself in the reflection |
| Validated on the small worked example first | 10 | **7** | Both targets were classified sensibly, and the 13-minute hang led to real fixes in the skill. But the integration tests were only skipped (no broker), and no test output was submitted: the results are described in prose ("Unit test run" has no output under it) |
| Scope clearly defined | 5 | **5** | Two items, each with an (a) test / (b) fix / (c) fail-before-pass-after plan, declared before any code change, with debt listed separately |
| ATC Version #2 | 20 | **15** | The yield primitive is a meaningful fix (a `goto` hold at +10 m instead of `interrupt`, which lands and disarms the drone, plus re-arm/takeoff on resume). The non-dict payload guard is small. The most safety-relevant item you found, cross-batch pairs never being checked for conflicts, was left as debt, along with "exits 0 regardless of outcome" (the exact lapse the lesson opened with) |
| Applied to your own HW2 ATC | 20 | **12** | The generated suite didn't find the bugs. You found them by reviewing why its tests were shallow, then wrote two tests that fail before the fix and pass after (described, not captured). There was no integration or live run of Version 2, so nothing in the submission shows the fixed ATC working on the fleet |
| Reflection | 15 | **14** | A good reflection, but I'm not 100% sure this is your own words vs. Claude reflecting on Claude's work.  Let me know if I'm wrong.  I want reflection to be yours. |
| Individual understanding — in class | 5 | **0** | Not answered yet |
| **Total** | **100** | **71** | final |

## How this was checked

- **Unit tests:** 69 passed, matching the report.
- **Live (Claude's runs):** fresh 3-UAV fleet (`NUM_DRONES=3 DRONE_SPACING_M=52 CENTER_LOCATION=ND`) for each run. An independent telemetry recorder measured separation and waypoint arrival (2 m, 3D).
  - **test3 @ 15 m:** 9/9 waypoints, min separation **26.12 m**, 0 violation samples, exit 0, 143 s, all disarmed at the end.
  - **test2 @ 15 m:** 6/6 waypoints, min separation **26.26 m**, 0 violation samples, exit 0, 97 s, all disarmed. The cross-batch blind spot didn't cause a problem on this workload, but nothing checks it.
  - So Version 2 does work on the graded workloads. That evidence just wasn't in the submission.
- **Filename:** `WORKED-EXAMPLE.md` has a trailing space (`"WORKED-EXAMPLE.md "`), so tools looking for the exact name won't find it.

## Notes

- **Your reflection already contains the plan for the next iteration:** add a "safety invariants" step (no two airborne drones within `min_separation`, all missions complete, no drone lands during a yield) and write a test that fails if each one breaks. The cross-batch bug is exactly what that step would catch.
- **Fix the exit code next.** Exiting 0 regardless of outcome means any automated check reads a failed run as a pass.

*Your analysis of why green tests weren't enough is the most insightful part of this submission. The next step is making the skill produce tests that would actually fail, and running the integration tier on the fleet so your report can show the fix working.*
