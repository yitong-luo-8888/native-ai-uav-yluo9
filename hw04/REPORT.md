# HW04 Report

## Baseline observations

### GPS

During normal flight, `satellites_visible` was constant at 10 for the
entire `test_monitor_flight.py` run. SITL's GPS model is deterministic —
no natural variation was observed. `hdop_h` sat at 1.21 and `h_acc_m` at
0.3, likewise flat throughout. Because the signal never moves on its own,
"normal" for GPS is a single value rather than a range: any reading below
10 indicates a fault.

### Compass

At rest and in level cruise, `field_magnitude` held steady around 525–530
with a small wobble. The individual axes (`mag_x`, `mag_y`, `mag_z`) swing
visibly when the drone turns — expected, since they encode heading — but
`field_magnitude`, being orientation-invariant, stayed roughly flat. The
one surprise: compass is genuinely noisier than GPS even at rest, so the
detector could not threshold on the raw value alone. It had to look at
how much `field_magnitude` moved over a short window, not where it sat.

## Detector write-ups

### GPS detector (`hw04/gps/detector.py`)

Window: 4 seconds of `satellites_visible` (minimum 4 samples).
Threshold: minimum over the window < 10.

Justification: normal is exactly 10 and constant. Observed fault
magnitudes: Low → 7, Medium → 7, High → 2. Because Low can drop to 9 at
its shallowest, the only threshold that catches every severity is
"below normal." The window is short because the signal is deterministic:
a real fault changes it on the next telemetry tick, and the window's only
job is to avoid reacting to a single odd sample. I used the minimum over
the window rather than the latest value so that even a transient dip
triggers a report — appropriate for a signal whose normal value is a
single point.

No adjustment was needed after testing: the threshold was chosen from the
observed normal value (10) and confirmed against three High-severity
mischief runs (all caught) and a full normal flight (no false alarms).

### Compass detector (`hw04/compass-mag/detector.py`)

Window: 5 seconds of `field_magnitude` (minimum 8 samples).
Threshold: max − min over the window > 30.

Justification: the fault does not shift the level of `field_magnitude` —
Medium (~425–600) and High (~400–800) straddle the normal value
(~525–530) on both sides. What changes is the spread. Normal spread over
a 5-second window is in the single digits; Low severity produces ~50,
Medium ~175, High ~400. Threshold 30 sits above normal wobble with margin
and below even the smallest observed fault. I considered tracking
variance instead of min/max, but variance needs several wobble cycles
before it clearly separates fault from normal — max − min responds
immediately on the first pass, which matters when the fault may only be
visible briefly. The approach is comparable to a moving-average high/low
band in a stock chart.

The one adjustment I made: my first instinct was to threshold on the
absolute value of `field_magnitude` (e.g. "below 500 is a fault"), but
the Medium runs straddle 525 on both sides — half their samples are above
normal, half below — so a level-based rule missed them. Switching to a
spread-based rule (max − min over the window) fixed this and catches all
three severities.

## Retrospective

In previous assignments, flight log analysis gave me a fully
deterministic dataset that was saved locally. I could pause, rewind,
plot, and cross-reference parameters at my own pace. The data didn't go
anywhere, and I could re-run analysis as many times as I wanted.

In HW04, the real-time data is not saved. Once a sample passes through
the pipeline, it's gone unless I explicitly logged it. This means I had
to infer flight behavior entirely from the live plots. If I missed a
transient spike or a brief window of abnormal behavior, I had no way to
go back and inspect it. The plots became the only ground truth, and I
had to mentally reconstruct the drone's state from them in real time.

This is a meaningful shift. In log analysis, the bottleneck is analysis.
In real-time monitoring, the bottleneck is observation. This meant
juggling multiple terminals and timing my actions carefully. Injecting
noise too early or too late meant missing the window in which the
detector should have fired. There's a real skill in orchestrating this
kind of live test harness — it's not unlike running a distributed system
where the observer is also part of the loop.