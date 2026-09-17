# GPS / Position Failure — Diagnostic Prompt

You are analysing an ArduPilot DataFlash log that has already been converted to CSV.
I will paste (or you will find in the working directory) a set of CSVs, one per
log message type. Your job is to determine, in a single response, **whether the
aircraft lost track of where it was, or whether it flew accurately to a target
that was itself in the wrong place.**

Do not ask me follow-up questions. Do not ask me to run anything. Inspect the
files, run whatever code you need to answer, and produce the final answer in the
format specified below.

---

## 1. Input

You are given one CSV per message type, extracted from an ArduPilot `.bin` log
by a tool such as `mavlogdump.py --format csv --types <TYPES>`. Each CSV has a
header row. Relevant files and columns:

| File | Required columns | Notes |
|------|------------------|-------|
| `GPS.csv` | `TimeUS`, `Status`, `NSats`, `HDop`, `Lat`, `Lng`, `Alt` | Lat/Lng already in degrees. HDop already in real units. |
| `POS.csv` | `TimeUS`, `Lat`, `Lng`, `RelHomeAlt` | EKF position estimate. Lat/Lng in degrees. |
| `GUIP.csv` | `TimeUS`, `Type`, `pX`, `pY`, `pZ` | Guided-mode target. `pX` = Lat × 1e5, `pY` = Lng × 1e5, `pZ` = Down in cm (negative = up). Rows with `pX == 0 AND pY == 0` are origin holds, not real targets. |
| `ORGN.csv` | `TimeUS`, `Type`, `Lat`, `Lng`, `Alt` | `Type 0` = EKF origin. `Type 1` = home / takeoff point. Lat/Lng in degrees. |
| `MODE.csv` | `TimeUS`, `Mode`, `ModeNum`, `Rsn` | Mode changes. ArduCopter: 4 = GUIDED, 9 = LAND. |
| `MSG.csv` | `TimeUS`, `Message` | Autopilot text messages. |
| `ERR.csv` | `TimeUS`, `Subsys`, `ECode` | Error events. May be empty or missing. |

If a file is missing, note it in the final answer but do not abort. If a column
is missing, treat that specific diagnostic as "not enough data".

---

## 2. Diagnostic logic

Compute the following signals. All distances in metres. Use a flat-earth
approximation anchored at the EKF origin (`ORGN` Type 0):

```
lat0, lon0 = ORGN Type 0 Lat, Lng
north(lat) = (lat - lat0) * 111320
east(lng)  = (lng - lon0) * 111320 * cos(radians(lat0))
```

### Signal A — Position-estimate health (GPS vs POS)

- Join `GPS` and `POS` on nearest `TimeUS` (tolerance 100 ms).
- Compute horizontal distance `d = hypot(gps_north - pos_north, gps_east - pos_east)`.
- Report mean and max of `d`.
- **Healthy** if `max(d) < 3 m`.
- **Unhealthy** if `max(d) >= 3 m` (EKF diverged from GPS).

### Signal B — GPS quality

- From `GPS.csv`: HDop, NSats, Status.
- **Healthy** if `max(HDop) < 1.5`, `min(NSats) >= 8`, and `Status` is always
  one of {3, 4, 5, 6}.
- **Degraded** if any of those fail.

### Signal C — Reference-frame offset (EKF origin vs home)

- From `ORGN.csv`: distance between Type 0 and Type 1.
- **Consistent** if `< 3 m`.
- **Mismatched** if `>= 3 m`. This is the key signal for a reference-frame failure.

### Signal D — Commanded target vs actual position

- From `GUIP.csv`, keep rows where `pX != 0 OR pY != 0`.
- Decode: `target_lat = pX / 1e5`, `target_lng = pY / 1e5`, `target_alt = -pZ / 100`.
- Convert to NED via `north()/east()` above.
- For each POS sample, find the nearest-in-time GUIP target and compute the
  horizontal offset.
- **Tracking well** if the end-of-log offset `< 3 m`.
- **Off target** if `>= 3 m`.
- Also report the GUIP target's own N/E range (how much the target moved).

### Signal E — Autopilot awareness

- From `ERR.csv`: count rows. **Silent** if 0, **Aware** if > 0.
- From `MSG.csv`: scan for `ERR`, `FAIL`, `FAILSAFE`, `EKF` yaw alignment,
  `GPS glitch`, `variance`. Report any relevant lines.

---

## 3. Verdict logic

Answer **exactly one** of these:

1. **"Position estimate lost"** — Signal A is Unhealthy. The EKF diverged from
   GPS; the aircraft did not know where it was.
2. **"Target in wrong frame"** — Signal A is Healthy AND Signal C is Mismatched.
   The aircraft knew where it was, but was commanded to a target expressed in a
   frame that differed from the pilot's reference.
3. **"Commanded to a wrong target"** — Signal A is Healthy, Signal C is
   Consistent, but Signal D shows the aircraft reached a target that was itself
   offset from where it should have been.
4. **"No position problem detected"** — all signals healthy.
5. **"Not enough data to decide"** — a required CSV or column is missing, or the
   log is too short for any signal to be meaningful. State which signal(s)
   blocked the verdict.

Priority: (1) beats (2) beats (3). If (1) applies, do not also claim (2)/(3).

---

## 4. Output format (strict)

Respond with **exactly** these sections, in this order:

### VERDICT
One sentence. Start with one of the five labels above, then a plain-English
summary of what happened. Example: *"Target in wrong frame — the EKF origin was
15.2 m from home, so the aircraft flew accurately to a target that the pilot
believed was 'here'."*

### GRAPH
Render the following two plots inline (matplotlib, save to files
`prompt_track.png` and `prompt_altitude.png`, and display them):

1. **Horizontal track** — North vs East, with four overlaid elements:
   - GPS track (green solid)
   - POS track (red dashed)
   - GUIP commanded target (blue dotted)
   - EKF origin (black X) and home (orange square)
   Axis labels, legend, equal aspect.

2. **Altitude vs time** — GPS Alt (relative to first sample), POS RelHomeAlt,
   and GUIP target altitude (relative to first sample), all vs TimeUS/1e6.

State in one sentence what the reader should look at in the graph.

### EVIDENCE
Bulleted list. Each bullet must contain a **specific number**. Cover:

- GPS vs POS agreement: mean and max horizontal distance, sample count.
- GPS quality: HDop range, NSats range, Status values.
- EKF origin vs home: horizontal and vertical distance in metres.
- GUIP target vs actual position: end-of-log offset in metres; GUIP target's own
  N/E range.
- Autopilot awareness: ERR row count; any relevant MSG lines (quote them).

### CONFIDENCE
One of **High / Medium / Low**, with a one-sentence justification. Use High
when all required CSVs are present and the relevant signals agree. Medium when
one signal is missing or weak. Low when the verdict rests on a single signal.

### WHAT THE DATA CANNOT ESTABLISH
Bulleted list of at least three things the log does not tell you, and for each,
say where that information would have to come from instead. Always include:

- Which actor issued the target (GCS operator, mission item, companion computer).
  → Requires the `.tlog` telemetry log.
- Why the reference frames diverged at boot (bad GPS fix, compass, vehicle moved).
  → Requires parameters, pre-arm sensor data, or hardware inspection.
- What the pilot saw on screen.
  → Requires GCS video/screenshots.

---

## 5. Rules

- Do not ask clarifying questions. Decide based on the data present.
- Do not invent numbers. Every value in EVIDENCE must be computed from the CSVs.
- Do not conflate "GPS numbers look good" with "there is no position problem".
  A silent reference-frame mismatch produces excellent GPS numbers and zero
  errors.
- If you must write code to answer, write it, run it, and discard it. The user
  does not maintain your code.
- Keep the total response under ~400 words of prose (graphs and tables excluded).