# HW03 — GPS / Position + Compass Health

## Coded solution

### GPS / position failure

The coded analyzer (`analyze.py`) reads seven message types extracted from
`2025-09-04 10-23-55.bin`: `GPS`, `POS`, `GUIP`, `ORGN`, `MODE`, `MSG`, and
`ERR`. It converts GPS and POS lat/lng to metres North/East relative to the
EKF origin (from `ORGN` Type 0), decodes `GUIP.pX/pY` as Lat×1e5 and `pZ` as
cm-Down, and computes three signals: GPS-vs-POS horizontal agreement, the
EKF-origin-to-home separation, and the end-of-flight GUIP-to-POS offset. On
the lab log it returns **"Target in wrong frame"**: GPS and POS agree within
0.54 m mean / 1.75 m max over 2168 samples, so the EKF estimate was healthy;
the EKF origin and home are 15.22 m apart; and the GUIP target matches home
to within 0.4 m while the drone reached it to within 0.45 m. Graphs are
`track_gps_pos_guip.png`, `altitude.png`, and `gps_quality.png`. One thing it
cannot tell is **who issued the target or in which frame** — the flight log
records the target value but not its source; that requires the `.tlog`
telemetry log from the GCS. I also hit two false starts: `bin2csv.py` was not
in the project, so I wrote my own `pymavlink`-based extractor, and my first
analysis script double-scaled the lat/lng and HDop columns, which I only
noticed when the EKF origin printed as `lat=0.0000042`.

### Compass health failure

The coded analyzer (`compass_health.py`) reads `MAG.csv`, `CTUN.csv`, and
`BAT.csv`, splits `MAG` by the `I` (instance) column, and for each compass
computes the field magnitude `sqrt(MagX² + MagY² + MagZ²)`, the hard-iron
offset magnitude `|Ofs|`, the motor-compensation magnitude `|MO|`, and the
correlation of magnitude with throttle (`CTUN.ThO`) and current (`BAT.Curr`).
It flags a suspect instance by combining each compass's deviation from the
peer median with its own standard deviation, then checks whether that
suspect's `Health` field has dropped below 0.9. On the lab log (19,314 rows,
3 instances) it returns **"Compass 2 is unhealthy"**: Compass 2 has a mean
field magnitude of 2661.8 mG (5× Earth's field), std 602.8, peak-to-peak
4594.5 mG, and correlates with throttle at r = +0.98 and current at r = +0.86,
while Compasses 0 and 1 sit tightly around 500 mG with std ≈ 6–7 and no load
correlation. Graphs are `compass_magnitudes.png` and `suspect_vs_load.png`.
One thing it cannot tell is **whether the interference comes from wiring, a
motor, or an external source** — that requires a bench test with the motors
running, or a compass swing test, which is outside the log.

## Prompt solution

### GPS / position failure

The prompt (`gps-position/prompt.md`) is self-contained: it declares the seven
input CSVs and their columns, defines five diagnostic signals (GPS-vs-POS
agreement, GPS quality, EKF-origin-to-home offset, GUIP-vs-POS offset,
autopilot awareness), specifies the five possible verdict strings and their
priority, and constrains the output to verdict / graph / evidence / confidence
/ limitations. On the lab log it returns **"Target in wrong frame"** with the
same numbers as the coded solution (GPS-vs-POS mean 0.54 m, ORGN separation
15.22 m, GUIP offset 0.45 m). One earlier version of the prompt failed because
it did not know that `GUIP.pX` is encoded as `Lat × 1e5` — Claude divided by
the usual `1e7` and produced a target 4,000 km away; adding the line *"If
|pX| > 1e6, assume pX = Lat × 1e5"* and a magnitude-based auto-detection
fallback fixed it. I ran the same prompt three times on the same log and got
the same verdict and the same key values each time, though the exact graph
colors and evidence phrasing varied slightly. On the battery log, the prompt
returned **"Not enough data to decide"** because `BAT.csv` was missing from
the extraction — it correctly named the missing file rather than guessing.

### Compass health failure

The prompt (`compass-health/prompt.md`) mirrors the structure: it declares
`MAG`, `CTUN`, `BAT`, `MSG`, `ERR` as inputs, defines six signals (field
magnitude, hard-iron offsets, motor-comp offsets, peer comparison, load
correlation, `Health` flag), specifies the suspect-scoring rule
`|mean − median(peers)| + std`, and constrains the output the same way. On the
lab log it returns **"Compass 2 is unhealthy"** — mean 2661.8 mG, std 602.8,
ptp 4594.5, peer delta +2124 mG, throttle correlation r = +0.98, current
correlation r = +0.86. One earlier version failed because it did not know the
ArduPilot CSVs have **two header rows** (row 1 = names, row 2 = units), so
Claude loaded the units row as data and produced NaN means; adding the
explicit line *"skip the units row if TimeUS is non-numeric on the first data
row"* fixed it. I ran the same prompt three times on the same log and got the
same verdict and the same suspect instance each time. On the battery log, the
prompt returned **"Not enough data to decide"** because `MAG.csv` was missing
from that extraction, and it correctly listed which signals it could not
evaluate.

## Retrospective

Both approaches converge on the same diagnoses, but they fail in different
ways.

The coded solutions are **fast, deterministic, and reproducible**: the same
CSV always produces the same numbers, and the threshold checks are explicit.
Their weakness is brittleness — my first GPS script double-scaled the data and
I only caught it because the EKF origin printed as `lat=0.0000042`; a less
obvious scaling error would have silently produced plausible-looking but wrong
output. The compass script has the same exposure: if ArduPilot changes the
`MAG` schema or the CSV exporter writes a different number of header rows,
the script breaks silently or throws.

The prompts are **robust to format drift** — Claude reads the columns, notices
the units row, and adapts when `GUIP.pX` is in a different unit than expected.
Their weakness is variability: across three runs on the same log I got the
same verdict and key values, but the graphs looked slightly different and the
evidence was phrased differently each time. For a one-off diagnosis this is
fine; for a fleet-monitoring pipeline it is a problem, because you cannot
write a downstream rule that depends on exact wording.

The clearest split is **where the failure modes live**. Code fails on inputs
(scale, schema, missing files) and succeeds on logic (thresholds, joins,
correlations are exactly what you wrote). Prompts fail on logic (a threshold
can be argued away, a signal can be missed if the model doesn't think to look
for it) and succeed on inputs (Claude handles messy, slightly-different CSVs
without modification). Neither is strictly better.

For a lab where the goal is a verdict on a known log, the prompt is faster to
write and more forgiving of format drift. For a production detector that runs
nightly on a fleet, I would ship the code — because the same input must give
the same output, and because the thresholds need to be auditable. The prompt
is the right tool for exploration; the code is the right tool for operation.

One thing both approaches share: they can only tell you **what** happened, not
**why**. The GPS log records that the EKF origin was 15.22 m from home; it
cannot tell you that the vehicle was moved after boot, or that the compass
calibration was performed in a bad location. The compass log records that
Compass 2's field correlates with throttle at r = +0.98; it cannot tell you
whether the interference is from a battery lead, an ESC, or a motor. That gap
is structural — it is what the `.tlog`, the parameters, and a physical
inspection are for.