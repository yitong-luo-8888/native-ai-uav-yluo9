# HW04 Grade 

**Categories:** GPS + MAG-COMPASS · **Check 2 severity:** High (as reported in REPORT.md)

Some good observations in the retrospective.

| Component | Points possible | Awarded | Notes |
|---|---:|---:|---|
| `README.txt` | 5 | **4** | Exact commands for plotter and both detectors. −1: the only install listed is `lab/backend/requirements.txt` (pymavlink + paho-mqtt), but `plotting/monitor_plot.py` imports matplotlib, and there's no `hw04/requirements.txt`. Both detectors started cleanly |
| Baseline + fault observation | 15 | **11** | GPS baseline clear (flat at 10, hdop/h_acc flat). Compass baseline is qualitative ("525-530 with a small wobble", no measured spread).  update rate / single-reading noise isn't described for either category. GPS fault: magnitudes per severity and "changes on the next tick", but −1 for no cross-category check. Compass fault: ranges per severity, but   no onset speed or cross-category check.   no plots or plot descriptions referenced |
| GPS detector | 20 | **18** | Check 1: pass. Check 2: 3/3 at High. −1 windowed: the trigger is `min < 10` over the window, so one low sample fires it, which contradicts the write-up's own "avoid reacting to a single odd sample". Write-up −1: no threshold-adjustment case ("No adjustment was needed") |
| Compass-mag detector | 20 | **20** | Check 1: pass. Check 2: 3/3 at High. Spread (max − min) is justified; level → spread switch after Medium runs straddled the baseline is a good adjustment case |
| Architecture sketch | 10 | **10** | Clear sections for window location, updating/clearing, resolution lag, and a concrete third-category recipe (plus when to refactor to a base class). Explains the shared category list |
| Retrospective | 10 | **9** | Present: saved vs. transient data, "bottleneck is observation, not analysis", orchestrating live tests. Doesn't directly address where HW03 habits carried over |
| **Total** | **80** | **72** | final |

## Grading runs (instructor, 2026-09-27)

Fresh SITL for each flight, `test_monitor_flight.py`, detector run alone per README.txt, `mischief_maker.py <TYPE> 30 90 High`.

| Run | Injected | Result | Latency | Recovery after reset |
|---|---|---|---|---|
| Normal flight, GPS detector | — | no false alarm | — | — |
| Normal flight, compass detector | — | no false alarm | — | — |
| GPS 1 / 2 / 3 | NUMSATS 4 / 3 / 2 | caught / caught / caught | 0.7 / 0.5 / 0.5 s | 4.2 s each |
| MAG-COMPASS 1 / 2 / 3 | MAG_RND 463 / 625 / 718 | caught / caught / caught | 0.2 s each | ~4.8 s each |

Compass run 1 fired at a spread of exactly 30 against a threshold of 30, right at the line. It's worth asking in class how much margin 30 really has at Low severity.
