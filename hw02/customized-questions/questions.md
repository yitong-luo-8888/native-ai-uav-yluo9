# HW02 — Individual Architecture Questions (yluo9)

Your design: a controller that processes UAVs in batches of two with a 10 s
staggered takeoff, reactive conflict detection at 1.5 × min-separation,
higher-ID-yields priority, `interrupt` for yielding, resume when the pair
re-opens past the same threshold.

---

**1. Batching and the concurrency model.**
`run_all()` processes UAVs two at a time: for a 3-UAV workload, UAVs 1 and 2
fly together and UAV 3 only starts after they finish. The assignment says each
UAV's missions begin as soon as its previous one completes, with different
UAVs' missions overlapping, and grading uses unseen workloads with different
concurrency patterns. What does batching do on a workload where UAV 3 must fly
concurrently with UAV 1? And since conflict checks only compare UAVs in the
same active batch, which pairs of UAVs can your system *never* detect a
conflict between?

**2. `interrupt` / LOITER on this fleet.**
You use `interrupt` to make a UAV yield. On this fleet there is no RC pilot,
and LOITER commands a descent that reaches the ground in about 7 seconds and
then disarms the vehicle. Did you observe that in your runs? Your loop sleeps
0.5 s per iteration and only calls `resume_drone` once separation re-opens — if
that's 8+ seconds after the interrupt, what state is the UAV in, and does
re-issuing the original `goto` (with the original altitude) recover it?

**3. Fixed sleeps instead of confirmation.**
Your takeoff is `arm` → `sleep(3)` → `takeoff` → `sleep(8)` → `goto`, with no
check that the UAV actually armed or reached altitude, and each waypoint has a
fixed `deadline = time.time() + 120`. The assignment notes SITL can take
30–60 s for pre-arm checks after a fresh start. Walk through what happens to
the whole run if UAV 1's arm takes 20 seconds. What pattern from
`test_flight.py` would have made this robust, and why did you not need it to
pass your own runs?
